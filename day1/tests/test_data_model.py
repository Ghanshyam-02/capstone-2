"""DATA-MODEL TESTS on the full dataset (Day 1 Task 4B)."""


def test_grain_no_duplicate_keys(full_db):
    # the brief's exact query, for every fact table: must return 0 rows
    for table, key in [("gold.fact_transaction", "transaction_id"),
                       ("gold.fact_settlement", "settlement_id"),
                       ("gold.fact_payment_event", "event_id")]:
        assert full_db(f"SELECT {key}, COUNT(*) FROM {table} GROUP BY {key} HAVING COUNT(*) > 1") == []


def test_referential_integrity(full_db):
    # transactions must not reference nonexistent merchants
    assert full_db("SELECT t.transaction_id FROM gold.fact_transaction t "
                   "LEFT JOIN gold.dim_merchant m ON m.merchant_sk = t.merchant_sk WHERE m.merchant_sk IS NULL") == []
    # settlements must not reference nonexistent transactions
    assert full_db("SELECT s.settlement_id FROM gold.fact_settlement s "
                   "LEFT JOIN gold.fact_transaction t USING (transaction_id) WHERE t.transaction_id IS NULL") == []


def test_settlement_reconciliation(full_db):
    # successful transactions = settled + unsettled
    successful, settled, unsettled = full_db(
        "SELECT SUM(amount), SUM(settled_amount), SUM(gap_amount) FROM gold.v_txn_settlement")[0]
    assert successful == settled + unsettled
    # and the KPI table the API reads adds up to the same total
    assert full_db("SELECT SUM(success_amount) FROM gold.agg_merchant_daily")[0][0] == successful
