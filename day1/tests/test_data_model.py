"""DATA-MODEL TESTS on the full dataset (Day 1 Task 4B, Day 2 data tests)."""
import pytest


# ---- Grain: the brief's exact test, for every fact table
@pytest.mark.parametrize("table, key", [("gold.fact_transaction", "transaction_id"),
                                        ("gold.fact_settlement", "settlement_id"),
                                        ("gold.fact_payment_event", "event_id"),
                                        ("gold.agg_merchant_daily", "txn_date, merchant_id")])
def test_fact_table_grain(full_db, table, key):
    assert full_db(f"SELECT {key}, COUNT(*) FROM {table} GROUP BY {key} HAVING COUNT(*) > 1") == []


def test_duplicate_events_in_the_source_were_detected(full_db):
    assert full_db("SELECT COUNT(*) FROM audit.dq_log WHERE reason = 'DUPLICATE_EVENT_ID'")[0][0] > 0


# ---- Referential integrity
def test_transactions_do_not_reference_nonexistent_merchants(full_db):
    assert full_db("SELECT t.transaction_id FROM gold.fact_transaction t "
                   "LEFT JOIN gold.dim_merchant m ON m.merchant_sk = t.merchant_sk WHERE m.merchant_sk IS NULL") == []


def test_settlements_reference_existing_transactions(full_db):
    assert full_db("SELECT s.settlement_id FROM gold.fact_settlement s "
                   "LEFT JOIN gold.fact_transaction t USING (transaction_id) WHERE t.transaction_id IS NULL") == []


# ---- Transaction / settlement reconciliation
def test_successful_equals_settled_plus_unsettled(full_db):
    successful, settled, unsettled = full_db(
        "SELECT SUM(amount), SUM(settled_amount), SUM(gap_amount) FROM gold.v_txn_settlement")[0]
    assert successful == settled + unsettled


def test_kpi_table_reconciles_with_the_facts(full_db):
    facts = full_db("SELECT COUNT(*), SUM(amount) FROM gold.fact_transaction WHERE status = 'SUCCESS'")[0]
    kpis = full_db("SELECT SUM(success_count), SUM(success_amount) FROM gold.agg_merchant_daily")[0]
    assert facts == kpis


def test_settled_amount_never_exceeds_successful_amount(full_db):
    assert full_db("SELECT merchant_id FROM gold.agg_merchant_daily GROUP BY merchant_id "
                   "HAVING SUM(settled_amount) > SUM(success_amount)") == []


# ---- Invalid data handling: nothing disappears silently
def test_every_bronze_row_is_in_silver_or_the_dq_log(full_db):
    bronze = full_db("SELECT COUNT(*) FROM bronze.transactions")[0][0]
    silver = full_db("SELECT COUNT(*) FROM silver.transactions")[0][0]
    logged = full_db("SELECT COUNT(*) FROM audit.dq_log WHERE source = 'transactions'")[0][0]
    assert bronze == silver + logged


def test_only_valid_values_reach_gold(full_db):
    assert full_db("SELECT 1 FROM gold.fact_settlement WHERE settlement_amount < 0") == []
    assert full_db("SELECT 1 FROM gold.fact_transaction WHERE currency <> 'INR'") == []


def test_split_settlement_t1001_counted_once(full_db):
    assert full_db("SELECT amount, settled_amount, settlement_records FROM gold.v_txn_settlement "
                   "WHERE transaction_id = 'T1001'") == [(10000, 10000, 2)]


def test_risk_level_as_of_transaction_date(full_db):
    # M101 is LOW until 14 Sep and HIGH from 15 Sep
    assert full_db("SELECT DISTINCT risk_level_at_txn FROM gold.fact_transaction "
                   "WHERE merchant_id = 'M101' AND transaction_ts < '2026-09-15'") == [("LOW",)]
    assert full_db("SELECT DISTINCT risk_level_at_txn FROM gold.fact_transaction "
                   "WHERE merchant_id = 'M101' AND transaction_ts >= '2026-09-15'") == [("HIGH",)]
