"""API TESTS against the real database built from data/raw (Day 1 Task 4C)."""
import time

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


def test_200_valid_request_returns_the_contract(client, full_db):
    r = client.get(URL, params=SEPTEMBER, headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"transaction_count", "transaction_amount", "settled_amount",
                         "settlement_rate", "settlement_gap", "sla_rate"}
    # the API must return exactly what the database says
    count, amount, settled = full_db("SELECT SUM(success_count), SUM(success_amount), SUM(settled_amount) "
                                     "FROM gold.agg_merchant_daily")[0]
    assert body["transaction_count"] == count
    assert body["settlement_rate"] == round(float(settled) / float(amount) * 100, 2)
    assert 0 <= body["settlement_rate"] <= 100 and 0 <= body["sla_rate"] <= 100


def test_400_invalid_date(client):
    bad = client.get(URL, params={"start_date": "2026-13-45", "end_date": "2026-09-30"}, headers=HEADERS)
    backwards = client.get(URL, params={"start_date": "2026-09-30", "end_date": "2026-09-01"}, headers=HEADERS)
    assert bad.status_code == 400 and backwards.status_code == 400


def test_404_unknown_merchant(client):
    assert client.get(URL, params={**SEPTEMBER, "merchant_id": "M999"}, headers=HEADERS).status_code == 404


def test_422_invalid_parameter(client):
    assert client.get(URL, params={**SEPTEMBER, "merchant_id": "abc"}, headers=HEADERS).status_code == 422
    assert client.get(URL, params={"end_date": "2026-09-30"}, headers=HEADERS).status_code == 422   # missing


def test_single_merchant_summary(client):
    body = client.get(URL, params={**SEPTEMBER, "merchant_id": "M108"}, headers=HEADERS).json()
    assert body["settlement_rate"] < 95                      # M108 is an abnormal merchant


def test_merchant_exceptions(client):
    r = client.get("/api/v1/merchant-exceptions", headers=HEADERS)
    assert r.status_code == 200
    ids = {m["merchant_id"] for m in r.json()}
    assert {"M104", "M108", "M117", "M110", "M121"} <= ids
    assert all(m["settlement_rate"] < 95 or m["sla_rate"] < 90 for m in r.json())


def test_dashboard_endpoints(client):
    assert len(client.get("/api/v1/daily-trend", params=SEPTEMBER, headers=HEADERS).json()) == 30
    merchants = client.get("/api/v1/merchants", params=SEPTEMBER, headers=HEADERS).json()
    assert merchants[0]["settlement_gap"] >= merchants[-1]["settlement_gap"]      # biggest gap first


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["database"] == "ok" and "version" in body


def test_response_time_under_500_ms(client):
    started = time.perf_counter()
    client.get(URL, params=SEPTEMBER, headers=HEADERS)
    assert time.perf_counter() - started < 0.5
