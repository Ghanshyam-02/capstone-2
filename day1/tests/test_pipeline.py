"""PIPELINE TEST - incremental processing."""
from tests.conftest import stl, txn


def test_pipeline_is_incremental(tiny_db):
    # batch 1: a PENDING settlement
    q = tiny_db({"transactions": [txn()], "settlements": [stl("S1", status="PENDING")]})
    assert q("SELECT settlement_class FROM gold.v_txn_settlement") == [("PENDING",)]

    # batch 2: only the new file is loaded, and the same settlement id now arrives as SETTLED
    q = tiny_db({"settlements": [stl("S1", ts="2026-09-02 09:00:00")]}, batch=2)
    assert q("SELECT COUNT(*) FROM bronze.transactions") == [(1,)]                 # batch 1 not loaded again
    assert q("SELECT settlement_class FROM gold.v_txn_settlement") == [("SETTLED",)]
    assert q("SELECT COUNT(*) FROM gold.fact_settlement") == [(1,)]                # updated, not duplicated
