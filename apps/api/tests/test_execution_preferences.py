from __future__ import annotations

from fastapi.testclient import TestClient


TRANSCRIPT = (
    "Jutro urodziny dla 10 dzieci, jedzenie i dekoracje do 300 PLN, "
    "bez orzechów, dostawa przed 16:00."
)


def create(client: TestClient) -> dict:
    response = client.post(
        "/v1/missions/text",
        json={
            "transcript": TRANSCRIPT,
            "locale": "pl-PL",
            "timezone": "Europe/Warsaw",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def approval_payload(detail: dict) -> dict:
    approval = detail["approval"]
    return {
        "choice": "approve",
        "expected_revision": detail["mission"]["revision"],
        "amount": approval["amount"],
        "currency": approval["currency"],
        "plan_hash": approval["plan_hash"],
        "merchant_id": approval["merchant_id"],
    }


def test_autonomous_policy_still_requires_exact_funding_consent(
    client: TestClient,
) -> None:
    updated = client.patch(
        "/v1/users/me/settings",
        json={"approval_policy": "autonomous_low_risk"},
    )
    assert updated.status_code == 200, updated.text

    mission = create(client)

    assert mission["mission"]["status"] == "approval_required"
    assert mission["mission"]["requires_approval"] is True
    assert mission["approval"]["status"] == "pending"
    event_types = [event["type"] for event in mission["events"]]
    assert "approval.skipped" in event_types
    assert "funding.approval_required" in event_types
    with client.app.state.database.reader() as connection:
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM virtual_card_requests"
        ).fetchone()["count"] == 0


def test_threshold_policy_only_interrupts_at_or_above_threshold(
    client: TestClient,
) -> None:
    low = client.patch(
        "/v1/users/me/settings",
        json={"approval_policy": "above_threshold", "approval_threshold": 100},
    )
    assert low.status_code == 200, low.text
    needs_approval = create(client)
    assert needs_approval["mission"]["status"] == "approval_required"

    high = client.patch(
        "/v1/users/me/settings",
        json={"approval_threshold": 500},
    )
    assert high.status_code == 200, high.text
    automatic = create(client)
    assert automatic["mission"]["status"] == "approval_required"
    assert automatic["approval"]["status"] == "pending"
    assert "funding.approval_required" in [
        event["type"] for event in automatic["events"]
    ]


def test_disabling_safe_recovery_stops_on_first_recoverable_failure(
    client: TestClient,
) -> None:
    updated = client.patch(
        "/v1/users/me/settings",
        json={
            "approval_policy": "autonomous_low_risk",
            "safe_recovery_enabled": False,
            "preferred_merchant_ids": ["merchant-b"],
        },
    )
    assert updated.status_code == 200, updated.text

    mission = create(client)
    approved = client.post(
        f"/v1/approvals/{mission['approval']['id']}/resolve",
        json=approval_payload(mission),
    )
    assert approved.status_code == 200, approved.text
    paused = approved.json()

    assert paused["mission"]["status"] == "waiting_for_user"
    assert paused["basket"]["status"] == "intervention_required"
    assert any(
        action["type"] == "recovery_decision" and action["status"] == "pending"
        for action in paused["action_requests"]
    )
    blocked = next(
        event
        for event in paused["events"]
        if event["type"] == "recovery.blocked_by_policy"
    )
    assert blocked["payload"]["safe_recovery_enabled"] is False
    catalog = next(
        event for event in paused["events"] if event["type"] == "catalog.searched"
    )
    assert catalog["payload"]["preferred_match"] is True


def test_cross_currency_threshold_fails_closed_without_an_fx_port(
    client: TestClient,
) -> None:
    profile = client.patch("/v1/users/me", json={"currency": "EUR"})
    assert profile.status_code == 200, profile.text
    settings = client.patch(
        "/v1/users/me/settings",
        json={"approval_policy": "above_threshold", "approval_threshold": 500},
    )
    assert settings.status_code == 200, settings.text

    mission = create(client)

    assert mission["mission"]["status"] == "approval_required"
    policy_event = next(
        event for event in mission["events"] if event["type"] == "policy.validated"
    )
    assert policy_event["payload"]["approval_mode"] == "always"
