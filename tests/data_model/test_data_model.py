"""Data-model tests on the REAL Snowflake tables (Task 4B). Run AFTER the pipeline:

    PowerShell:  $env:RUN_SNOWFLAKE_TESTS="1"; pytest tests/data_model -v

Snowflake does not enforce primary/foreign keys, so these tests are the proof.
"""
import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_SNOWFLAKE_TESTS") != "1",
                                reason="set RUN_SNOWFLAKE_TESTS=1 to run against Snowflake")


@pytest.fixture(scope="module")
def sql():
    from common import config
    from common.snowflake_conn import get_connection
    conn = get_connection(config.SNOWFLAKE_PIPELINE_ROLE)
    yield lambda query: conn.cursor().execute(query).fetchall()
    conn.close()


# ---- Grain: the brief's exact test, for every fact table
@pytest.mark.parametrize("table, key", [("GOLD.FACT_TRANSACTION", "TRANSACTION_ID"),
                                        ("GOLD.FACT_SETTLEMENT", "SETTLEMENT_ID"),
                                        ("GOLD.FACT_PAYMENT_EVENT", "EVENT_ID")])
def test_grain(sql, table, key):
    assert sql(f"SELECT {key}, COUNT(*) FROM {table} GROUP BY {key} HAVING COUNT(*) > 1") == []


# ---- Referential integrity
def test_transactions_do_not_reference_nonexistent_merchants(sql):
    assert sql("SELECT t.TRANSACTION_ID FROM GOLD.FACT_TRANSACTION t "
               "LEFT JOIN GOLD.DIM_MERCHANT m ON m.MERCHANT_SK = t.MERCHANT_SK "
               "WHERE m.MERCHANT_SK IS NULL") == []


def test_settlements_reference_existing_transactions(sql):
    assert sql("SELECT s.SETTLEMENT_ID FROM GOLD.FACT_SETTLEMENT s "
               "LEFT JOIN GOLD.FACT_TRANSACTION t ON t.TRANSACTION_ID = s.TRANSACTION_ID "
               "WHERE t.TRANSACTION_ID IS NULL") == []


# ---- Settlement reconciliation: successful = settled + unsettled
def test_settlement_reconciliation(sql):
    successful, settled, unsettled = sql(
        "SELECT SUM(AMOUNT), SUM(SETTLED_AMOUNT), SUM(GAP_AMOUNT) FROM GOLD.V_TXN_SETTLEMENT")[0]
    assert successful == settled + unsettled

    fact_total = sql("SELECT SUM(AMOUNT) FROM GOLD.FACT_TRANSACTION WHERE STATUS = 'SUCCESS'")[0][0]
    kpi_total = sql("SELECT SUM(SUCCESS_AMOUNT) FROM GOLD.AGG_MERCHANT_DAILY")[0][0]
    assert successful == fact_total == kpi_total


def test_transaction_count_reconciliation(sql):
    # every successful transaction is in exactly one bucket: settled / partly / pending / unsettled
    successful = sql("SELECT COUNT(*) FROM GOLD.FACT_TRANSACTION WHERE STATUS = 'SUCCESS'")[0][0]
    buckets = sql("SELECT SETTLEMENT_CLASS, COUNT(*) FROM GOLD.V_TXN_SETTLEMENT GROUP BY 1")
    assert successful == sum(count for _, count in buckets)
    assert successful == sql("SELECT SUM(SUCCESS_COUNT) FROM GOLD.AGG_MERCHANT_DAILY")[0][0]


def test_split_settlement_counted_once(sql):
    assert sql("SELECT AMOUNT, SETTLED_AMOUNT, SETTLEMENT_RECORDS FROM GOLD.V_TXN_SETTLEMENT "
               "WHERE TRANSACTION_ID = 'T1001'") == [(10000, 10000, 2)]
