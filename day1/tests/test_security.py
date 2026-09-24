"""SECURITY TESTS (Day 1 Task 4D)."""
import re

import duckdb
import pytest
from fastapi.testclient import TestClient

from api.main import app
from common.config import PROJECT_ROOT, db_path

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


def test_api_database_connection_is_read_only(full_db):
    con = duckdb.connect(str(db_path()), read_only=True)
    with pytest.raises(duckdb.Error):
        con.execute("DELETE FROM gold.fact_transaction")
    con.close()


def test_no_hard_coded_secrets_in_the_code():
    pattern = re.compile(r"(api_key|password|secret|token)\s*=\s*['\"][A-Za-z0-9_\-]{12,}['\"]", re.IGNORECASE)
    for path in list(PROJECT_ROOT.glob("**/*.py")) + list(PROJECT_ROOT.glob("**/*.sql")):
        if ".venv" in path.parts or "tests" in path.parts:
            continue
        assert not pattern.search(path.read_text(encoding="utf-8")), f"possible secret in {path}"


def test_api_never_returns_customer_ids(client):
    text = client.get("/api/v1/merchant-exceptions", headers={"X-API-Key": "test-key"}).text
    assert "customer" not in text.lower() and not re.search(r"C\d{5}", text)
