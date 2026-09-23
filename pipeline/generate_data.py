"""Generate small, realistic CSV files WITH the hidden data problems planted.

    python -m pipeline.generate_data --batch 1     # 1-7 Sep 2026 + merchant master
    python -m pipeline.generate_data --batch 2     # 8 Sep 2026 + late updates (incremental demo)

Same batch number -> same data every time (fixed random seed).
"""
import argparse
import csv
import random
from datetime import date, datetime, time, timedelta
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
FMT = "%Y-%m-%d %H:%M:%S"

MERCHANTS = [
    ("M100", "Sharma General Store", "GROCERY"),
    ("M101", "Metro Electronics", "ELECTRONICS"),
    ("M102", "Blue Lotus Restaurant", "FOOD"),
    ("M103", "Urban Threads", "FASHION"),
    ("M104", "QuickFuel Station", "FUEL"),
    ("M105", "CarePlus Pharmacy", "HEALTH"),
    ("M106", "BookNook", "BOOKS"),
    ("M107", "FitZone Gym", "FITNESS"),
    ("M108", "ABC Retail", "RETAIL"),
    ("M109", "TravelKart", "TRAVEL"),
    ("M110", "HomeNest Furnishing", "HOME"),
    ("M111", "Spice Route Mart", "GROCERY"),
]
UNRELIABLE = {"M104", "M108"}   # often not settled   -> low settlement rate
SLOW = {"M110"}                 # settles, but late   -> low SLA only

COLUMNS = {
    "merchant": ["merchant_id", "merchant_name", "merchant_category", "country",
                 "risk_level", "effective_from", "effective_to"],
    "transactions": ["transaction_id", "merchant_id", "customer_id", "transaction_ts",
                     "amount", "currency", "status", "payment_channel"],
    "settlements": ["settlement_id", "transaction_id", "settlement_ts", "settlement_amount",
                    "settlement_status", "settlement_batch"],
    "payment_events": ["event_id", "transaction_id", "event_type", "event_ts",
                       "ingestion_ts", "processing_ms"],
}


def merchant_rows() -> list[dict]:
    rows = []
    for mid, name, category in MERCHANTS:
        if mid == "M100":   # the brief's example: LOW Jan-Mar, HIGH Apr-Jun, MEDIUM from Jul
            periods = [("LOW", "2026-01-01", "2026-03-31"), ("HIGH", "2026-04-01", "2026-06-30"),
                       ("MEDIUM", "2026-07-01", "")]
        elif mid == "M101":  # risk changes INSIDE our data window
            periods = [("LOW", "2026-01-01", "2026-09-03"), ("HIGH", "2026-09-04", "")]
        elif mid in UNRELIABLE:
            periods = [("HIGH", "2026-01-01", "")]
        else:
            periods = [(random.Random(mid).choice(["LOW", "LOW", "MEDIUM"]), "2026-01-01", "")]
        for risk, eff_from, eff_to in periods:
            rows.append(dict(merchant_id=mid, merchant_name=name, merchant_category=category,
                             country="India", risk_level=risk, effective_from=eff_from, effective_to=eff_to))
    return rows


class Builder:
    def __init__(self, batch: int):
        self.batch = batch
        self.rng = random.Random(1000 + batch)
        self.txns, self.settlements, self.events = [], [], []
        self.pending_settlements = []          # PENDING rows that settle in the next batch
        self._t = self._s = self._e = 0

    # ids are unique across batches: T1xxxxx for batch 1, T2xxxxx for batch 2 ...
    def _next(self, kind):
        if kind == "T":
            self._t += 1
            return f"T{self.batch}{self._t:05d}"
        if kind == "S":
            self._s += 1
            return f"S{self.batch}{self._s:05d}"
        self._e += 1
        return f"E{self.batch}{self._e:06d}"

    def add_event(self, txn_id, event_type, event_ts, late=False):
        r = self.rng
        delay = timedelta(minutes=r.randint(6, 90)) if late else timedelta(seconds=r.randint(1, 10))
        self.events.append(dict(event_id=self._next("E"), transaction_id=txn_id, event_type=event_type,
                                event_ts=event_ts.strftime(FMT), ingestion_ts=(event_ts + delay).strftime(FMT),
                                processing_ms=r.randint(40, 2500)))

    def add_settlement(self, txn_id, ts, amount, status):
        row = dict(settlement_id=self._next("S"), transaction_id=txn_id, settlement_ts=ts.strftime(FMT),
                   settlement_amount=f"{amount:.2f}", settlement_status=status,
                   settlement_batch=f"SB{ts:%Y%m%d}{'AM' if ts.hour < 12 else 'PM'}")
        self.settlements.append(row)
        return row

    def add_transaction(self, day: date, merchant_id=None, amount=None, status=None, txn_id=None):
        r = self.rng
        txn_id = txn_id or self._next("T")
        merchant_id = merchant_id or r.choice(MERCHANTS)[0]
        ts = datetime.combine(day, time(9)) + timedelta(seconds=r.randint(0, 12 * 3600))
        amount = amount if amount is not None else round(r.uniform(100, 50000), 2)
        status = status or r.choices(["SUCCESS", "FAILED", "REVERSED"], [85, 10, 5])[0]
        self.txns.append(dict(transaction_id=txn_id, merchant_id=merchant_id,
                              customer_id=f"C{r.randint(1, 400):05d}", transaction_ts=ts.strftime(FMT),
                              amount=f"{amount:.2f}", currency="INR", status=status,
                              payment_channel=r.choice(["POS", "ONLINE", "QR"])))

        late = r.random() < 0.05
        self.add_event(txn_id, "CREATED", ts, late)
        if status == "FAILED":
            self.add_event(txn_id, "FAILED", ts + timedelta(seconds=r.randint(1, 20)))
            return txn_id
        self.add_event(txn_id, "AUTHORIZED", ts + timedelta(seconds=r.randint(1, 30)), late)
        if status != "SUCCESS":
            return txn_id

        # --- settlement behaviour
        unreliable, slow = merchant_id in UNRELIABLE, merchant_id in SLOW
        roll = r.random()
        if unreliable and roll < 0.30:
            outcome = r.choice(["NONE", "PENDING", "FAILED"])
        elif not unreliable and roll < 0.03:
            outcome = r.choice(["NONE", "PENDING"])
        else:
            outcome = "SETTLED"
        delay_min = r.randint(35, 150) if (slow or (unreliable and r.random() < 0.5)) else r.randint(3, 25)
        settle_ts = ts + timedelta(minutes=delay_min)

        if outcome == "SETTLED":
            if r.random() < 0.10:      # split settlement: 80% + 20%
                first = round(amount * 0.8, 2)
                self.add_settlement(txn_id, settle_ts, first, "SETTLED")
                settle_ts += timedelta(minutes=4)
                self.add_settlement(txn_id, settle_ts, round(amount - first, 2), "SETTLED")
            else:
                self.add_settlement(txn_id, settle_ts, amount, "SETTLED")
            self.add_event(txn_id, "SETTLED", settle_ts, late)
        elif outcome == "PENDING":
            row = self.add_settlement(txn_id, settle_ts, amount, "PENDING")
            self.pending_settlements.append(row)
        elif outcome == "FAILED":
            self.add_settlement(txn_id, settle_ts, amount, "FAILED")
        return txn_id


def build_batch(batch: int, start: date, days: int, per_day: int) -> Builder:
    b = Builder(batch)
    for d in range(days):
        for _ in range(per_day):
            b.add_transaction(start + timedelta(days=d))
    return b


def plant_problems_batch1(b: Builder):
    """Issue 5 - the data-quality problems listed in the brief."""
    # Issue 1 - the brief's exact example: T1001 settled as 8,000 + 2,000
    day = date(2026, 9, 2)
    ts = datetime(2026, 9, 2, 10, 0, 0)
    b.txns.append(dict(transaction_id="T1001", merchant_id="M100", customer_id="C00001",
                       transaction_ts=ts.strftime(FMT), amount="10000.00", currency="INR",
                       status="SUCCESS", payment_channel="POS"))
    b.add_settlement("T1001", ts + timedelta(minutes=10), 8000, "SETTLED")
    b.add_settlement("T1001", ts + timedelta(minutes=12), 2000, "SETTLED")
    # Issue 3 - out-of-order arrival for T1001 (written SETTLED, AUTHORIZED, CREATED)
    for etype, minute in (("SETTLED", 12), ("AUTHORIZED", 1), ("CREATED", 0)):
        b.add_event("T1001", etype, ts + timedelta(minutes=minute))
    # Issue 2 - the brief's late event: event 10:02:15, ingested 10:08:41
    b.events.append(dict(event_id="E1LATE01", transaction_id="T1001", event_type="AUTHORIZED",
                         event_ts=f"{day} 10:02:15", ingestion_ts=f"{day} 10:08:41", processing_ms=900))

    t = b.txns
    for i in (3, 17, 41):
        t[i]["merchant_id"] = ""                    # missing merchant id
    t[25]["merchant_id"] = "M999"                   # merchant that does not exist
    t[30]["currency"] = "XYZ"                       # invalid currency
    t[31]["currency"] = ""                          # missing currency
    t[32]["currency"] = " inr "                     # messy but valid -> cleaned to INR

    success = [x for x in t if x["status"] == "SUCCESS" and x["merchant_id"] and x["currency"] == "INR"]
    # negative settlement amounts
    for x in success[50:52]:
        b.add_settlement(x["transaction_id"], datetime.fromisoformat(x["transaction_ts"]) + timedelta(hours=2),
                         -500, "SETTLED")
    # settlements without a matching transaction
    for missing in ("T199998", "T199999"):
        b.add_settlement(missing, datetime(2026, 9, 5, 15, 0), 1234.50, "SETTLED")
    # unreadable timestamp -> REJECT
    b.settlements.append(dict(settlement_id="S1BADTS", transaction_id=success[60]["transaction_id"],
                              settlement_ts="2026-09-31 25:61:00", settlement_amount="100.00",
                              settlement_status="SETTLED", settlement_batch="SB-BAD"))
    # duplicate event ids (same event delivered twice)
    for e in b.rng.sample(b.events, 5):
        b.events.append(dict(e))


def plant_problems_batch2(b: Builder, batch1: Builder):
    # Settlements that were PENDING in batch 1 are now SETTLED (same settlement_id -> MERGE update)
    for p in batch1.pending_settlements[:4]:
        ts = datetime.strptime(p["settlement_ts"], FMT) + timedelta(hours=26)
        b.settlements.append(dict(p, settlement_ts=ts.strftime(FMT), settlement_status="SETTLED",
                                  settlement_batch=f"SB{ts:%Y%m%d}LATE"))
    # An event that was already delivered in batch 1 arrives again (cross-batch duplicate)
    b.events.append(dict(batch1.events[0]))
    # One more negative settlement so the DQ log grows
    x = next(t for t in b.txns if t["status"] == "SUCCESS")
    b.add_settlement(x["transaction_id"], datetime.fromisoformat(x["transaction_ts"]) + timedelta(hours=1),
                     -250, "SETTLED")


def write_csv(name: str, batch: int, rows: list[dict]):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}_{batch:03d}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS[name])
        writer.writeheader()
        writer.writerows(rows)
    print(f"  wrote {path.relative_to(OUT_DIR.parent.parent)}  ({len(rows)} rows)")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--batch", type=int, default=1, choices=[1, 2])
    args = parser.parse_args()

    batch1 = build_batch(1, date(2026, 9, 1), days=7, per_day=25)
    plant_problems_batch1(batch1)

    if args.batch == 1:
        out = batch1
        write_csv("merchant", 1, merchant_rows())
    else:
        out = build_batch(2, date(2026, 9, 8), days=1, per_day=25)
        plant_problems_batch2(out, batch1)

    out.rng.shuffle(out.events)      # Issue 3 - arrival order != business order
    print(f"Batch {args.batch}:")
    write_csv("transactions", args.batch, out.txns)
    write_csv("settlements", args.batch, out.settlements)
    write_csv("payment_events", args.batch, out.events)


if __name__ == "__main__":
    main()
