"""Unit tests - one per case listed in the brief (Task 4A). No database needed.

    pytest tests/unit -v
"""
from datetime import datetime
from decimal import Decimal

from common import kpi
from pipeline import rules

MERCHANTS = {"M100"}
TRANSACTIONS = {"T1"}


def txn(**change):
    row = dict(transaction_id="T1", merchant_id="M100", customer_id="C1", transaction_ts="2026-09-01 10:00:00",
               amount="1000.00", currency="INR", status="SUCCESS", payment_channel="POS")
    return {**row, **change}


def settlement(**change):
    row = dict(settlement_id="S1", transaction_id="T1", settlement_ts="2026-09-01 10:10:00",
               settlement_amount="1000.00", settlement_status="SETTLED", settlement_batch="B1")
    return {**row, **change}


def event(**change):
    row = dict(event_id="E1", transaction_id="T1", event_type="CREATED", event_ts="2026-09-01 10:02:15",
               ingestion_ts="2026-09-01 10:02:20", processing_ms="120")
    return {**row, **change}


def test_successful_transaction():
    result = rules.validate_transaction(txn(), MERCHANTS)
    assert result.severity == rules.OK
    assert result.record["amount"] == Decimal("1000.00")


def test_failed_transaction_is_valid_data():
    # a failed payment is a real event -> kept (the KPIs only count SUCCESS)
    result = rules.validate_transaction(txn(status="FAILED"), MERCHANTS)
    assert result.severity == rules.OK and result.record["status"] == "FAILED"


def test_duplicate_event():
    first = rules.validate_event(event(), TRANSACTIONS).record
    copy = rules.validate_event(event(ingestion_ts="2026-09-01 10:03:00"), TRANSACTIONS).record
    kept, duplicates = rules.remove_duplicate_events([copy, first], already_loaded=set())
    assert len(kept) == 1 and len(duplicates) == 1
    kept, duplicates = rules.remove_duplicate_events([first], already_loaded={"E1"})   # loaded last run
    assert kept == [] and len(duplicates) == 1


def test_missing_merchant():
    result = rules.validate_transaction(txn(merchant_id=""), MERCHANTS)
    assert (result.severity, result.reason) == (rules.QUARANTINE, "MISSING_MERCHANT_ID")


def test_invalid_currency():
    result = rules.validate_transaction(txn(currency="XYZ"), MERCHANTS)
    assert (result.severity, result.reason) == (rules.QUARANTINE, "INVALID_CURRENCY")


def test_unmatched_settlement():
    result = rules.validate_settlement(settlement(transaction_id="T404"), TRANSACTIONS)
    assert (result.severity, result.reason) == (rules.QUARANTINE, "UNMATCHED_SETTLEMENT")


def test_negative_settlement():
    result = rules.validate_settlement(settlement(settlement_amount="-500"), TRANSACTIONS)
    assert (result.severity, result.reason) == (rules.QUARANTINE, "NEGATIVE_SETTLEMENT_AMOUNT")


def test_late_event():
    # the brief's example: happened 10:02:15, received 10:08:41 -> late, but still kept
    result = rules.validate_event(event(ingestion_ts="2026-09-01 10:08:41"), TRANSACTIONS)
    assert (result.severity, result.reason) == (rules.WARNING, "LATE_EVENT")
    assert result.keep and result.record["is_late"]


def test_settlement_calculation():
    txn_ts = datetime(2026, 9, 1, 10, 0)

    def s(amount, status="SETTLED", minute=10):
        return {"settlement_amount": Decimal(amount), "settlement_status": status,
                "settlement_ts": datetime(2026, 9, 1, 10, minute)}

    # one-to-many: 10,000 settled as 8,000 + 2,000 -> counted once, fully settled, within SLA
    split = rules.summarize_settlement(Decimal("10000"), txn_ts, [s("8000"), s("2000", minute=12)])
    assert split == {"settled_amount": Decimal("10000"), "gap_amount": 0,
                     "settlement_class": "SETTLED", "sla_met": True}
    # nothing settled
    assert rules.summarize_settlement(Decimal("500"), txn_ts, [])["settlement_class"] == "UNSETTLED"
    # settled after 45 minutes -> SLA missed
    assert rules.summarize_settlement(Decimal("500"), txn_ts, [s("500", minute=45)])["sla_met"] is False


def test_kpi_formulas():
    # numbers from the brief's API example
    assert kpi.settlement_rate(458_700_000, 482_500_000) == 95.07
    assert kpi.settlement_gap(482_500_000, 458_700_000) == 23_800_000
    assert kpi.settlement_rate(150, 100) == 100.0          # never above 100
    assert kpi.is_merchant_exception(88.4, 99) and kpi.is_high_risk_merchant(88.4, 72.5)
