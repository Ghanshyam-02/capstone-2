"""BUSINESS-RULE TESTS - one per case in the brief (Day 1 Task 4A).

Each test writes a few hand-made rows, runs the REAL pipeline on them, and checks
what landed in Silver / Gold / the DQ log.
"""
from tests.conftest import evt, stl, txn


def dq(q, reason):
    return q("SELECT severity FROM audit.dq_log WHERE reason = ?", [reason])


def test_successful_transaction(tiny_db):
    q = tiny_db({"transactions": [txn()]})
    assert q("SELECT transaction_id, amount, status FROM gold.fact_transaction") == [("T1", 1000, "SUCCESS")]


def test_failed_transaction_is_kept_but_not_counted_in_kpis(tiny_db):
    q = tiny_db({"transactions": [txn("T1"), txn("T2", status="FAILED")]})
    assert q("SELECT COUNT(*) FROM gold.fact_transaction") == [(2,)]                   # both are real attempts
    assert q("SELECT SUM(success_count), SUM(success_amount) FROM gold.agg_merchant_daily") == [(1, 1000)]


def test_duplicate_event_is_rejected(tiny_db):
    q = tiny_db({"transactions": [txn()],
                 "payment_events": [evt("E1"), evt("E1", received="2026-09-01 10:00:09")]})
    assert q("SELECT COUNT(*) FROM gold.fact_payment_event") == [(1,)]
    assert dq(q, "DUPLICATE_EVENT_ID") == [("REJECT",)]


def test_missing_merchant_is_quarantined(tiny_db):
    q = tiny_db({"transactions": [txn(merchant="")]})
    assert q("SELECT COUNT(*) FROM silver.transactions") == [(0,)]
    assert dq(q, "MISSING_MERCHANT_ID") == [("QUARANTINE",)]


def test_invalid_currency_is_quarantined_but_messy_valid_currency_is_cleaned(tiny_db):
    q = tiny_db({"transactions": [txn("T1", currency="XYZ"), txn("T2", currency=" inr ")]})
    assert dq(q, "INVALID_CURRENCY") == [("QUARANTINE",)]
    assert q("SELECT transaction_id, currency FROM silver.transactions") == [("T2", "INR")]


def test_unmatched_settlement_is_quarantined(tiny_db):
    q = tiny_db({"transactions": [txn()], "settlements": [stl("S1", tid="T404")]})
    assert dq(q, "UNMATCHED_SETTLEMENT") == [("QUARANTINE",)]


def test_negative_settlement_is_quarantined(tiny_db):
    q = tiny_db({"transactions": [txn()], "settlements": [stl("S1", amount="-500")]})
    assert q("SELECT COUNT(*) FROM gold.fact_settlement") == [(0,)]
    assert dq(q, "NEGATIVE_SETTLEMENT_AMOUNT") == [("QUARANTINE",)]


def test_late_event_is_kept_with_a_warning(tiny_db):
    # the brief's example: happened 10:02:15, received 10:08:41 (6 min 26 s later)
    q = tiny_db({"transactions": [txn()],
                 "payment_events": [evt("E1", ts="2026-09-01 10:02:15", received="2026-09-01 10:08:41")]})
    assert q("SELECT is_late, ingestion_delay_sec FROM gold.fact_payment_event") == [(True, 386)]
    assert dq(q, "LATE_EVENT") == [("WARNING",)]


def test_out_of_order_events_are_sequenced_by_business_time(tiny_db):
    q = tiny_db({"transactions": [txn()], "payment_events": [
        evt("E3", etype="SETTLED", ts="2026-09-01 10:03:00", received="2026-09-01 10:03:01"),
        evt("E2", etype="AUTHORIZED", ts="2026-09-01 10:01:00", received="2026-09-01 10:01:01"),
        evt("E1", etype="CREATED", ts="2026-09-01 10:00:00", received="2026-09-01 10:04:00")]})
    assert q("SELECT event_type FROM gold.fact_payment_event ORDER BY event_seq") == \
        [("CREATED",), ("AUTHORIZED",), ("SETTLED",)]


def test_settlement_calculation_and_gap(tiny_db):
    q = tiny_db({"transactions": [txn("T1"), txn("T2", amount="500.00")],
                 "settlements": [stl("S1", "T1", amount="600.00")]})          # T1 partly, T2 not at all
    assert q("SELECT transaction_id, settled_amount, gap_amount, settlement_class FROM gold.v_txn_settlement "
             "ORDER BY 1") == [("T1", 600, 400, "PARTIALLY_SETTLED"), ("T2", 0, 500, "UNSETTLED")]


def test_multiple_settlements_do_not_inflate_the_settlement_rate(tiny_db):
    """MANDATORY NEGATIVE TEST (Day 2): 10,000 settled as 8,000 + 2,000 must give 100 %, not 200 %."""
    q = tiny_db({"transactions": [txn(amount="10000.00")],
                 "settlements": [stl("S1", amount="8000.00"), stl("S2", amount="2000.00", ts="2026-09-01 10:12:00")]})
    assert q("SELECT settled_amount, settlement_records FROM gold.v_txn_settlement") == [(10000, 2)]
    success, settled = q("SELECT SUM(success_amount), SUM(settled_amount) FROM gold.agg_merchant_daily")[0]
    assert settled / success * 100 == 100


def test_sla_is_missed_when_settled_after_30_minutes(tiny_db):
    q = tiny_db({"transactions": [txn("T1"), txn("T2")],
                 "settlements": [stl("S1", "T1", ts="2026-09-01 10:20:00"),
                                 stl("S2", "T2", ts="2026-09-01 10:45:00")]})
    assert q("SELECT transaction_id, sla_met FROM gold.v_txn_settlement ORDER BY 1") == [("T1", 1), ("T2", 0)]
    assert q("SELECT transaction_id, exception_type, settlement_delay_min FROM gold.v_settlement_exceptions") == \
        [("T2", "DELAYED", 45)]
