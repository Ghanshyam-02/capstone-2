"""TDD / unit tests for the data-quality and settlement rules (brief: Task 4A).

Run:  pytest tests/unit -v      (no database needed, < 1 second)
"""
from datetime import date, datetime
from decimal import Decimal

from pipeline import rules

MERCHANTS = {"M100", "M101"}
TXNS = {"T1", "T2"}


def txn(**overrides):
    row = dict(transaction_id="T1", merchant_id="M100", customer_id="C1", transaction_ts="2026-09-01 10:00:00",
               amount="1000.00", currency="INR", status="SUCCESS", payment_channel="POS")
    row.update(overrides)
    return row


def settlement(**overrides):
    row = dict(settlement_id="S1", transaction_id="T1", settlement_ts="2026-09-01 10:10:00",
               settlement_amount="1000.00", settlement_status="SETTLED", settlement_batch="B1")
    row.update(overrides)
    return row


def event(**overrides):
    row = dict(event_id="E1", transaction_id="T1", event_type="CREATED", event_ts="2026-09-01 10:02:15",
               ingestion_ts="2026-09-01 10:02:20", processing_ms="120")
    row.update(overrides)
    return row


# ---------------------------------------------------------------- transactions
def test_successful_transaction_is_accepted_and_typed():
    result = rules.validate_transaction(txn(), MERCHANTS)
    assert result.severity == rules.OK
    assert result.record["amount"] == Decimal("1000.00")
    assert result.record["transaction_ts"] == datetime(2026, 9, 1, 10, 0)


def test_failed_transaction_is_valid_but_not_counted_in_kpis():
    result = rules.validate_transaction(txn(status="FAILED"), MERCHANTS)
    assert result.severity == rules.OK
    totals = rules.reconcile([result.record], [])
    assert totals["success_count"] == 0 and totals["success_amount"] == 0


def test_missing_merchant_is_quarantined():
    result = rules.validate_transaction(txn(merchant_id="  "), MERCHANTS)
    assert (result.severity, result.reason) == (rules.QUARANTINE, "MISSING_MERCHANT_ID")
    assert not result.keep


def test_unknown_merchant_is_quarantined():
    result = rules.validate_transaction(txn(merchant_id="M999"), MERCHANTS)
    assert result.reason == "UNKNOWN_MERCHANT"


def test_invalid_currency_is_quarantined_but_messy_valid_currency_is_cleaned():
    assert rules.validate_transaction(txn(currency="XYZ"), MERCHANTS).reason == "INVALID_CURRENCY"
    cleaned = rules.validate_transaction(txn(currency=" inr "), MERCHANTS)
    assert cleaned.severity == rules.OK and cleaned.record["currency"] == "INR"


def test_unreadable_timestamp_is_rejected():
    result = rules.validate_transaction(txn(transaction_ts="2026-09-31 25:61:00"), MERCHANTS)
    assert (result.severity, result.reason) == (rules.REJECT, "INVALID_TIMESTAMP")


# ---------------------------------------------------------------- settlements
def test_unmatched_settlement_is_quarantined():
    result = rules.validate_settlement(settlement(transaction_id="T404"), TXNS)
    assert (result.severity, result.reason) == (rules.QUARANTINE, "UNMATCHED_SETTLEMENT")


def test_negative_settlement_is_quarantined():
    result = rules.validate_settlement(settlement(settlement_amount="-500"), TXNS)
    assert (result.severity, result.reason) == (rules.QUARANTINE, "NEGATIVE_SETTLEMENT_AMOUNT")


# ---------------------------------------------------------------- events
def test_late_event_is_kept_with_warning():
    # the brief's example: event 10:02:15, ingested 10:08:41 (6m26s later)
    result = rules.validate_event(event(ingestion_ts="2026-09-01 10:08:41"), TXNS, late_threshold_min=5)
    assert (result.severity, result.reason) == (rules.WARNING, "LATE_EVENT")
    assert result.keep and result.record["is_late"] is True
    assert result.record["ingestion_delay_sec"] == 386


def test_on_time_event_is_ok():
    result = rules.validate_event(event(), TXNS)
    assert result.severity == rules.OK and result.record["is_late"] is False


def test_duplicate_event_is_rejected_within_batch_and_across_batches():
    first = rules.validate_event(event(event_id="E1"), TXNS).record
    again = rules.validate_event(event(event_id="E1", ingestion_ts="2026-09-01 10:03:00"), TXNS).record
    other = rules.validate_event(event(event_id="E2"), TXNS).record

    kept, dups = rules.split_duplicates([again, first, other], "event_id", sort_key=lambda r: r["ingestion_ts"])
    assert [r["event_id"] for r in kept] == ["E1", "E2"]
    assert kept[0]["ingestion_ts"] == first["ingestion_ts"]        # earliest copy wins
    assert len(dups) == 1

    kept, dups = rules.split_duplicates([other], "event_id", existing_keys={"E2"})
    assert kept == [] and len(dups) == 1                           # already loaded last run


# ---------------------------------------------------------------- settlement calculation
def _s(amount, status="SETTLED", minute=10):
    return {"settlement_amount": Decimal(amount), "settlement_status": status,
            "settlement_ts": datetime(2026, 9, 1, 10, minute)}


TXN_TS = datetime(2026, 9, 1, 10, 0)


def test_split_settlement_is_summed_not_double_counted():
    # T1001 from the brief: 10,000 settled as 8,000 + 2,000
    summary = rules.summarize_settlement(Decimal("10000"), TXN_TS, [_s("8000"), _s("2000", minute=12)])
    assert summary["settled_amount"] == Decimal("10000")
    assert summary["gap_amount"] == 0
    assert summary["settlement_class"] == "SETTLED"
    assert summary["sla_met"] is True


def test_partial_pending_failed_and_unsettled_classes():
    amount = Decimal("1000")
    assert rules.summarize_settlement(amount, TXN_TS, [_s("400")])["settlement_class"] == "PARTIALLY_SETTLED"
    assert rules.summarize_settlement(amount, TXN_TS, [_s("1000", "PENDING")])["settlement_class"] == "PENDING"
    assert rules.summarize_settlement(amount, TXN_TS, [_s("1000", "FAILED")])["settlement_class"] == "SETTLEMENT_FAILED"
    unsettled = rules.summarize_settlement(amount, TXN_TS, [])
    assert unsettled["settlement_class"] == "UNSETTLED" and unsettled["gap_amount"] == amount


def test_settlement_after_30_minutes_misses_sla():
    summary = rules.summarize_settlement(Decimal("1000"), TXN_TS, [_s("1000", minute=45)])
    assert summary["settlement_class"] == "SETTLED" and summary["sla_met"] is False


def test_over_settlement_is_capped_at_transaction_amount():
    summary = rules.summarize_settlement(Decimal("1000"), TXN_TS, [_s("1000"), _s("1000")])
    assert summary["settled_amount"] == Decimal("1000")


def test_reconciliation_successful_equals_settled_plus_gap():
    txns = [
        {"transaction_id": "T1", "status": "SUCCESS", "amount": Decimal("10000"), "transaction_ts": TXN_TS},
        {"transaction_id": "T2", "status": "SUCCESS", "amount": Decimal("500"), "transaction_ts": TXN_TS},
        {"transaction_id": "T3", "status": "FAILED", "amount": Decimal("999"), "transaction_ts": TXN_TS},
    ]
    stl = [dict(_s("8000"), transaction_id="T1"), dict(_s("2000"), transaction_id="T1")]
    totals = rules.reconcile(txns, stl)
    assert totals["success_amount"] == Decimal("10500")
    assert totals["settled_amount"] == Decimal("10000")
    assert totals["success_amount"] == totals["settled_amount"] + totals["gap_amount"]
    assert totals["by_class"]["UNSETTLED"] == {"count": 1, "amount": Decimal("500")}


# ---------------------------------------------------------------- merchant risk history
def test_risk_level_is_taken_as_of_transaction_date():
    history = [
        {"risk_level": "LOW", "effective_from": date(2026, 1, 1), "effective_to": date(2026, 3, 31)},
        {"risk_level": "HIGH", "effective_from": date(2026, 4, 1), "effective_to": date(2026, 6, 30)},
        {"risk_level": "MEDIUM", "effective_from": date(2026, 7, 1), "effective_to": None},
    ]
    assert rules.risk_as_of(history, date(2026, 2, 15)) == "LOW"
    assert rules.risk_as_of(history, date(2026, 5, 1)) == "HIGH"
    assert rules.risk_as_of(history, date(2026, 9, 1)) == "MEDIUM"
