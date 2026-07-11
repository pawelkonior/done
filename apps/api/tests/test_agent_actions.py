from __future__ import annotations

from fastapi.testclient import TestClient


def _create_buyable_mission(client: TestClient) -> dict:
    response = client.post(
        "/v1/missions/text",
        json={
            "transcript": (
                "Za tydzień organizuję przyjęcie urodzinowe dla 10 dzieci. "
                "Kup jedzenie, napoje i dekoracje do 300 PLN, bez orzechów, "
                "z dostawą przed 16:00."
            ),
            "locale": "pl-PL",
            "timezone": "Europe/Warsaw",
        },
    )
    assert response.status_code == 201, response.text
    detail = response.json()
    assert detail["mission"]["status"] == "approval_required"
    return detail


def test_agent_reports_product_not_buyable_and_hands_decision_to_support(
    client: TestClient,
) -> None:
    created = _create_buyable_mission(client)
    mission_id = created["mission"]["id"]
    product = created["basket"]["items"][0]

    response = client.post(
        f"/v1/missions/{mission_id}/product-not-buyable",
        json={
            "product_id": product["product_id"],
            "reason": "out_of_stock",
            "expected_revision": created["mission"]["revision"],
        },
    )

    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["mission"]["status"] == "waiting_for_support"
    assert detail["mission"]["latest_update"] == (
        f"{product['name']} cannot currently be purchased. "
        "A human is reviewing what to do next."
    )
    assert detail["basket"]["status"] == "intervention_required"
    assert detail["approval"]["status"] == "cancelled"
    assert detail["approval"]["selected_option"] == "product_not_buyable"

    action = next(
        item
        for item in detail["action_requests"]
        if item["reason_code"] == "PRODUCT_NOT_BUYABLE"
    )
    assert action["owner"] == "support"
    assert action["status"] == "pending"
    assert action["context"] == {
        "product_id": product["product_id"],
        "reason": "out_of_stock",
        "reported_by": "agent",
        "hard_constraints_preserved": True,
    }
    event = next(
        item for item in detail["events"] if item["type"] == "product.not_buyable"
    )
    assert event["severity"] == "action"
    assert event["payload"]["notify_user"] is True
    assert event["payload"]["decision_owner"] == "support"


def test_product_not_buyable_report_rejects_product_outside_current_plan(
    client: TestClient,
) -> None:
    created = _create_buyable_mission(client)
    response = client.post(
        f"/v1/missions/{created['mission']['id']}/product-not-buyable",
        json={
            "product_id": "prd_not_in_plan",
            "reason": "unknown",
            "expected_revision": created["mission"]["revision"],
        },
    )

    assert response.status_code == 409
    assert response.json()["error"] == "workflow_conflict"
