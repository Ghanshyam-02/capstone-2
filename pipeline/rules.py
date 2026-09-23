"""Data-quality and settlement business rules.

Pure Python (no database) so every rule can be unit-tested in milliseconds.
The Silver step calls these functions for every Bronze row.

Severity levels (decided in docs/01_business_spec.md):
    OK          -> goes to Silver
    WARNING     -> goes to Silver, but is also logged (e.g. late event)
    QUARANTINE  -> held back in AUDIT.DQ_LOG for a human to review/fix
    REJECT      -> unusable (no id, unreadable value, duplicate) - logged, never loaded
"""
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

OK, WARNING, QUARANTINE, REJECT = "OK", "WARNING", "QUARANTINE", "REJECT"

VALID_CURRENCIES = {"INR"}                    # assumption: India acquiring, INR only
TXN_STATUSES = {"SUCCESS", "FAILED", "REVERSED"}
PAYMENT_CHANNELS = {"POS", "ONLINE", "QR"}
SETTLEMENT_STATUSES = {"SETTLED", "PENDING", "FAILED"}
EVENT_TYPES = {"CREATED", "AUTHORIZED", "SETTLED", "FAILED"}
RISK_LEVELS = {"LOW", "MEDIUM", "HIGH"}
SLA_SECONDS = 30 * 60


@dataclass
class Result:
    severity: str
    reason: str | None = None
    record: dict | None = None          # cleaned + typed record (only when it is kept)

    @property
    def keep(self) -> bool:
        return self.severity in (OK, WARNING)


# ---------------------------------------------------------------- helpers
def _clean(value) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def parse_ts(value) -> datetime | None:
    value = _clean(value)
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def parse_date(value) -> date | None:
    value = _clean(value)
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_amount(value) -> Decimal | None:
    value = _clean(value)
    if value is None:
        return None
    try:
        amount = Decimal(value)
    except InvalidOperation:
        return None
    return amount.quantize(Decimal("0.01")) if amount.is_finite() else None


def _reject(reason):
    return Result(REJECT, reason)


def _quarantine(reason):
    return Result(QUARANTINE, reason)


# ---------------------------------------------------------------- validators
def validate_merchant(raw: dict) -> Result:
    merchant_id = _clean(raw.get("merchant_id"))
    if not merchant_id:
        return _reject("MISSING_MERCHANT_ID")
    eff_from = parse_date(raw.get("effective_from"))
    if eff_from is None:
        return _reject("INVALID_EFFECTIVE_FROM")
    eff_to = None
    if _clean(raw.get("effective_to")):
        eff_to = parse_date(raw.get("effective_to"))
        if eff_to is None:
            return _reject("INVALID_EFFECTIVE_TO")
    risk = (_clean(raw.get("risk_level")) or "").upper()
    if risk not in RISK_LEVELS:
        return _quarantine("INVALID_RISK_LEVEL")
    if eff_to is not None and eff_to < eff_from:
        return _quarantine("INVALID_EFFECTIVE_RANGE")
    return Result(OK, record={
        "merchant_id": merchant_id,
        "merchant_name": _clean(raw.get("merchant_name")),
        "merchant_category": _clean(raw.get("merchant_category")),
        "country": _clean(raw.get("country")),
        "risk_level": risk,
        "effective_from": eff_from,
        "effective_to": eff_to,
    })


def validate_transaction(raw: dict, known_merchants: set[str]) -> Result:
    transaction_id = _clean(raw.get("transaction_id"))
    if not transaction_id:
        return _reject("MISSING_TRANSACTION_ID")
    ts = parse_ts(raw.get("transaction_ts"))
    if ts is None:
        return _reject("INVALID_TIMESTAMP")
    amount = parse_amount(raw.get("amount"))
    if amount is None:
        return _reject("INVALID_AMOUNT")

    merchant_id = _clean(raw.get("merchant_id"))
    if not merchant_id:
        return _quarantine("MISSING_MERCHANT_ID")
    if merchant_id not in known_merchants:
        return _quarantine("UNKNOWN_MERCHANT")
    currency = (_clean(raw.get("currency")) or "").upper()
    if currency not in VALID_CURRENCIES:
        return _quarantine("INVALID_CURRENCY")
    if amount <= 0:
        return _quarantine("NON_POSITIVE_AMOUNT")
    status = (_clean(raw.get("status")) or "").upper()
    if status not in TXN_STATUSES:
        return _quarantine("INVALID_STATUS")
    channel = (_clean(raw.get("payment_channel")) or "").upper()
    if channel not in PAYMENT_CHANNELS:
        return _quarantine("INVALID_CHANNEL")

    return Result(OK, record={
        "transaction_id": transaction_id,
        "merchant_id": merchant_id,
        "customer_id": _clean(raw.get("customer_id")),
        "transaction_ts": ts,
        "amount": amount,
        "currency": currency,
        "status": status,
        "payment_channel": channel,
    })


def validate_settlement(raw: dict, known_transactions: set[str]) -> Result:
    settlement_id = _clean(raw.get("settlement_id"))
    if not settlement_id:
        return _reject("MISSING_SETTLEMENT_ID")
    ts = parse_ts(raw.get("settlement_ts"))
    if ts is None:
        return _reject("INVALID_TIMESTAMP")
    amount = parse_amount(raw.get("settlement_amount"))
    if amount is None:
        return _reject("INVALID_AMOUNT")

    if amount < 0:
        return _quarantine("NEGATIVE_SETTLEMENT_AMOUNT")
    status = (_clean(raw.get("settlement_status")) or "").upper()
    if status not in SETTLEMENT_STATUSES:
        return _quarantine("INVALID_STATUS")
    transaction_id = _clean(raw.get("transaction_id"))
    if not transaction_id or transaction_id not in known_transactions:
        return _quarantine("UNMATCHED_SETTLEMENT")

    return Result(OK, record={
        "settlement_id": settlement_id,
        "transaction_id": transaction_id,
        "settlement_ts": ts,
        "settlement_amount": amount,
        "settlement_status": status,
        "settlement_batch": _clean(raw.get("settlement_batch")),
    })


def validate_event(raw: dict, known_transactions: set[str], late_threshold_min: int = 5) -> Result:
    event_id = _clean(raw.get("event_id"))
    if not event_id:
        return _reject("MISSING_EVENT_ID")
    event_ts = parse_ts(raw.get("event_ts"))
    ingestion_ts = parse_ts(raw.get("ingestion_ts"))
    if event_ts is None or ingestion_ts is None:
        return _reject("INVALID_TIMESTAMP")

    event_type = (_clean(raw.get("event_type")) or "").upper()
    if event_type not in EVENT_TYPES:
        return _quarantine("INVALID_EVENT_TYPE")
    transaction_id = _clean(raw.get("transaction_id"))
    if not transaction_id or transaction_id not in known_transactions:
        return _quarantine("UNMATCHED_EVENT")

    try:
        processing_ms = int(_clean(raw.get("processing_ms")) or "")
    except ValueError:
        processing_ms = None

    # Business time (event_ts) vs processing time (ingestion_ts) - Issue 2.
    delay_sec = int((ingestion_ts - event_ts).total_seconds())
    is_late = delay_sec > late_threshold_min * 60
    record = {
        "event_id": event_id,
        "transaction_id": transaction_id,
        "event_type": event_type,
        "event_ts": event_ts,
        "ingestion_ts": ingestion_ts,
        "processing_ms": processing_ms,
        "ingestion_delay_sec": delay_sec,
        "is_late": is_late,
    }
    if is_late:
        return Result(WARNING, "LATE_EVENT", record)
    return Result(OK, record=record)


def split_duplicates(records: list[dict], key: str, existing_keys: set[str] = frozenset(),
                     sort_key=None) -> tuple[list[dict], list[dict]]:
    """Keep the first record per key; return (kept, duplicates).

    `existing_keys` = keys already loaded in an earlier run (cross-batch duplicates).
    """
    ordered = sorted(records, key=sort_key) if sort_key else records
    seen = set(existing_keys)
    kept, duplicates = [], []
    for record in ordered:
        if record[key] in seen:
            duplicates.append(record)
        else:
            seen.add(record[key])
            kept.append(record)
    return kept, duplicates


# ---------------------------------------------------------------- settlement logic
def summarize_settlement(amount: Decimal, transaction_ts: datetime, settlements: list[dict]) -> dict:
    """Roll up ALL settlement records of ONE transaction (fixes one-to-many).

    Mirrors the SQL view GOLD.V_TXN_SETTLEMENT.
    """
    settled_rows = [s for s in settlements if s["settlement_status"] == "SETTLED"]
    settled_raw = sum((s["settlement_amount"] for s in settled_rows), Decimal("0"))
    settled = min(settled_raw, amount)                       # cap: never above 100%
    last_settled_ts = max((s["settlement_ts"] for s in settled_rows), default=None)

    if settled_raw >= amount:
        settlement_class = "SETTLED"
    elif settled_raw > 0:
        settlement_class = "PARTIALLY_SETTLED"
    elif any(s["settlement_status"] == "PENDING" for s in settlements):
        settlement_class = "PENDING"
    elif any(s["settlement_status"] == "FAILED" for s in settlements):
        settlement_class = "SETTLEMENT_FAILED"
    else:
        settlement_class = "UNSETTLED"

    sla_met = (settlement_class == "SETTLED"
               and (last_settled_ts - transaction_ts).total_seconds() <= SLA_SECONDS)
    return {
        "settled_amount": settled,
        "gap_amount": amount - settled,
        "settlement_class": settlement_class,
        "sla_met": sla_met,
    }


def reconcile(transactions: list[dict], settlements: list[dict]) -> dict:
    """Successful transactions = settled + unsettled  (reconciliation of totals)."""
    by_txn: dict[str, list[dict]] = {}
    for s in settlements:
        by_txn.setdefault(s["transaction_id"], []).append(s)

    totals = {"success_count": 0, "success_amount": Decimal("0"), "settled_amount": Decimal("0"),
              "gap_amount": Decimal("0"), "sla_met_count": 0, "by_class": {}}
    for t in transactions:
        if t["status"] != "SUCCESS":
            continue                                   # FAILED / REVERSED never count
        summary = summarize_settlement(t["amount"], t["transaction_ts"], by_txn.get(t["transaction_id"], []))
        totals["success_count"] += 1
        totals["success_amount"] += t["amount"]
        totals["settled_amount"] += summary["settled_amount"]
        totals["gap_amount"] += summary["gap_amount"]
        totals["sla_met_count"] += int(summary["sla_met"])
        cls = totals["by_class"].setdefault(summary["settlement_class"], {"count": 0, "amount": Decimal("0")})
        cls["count"] += 1
        cls["amount"] += summary["gap_amount"]
    return totals


def risk_as_of(history: list[dict], on: date) -> str | None:
    """Risk level valid on a given date (SCD Type 2 lookup) - Issue 4."""
    for row in sorted(history, key=lambda r: r["effective_from"], reverse=True):
        eff_to = row.get("effective_to") or date.max
        if row["effective_from"] <= on <= eff_to:
            return row["risk_level"]
    return None
