"""API contract tests (brief: Task 4C). A fake repository replaces Snowflake,
so these run anywhere in < 1 second.
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from api.main import app, get_repo

KEY = "test-key"
HEADERS = {"X-API-Key": KEY}
RANGE = {"start_date": "2026-09-01", "end_date": "2026-09-07"}


class FakeRepo:
    def ping(self):
        return True

    def merchant_exists(self, merchant_id):
        return merchant_id in {"M100", "M108"}

    def data_range(self):
        return date(2026, 9, 1), date(2026, 9, 8)

    def totals(self, start, end, merchant_id):
        return {"success_count": 15240, "success_amount": 482_500_000.0,
                "settled_amount": 458_700_000.0, "sla_met_count": 13929}

    def merchant_totals(self, start, end):
        return [
            {"merchant_id": "M100", "merchant_name": "Good Store", "risk_level": "LOW", "success_count": 100,
             "success_amount": 100_000.0, "settled_amount": 100_000.0, "sla_met_count": 99},
            {"merchant_id": "M108", "merchant_name": "ABC Retail", "risk_level": "HIGH", "success_count": 200,
             "success_amount": 100_000.0, "settled_amount": 88_400.0, "sla_met_count": 145},
        ]

    def daily(self, start, end, merchant_id):
        return [{"date": date(2026, 9, 1), "transaction_amount": 10.0, "settled_amount": 9.0}]

    def gap_breakdown(self, start, end, merchant_id):
        return [{"category": "PENDING", "transaction_count": 1, "amount": 5.0}]

    def data_quality(self):
        return [{"source": "transactions", "severity": "QUARANTINE", "reason": "MISSING_MERCHANT_ID",
                 "record_count": 3}]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("API_KEY", KEY)
    app.dependency_overrides[get_repo] = FakeRepo
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_200_valid_request_matches_contract(client):
    r = client.get("/api/v1/settlement-summary", params=RANGE, headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    for field in ("transaction_count", "transaction_amount", "settled_amount",
                  "settlement_rate", "settlement_gap", "sla_rate"):
        assert field in body
    assert body["settlement_rate"] == 95.07
    assert body["settlement_gap"] == 23_800_000
    assert 0 <= body["settlement_rate"] <= 100
    assert 0 <= body["sla_rate"] <= 100
    assert body["merchant_risk_count"] == 1          # M108: 88.4% and 72.5%


@pytest.mark.parametrize("params", [
    {"start_date": "2026-13-45", "end_date": "2026-09-07"},     # not a real date
    {"start_date": "07-09-2026", "end_date": "2026-09-07"},     # wrong format
    {"start_date": "2026-09-07", "end_date": "2026-09-01"},     # end before start
])
def test_400_invalid_date(client, params):
    assert client.get("/api/v1/settlement-summary", params=params, headers=HEADERS).status_code == 400


def test_404_unknown_merchant(client):
    r = client.get("/api/v1/settlement-summary", params={**RANGE, "merchant_id": "M999"}, headers=HEADERS)
    assert r.status_code == 404


@pytest.mark.parametrize("params", [
    {**RANGE, "merchant_id": "abc"},                      # bad format
    {**RANGE, "merchant_id": "M100' OR '1'='1"},          # SQL-injection attempt
    {"end_date": "2026-09-07"},                           # missing required parameter
])
def test_422_invalid_parameter(client, params):
    assert client.get("/api/v1/settlement-summary", params=params, headers=HEADERS).status_code == 422


def test_401_without_or_with_wrong_api_key(client):
    assert client.get("/api/v1/settlement-summary", params=RANGE).status_code == 401
    assert client.get("/api/v1/settlement-summary", params=RANGE,
                      headers={"X-API-Key": "wrong"}).status_code == 401


def test_merchant_exceptions_returns_only_exceptions(client):
    r = client.get("/api/v1/merchant-exceptions", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert [m["merchant_id"] for m in body] == ["M108"]
    assert body[0] == {"merchant_id": "M108", "merchant_name": "ABC Retail", "settlement_rate": 88.4,
                       "sla_rate": 72.5, "risk_level": "HIGH", "settlement_gap": 11600.0}


def test_merchant_performance_sorted_by_gap(client):
    body = client.get("/api/v1/merchant-performance", params=RANGE, headers=HEADERS).json()
    assert [m["merchant_id"] for m in body] == ["M108", "M100"]
    assert all(0 <= m["settlement_rate"] <= 100 for m in body)


def test_other_endpoints(client):
    assert client.get("/api/v1/daily-trend", params=RANGE, headers=HEADERS).status_code == 200
    assert client.get("/api/v1/gap-breakdown", params=RANGE, headers=HEADERS).status_code == 200
    assert client.get("/api/v1/data-quality", headers=HEADERS).status_code == 200
    assert client.get("/api/v1/data-range", headers=HEADERS).json() == {"min_date": "2026-09-01",
                                                                         "max_date": "2026-09-08"}


def test_health_needs_no_key(client):
    assert client.get("/health").json() == {"status": "ok", "database": "ok"}


def test_openapi_docs_available(client):
    assert "/api/v1/settlement-summary" in client.get("/openapi.json").json()["paths"]
