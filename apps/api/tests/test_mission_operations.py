from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient


def _create(client: TestClient, transcript: str) -> dict:
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


def test_correction_revises_same_mission_and_invalidates_approval(
    client: TestClient, transcript: str
) -> None:
    created = _create(client, transcript)
    mission_id = created["mission"]["id"]
    revision = created["mission"]["revision"]
    approval_id = created["approval"]["id"]

    response = client.post(
        f"/v1/missions/{mission_id}/corrections",
        headers={"If-Match": f'W/"{revision}"'},
        json={"correction": "Set budget to 350 PLN"},
    )
    assert response.status_code == 200, response.text
    corrected = response.json()

    assert corrected["mission"]["id"] == mission_id
    assert corrected["mission"]["revision"] == revision + 1
    assert corrected["contract"]["version"] == 2
    assert corrected["contract"]["budget"]["limit"] == 350.0
    assert corrected["approval"]["id"] != approval_id
    assert corrected["approval"]["status"] == "pending"
    event_types = [event["type"] for event in corrected["events"]]
    assert "mission.corrected" in event_types
    assert "contract.revised" in event_types
    assert "approval.superseded" in event_types

    with client.app.state.database.reader() as connection:
        old_approval = connection.execute(
            "SELECT status, selected_option FROM approval_requests WHERE id = ?",
            (approval_id,),
        ).fetchone()
    assert old_approval["status"] == "cancelled"
    assert old_approval["selected_option"] == "superseded"


def test_delivery_selection_changes_total_selection_and_approval(
    client: TestClient, transcript: str
) -> None:
    created = _create(client, transcript)
    mission_id = created["mission"]["id"]
    revision = created["mission"]["revision"]
    old_total = created["basket"]["total"]
    old_approval_id = created["approval"]["id"]
    old_delivery_id = next(
        option["id"] for option in created["delivery_options"] if option["selected"]
    )
    replacement = min(
        (option for option in created["delivery_options"] if not option["selected"]),
        key=lambda option: option["cost"],
    )

    response = client.put(
        f"/v1/missions/{mission_id}/delivery-option",
        headers={"If-Match": f'"{revision}"'},
        json={"delivery_option_id": replacement["id"]},
    )
    assert response.status_code == 200, response.text
    updated = response.json()

    assert updated["mission"]["id"] == mission_id
    assert updated["mission"]["revision"] == revision + 1
    assert updated["basket"]["delivery_option_id"] == replacement["id"]
    assert updated["basket"]["total"] != old_total
    selected = [option for option in updated["delivery_options"] if option["selected"]]
    assert [option["id"] for option in selected] == [replacement["id"]]
    assert updated["approval"]["id"] != old_approval_id
    assert updated["approval"]["status"] == "pending"
    assert "approval.superseded" in [event["type"] for event in updated["events"]]

    stale = client.put(
        f"/v1/missions/{mission_id}/delivery-option",
        json={
            "delivery_option_id": old_delivery_id,
            "expected_revision": revision,
        },
    )
    assert stale.status_code == 409
    assert "revision changed" in stale.json()["message"]


def test_stale_or_conflicting_revision_returns_409(
    client: TestClient, transcript: str
) -> None:
    created = _create(client, transcript)
    mission_id = created["mission"]["id"]
    revision = created["mission"]["revision"]

    first = client.post(
        f"/v1/missions/{mission_id}/corrections",
        json={"correction": "Set budget to 350 PLN", "expected_revision": revision},
    )
    assert first.status_code == 200

    stale = client.post(
        f"/v1/missions/{mission_id}/corrections",
        json={"correction": "Set budget to 360 PLN", "expected_revision": revision},
    )
    assert stale.status_code == 409

    current_revision = first.json()["mission"]["revision"]
    conflicting_sources = client.post(
        f"/v1/missions/{mission_id}/corrections",
        headers={"If-Match": str(current_revision + 1)},
        json={
            "correction": "Set budget to 370 PLN",
            "expected_revision": current_revision,
        },
    )
    assert conflicting_sources.status_code == 409
    assert "does not match" in conflicting_sources.json()["message"]


def test_list_filters_search_dates_sort_and_requires_action(
    client: TestClient,
) -> None:
    first = _create(
        client,
        "Jutro przyjęcie dla 10 dzieci do 300 PLN bez orzechów, dostawa przed 16:00.",
    )
    second = _create(
        client,
        "Jutro przyjęcie dla 12 dzieci do 320 PLN bez orzechów, dostawa przed 16:00.",
    )
    first_id = first["mission"]["id"]
    second_id = second["mission"]["id"]

    with client.app.state.database.transaction() as connection:
        connection.execute(
            "UPDATE missions SET created_at = ?, updated_at = ? WHERE id = ?",
            ("2026-01-01T10:00:00+00:00", "2026-01-01T10:00:00+00:00", first_id),
        )
        connection.execute(
            "UPDATE missions SET created_at = ?, updated_at = ? WHERE id = ?",
            ("2026-01-02T10:00:00+00:00", "2026-01-02T10:00:00+00:00", second_id),
        )

    searched = client.get("/v1/missions", params={"q": "12 children"})
    assert searched.status_code == 200
    assert [item["id"] for item in searched.json()["missions"]] == [second_id]

    action_required = client.get(
        "/v1/missions", params={"status": "active", "requires_action": "true"}
    )
    assert action_required.status_code == 200
    assert {item["id"] for item in action_required.json()["missions"]} == {
        first_id,
        second_id,
    }

    oldest = client.get("/v1/missions", params={"sort": "oldest"}).json()
    newest = client.get("/v1/missions", params={"sort": "newest"}).json()
    assert [item["id"] for item in oldest["missions"]] == [first_id, second_id]
    assert [item["id"] for item in newest["missions"]] == [second_id, first_id]

    completed = client.post(
        f"/v1/approvals/{first['approval']['id']}/resolve",
        json={"choice": "approve"},
    )
    assert completed.status_code == 200
    today = datetime.now(UTC).date()

    same_day = client.get(
        "/v1/missions",
        params={
            "status": "completed",
            "completed_from": today.isoformat(),
            "completed_to": today.isoformat(),
        },
    )
    assert same_day.status_code == 200, same_day.text
    assert [item["id"] for item in same_day.json()["missions"]] == [first_id]

    before_completion = client.get(
        "/v1/missions",
        params={"completed_to": (today - timedelta(days=1)).isoformat()},
    )
    assert before_completion.status_code == 200
    assert before_completion.json()["total"] == 0

    no_action = client.get("/v1/missions", params={"requires_action": "false"})
    assert no_action.status_code == 200
    assert [item["id"] for item in no_action.json()["missions"]] == [first_id]

    invalid_range = client.get(
        "/v1/missions",
        params={
            "completed_from": today.isoformat(),
            "completed_to": (today - timedelta(days=1)).isoformat(),
        },
    )
    assert invalid_range.status_code == 422

    invalid_sort = client.get("/v1/missions", params={"sort": "unsupported"})
    assert invalid_sort.status_code == 422
