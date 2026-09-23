"""BRONZE -> SILVER: validate, clean, remove duplicates, convert types.

For each source file type:
  1. read only NEW Bronze rows (LOAD_TS newer than the watermark)   -> incremental
  2. check every row with pipeline/rules.py
  3. good rows -> MERGE into Silver     bad rows -> AUDIT.DQ_LOG      -> nothing disappears
  4. move the watermark forward
"""
import json

import snowflake.connector

from common import config
from pipeline import rules
from pipeline.generate_data import COLUMNS

SOURCES = ["merchant", "transactions", "settlements", "payment_events"]   # order matters
KEYS = {"merchant": ["merchant_id", "effective_from"], "transactions": ["transaction_id"],
        "settlements": ["settlement_id"], "payment_events": ["event_id"]}
SILVER_COLUMNS = {
    "merchant": COLUMNS["merchant"],
    "transactions": COLUMNS["transactions"],
    "settlements": COLUMNS["settlements"],
    "payment_events": COLUMNS["payment_events"] + ["ingestion_delay_sec", "is_late"],
}


def ids(cur, sql) -> set:
    return {row[0] for row in cur.execute(sql).fetchall()}


def validate(source: str, raw_rows: list[dict], cur) -> tuple[list[dict], list[tuple]]:
    """Returns (good rows, problems). A problem = (record id, severity, reason, raw row as JSON)."""
    if source == "merchant":
        results = [rules.validate_merchant(r) for r in raw_rows]
    elif source == "transactions":
        merchants = ids(cur, "SELECT MERCHANT_ID FROM SILVER.MERCHANT")
        results = [rules.validate_transaction(r, merchants) for r in raw_rows]
    elif source == "settlements":
        txns = ids(cur, "SELECT TRANSACTION_ID FROM SILVER.TRANSACTIONS")
        results = [rules.validate_settlement(r, txns) for r in raw_rows]
    else:
        txns = ids(cur, "SELECT TRANSACTION_ID FROM SILVER.TRANSACTIONS")
        results = [rules.validate_event(r, txns, config.LATE_EVENT_THRESHOLD_MIN) for r in raw_rows]

    key = KEYS[source][0]
    good, problems = [], []
    for raw, result in zip(raw_rows, results):
        if result.severity != rules.OK:
            masked = dict(raw, customer_id="***") if raw.get("customer_id") else raw   # hide PII
            problems.append((raw.get(key), result.severity, result.reason, json.dumps(masked)))
        if result.keep:
            good.append(dict(result.record, source_file=raw["source_file"]))

    if source == "payment_events":
        # the same event id twice (in this file, or loaded in an earlier run) is a duplicate
        loaded = ids(cur, "SELECT EVENT_ID FROM SILVER.PAYMENT_EVENTS")
        good, dups = rules.remove_duplicate_events(good, loaded)
        problems += [(d["event_id"], rules.REJECT, "DUPLICATE_EVENT_ID", json.dumps(d, default=str))
                     for d in dups]
    else:
        # other sources: if a row is sent again, the latest version wins
        latest = {tuple(r[k] for k in KEYS[source]): r for r in good}
        good = list(latest.values())
    return good, problems


def process_source(conn, source: str, run_id: str) -> dict:
    cur = conn.cursor()
    bronze, silver = f"BRONZE.{source.upper()}", f"SILVER.{source.upper()}"
    cols = SILVER_COLUMNS[source] + ["source_file"]

    # 1. read only rows newer than the watermark.
    #    (table/column names come from the constants above, never from user input)
    cur.execute(f"SET hi = (SELECT COALESCE(MAX(LOAD_TS), '1970-01-01'::TIMESTAMP_LTZ) FROM {bronze})")
    dict_cur = conn.cursor(snowflake.connector.DictCursor)
    dict_cur.execute(
        f"SELECT {', '.join(COLUMNS[source])}, SOURCE_FILE FROM {bronze} "
        "WHERE LOAD_TS > (SELECT LAST_LOAD_TS FROM AUDIT.WATERMARK WHERE SOURCE = %s) AND LOAD_TS <= $hi",
        (source,))
    raw_rows = [{k.lower(): v for k, v in row.items()} for row in dict_cur.fetchall()]

    # 2. validate
    good, problems = validate(source, raw_rows, cur)

    # 3. put good rows in a temporary table, then MERGE (insert new / update existing)
    cur.execute(f"CREATE OR REPLACE TEMPORARY TABLE AUDIT.STAGING AS SELECT {', '.join(cols)} FROM {silver} WHERE 1 = 0")
    if good:
        cur.executemany(f"INSERT INTO AUDIT.STAGING ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                        [tuple(r.get(c) for c in cols) for r in good])
    on = " AND ".join(f"t.{k} = s.{k}" for k in KEYS[source])
    update = ", ".join(f"t.{c} = s.{c}" for c in cols if c not in KEYS[source])

    cur.execute("BEGIN")          # data + DQ log + watermark succeed or fail together
    cur.execute(f"MERGE INTO {silver} t USING AUDIT.STAGING s ON {on} "
                f"WHEN MATCHED THEN UPDATE SET {update}, t.LOADED_AT = CURRENT_TIMESTAMP() "
                f"WHEN NOT MATCHED THEN INSERT ({', '.join(cols)}) VALUES ({', '.join('s.' + c for c in cols)})")
    if problems:
        cur.executemany("INSERT INTO AUDIT.DQ_LOG (RUN_ID, SOURCE, RECORD_KEY, SEVERITY, REASON, RAW_RECORD) "
                        "VALUES (%s, %s, %s, %s, %s, %s)", [(run_id, source, *p) for p in problems])
    cur.execute("UPDATE AUDIT.WATERMARK SET LAST_LOAD_TS = GREATEST($hi, LAST_LOAD_TS) WHERE SOURCE = %s",
                (source,))
    cur.execute("COMMIT")

    counts = {s: sum(1 for p in problems if p[1] == s) for s in (rules.QUARANTINE, rules.REJECT, rules.WARNING)}
    print(f"  [silver] {source:15s} read={len(raw_rows):4d} loaded={len(good):4d} "
          f"quarantined={counts['QUARANTINE']:3d} rejected={counts['REJECT']:3d} warnings={counts['WARNING']:3d}")
    return {"loaded": len(good), **counts}


def build_silver(conn, run_id: str) -> dict:
    totals = {"loaded": 0, rules.QUARANTINE: 0, rules.REJECT: 0, rules.WARNING: 0}
    for source in SOURCES:
        for k, v in process_source(conn, source, run_id).items():
            totals[k] += v
    return totals
