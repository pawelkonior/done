from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def test_incomplete_mission_does_not_expose_internal_deadline_sentinel(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(tmp_path / "runtime-contract.sqlite3")) as client:
        response = client.post(
            "/v1/missions/text",
            json={
                "transcript": "Kup prezent do 100 PLN jutro",
                "locale": "pl-PL",
                "timezone": "Europe/Warsaw",
            },
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["mission"]["status"] == "clarification_required"
    assert body["contract"] is None
    assert body["draft"]["deadline"] is None
    assert body["mission"]["deadline"] is None
