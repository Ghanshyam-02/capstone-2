"""SECURITY TESTS (Day 1 Task 4D)."""
import pytest
from fastapi.testclient import TestClient

from api.main import app

URL = "/api/v1/settlement-summary"
SEPTEMBER = {"start_date": "2026-09-01", "end_date": "2026-09-30"}


@pytest.fixture
def client(full_db, monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    return TestClient(app)


def test_api_needs_a_valid_key(client):
    assert client.get(URL, params=SEPTEMBER).status_code == 401
    assert client.get(URL, params=SEPTEMBER, headers={"X-API-Key": "wrong"}).status_code == 401


def test_sql_injection_is_blocked(client):
    r = client.get(URL, params={**SEPTEMBER, "merchant_id": "M100' OR '1'='1"}, headers={"X-API-Key": "test-key"})
    assert r.status_code == 422
