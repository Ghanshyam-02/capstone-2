"""BRONZE -> SILVER: validate, clean, de-duplicate, type.

Security note: table/column names in the SQL below come from the constant
dictionaries in this file (never from user input), which is why the f-strings
are marked `# nosec B608`. All VALUES are passed as bind parameters (%s).

For each source:
  1. read only NEW Bronze rows (LOAD_TS > watermark)            -> incremental
  2. run the rules in pipeline/rules.py on every row
  3. good rows  -> MERGE into SILVER (upsert, safe to re-run)
     bad rows   -> AUDIT.DQ_LOG with severity + reason            -> nothing disappears
  4. move the watermark forward - in the SAME transaction as the data
"""
import json

import snowflake.connector

from common import config
from pipeline import rules
from pipeline.generate_data import COLUMNS
from pipeline.ingest import SOURCES, bronze_table

KEYS = {"merchant": ["merchant_id", "effective_from"], "transactions": ["transaction_id"],
        "settlements": ["settlement_id"], "payment_events": ["event_id"]}
SILVER_COLUMNS = {
    "merchant": ["merchant_id", "merchant_name", "merchant_category", "country", "risk_level",
                 "effective_from", "effective_to"],
    "transactions": COLUMNS["transactions"],
    "settlements": COLUMNS["settlements"],
    "payment_events": ["event_id", "transaction_id", "event_type", "event_ts", "ingestion_ts",
                       "processing_ms", "ingestion_delay_sec", "is_late"],
}


def silver_table(source: str) -> str:
    return f"SILVER.{source.upper()}"


def _mask(raw: dict) -> str:
    """Raw row for the DQ log, with the customer id masked (PII)."""
    safe = dict(raw)
    if safe.get("customer_id"):
        safe["customer_id"] = "***"
    return json.dumps(safe, default=str)


def _ids(cur, sql: str) -> set[str]:
    return {row[0] for row in cur.execute(sql).fetchall()}


def _validate(source: str, raw_rows: list[dict], cur) -> tuple[list[dict], list[tuple]]:
    """Returns (rows to load, dq issues as (key, severity, reason, raw))."""
    issues, results = [], []
    if source == "merchant":
        results = [(raw, rules.validate_merchant(raw)) for raw in raw_rows]
    elif source == "transactions":
        known = _ids(cur, "SELECT DISTINCT MERCHANT_ID FROM SILVER.MERCHANT")
        results = [(raw, rules.validate_transaction(raw, known)) for raw in raw_rows]
    elif source == "settlements":
        known = _ids(cur, "SELECT TRANSACTION_ID FROM SILVER.TRANSACTIONS")
        results = [(raw, rules.validate_settlement(raw, known)) for raw in raw_rows]
    elif source == "payment_events":
        known = _ids(cur, "SELECT TRANSACTION_ID FROM SILVER.TRANSACTIONS")
        results = [(raw, rules.validate_event(raw, known, config.LATE_EVENT_THRESHOLD_MIN))
                   for raw in raw_rows]

    key = KEYS[source][0]
    good = []
    for raw, result in results:
        if result.severity != rules.OK:
            issues.append((raw.get(key), result.severity, result.reason, _mask(raw)))
        if result.keep:
            result.record["_raw"] = raw
            result.record["source_file"] = raw.get("source_file")
            good.append(result.record)

    # Duplicates: events are immutable, so a repeated event_id (in this batch OR an
    # earlier one) is rejected. For other sources the latest version wins (upsert).
    if source == "payment_events":
        existing = _ids(cur, "SELECT EVENT_ID FROM SILVER.PAYMENT_EVENTS")
        good, dups = rules.split_duplicates(good, "event_id", existing, sort_key=lambda r: r["ingestion_ts"])
        reason = "DUPLICATE_EVENT_ID"
    else:
        keys = KEYS[source]
        good.reverse()   # keep the LAST occurrence in the batch
        tagged = [dict(r, _key="|".join(str(r[k]) for k in keys)) for r in good]
        good, dups = rules.split_duplicates(tagged, "_key")
        reason = "DUPLICATE_IN_BATCH"
    for d in dups:
        issues.append((d[key], rules.REJECT, reason, _mask(d["_raw"])))
    return good, issues


def process_source(conn, source: str, run_id: str) -> dict:
    cur = conn.cursor()
    table, cols, keys = silver_table(source), SILVER_COLUMNS[source], KEYS[source]
    bronze_cols = COLUMNS[source] + ["source_file"]

    # 1. new rows only
    cur.execute(f"SET hi = (SELECT COALESCE(MAX(LOAD_TS), '1970-01-01'::TIMESTAMP_LTZ) "  # nosec B608
                f"FROM {bronze_table(source)})")
    dict_cur = conn.cursor(snowflake.connector.DictCursor)
    dict_cur.execute(
        f"SELECT {', '.join(bronze_cols)} FROM {bronze_table(source)} "  # nosec B608
        "WHERE LOAD_TS > (SELECT LAST_LOAD_TS FROM AUDIT.WATERMARK WHERE LAYER = 'SILVER' AND SOURCE = %s) "
        "AND LOAD_TS <= $hi ORDER BY LOAD_TS, SOURCE_FILE",
        (source,))
    raw_rows = [{k.lower(): v for k, v in row.items()} for row in dict_cur.fetchall()]

    # 2. validate
    good, issues = _validate(source, raw_rows, cur)

    # 3. stage good rows (temp table), then MERGE + DQ log + watermark in ONE transaction
    stage = f"AUDIT.STG_{source.upper()}"
    all_cols = cols + ["source_file"]
    cur.execute(f"CREATE OR REPLACE TEMPORARY TABLE {stage} AS "  # nosec B608
                f"SELECT {', '.join(all_cols)} FROM {table} WHERE 1 = 0")
    if good:
        placeholders = ", ".join(["%s"] * len(all_cols))
        cur.executemany(f"INSERT INTO {stage} ({', '.join(all_cols)}) VALUES ({placeholders})",  # nosec B608
                        [tuple(r.get(c) for c in all_cols) for r in good])

    on = " AND ".join(f"t.{k} = s.{k}" for k in keys)
    updates = ", ".join(f"t.{c} = s.{c}" for c in all_cols if c not in keys)
    merge = f"MERGE INTO {table} t USING {stage} s ON {on} "  # nosec B608
    if source != "payment_events":              # events never change -> insert only
        merge += f"WHEN MATCHED THEN UPDATE SET {updates}, t.LOADED_AT = CURRENT_TIMESTAMP() "  # nosec B608
    merge += (f"WHEN NOT MATCHED THEN INSERT ({', '.join(all_cols)}, LOADED_AT) "
              f"VALUES ({', '.join('s.' + c for c in all_cols)}, CURRENT_TIMESTAMP())")

    cur.execute("BEGIN")
    try:
        cur.execute(merge)
        if issues:
            cur.executemany(
                "INSERT INTO AUDIT.DQ_LOG (RUN_ID, SOURCE, RECORD_KEY, SEVERITY, REASON, RAW_RECORD) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                [(run_id, source, k, sev, reason, raw) for k, sev, reason, raw in issues])
        cur.execute("UPDATE AUDIT.WATERMARK SET LAST_LOAD_TS = GREATEST($hi, LAST_LOAD_TS), "
                    "UPDATED_AT = CURRENT_TIMESTAMP() WHERE LAYER = 'SILVER' AND SOURCE = %s", (source,))
        cur.execute("COMMIT")
    except Exception:
        cur.execute("ROLLBACK")
        raise

    stats = {"read": len(raw_rows), "loaded": len(good),
             "quarantined": sum(1 for i in issues if i[1] == rules.QUARANTINE),
             "rejected": sum(1 for i in issues if i[1] == rules.REJECT),
             "warnings": sum(1 for i in issues if i[1] == rules.WARNING)}
    print(f"  [silver] {source:15s} read={stats['read']:4d} loaded={stats['loaded']:4d} "
          f"quarantined={stats['quarantined']:3d} rejected={stats['rejected']:3d} warnings={stats['warnings']:3d}")
    return stats


def build_silver(conn, run_id: str) -> dict:
    totals = {"read": 0, "loaded": 0, "quarantined": 0, "rejected": 0, "warnings": 0}
    for source in SOURCES:
        for k, v in process_source(conn, source, run_id).items():
            totals[k] += v
    return totals
