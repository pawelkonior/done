from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.main import create_app  # noqa: E402


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = create_app(tmp_path / "test.sqlite3")
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def transcript() -> str:
    return (
        "Jutro organizuję przyjęcie urodzinowe dla 10 dzieci. "
        "Kup jedzenie, napoje i dekoracje do 300 PLN, bez orzechów, "
        "z dostawą przed 16:00."
    )
