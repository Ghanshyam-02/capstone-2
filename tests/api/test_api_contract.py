"""API contract tests (Task 4C). A fake repository replaces Snowflake.

    pytest tests/api -v
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from api.main import app, get_repo

HEADERS = {"X-API-Key": "test-key"}
URL = "/api/v1/settlement-summary"
DATES = {"start_date": "2026-09-01", "end_date": "2026-09-07"}


class FakeRepo:
    def ping(self):
        return True

    def merchant_exists(self, merchant_id):
        return merchant_id == "M1008"

    def totals(self, start, end, merchant_id=None):
        return {"count": 15240, "amount": 482_500_000.0, "settled": 458_700_000.0, "sla_met": 13929}

    def merchant_totals(self, start=None, end=None):
        return [
            {"merchant_id": "M1001", "merchant_name": "Good Store", "risk_level": "LOW",
             "count": 100, "amount": 1000.0, "settled": 1000.0, "sla_met": 100},
            {"merchant_id": "M1008", "merchant_name": "ABC Retail", "risk_level": "HIGH",
             "count": 200, "amount": 1000.0, "settled": 884.0, "sla_met": 145},
        ]

    def daily(self, start, end):
        return [{"date": date(2026, 9, 1), "transaction_amount": 10.0, "settled_amount": 9.0}]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    app.dependency_overrides[get_repo] = FakeRepo
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_200_valid_request(client):
    r = client.get(URL, params=DATES, headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["settlement_rate"] == 95.07
    assert body["settlement_gap"] == 23_800_000
    assert 0 <= body["settlement_rate"] <= 100          # the brief: rate between 0 and 100
    assert 0 <= body["sla_rate"] <= 100


def test_400_invalid_date(client):
    assert client.get(URL, params={"start_date": "2026-13-45", "end_date": "2026-09-07"},
                      headers=HEADERS).status_code == 400
    assert client.get(URL, params={"start_date": "2026-09-07", "end_date": "2026-09-01"},
                      headers=HEADERS).status_code == 400


def test_404_unknown_merchant(client):
    assert client.get(URL, params={**DATES, "merchant_id": "M9999"}, headers=HEADERS).status_code == 404


def test_422_invalid_parameter(client):
    assert client.get(URL, params={**DATES, "merchant_id": "abc"}, headers=HEADERS).status_code == 422
    assert client.get(URL, params={**DATES, "merchant_id": "M1' OR '1'='1"}, headers=HEADERS).status_code == 422
    assert client.get(URL, params={"end_date": "2026-09-07"}, headers=HEADERS).status_code == 422   # missing


def test_401_without_api_key(client):
    assert client.get(URL, params=DATES).status_code == 401


def test_merchant_exceptions(client):
    body = client.get("/api/v1/merchant-exceptions", headers=HEADERS).json()
    assert body == [{"merchant_id": "M1008", "merchant_name": "ABC Retail", "settlement_rate": 88.4,
                     "sla_rate": 72.5, "risk_level": "HIGH", "settlement_gap": 116.0}]
