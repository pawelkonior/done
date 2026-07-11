from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def approval_payload(detail: dict) -> dict:
    approval = detail["approval"]
    return {
        "choice": "approve",
        "expected_revision": detail["mission"]["revision"],
        "amount": approval["amount"],
        "currency": approval["currency"],
        "plan_hash": approval["plan_hash"],
        "merchant_id": approval["merchant_id"],
        "voice_transcript": (
            f"Tak, zatwierdzam {approval['amount']} {approval['currency']} "
            f"u {approval['merchant_id']}."
        ),
    }


PROFILE_KEYS = {
    "id",
    "name",
    "email",
    "locale",
    "currency",
    "timezone",
    "autonomy_level",
    "delivery_address",
    "payment_method",
    "default_constraints",
    "contact_preference",
    "stats",
}


def test_seeded_profile_has_safe_frontend_contract(client: TestClient) -> None:
    response = client.get("/v1/users/me")
    assert response.status_code == 200
    profile = response.json()

    assert set(profile) == PROFILE_KEYS
    assert profile["id"] == "demo-user"
    assert profile["currency"] == "PLN"
    assert set(profile["delivery_address"]) == {
        "label",
        "line1",
        "city",
        "postal_code",
        "country",
    }
    assert set(profile["payment_method"]) == {
        "token",
        "brand",
        "last4",
        "expiry_month",
        "expiry_year",
        "is_demo",
    }
    assert profile["payment_method"]["token"].startswith("pm_")
    assert profile["payment_method"]["last4"] == "4242"
    assert "card_number" not in profile["payment_method"]
    assert profile["stats"] == {"missions": 0, "recoveries": 0, "saved": 0.0}


def test_profile_patch_is_partial_nested_and_persistent(client: TestClient) -> None:
    original = client.get("/v1/users/me").json()
    response = client.patch(
        "/v1/users/me",
        json={
            "name": "Paweł Nowak",
            "email": "pawel.nowak@example.com",
            "delivery_address": {"city": "Kraków", "postal_code": "30-001"},
            "payment_method": {"expiry_month": 8, "expiry_year": 2031},
            "default_constraints": ["Never exceed budget", "No nut substitutions"],
            "contact_preference": "important_updates",
        },
    )
    assert response.status_code == 200, response.text
    updated = response.json()

    assert updated["name"] == "Paweł Nowak"
    assert updated["email"] == "pawel.nowak@example.com"
    assert updated["delivery_address"]["city"] == "Kraków"
    assert updated["delivery_address"]["line1"] == original["delivery_address"]["line1"]
    assert updated["payment_method"]["expiry_month"] == 8
    assert updated["payment_method"]["token"] == original["payment_method"]["token"]
    assert updated["contact_preference"] == "important_updates"
    assert client.get("/v1/users/me").json() == updated


def test_profile_rejects_raw_or_invalid_payment_data(client: TestClient) -> None:
    raw_card = client.patch(
        "/v1/users/me",
        json={"payment_method": {"card_number": "4111111111111111"}},
    )
    assert raw_card.status_code == 422

    invalid_token = client.patch(
        "/v1/users/me",
        json={"payment_method": {"token": "4111111111111111"}},
    )
    assert invalid_token.status_code == 422

    invalid_timezone = client.patch(
        "/v1/users/me", json={"timezone": "Not/A_Timezone"}
    )
    assert invalid_timezone.status_code == 422

    nested_null = client.patch(
        "/v1/users/me", json={"delivery_address": {"city": None}}
    )
    assert nested_null.status_code == 422

    expired = client.patch(
        "/v1/users/me",
        json={"payment_method": {"expiry_month": 1, "expiry_year": 2024}},
    )
    assert expired.status_code == 422


def test_settings_patch_validates_policy_threshold_and_merchants(
    client: TestClient,
) -> None:
    response = client.patch(
        "/v1/users/me/settings",
        json={
            "voice_language": "pl-PL",
            "confirmation_voice_enabled": False,
            "safe_recovery_enabled": True,
            "approval_policy": "above_threshold",
            "approval_threshold": 150.5,
            "notifications_enabled": False,
            "preferred_merchant_ids": ["merchant-b", "merchant-c"],
        },
    )
    assert response.status_code == 200, response.text
    settings = response.json()
    assert set(settings) == {
        "voice_language",
        "confirmation_voice_enabled",
        "safe_recovery_enabled",
        "approval_policy",
        "approval_threshold",
        "notifications_enabled",
        "preferred_merchant_ids",
    }
    assert settings["approval_policy"] == "above_threshold"
    assert settings["approval_threshold"] == 150.5
    assert settings["preferred_merchant_ids"] == ["merchant-b", "merchant-c"]
    assert client.get("/v1/users/me/settings").json() == settings

    unknown = client.patch(
        "/v1/users/me/settings",
        json={"preferred_merchant_ids": ["merchant-does-not-exist"]},
    )
    assert unknown.status_code == 422
    assert "Unknown or inactive merchants" in unknown.json()["detail"]["message"]
    assert client.get("/v1/users/me/settings").json() == settings


def test_above_threshold_policy_requires_positive_threshold(client: TestClient) -> None:
    response = client.patch(
        "/v1/users/me/settings",
        json={"approval_policy": "above_threshold", "approval_threshold": 0},
    )
    assert response.status_code == 422
    assert "greater than zero" in response.json()["detail"]["message"]


def test_merchants_export_and_mission_stats(client: TestClient, transcript: str) -> None:
    merchants_response = client.get("/v1/merchants")
    assert merchants_response.status_code == 200
    merchants = merchants_response.json()
    assert merchants["total"] == 3
    assert merchants["items"] == merchants["merchants"]
    assert {merchant["id"] for merchant in merchants["merchants"]} == {
        "merchant-a",
        "merchant-b",
        "merchant-c",
    }
    assert next(
        merchant for merchant in merchants["merchants"] if merchant["id"] == "merchant-b"
    )["preferred"] is True

    created = client.post(
        "/v1/missions/text",
        json={
            "transcript": transcript,
            "locale": "pl-PL",
            "timezone": "Europe/Warsaw",
        },
    ).json()
    approval_id = created["approval"]["id"]
    changed_plan = client.post(
        f"/v1/approvals/{approval_id}/resolve", json=approval_payload(created)
    )
    assert changed_plan.status_code == 200
    completed = client.post(
        f"/v1/approvals/{changed_plan.json()['approval']['id']}/resolve",
        json=approval_payload(changed_plan.json()),
    )
    assert completed.status_code == 200

    profile = client.get("/v1/users/me").json()
    assert profile["stats"]["missions"] == 1
    assert profile["stats"]["recoveries"] == 2
    assert profile["stats"]["saved"] > 0

    exported = client.get("/v1/users/me/export")
    assert exported.status_code == 200
    payload = exported.json()
    assert payload["schema_version"] == 1
    assert payload["generated_at"]
    assert payload["profile"]["stats"] == profile["stats"]
    assert set(payload["profile"]["payment_method"]) == {
        "token",
        "brand",
        "last4",
        "expiry_month",
        "expiry_year",
        "is_demo",
    }
    assert set(payload["settings"]) == {
        "voice_language",
        "confirmation_voice_enabled",
        "safe_recovery_enabled",
        "approval_policy",
        "approval_threshold",
        "notifications_enabled",
        "preferred_merchant_ids",
    }


def test_profile_and_settings_survive_app_recreation(tmp_path: Path) -> None:
    from app.main import create_app

    database_path = tmp_path / "users-persistent.sqlite3"
    with TestClient(create_app(database_path)) as first:
        assert first.patch(
            "/v1/users/me",
            json={"name": "Persistent User", "delivery_address": {"city": "Gdańsk"}},
        ).status_code == 200
        assert first.patch(
            "/v1/users/me/settings",
            json={"notifications_enabled": False},
        ).status_code == 200

    with TestClient(create_app(database_path)) as second:
        assert second.get("/v1/users/me").json()["name"] == "Persistent User"
        assert second.get("/v1/users/me").json()["delivery_address"]["city"] == "Gdańsk"
        assert (
            second.get("/v1/users/me/settings").json()["notifications_enabled"]
            is False
        )
