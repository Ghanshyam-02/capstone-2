"""API CONTRACT TESTS against the real database (Day 1 Task 4C)."""
import pytest
from fastapi.testclient import TestClient

from api.main import app

HEADERS = {"X-API-Key": "test-key"}
URL = "/api/v1/settlement-summary"
SEPTEMBER = {"start_date": "2026-09-01", "end_date": "2026-09-30"}


@pytest.fixture
def client(full_db, monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    return TestClient(app)


def test_200_valid_request(client, full_db):
    r = client.get(URL, params=SEPTEMBER, headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert 0 <= body["settlement_rate"] <= 100
    # the API returns exactly what the database says
    amount, settled = full_db("SELECT SUM(success_amount), SUM(settled_amount) FROM gold.agg_merchant_daily")[0]
    assert body["settlement_rate"] == round(float(settled) / float(amount) * 100, 2)


def test_400_invalid_date(client):
    assert client.get(URL, params={"start_date": "2026-13-45", "end_date": "2026-09-30"},
                      headers=HEADERS).status_code == 400


def test_404_unknown_merchant(client):
    assert client.get(URL, params={**SEPTEMBER, "merchant_id": "M999"}, headers=HEADERS).status_code == 404


def test_422_invalid_parameter(client):
    assert client.get(URL, params={**SEPTEMBER, "merchant_id": "abc"}, headers=HEADERS).status_code == 422
