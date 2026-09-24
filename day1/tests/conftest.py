"""Shared test fixtures.

- full_db   : builds a database from the REAL data in data/raw (once per test run)
- tiny_db   : builds a database from a few hand-written rows (for business-rule tests)
Tests never touch your own data/warehouse database: each uses a temporary file.
"""
import csv
import os
from pathlib import Path

import duckdb
import pytest

from pipeline.ingest import COLUMNS
from pipeline.run_pipeline import run

MERCHANT = dict(merchant_id="M100", merchant_name="Test Store", merchant_category="GROCERY", country="India",
                risk_level="LOW", effective_from="2026-01-01", effective_to="")


@pytest.fixture(scope="session")
def full_db(tmp_path_factory):
    """Database built from data/raw. Returns a function that runs a query."""
    path = tmp_path_factory.mktemp("full") / "settlement.duckdb"
    old = os.environ.get("SETTLEMENT_DB")
    os.environ["SETTLEMENT_DB"] = str(path)
    run()
    yield query_function(path)
    if old is None:
        os.environ.pop("SETTLEMENT_DB")
    else:
        os.environ["SETTLEMENT_DB"] = old


def write_csvs(folder: Path, batch: int, rows: dict):
    """Write one CSV per source, e.g. rows={"transactions": [{...}, {...}]}."""
    folder.mkdir(parents=True, exist_ok=True)
    for source, cols in COLUMNS.items():
        if source not in rows:
            continue
        with (folder / f"{source}_{batch:03d}.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=cols)
            writer.writeheader()
            writer.writerows(rows[source])


@pytest.fixture
def tiny_db(tmp_path, monkeypatch):
    """Returns build(rows, batch=1): writes CSVs, runs the pipeline, returns a query function."""
    monkeypatch.setenv("SETTLEMENT_DB", str(tmp_path / "tiny.duckdb"))
    raw = tmp_path / "raw"

    def build(rows: dict, batch: int = 1):
        rows = {"merchant": [MERCHANT], **rows} if batch == 1 else rows
        write_csvs(raw, batch, rows)
        run(raw)
        return query_function(tmp_path / "tiny.duckdb")

    return build


def query_function(path: Path):
    """Each query opens and closes its own read-only connection."""
    def query(sql, params=None):
        con = duckdb.connect(str(path), read_only=True)
        try:
            return con.execute(sql, params or []).fetchall()
        finally:
            con.close()
    return query


def txn(tid="T1", ts="2026-09-01 10:00:00", amount="1000.00", status="SUCCESS", merchant="M100", currency="INR"):
    return dict(transaction_id=tid, merchant_id=merchant, customer_id="C1", transaction_ts=ts,
                amount=amount, currency=currency, status=status, payment_channel="POS")


def stl(sid, tid="T1", ts="2026-09-01 10:10:00", amount="1000.00", status="SETTLED"):
    return dict(settlement_id=sid, transaction_id=tid, settlement_ts=ts, settlement_amount=amount,
                settlement_status=status, settlement_batch="B1")


def evt(eid, tid="T1", etype="CREATED", ts="2026-09-01 10:00:00", received="2026-09-01 10:00:05"):
    return dict(event_id=eid, transaction_id=tid, event_type=etype, event_ts=ts, ingestion_ts=received,
                processing_ms="100")
