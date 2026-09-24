"""PIPELINE TESTS - incremental processing and re-runs."""
from tests.conftest import stl, txn


def test_running_again_with_no_new_files_changes_nothing(tiny_db):
    q = tiny_db({"transactions": [txn()], "settlements": [stl("S1")]})
    q2 = tiny_db({"transactions": [txn()], "settlements": [stl("S1")]})       # same file name again
    assert q2("SELECT COUNT(*) FROM bronze.transactions") == [(1,)]           # not loaded twice
    assert q2("SELECT COUNT(*) FROM audit.pipeline_runs WHERE status = 'SUCCESS'") == [(2,)]


def test_new_batch_is_processed_incrementally_and_updates_a_pending_settlement(tiny_db):
    q = tiny_db({"transactions": [txn()], "settlements": [stl("S1", status="PENDING")]})
    assert q("SELECT settlement_class FROM gold.v_txn_settlement") == [("PENDING",)]

    # batch 2: the same settlement id arrives again, now SETTLED
    q = tiny_db({"settlements": [stl("S1", ts="2026-09-02 09:00:00")]}, batch=2)
    assert q("SELECT file_name FROM audit.loaded_files ORDER BY load_id") == \
        [("merchant_001.csv",), ("transactions_001.csv",), ("settlements_001.csv",), ("settlements_002.csv",)]
    assert q("SELECT settlement_class FROM gold.v_txn_settlement") == [("SETTLED",)]
    assert q("SELECT COUNT(*) FROM gold.fact_settlement") == [(1,)]                 # updated, not duplicated
    assert q("SELECT * FROM audit.watermark ORDER BY layer") == [("gold", 4), ("silver", 4)]
