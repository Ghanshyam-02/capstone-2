"""Data-quality and settlement rules - plain Python, so they are easy to unit-test.

Every Bronze row gets one of these results:
    OK          -> loaded into Silver
    WARNING     -> loaded into Silver AND logged        (late event)
    QUARANTINE  -> NOT loaded, logged for review        (missing merchant, bad currency, negative amount, orphan)
    REJECT      -> NOT loaded, logged                   (no id, unreadable value, duplicate)
"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

OK, WARNING, QUARANTINE, REJECT = "OK", "WARNING", "QUARANTINE", "REJECT"
SLA_SECONDS = 30 * 60


@dataclass
class Result:
    severity: str
    reason: str | None = None
    record: dict | None = None      # cleaned, typed row (only when it is kept)

    @property
    def keep(self) -> bool:
        return self.severity in (OK, WARNING)


def clean(value) -> str | None:
    value = str(value).strip() if value is not None else ""
    return value or None


def to_datetime(value) -> datetime | None:
    try:
        return datetime.fromisoformat(clean(value))
    except (TypeError, ValueError):
        return None


def to_amount(value) -> Decimal | None:
    try:
        return Decimal(clean(value)).quantize(Decimal("0.01"))
    except (TypeError, InvalidOperation):
        return None


# ---------------------------------------------------------------- validators
def validate_merchant(raw: dict) -> Result:
    if not clean(raw.get("merchant_id")):
        return Result(REJECT, "MISSING_MERCHANT_ID")
    risk = (clean(raw.get("risk_level")) or "").upper()
    if risk not in {"LOW", "MEDIUM", "HIGH"}:
        return Result(QUARANTINE, "INVALID_RISK_LEVEL")
    eff_from = to_datetime(raw.get("effective_from"))
    if eff_from is None:
        return Result(REJECT, "INVALID_EFFECTIVE_FROM")
    eff_to = to_datetime(raw.get("effective_to"))          # empty = still active
    return Result(OK, record={
        "merchant_id": clean(raw["merchant_id"]),
        "merchant_name": clean(raw.get("merchant_name")),
        "merchant_category": clean(raw.get("merchant_category")),
        "country": clean(raw.get("country")),
        "risk_level": risk,
        "effective_from": eff_from.date(),
        "effective_to": eff_to.date() if eff_to else None,
    })


def validate_transaction(raw: dict, known_merchants: set) -> Result:
    if not clean(raw.get("transaction_id")):
        return Result(REJECT, "MISSING_TRANSACTION_ID")
    ts, amount = to_datetime(raw.get("transaction_ts")), to_amount(raw.get("amount"))
    if ts is None:
        return Result(REJECT, "INVALID_TIMESTAMP")
    if amount is None:
        return Result(REJECT, "INVALID_AMOUNT")

    merchant_id = clean(raw.get("merchant_id"))
    if not merchant_id:
        return Result(QUARANTINE, "MISSING_MERCHANT_ID")
    if merchant_id not in known_merchants:
        return Result(QUARANTINE, "UNKNOWN_MERCHANT")
    currency = (clean(raw.get("currency")) or "").upper()
    if currency != "INR":
        return Result(QUARANTINE, "INVALID_CURRENCY")
    status = (clean(raw.get("status")) or "").upper()
    if status not in {"SUCCESS", "FAILED", "REVERSED"}:
        return Result(QUARANTINE, "INVALID_STATUS")

    return Result(OK, record={
        "transaction_id": clean(raw["transaction_id"]),
        "merchant_id": merchant_id,
        "customer_id": clean(raw.get("customer_id")),
        "transaction_ts": ts,
        "amount": amount,
        "currency": currency,
        "status": status,
        "payment_channel": (clean(raw.get("payment_channel")) or "").upper(),
    })


def validate_settlement(raw: dict, known_transactions: set) -> Result:
    if not clean(raw.get("settlement_id")):
        return Result(REJECT, "MISSING_SETTLEMENT_ID")
    ts, amount = to_datetime(raw.get("settlement_ts")), to_amount(raw.get("settlement_amount"))
    if ts is None:
        return Result(REJECT, "INVALID_TIMESTAMP")
    if amount is None:
        return Result(REJECT, "INVALID_AMOUNT")

    if amount < 0:
        return Result(QUARANTINE, "NEGATIVE_SETTLEMENT_AMOUNT")
    if clean(raw.get("transaction_id")) not in known_transactions:
        return Result(QUARANTINE, "UNMATCHED_SETTLEMENT")

    return Result(OK, record={
        "settlement_id": clean(raw["settlement_id"]),
        "transaction_id": clean(raw["transaction_id"]),
        "settlement_ts": ts,
        "settlement_amount": amount,
        "settlement_status": (clean(raw.get("settlement_status")) or "").upper(),
        "settlement_batch": clean(raw.get("settlement_batch")),
    })


def validate_event(raw: dict, known_transactions: set, late_after_min: int = 5) -> Result:
    if not clean(raw.get("event_id")):
        return Result(REJECT, "MISSING_EVENT_ID")
    event_ts, ingestion_ts = to_datetime(raw.get("event_ts")), to_datetime(raw.get("ingestion_ts"))
    if event_ts is None or ingestion_ts is None:
        return Result(REJECT, "INVALID_TIMESTAMP")
    if clean(raw.get("transaction_id")) not in known_transactions:
        return Result(QUARANTINE, "UNMATCHED_EVENT")

    # business time (event_ts) vs processing time (ingestion_ts)
    delay_sec = int((ingestion_ts - event_ts).total_seconds())
    is_late = delay_sec > late_after_min * 60
    record = {
        "event_id": clean(raw["event_id"]),
        "transaction_id": clean(raw["transaction_id"]),
        "event_type": (clean(raw.get("event_type")) or "").upper(),
        "event_ts": event_ts,
        "ingestion_ts": ingestion_ts,
        "processing_ms": int(to_amount(raw.get("processing_ms")) or 0),
        "ingestion_delay_sec": delay_sec,
        "is_late": is_late,
    }
    return Result(WARNING, "LATE_EVENT", record) if is_late else Result(OK, record=record)


def remove_duplicate_events(events: list[dict], already_loaded: set) -> tuple[list[dict], list[dict]]:
    """Keep the first copy of each event_id (by ingestion time). Returns (kept, duplicates)."""
    seen, kept, duplicates = set(already_loaded), [], []
    for e in sorted(events, key=lambda e: e["ingestion_ts"]):
        if e["event_id"] in seen:
            duplicates.append(e)
        else:
            seen.add(e["event_id"])
            kept.append(e)
    return kept, duplicates


# ---------------------------------------------------------------- settlement calculation
def summarize_settlement(amount: Decimal, transaction_ts: datetime, settlements: list[dict]) -> dict:
    """Roll up ALL settlement rows of ONE transaction (the one-to-many fix).

    Same logic as the SQL view GOLD.V_TXN_SETTLEMENT.
    """
    settled_rows = [s for s in settlements if s["settlement_status"] == "SETTLED"]
    settled = min(sum((s["settlement_amount"] for s in settled_rows), Decimal("0")), amount)
    last_settled = max((s["settlement_ts"] for s in settled_rows), default=None)

    if settled >= amount:
        status = "SETTLED"
    elif settled > 0:
        status = "PARTIALLY_SETTLED"
    elif any(s["settlement_status"] == "PENDING" for s in settlements):
        status = "PENDING"
    else:
        status = "UNSETTLED"

    sla_met = status == "SETTLED" and (last_settled - transaction_ts).total_seconds() <= SLA_SECONDS
    return {"settled_amount": settled, "gap_amount": amount - settled, "settlement_class": status,
            "sla_met": sla_met}
