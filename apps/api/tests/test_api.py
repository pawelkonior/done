from __future__ import annotations

import sqlite3
from pathlib import Path

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
        f"/v1/approvals/{approval_id}/resolve", json={"choice": "approve"}
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


def test_approval_is_idempotent(client: TestClient, transcript: str) -> None:
    created = create_mission(client, transcript)
    approval_id = created["approval"]["id"]
    endpoint = f"/v1/approvals/{approval_id}/resolve"

    first = client.post(endpoint, json={"choice": "approve"})
    second = client.post(endpoint, json={"choice": "approve"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["order"]["id"] == second.json()["order"]["id"]
    first_completed = [
        event for event in second.json()["events"] if event["type"] == "mission.completed"
    ]
    assert len(first_completed) == 1
    assert len(second.json()["payment_attempts"]) == 2


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
    cancelled = client.post(f"/v1/missions/{mission_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["mission"]["status"] == "cancelled"

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
