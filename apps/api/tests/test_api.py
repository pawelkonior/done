from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient


def create_mission(client: TestClient, transcript: str) -> dict:
    response = client.post(
        "/v1/missions/text",
        json={
            "transcript": transcript,
            "locale": "pl-PL",
            "timezone": "Europe/Warsaw",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def approval_payload(detail: dict, choice: str = "approve") -> dict:
    approval = detail["approval"]
    payload = {
        "choice": choice,
        "expected_revision": detail["mission"]["revision"],
    }
    if choice == "approve":
        payload.update(
            {
                "amount": approval["amount"],
                "currency": approval["currency"],
                "plan_hash": approval["plan_hash"],
                "merchant_id": approval["merchant_id"],
                "voice_transcript": (
                    f"Tak, zatwierdzam {approval['amount']} "
                    f"{approval['currency']} u {approval['merchant_id']}."
                ),
            }
        )
    return payload


def test_health_and_seed_data(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["database"] == "ok"
    assert response.json()["seeded_products"] >= 10


def test_creation_reaches_approval_with_full_mobile_contract(
    client: TestClient, transcript: str
) -> None:
    detail = create_mission(client, transcript)

    assert set(
        [
            "mission",
            "contract",
            "basket",
            "approval",
            "events",
            "metrics",
            "delivery_options",
        ]
    ).issubset(detail)
    assert detail["mission"]["status"] == "approval_required"
    assert detail["mission"]["current_step"] == 5
    assert detail["mission"]["total_steps"] == 6
    assert detail["mission"]["progress"] > 0.8
    assert detail["contract"]["budget"]["limit"] == 300.0
    assert detail["contract"]["participants"][0]["count"] == 10
    assert any(
        constraint["type"] == "allergen"
        and constraint["value"] == "nuts"
        for constraint in detail["contract"]["hard_constraints"]
    )
    assert detail["basket"]["total"] <= 300.0
    assert detail["basket"]["items"]
    assert all(item["nut_free"] for item in detail["basket"]["items"])
    assert detail["approval"]["status"] == "pending"
    assert any(option["id"] == "approve" for option in detail["approval"]["options"])
    assert len(detail["delivery_options"]) == 3
    assert sum(option["selected"] for option in detail["delivery_options"]) == 1

    event_types = [event["type"] for event in detail["events"]]
    assert event_types[:3] == [
        "mission.created",
        "voice.transcribed",
        "intent.parsed",
    ]
    assert "basket.optimized" in event_types
    assert event_types[-1] == "approval.requested"


def test_approval_runs_two_recoveries_and_completes(
    client: TestClient, transcript: str
) -> None:
    created = create_mission(client, transcript)
    approval_id = created["approval"]["id"]

    response = client.post(
        f"/v1/approvals/{approval_id}/resolve", json=approval_payload(created)
    )
    assert response.status_code == 200, response.text
    changed_plan = response.json()

    # The unavailable item changes the approved basket.  Checkout must stop
    # before reservation/card/payment and ask for an approval bound to the new
    # plan rather than reusing the old consent.
    assert changed_plan["mission"]["status"] == "approval_required"
    assert changed_plan["approval"]["id"] != approval_id
    assert changed_plan["approval"]["status"] == "pending"
    with client.app.state.database.reader() as connection:
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM inventory_reservations"
        ).fetchone()["count"] == 0
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM virtual_card_requests"
        ).fetchone()["count"] == 0
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM payment_attempts"
        ).fetchone()["count"] == 0

    response = client.post(
        f"/v1/approvals/{changed_plan['approval']['id']}/resolve",
        json=approval_payload(changed_plan),
    )
    assert response.status_code == 200, response.text
    completed = response.json()

    assert completed["mission"]["status"] == "completed"
    assert completed["mission"]["progress"] == 1.0
    assert completed["approval"]["status"] == "approved"
    assert completed["basket"]["status"] == "ordered"
    assert completed["basket"]["total"] <= completed["metrics"]["budget_limit"]
    assert completed["metrics"]["recovered_failures"] == 2
    assert completed["metrics"]["payment_attempts"] == 2
    assert completed["metrics"]["constraint_satisfaction_rate"] == 1.0
    assert completed["order"]["status"] == "confirmed"
    assert completed["summary"]["confirmation_code"].startswith("DONE-")
    assert completed["funding"]["status"] == "used_closed"
    assert completed["funding"]["contains_card_secrets"] is False

    with client.app.state.database.reader() as connection:
        binding = connection.execute(
            """
            SELECT ae.plan_hash AS approval_hash,
                   ga.plan_hash AS guardrail_hash,
                   ir.plan_hash AS reservation_hash,
                   vcr.plan_hash AS card_hash,
                   ae.merchant_id, vcr.merchant_lock,
                   ae.amount_cents, vcr.max_amount_cents
            FROM approval_evidence ae
            JOIN guardrail_attestations ga
              ON ga.mission_id = ae.mission_id AND ga.plan_hash = ae.plan_hash
            JOIN inventory_reservations ir
              ON ir.mission_id = ae.mission_id AND ir.plan_hash = ae.plan_hash
            JOIN virtual_card_requests vcr
              ON vcr.mission_id = ae.mission_id AND vcr.plan_hash = ae.plan_hash
            WHERE ae.approval_id = ?
            """,
            (changed_plan["approval"]["id"],),
        ).fetchone()
    assert binding is not None
    assert len(
        {
            binding["approval_hash"],
            binding["guardrail_hash"],
            binding["reservation_hash"],
            binding["card_hash"],
        }
    ) == 1
    assert binding["merchant_id"] == binding["merchant_lock"]
    assert binding["amount_cents"] == binding["max_amount_cents"]

    replacement = next(
        item for item in completed["basket"]["items"] if item["replaced_product_id"]
    )
    assert replacement["product_id"] == "snack-crackers"
    assert replacement["replaced_product_id"] == "snack-pretzels"
    assert replacement["nut_free"] is True

    assert [attempt["status"] for attempt in completed["payment_attempts"]] == [
        "declined",
        "authorized",
    ]
    assert [attempt["provider"] for attempt in completed["payment_attempts"]] == [
        "PSP_A",
        "PSP_B",
    ]
    event_types = [event["type"] for event in completed["events"]]
    for required in (
        "inventory.unavailable",
        "product.replaced",
        "payment.declined",
        "payment.rerouted",
        "mission.completed",
    ):
        assert required in event_types
    assert event_types.index("inventory.unavailable") < event_types.index("product.replaced")
    assert event_types.index("payment.declined") < event_types.index("payment.rerouted")


def test_purchase_approval_requires_positive_spoken_amount_and_currency(
    client: TestClient, transcript: str
) -> None:
    created = create_mission(client, transcript)
    endpoint = f"/v1/approvals/{created['approval']['id']}/resolve"
    valid = approval_payload(created)

    missing = dict(valid)
    missing.pop("voice_transcript")
    negative = {
        **valid,
        "voice_transcript": "Nie, nie zatwierdzam 300 PLN u merchant-b.",
    }
    wrong_amount = {
        **valid,
        "voice_transcript": "Tak, zatwierdzam 1 PLN u merchant-b.",
    }
    wrong_merchant = {
        **valid,
        "voice_transcript": "Tak, zatwierdzam 300 PLN u merchant-a.",
    }

    for payload in (missing, negative, wrong_amount, wrong_merchant):
        response = client.post(endpoint, json=payload)
        assert response.status_code == 409, response.text

    detail = client.get(f"/v1/missions/{created['mission']['id']}").json()
    assert detail["approval"]["status"] == "pending"
    with client.app.state.database.reader() as connection:
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM inventory_reservations"
        ).fetchone()["count"] == 0
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM virtual_card_requests"
        ).fetchone()["count"] == 0
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM payment_attempts"
        ).fetchone()["count"] == 0


def test_approval_is_idempotent(client: TestClient, transcript: str) -> None:
    created = create_mission(client, transcript)
    approval_id = created["approval"]["id"]
    endpoint = f"/v1/approvals/{approval_id}/resolve"

    original_payload = approval_payload(created)
    first = client.post(endpoint, json=original_payload)
    second = client.post(endpoint, json=original_payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["approval"]["id"] == second.json()["approval"]["id"]
    assert first.json()["approval"]["status"] == "pending"

    refreshed_endpoint = f"/v1/approvals/{first.json()['approval']['id']}/resolve"
    refreshed_payload = approval_payload(first.json())
    completed_once = client.post(refreshed_endpoint, json=refreshed_payload)
    completed_twice = client.post(refreshed_endpoint, json=refreshed_payload)
    assert completed_once.status_code == 200
    assert completed_twice.status_code == 200
    assert completed_once.json()["order"]["id"] == completed_twice.json()["order"]["id"]
    completed_events = [
        event
        for event in completed_twice.json()["events"]
        if event["type"] == "mission.completed"
    ]
    assert len(completed_events) == 1
    assert len(completed_twice.json()["payment_attempts"]) == 2


def test_polling_cursor_and_mission_list(client: TestClient, transcript: str) -> None:
    created = create_mission(client, transcript)
    mission_id = created["mission"]["id"]

    listing = client.get("/v1/missions?status=active")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    summary = listing.json()["missions"][0]
    assert set(summary) == {
        "id",
        "title",
        "subtitle",
        "status",
        "current_step",
        "total_steps",
        "progress",
        "latest_update",
            "created_at",
            "completed_at",
            "recovered_failures",
        }

    first_page = client.get(f"/v1/missions/{mission_id}/events?after_id=0").json()
    assert first_page["events"]
    cursor = first_page["events"][-2]["id"]
    second_page = client.get(
        f"/v1/missions/{mission_id}/events?after_id={cursor}"
    ).json()
    assert second_page["events"][0]["id"] > cursor
    assert second_page["cursor"] == second_page["events"][-1]["id"]


def test_failure_injection_is_deduplicated(client: TestClient, transcript: str) -> None:
    created = create_mission(client, transcript)
    mission_id = created["mission"]["id"]

    # The two killer-demo failures are queued automatically at creation.
    existing = client.post(
        "/v1/demo/failures",
        json={"mission_id": mission_id, "failure_type": "out_of_stock"},
    )
    assert existing.status_code == 201
    assert existing.json()["failure_type"] == "product_unavailable"
    assert existing.json()["already_queued"] is True

    new_failure = client.post(
        "/v1/demo/failures",
        json={"mission_id": mission_id, "failure_type": "delivery_slot_lost"},
    )
    assert new_failure.status_code == 201
    assert new_failure.json()["already_queued"] is False


def test_cancel_and_reset(client: TestClient, transcript: str) -> None:
    created = create_mission(client, transcript)
    mission_id = created["mission"]["id"]
    missing_revision = client.post(f"/v1/missions/{mission_id}/cancel")
    assert missing_revision.status_code == 409
    support = client.post(
        f"/v1/missions/{mission_id}/support",
        json={
            "reason": "Please stop and close every pending action",
            "expected_revision": created["mission"]["revision"],
        },
    )
    assert support.status_code == 200
    assert any(
        action["status"] == "pending" for action in support.json()["action_requests"]
    )
    cancelled = client.post(
        f"/v1/missions/{mission_id}/cancel",
        json={"expected_revision": support.json()["mission"]["revision"]},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["mission"]["status"] == "cancelled"
    assert all(
        action["status"] == "resolved"
        for action in cancelled.json()["action_requests"]
    )

    reset = client.post("/v1/demo/reset")
    assert reset.status_code == 200
    assert reset.json()["missions_deleted"] == 1
    assert client.get("/v1/missions").json()["total"] == 0
    assert client.get("/health").json()["seeded_products"] >= 10


def test_sqlite_state_survives_app_recreation(tmp_path: Path, transcript: str) -> None:
    from app.main import create_app

    database_path = tmp_path / "persistent.sqlite3"
    with TestClient(create_app(database_path)) as first_client:
        created = create_mission(first_client, transcript)
        mission_id = created["mission"]["id"]

    with TestClient(create_app(database_path)) as second_client:
        detail = second_client.get(f"/v1/missions/{mission_id}")
        assert detail.status_code == 200
        assert detail.json()["mission"]["status"] == "approval_required"

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM missions").fetchone()[0] == 1


def test_validation_and_not_found_errors(client: TestClient) -> None:
    invalid = client.post("/v1/missions/text", json={"transcript": ""})
    assert invalid.status_code == 422

    missing = client.get("/v1/missions/not-a-real-id")
    assert missing.status_code == 404
    assert missing.json()["error"] == "mission_not_found"


def test_ambiguous_voice_intake_is_saved_without_guessing_and_resumes(
    client: TestClient,
) -> None:
    response = client.post(
        "/v1/missions/voice",
        json={
            "transcript": (
                "Rzeczy na urodziny 10 latków, 5 oosb, za tydzień, "
                "koszt max 500 zł."
            ),
            "locale": "pl-PL",
            "timezone": "Europe/Warsaw",
        },
    )
    assert response.status_code == 201, response.text
    draft = response.json()
    mission_id = draft["mission"]["id"]

    assert draft["mission"]["status"] == "clarification_required"
    assert draft["draft"]["recipient_age"] == 10
    assert draft["draft"]["participants"] == 5
    assert draft["draft"]["budget"] == {"minor": 50_000, "currency": "PLN"}
    assert set(draft["draft"]["missing_fields"]) == {
        "shopping_scope",
        "deadline_time",
    }
    expected_date = datetime.now(ZoneInfo("Europe/Warsaw")).date() + timedelta(days=7)
    assert draft["draft"]["deadline_date"] == expected_date.isoformat()
    assert draft["contract"] is None
    assert draft["basket"] is None
    assert draft["approval"] is None
    assert draft["funding"] == {
        "status": "not_ready",
        "contains_card_secrets": False,
    }

    action = next(
        item
        for item in draft["action_requests"]
        if item["type"] == "clarification" and item["status"] == "pending"
    )
    resumed_response = client.post(
        f"/v1/action-requests/{action['id']}/resolve",
        json={
            "choice": "answer_by_voice",
            "voice_transcript": (
                "Chodzi o dekoracje i wyposażenie przyjęcia, dostawa do 18:00."
            ),
            "expected_revision": draft["mission"]["revision"],
        },
    )
    assert resumed_response.status_code == 200, resumed_response.text
    resumed = resumed_response.json()
    assert resumed["mission"]["id"] == mission_id
    assert resumed["mission"]["status"] == "approval_required"
    assert resumed["contract"]["participants"][0]["count"] == 5
    assert resumed["contract"]["budget"]["limit"] == 500.0
    assert resumed["approval"]["plan_hash"].startswith("sha256:")
    assert resumed["approval"]["merchant_id"] == resumed["basket"]["merchant"]["id"]


def test_exact_voice_request_resumes_same_mission_into_dynamic_gift_plan(
    client: TestClient,
) -> None:
    transcript = (
        "rzeczy na urodziny 10 latkow, 5 oosb, za tydzien, koszt max 500zl"
    )
    created_response = client.post(
        "/v1/missions/voice",
        json={
            "transcript": transcript,
            "locale": "pl-PL",
            "timezone": "Europe/Warsaw",
        },
    )
    assert created_response.status_code == 201, created_response.text
    created = created_response.json()
    mission_id = created["mission"]["id"]

    assert created["mission"]["status"] == "clarification_required"
    assert created["draft"]["constraints"] == []
    assert set(created["draft"]["missing_fields"]) == {
        "shopping_scope",
        "deadline_time",
    }

    action = next(
        item
        for item in created["action_requests"]
        if item["type"] == "clarification" and item["status"] == "pending"
    )
    correction_response = client.post(
        f"/v1/action-requests/{action['id']}/resolve",
        json={
            "choice": "answer_by_voice",
            "voice_transcript": (
                "Kup prezenty dla tych pięciu 10-latków, dostawa do 18:00."
            ),
            "expected_revision": created["mission"]["revision"],
        },
    )
    assert correction_response.status_code == 200, correction_response.text
    planned = correction_response.json()

    assert planned["mission"]["id"] == mission_id
    assert planned["mission"]["mission_type"] == "gift_shopping"
    assert planned["mission"]["status"] == "approval_required"
    assert planned["mission"]["budget_limit"] == 500.0
    assert planned["basket"]["item_count"] == 5
    assert planned["basket"]["total"] <= 500.0
    assert planned["basket"]["currency"] == "PLN"
    assert all("gift" in item["tags"] for item in planned["basket"]["items"])
    assert all(
        any(tag.startswith("age-") for tag in item["tags"])
        for item in planned["basket"]["items"]
    )
    merchant_id = planned["basket"]["merchant"]["id"]
    assert {option["merchant_id"] for option in planned["delivery_options"]} == {
        merchant_id
    }
    assert planned["approval"]["merchant_id"] == merchant_id
    assert planned["contract"]["forbidden_categories"] == []
    assert {item["type"] for item in planned["contract"]["hard_constraints"]} == {
        "budget",
        "delivery_deadline",
    }
    catalog_event = next(
        event for event in planned["events"] if event["type"] == "catalog.searched"
    )
    with client.app.state.database.reader() as connection:
        eligible_count = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM products p JOIN merchants m ON m.id = p.merchant_id
            WHERE m.active = 1 AND p.stock > 0 AND p.currency = 'PLN'
              AND p.category IN ('gifts', 'toys', 'books', 'games', 'creative')
            """
        ).fetchone()["count"]
        product_failures = connection.execute(
            """
            SELECT COUNT(*) AS count FROM failure_injections
            WHERE mission_id = ? AND failure_type = 'product_unavailable'
            """,
            (mission_id,),
        ).fetchone()["count"]
    assert catalog_event["payload"]["candidates_considered"] == eligible_count
    assert product_failures == 0


def test_catalog_no_plan_stops_before_approval_and_funding(
    client: TestClient,
) -> None:
    response = client.post(
        "/v1/missions/voice",
        json={
            "transcript": (
                "Buy gifts for five kids aged ten, in a week at 4:30 pm, "
                "budget 120 EUR"
            ),
            "locale": "en-GB",
            "timezone": "Europe/Warsaw",
        },
    )
    assert response.status_code == 201, response.text
    detail = response.json()

    assert detail["mission"]["status"] == "waiting_for_user"
    assert detail["mission"]["requires_approval"] is False
    assert detail["contract"] is not None
    assert detail["basket"] is None
    assert detail["approval"] is None
    assert detail["funding"] == {
        "status": "not_ready",
        "contains_card_secrets": False,
    }
    assert any(
        item["reason_code"] == "NO_COMPLIANT_CATALOG_PLAN"
        and item["status"] == "pending"
        for item in detail["action_requests"]
    )
    with client.app.state.database.reader() as connection:
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM inventory_reservations"
        ).fetchone()["count"] == 0
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM virtual_card_requests"
        ).fetchone()["count"] == 0


def test_every_purchase_approval_requires_full_immutable_binding(
    client: TestClient, transcript: str
) -> None:
    created = create_mission(client, transcript)
    endpoint = f"/v1/approvals/{created['approval']['id']}/resolve"
    valid = approval_payload(created)

    for field in (
        "expected_revision",
        "amount",
        "currency",
        "plan_hash",
        "merchant_id",
    ):
        incomplete = dict(valid)
        incomplete.pop(field)
        response = client.post(endpoint, json=incomplete)
        assert response.status_code == 409, (field, response.text)

    wrong_merchant = dict(valid, merchant_id="merchant-c")
    response = client.post(endpoint, json=wrong_merchant)
    assert response.status_code == 409
    detail = client.get(f"/v1/missions/{created['mission']['id']}").json()
    assert detail["approval"]["status"] == "pending"
    assert detail["funding"]["status"] == "not_ready"


def test_missing_approval_evidence_never_gets_synthesized_at_resolution(
    client: TestClient, transcript: str
) -> None:
    created = create_mission(client, transcript)
    approval_id = created["approval"]["id"]
    with client.app.state.database.transaction() as connection:
        connection.execute(
            "DELETE FROM approval_evidence WHERE approval_id = ?", (approval_id,)
        )

    response = client.post(
        f"/v1/approvals/{approval_id}/resolve",
        json=approval_payload(created),
    )
    assert response.status_code == 200, response.text
    refreshed = response.json()
    assert refreshed["mission"]["status"] == "approval_required"
    assert refreshed["approval"]["id"] != approval_id
    assert refreshed["approval"]["status"] == "pending"
    assert "approval.rejected_missing_evidence" in {
        event["type"] for event in refreshed["events"]
    }
    with client.app.state.database.reader() as connection:
        old = connection.execute(
            "SELECT status FROM approval_requests WHERE id = ?", (approval_id,)
        ).fetchone()
        side_effects = {
            table: connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()[
                "count"
            ]
            for table in (
                "inventory_reservations",
                "virtual_card_requests",
                "payment_attempts",
            )
        }
    assert old["status"] == "cancelled"
    assert side_effects == {
        "inventory_reservations": 0,
        "virtual_card_requests": 0,
        "payment_attempts": 0,
    }


def test_expired_approval_is_committed_and_replaced(
    client: TestClient, transcript: str
) -> None:
    created = create_mission(client, transcript)
    approval_id = created["approval"]["id"]
    with client.app.state.database.transaction() as connection:
        connection.execute(
            "UPDATE approval_requests SET expires_at = ? WHERE id = ?",
            ("2020-01-01T00:00:00+00:00", approval_id),
        )

    response = client.post(
        f"/v1/approvals/{approval_id}/resolve",
        json=approval_payload(created),
    )
    assert response.status_code == 200, response.text
    refreshed = response.json()
    assert refreshed["approval"]["id"] != approval_id
    assert refreshed["approval"]["status"] == "pending"
    with client.app.state.database.reader() as connection:
        old = connection.execute(
            "SELECT status FROM approval_requests WHERE id = ?", (approval_id,)
        ).fetchone()
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM virtual_card_requests"
        ).fetchone()["count"] == 0
    assert old["status"] == "expired"


def test_unverified_vegan_constraint_pauses_before_approval_or_funding(
    client: TestClient,
) -> None:
    detail = create_mission(
        client,
        "Jutro przyjęcie dla 10 dzieci: wegańskie jedzenie i dekoracje "
        "do 300 PLN, dostawa przed 16:00.",
    )
    assert detail["mission"]["status"] == "waiting_for_user"
    assert detail["approval"] is None
    assert detail["basket"] is None
    assert any(
        action["reason_code"] == "NO_COMPLIANT_CATALOG_PLAN"
        and action["status"] == "pending"
        for action in detail["action_requests"]
    )
    with client.app.state.database.reader() as connection:
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM guardrail_attestations"
        ).fetchone()["count"] == 0
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM virtual_card_requests"
        ).fetchone()["count"] == 0


def test_catalog_safety_change_invalidates_approval_before_side_effects(
    client: TestClient, transcript: str
) -> None:
    created = create_mission(client, transcript)
    with client.app.state.database.transaction() as connection:
        connection.execute(
            "UPDATE products SET allergens_json = ? WHERE id = 'snack-pretzels'",
            ('["nuts"]',),
        )

    response = client.post(
        f"/v1/approvals/{created['approval']['id']}/resolve",
        json=approval_payload(created),
    )
    assert response.status_code == 200, response.text
    blocked = response.json()
    assert blocked["mission"]["status"] == "waiting_for_user"
    assert blocked["approval"]["status"] == "cancelled"
    assert any(
        action["reason_code"] == "PLAN_NO_LONGER_COMPLIANT"
        and action["status"] == "pending"
        for action in blocked["action_requests"]
    )
    assert "approval.rejected_policy_change" in {
        event["type"] for event in blocked["events"]
    }
    with client.app.state.database.reader() as connection:
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM inventory_reservations"
        ).fetchone()["count"] == 0
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM virtual_card_requests"
        ).fetchone()["count"] == 0
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM payment_attempts"
        ).fetchone()["count"] == 0


def test_allowed_and_forbidden_categories_block_catalog_drift(
    client: TestClient, transcript: str
) -> None:
    with client.app.state.database.transaction() as connection:
        connection.execute(
            "UPDATE products SET category = 'alcohol' "
            "WHERE substitute_group = 'savory-kids'"
        )

    blocked = create_mission(client, transcript)
    assert blocked["mission"]["status"] == "waiting_for_user"
    assert blocked["approval"] is None
    assert blocked["basket"] is None
    with client.app.state.database.reader() as connection:
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM guardrail_attestations"
        ).fetchone()["count"] == 0
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM virtual_card_requests"
        ).fetchone()["count"] == 0


def test_live_mode_stops_before_synthetic_reservation_card_or_payment(
    tmp_path: Path,
    monkeypatch,
    transcript: str,
) -> None:
    from app.application.mission_service import MissionServiceSettings
    from app.main import create_app

    token = "test-live-token-with-at-least-32-characters"
    monkeypatch.setenv("DONE_COMMERCE_MODE", "live")
    monkeypatch.setenv("DONE_API_AUTH_TOKEN", token)
    application = create_app(
        tmp_path / "live.sqlite3",
        mission_settings=MissionServiceSettings(inject_demo_failures=False),
    )
    with TestClient(
        application,
        headers={"Authorization": f"Bearer {token}"},
    ) as live_client:
        created = create_mission(live_client, transcript)
        response = live_client.post(
            f"/v1/approvals/{created['approval']['id']}/resolve",
            json=approval_payload(created),
        )
        assert response.status_code == 200, response.text
        paused = response.json()
        assert paused["mission"]["status"] == "waiting_for_support"
        assert any(
            action["reason_code"] == "MERCHANT_AND_CARD_PROVIDERS_NOT_CONFIGURED"
            for action in paused["action_requests"]
        )
        with application.state.database.reader() as connection:
            counts = {
                table: connection.execute(
                    f"SELECT COUNT(*) AS count FROM {table}"
                ).fetchone()["count"]
                for table in (
                    "inventory_reservations",
                    "virtual_card_requests",
                    "payment_attempts",
                )
            }
    assert counts == {
        "inventory_reservations": 0,
        "virtual_card_requests": 0,
        "payment_attempts": 0,
    }
