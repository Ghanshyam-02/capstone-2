"""Data-model tests against the REAL Snowflake tables (brief: Task 4B).

Snowflake does not enforce PK/FK, so these tests are what proves grain and
referential integrity. Run after the pipeline:

    Windows PowerShell:  $env:RUN_SNOWFLAKE_TESTS="1"; pytest tests/data_model -v
    macOS / Linux:       RUN_SNOWFLAKE_TESTS=1 pytest tests/data_model -v
"""
import os

import pytest

pytestmark = [
    pytest.mark.snowflake,
    pytest.mark.skipif(os.getenv("RUN_SNOWFLAKE_TESTS") != "1", reason="set RUN_SNOWFLAKE_TESTS=1 to run"),
]


@pytest.fixture(scope="module")
def cur():
    from common import config
    from common.snowflake_conn import get_connection
    conn = get_connection(config.SNOWFLAKE_PIPELINE_ROLE)
    yield conn.cursor()
    conn.close()


def rows(cur, sql):
    return cur.execute(sql).fetchall()


# ---------------------------------------------------------------- grain
@pytest.mark.parametrize("table, key", [
    ("GOLD.FACT_TRANSACTION", "TRANSACTION_ID"),
    ("GOLD.FACT_SETTLEMENT", "SETTLEMENT_ID"),
    ("GOLD.FACT_PAYMENT_EVENT", "EVENT_ID"),
    ("GOLD.DIM_MERCHANT", "MERCHANT_ID, EFFECTIVE_FROM"),
    ("GOLD.AGG_MERCHANT_DAILY", "TXN_DATE, MERCHANT_ID"),
    ("SILVER.TRANSACTIONS", "TRANSACTION_ID"),
])
def test_grain_has_no_duplicates(cur, table, key):
    dupes = rows(cur, f"SELECT {key}, COUNT(*) FROM {table} GROUP BY {key} HAVING COUNT(*) > 1")  # nosec B608
    assert dupes == [], f"{table} grain broken: {dupes[:5]}"


def test_view_has_one_row_per_transaction(cur):
    view, fact = rows(cur, "SELECT (SELECT COUNT(*) FROM GOLD.V_TXN_SETTLEMENT), "
                           "(SELECT COUNT(*) FROM GOLD.FACT_TRANSACTION)")[0]
    assert view == fact


# ---------------------------------------------------------------- referential integrity
def test_transactions_reference_existing_merchants(cur):
    assert rows(cur, "SELECT t.TRANSACTION_ID FROM GOLD.FACT_TRANSACTION t "
                     "LEFT JOIN GOLD.DIM_MERCHANT m ON m.MERCHANT_SK = t.MERCHANT_SK "
                     "WHERE m.MERCHANT_SK IS NULL") == []


def test_settlements_reference_existing_transactions(cur):
    assert rows(cur, "SELECT s.SETTLEMENT_ID FROM GOLD.FACT_SETTLEMENT s "
                     "LEFT JOIN GOLD.FACT_TRANSACTION t ON t.TRANSACTION_ID = s.TRANSACTION_ID "
                     "WHERE t.TRANSACTION_ID IS NULL") == []


def test_facts_reference_existing_dates(cur):
    assert rows(cur, "SELECT f.TRANSACTION_ID FROM GOLD.FACT_TRANSACTION f "
                     "LEFT JOIN GOLD.DIM_DATE d ON d.DATE_KEY = f.DATE_KEY WHERE d.DATE_KEY IS NULL") == []


# ---------------------------------------------------------------- reconciliation
def test_successful_equals_settled_plus_unsettled(cur):
    success, settled, gap = rows(cur, "SELECT SUM(AMOUNT), SUM(SETTLED_AMOUNT), SUM(GAP_AMOUNT) "
                                      "FROM GOLD.V_TXN_SETTLEMENT WHERE STATUS = 'SUCCESS'")[0]
    assert success == settled + gap


def test_kpi_table_matches_transaction_level_view(cur):
    agg = rows(cur, "SELECT SUM(SUCCESS_AMOUNT), SUM(SETTLED_AMOUNT), SUM(SUCCESS_COUNT) "
                    "FROM GOLD.AGG_MERCHANT_DAILY")[0]
    view = rows(cur, "SELECT SUM(AMOUNT), SUM(SETTLED_AMOUNT), COUNT(*) "
                     "FROM GOLD.V_TXN_SETTLEMENT WHERE STATUS = 'SUCCESS'")[0]
    assert agg == view


def test_gap_categories_add_up_to_total_gap(cur):
    total, parts = rows(cur, "SELECT SUM(SUCCESS_AMOUNT - SETTLED_AMOUNT), "
                             "SUM(GAP_PARTIAL_AMT + GAP_PENDING_AMT + GAP_FAILED_AMT + GAP_UNSETTLED_AMT) "
                             "FROM GOLD.AGG_MERCHANT_DAILY")[0]
    assert total == parts


def test_split_settlement_t1001_counted_once(cur):
    amount, settled, records = rows(cur, "SELECT AMOUNT, SETTLED_AMOUNT, SETTLEMENT_RECORDS "
                                         "FROM GOLD.V_TXN_SETTLEMENT WHERE TRANSACTION_ID = 'T1001'")[0]
    assert (amount, settled, records) == (10000, 10000, 2)


# ---------------------------------------------------------------- business rules
def test_point_in_time_risk_for_m101(cur):
    # M101 is LOW until 2026-09-03 and HIGH from 2026-09-04
    wrong = rows(cur, "SELECT TRANSACTION_ID FROM GOLD.FACT_TRANSACTION WHERE MERCHANT_ID = 'M101' AND ("
                      "(TRANSACTION_TS::DATE <= '2026-09-03' AND RISK_LEVEL_AT_TXN <> 'LOW') OR "
                      "(TRANSACTION_TS::DATE >= '2026-09-04' AND RISK_LEVEL_AT_TXN <> 'HIGH'))")
    assert wrong == []


def test_only_valid_values_reach_gold(cur):
    assert rows(cur, "SELECT 1 FROM GOLD.FACT_TRANSACTION WHERE CURRENCY <> 'INR' OR AMOUNT <= 0 "
                     "OR STATUS NOT IN ('SUCCESS','FAILED','REVERSED')") == []
    assert rows(cur, "SELECT 1 FROM GOLD.FACT_SETTLEMENT WHERE SETTLEMENT_AMOUNT < 0") == []


def test_invalid_records_did_not_disappear(cur):
    reasons = {r[0] for r in rows(cur, "SELECT DISTINCT REASON FROM AUDIT.DQ_LOG")}
    assert {"MISSING_MERCHANT_ID", "INVALID_CURRENCY", "NEGATIVE_SETTLEMENT_AMOUNT",
            "UNMATCHED_SETTLEMENT", "DUPLICATE_EVENT_ID", "LATE_EVENT"} <= reasons
