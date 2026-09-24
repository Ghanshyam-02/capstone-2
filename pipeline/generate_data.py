"""Generate realistic CSV files WITH the hidden data problems planted.

The generated files are already in the repo, so you do NOT need to run this:
    data/raw/*_001.csv       batch 1: Sep 2026 (30 days) + merchant master  -> loaded by the pipeline
    data/incoming/*_002.csv  batch 2: 1 Oct 2026 + late updates             -> copy to data/raw in Phase 6

To re-create them (same data every time - fixed random seed):
    python -m pipeline.generate_data --batch 1
    python -m pipeline.generate_data --batch 2

Patterns built in, so the dashboard has something to explain:
  * busy hours (lunch / evening) and busier weekends
  * big merchants have more volume than small ones
  * amounts depend on the merchant category (fuel is small, electronics is big)
  * M104, M108, M117 often do not settle      -> low settlement rate
  * M110, M121 settle, but slowly             -> low SLA
  * 15 Sep 2026: settlement processor incident -> gap spike on the daily chart
"""
import argparse
import csv
import random
from datetime import date, datetime, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FMT = "%Y-%m-%d %H:%M:%S"

# merchant id, name, category, popularity weight
MERCHANTS = [
    ("M100", "Sharma General Store", "GROCERY", 8),
    ("M101", "Metro Electronics", "ELECTRONICS", 6),
    ("M102", "Blue Lotus Restaurant", "FOOD", 7),
    ("M103", "Urban Threads", "FASHION", 5),
    ("M104", "QuickFuel Station", "FUEL", 9),
    ("M105", "CarePlus Pharmacy", "HEALTH", 6),
    ("M106", "BookNook", "BOOKS", 2),
    ("M107", "FitZone Gym", "FITNESS", 2),
    ("M108", "ABC Retail", "RETAIL", 8),
    ("M109", "TravelKart", "TRAVEL", 4),
    ("M110", "HomeNest Furnishing", "HOME", 3),
    ("M111", "Spice Route Mart", "GROCERY", 7),
    ("M112", "Pixel Mobile Store", "ELECTRONICS", 5),
    ("M113", "Chai Point Cafe", "FOOD", 9),
    ("M114", "StyleHub Fashion", "FASHION", 4),
    ("M115", "Highway Fuels", "FUEL", 6),
    ("M116", "MedPlus Chemist", "HEALTH", 5),
    ("M117", "MegaMart Hypermarket", "RETAIL", 10),
    ("M118", "SkyHigh Travels", "TRAVEL", 3),
    ("M119", "Royal Furniture", "HOME", 2),
    ("M120", "Green Basket Organics", "GROCERY", 4),
    ("M121", "Galaxy Electronics", "ELECTRONICS", 4),
    ("M122", "Tandoor Express", "FOOD", 6),
    ("M123", "Little Readers", "BOOKS", 1),
    ("M124", "PowerYoga Studio", "FITNESS", 2),
]
AMOUNT_RANGE = {"GROCERY": (100, 4000), "ELECTRONICS": (2000, 90000), "FOOD": (150, 3000),
                "FASHION": (500, 15000), "FUEL": (300, 6000), "HEALTH": (100, 5000),
                "BOOKS": (200, 3000), "FITNESS": (1000, 12000), "RETAIL": (300, 20000),
                "TRAVEL": (2500, 60000), "HOME": (3000, 80000)}
UNRELIABLE = {"M104", "M108", "M117"}      # often not settled   -> low settlement rate
SLOW = {"M110", "M121"}                    # settles, but late   -> low SLA only
INCIDENT_DAY = date(2026, 9, 15)           # settlement processor problem
HOUR_WEIGHTS = [0, 0, 0, 0, 0, 0, 1, 2, 4, 6, 7, 9, 10, 9, 7, 6, 6, 7, 9, 10, 9, 6, 3, 1]

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
    for mid, name, category, _ in MERCHANTS:
        if mid == "M100":    # the brief's example: LOW Jan-Mar, HIGH Apr-Jun, MEDIUM from Jul
            periods = [("LOW", "2026-01-01", "2026-03-31"), ("HIGH", "2026-04-01", "2026-06-30"),
                       ("MEDIUM", "2026-07-01", "")]
        elif mid == "M101":  # risk changes INSIDE our data window
            periods = [("LOW", "2026-01-01", "2026-09-14"), ("HIGH", "2026-09-15", "")]
        elif mid in UNRELIABLE:
            periods = [("MEDIUM", "2026-01-01", "2026-08-31"), ("HIGH", "2026-09-01", "")]
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
        self.pending_settlements = []          # PENDING rows that get SETTLED in batch 2
        self.counter = {"T": 0, "S": 0, "E": 0}

    def next_id(self, kind):                   # T100001 (batch 1), T200001 (batch 2) ...
        self.counter[kind] += 1
        return f"{kind}{self.batch}{self.counter[kind]:06d}"

    def add_event(self, txn_id, event_type, event_ts, late=False):
        r = self.rng
        delay = timedelta(minutes=r.randint(6, 90)) if late else timedelta(seconds=r.randint(1, 10))
        self.events.append(dict(event_id=self.next_id("E"), transaction_id=txn_id, event_type=event_type,
                                event_ts=event_ts.strftime(FMT), ingestion_ts=(event_ts + delay).strftime(FMT),
                                processing_ms=r.randint(40, 2500)))

    def add_settlement(self, txn_id, ts, amount, status):
        row = dict(settlement_id=self.next_id("S"), transaction_id=txn_id, settlement_ts=ts.strftime(FMT),
                   settlement_amount=f"{amount:.2f}", settlement_status=status,
                   settlement_batch=f"SB{ts:%Y%m%d}{'AM' if ts.hour < 12 else 'PM'}")
        self.settlements.append(row)
        return row

    def add_transaction(self, day: date):
        r = self.rng
        mid, _, category, _ = r.choices(MERCHANTS, weights=[m[3] for m in MERCHANTS])[0]
        txn_id = self.next_id("T")
        hour = r.choices(range(24), weights=HOUR_WEIGHTS)[0]
        ts = datetime(day.year, day.month, day.day, hour) + timedelta(seconds=r.randint(0, 3599))
        low, high = AMOUNT_RANGE[category]
        amount = round(r.uniform(low, high), 2)
        status = r.choices(["SUCCESS", "FAILED", "REVERSED"], [88, 8, 4])[0]
        self.txns.append(dict(transaction_id=txn_id, merchant_id=mid, customer_id=f"C{r.randint(1, 3000):05d}",
                              transaction_ts=ts.strftime(FMT), amount=f"{amount:.2f}", currency="INR",
                              status=status, payment_channel=r.choices(["POS", "ONLINE", "QR"], [40, 35, 25])[0]))

        late = r.random() < 0.04
        self.add_event(txn_id, "CREATED", ts, late)
        if status == "FAILED":
            self.add_event(txn_id, "FAILED", ts + timedelta(seconds=r.randint(1, 20)))
            return
        self.add_event(txn_id, "AUTHORIZED", ts + timedelta(seconds=r.randint(1, 30)), late)
        if status != "SUCCESS":
            return

        # ---- how does this payment settle?
        unreliable, incident = mid in UNRELIABLE, day == INCIDENT_DAY
        roll = r.random()
        if unreliable and roll < 0.25:
            outcome = r.choice(["NONE", "PENDING", "FAILED"])
        elif incident and roll < 0.15:
            outcome = r.choice(["NONE", "PENDING"])
        elif roll < 0.02:
            outcome = r.choice(["NONE", "PENDING"])
        else:
            outcome = "SETTLED"
        slow = mid in SLOW or incident or (unreliable and r.random() < 0.4)
        settle_ts = ts + timedelta(minutes=r.randint(35, 180) if slow else r.randint(3, 25))

        if outcome == "SETTLED":
            if r.random() < 0.10:              # split settlement: 80% + 20%
                first = round(amount * 0.8, 2)
                self.add_settlement(txn_id, settle_ts, first, "SETTLED")
                settle_ts += timedelta(minutes=4)
                self.add_settlement(txn_id, settle_ts, round(amount - first, 2), "SETTLED")
            elif r.random() < 0.03:            # partially settled
                self.add_settlement(txn_id, settle_ts, round(amount * 0.6, 2), "SETTLED")
            else:
                self.add_settlement(txn_id, settle_ts, amount, "SETTLED")
            self.add_event(txn_id, "SETTLED", settle_ts, late)
        elif outcome == "PENDING":
            self.pending_settlements.append(self.add_settlement(txn_id, settle_ts, amount, "PENDING"))
        elif outcome == "FAILED":
            self.add_settlement(txn_id, settle_ts, amount, "FAILED")


def build_batch(batch: int, start: date, days: int, per_day: int) -> Builder:
    b = Builder(batch)
    for d in range(days):
        day = start + timedelta(days=d)
        volume = int(per_day * (1.3 if day.weekday() >= 5 else 1.0) * b.rng.uniform(0.9, 1.1))
        for _ in range(volume):
            b.add_transaction(day)
    return b


def plant_problems_batch1(b: Builder):
    """Issue 1-5 from the brief, planted on purpose."""
    r = b.rng
    # Issue 1 - the brief's example: T1001 = 10,000 settled as 8,000 + 2,000
    ts = datetime(2026, 9, 2, 10, 0, 0)
    b.txns.append(dict(transaction_id="T1001", merchant_id="M100", customer_id="C00001",
                       transaction_ts=ts.strftime(FMT), amount="10000.00", currency="INR",
                       status="SUCCESS", payment_channel="POS"))
    b.add_settlement("T1001", ts + timedelta(minutes=10), 8000, "SETTLED")
    b.add_settlement("T1001", ts + timedelta(minutes=12), 2000, "SETTLED")
    # Issue 3 - T1001's events written in the wrong order (SETTLED, AUTHORIZED, CREATED)
    for event_type, minute in (("SETTLED", 12), ("AUTHORIZED", 1), ("CREATED", 0)):
        b.add_event("T1001", event_type, ts + timedelta(minutes=minute))
    # Issue 2 - the brief's late event: happened 10:02:15, received 10:08:41
    b.events.append(dict(event_id="E1LATE01", transaction_id="T1001", event_type="AUTHORIZED",
                         event_ts="2026-09-02 10:02:15", ingestion_ts="2026-09-02 10:08:41", processing_ms=900))

    # Issue 5 - data-quality problems
    picks = r.sample(b.txns[:-1], 40)
    for t in picks[:15]:
        t["merchant_id"] = ""                          # missing merchant id
    for t in picks[15:20]:
        t["merchant_id"] = "M999"                      # merchant that does not exist
    for t in picks[20:30]:
        t["currency"] = r.choice(["XYZ", "USDD", ""])  # invalid currency
    for t in picks[30:40]:
        t["currency"] = r.choice([" inr ", "inr"])     # messy but valid -> cleaned to INR

    bad_ids = {t["transaction_id"] for t in picks[:30]}
    good_success = [t for t in b.txns if t["status"] == "SUCCESS" and t["transaction_id"] not in bad_ids]
    for t in r.sample(good_success, 8):                # negative settlement amounts
        b.add_settlement(t["transaction_id"], datetime.fromisoformat(t["transaction_ts"]) + timedelta(hours=2),
                         -round(r.uniform(100, 1000), 2), "SETTLED")
    for i in range(10):                                # settlements without a transaction
        b.add_settlement(f"T19999{i:02d}", datetime(2026, 9, 5 + i, 15, 0), round(r.uniform(500, 5000), 2),
                         "SETTLED")
    for t in r.sample(good_success, 3):                # unreadable timestamp -> REJECT
        b.settlements.append(dict(settlement_id=b.next_id("S"), transaction_id=t["transaction_id"],
                                  settlement_ts="2026-09-31 25:61:00", settlement_amount="100.00",
                                  settlement_status="SETTLED", settlement_batch="SB-BAD"))
    for e in r.sample(b.events, 25):                   # duplicate event ids
        b.events.append(dict(e))


def plant_problems_batch2(b: Builder, batch1: Builder):
    # PENDING settlements from batch 1 are now SETTLED (same settlement_id -> MERGE updates them)
    for p in batch1.pending_settlements[:20]:
        ts = datetime.strptime(p["settlement_ts"], FMT) + timedelta(hours=26)
        b.settlements.append(dict(p, settlement_ts=ts.strftime(FMT), settlement_status="SETTLED",
                                  settlement_batch=f"SB{ts:%Y%m%d}LATE"))
    b.events.append(dict(batch1.events[0]))           # event already delivered in batch 1
    t = next(t for t in b.txns if t["status"] == "SUCCESS")
    b.add_settlement(t["transaction_id"], datetime.fromisoformat(t["transaction_ts"]) + timedelta(hours=1),
                     -250, "SETTLED")                 # one more negative settlement


def write_csv(name: str, batch: int, rows: list[dict]):
    out_dir = DATA_DIR / ("raw" if batch == 1 else "incoming")      # batch 2 waits until Phase 6
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}_{batch:03d}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS[name])
        writer.writeheader()
        writer.writerows(rows)
    print(f"  wrote data/{out_dir.name}/{path.name}  ({len(rows):,} rows)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, default=1, choices=[1, 2])
    args = parser.parse_args()

    batch1 = build_batch(1, date(2026, 9, 1), days=30, per_day=120)
    plant_problems_batch1(batch1)

    if args.batch == 1:
        out = batch1
        write_csv("merchant", 1, merchant_rows())
    else:
        out = build_batch(2, date(2026, 10, 1), days=1, per_day=120)
        plant_problems_batch2(out, batch1)

    out.rng.shuffle(out.events)       # Issue 3 - arrival order is not business order
    print(f"Batch {args.batch}:")
    write_csv("transactions", args.batch, out.txns)
    write_csv("settlements", args.batch, out.settlements)
    write_csv("payment_events", args.batch, out.events)


if __name__ == "__main__":
    main()
