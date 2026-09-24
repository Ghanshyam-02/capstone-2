"""Run the whole pipeline:  SOURCE FILES -> BRONZE -> SILVER -> GOLD

    python -m pipeline.run_pipeline

Safe to run again and again: only NEW files and rows are processed.
"""
import uuid
from pathlib import Path

from common.config import PROJECT_ROOT
from common.db import connect
from pipeline.ingest import RAW_DIR, ingest_to_bronze

SQL_DIR = PROJECT_ROOT / "sql"


def run_sql_file(con, name: str):
    con.execute((SQL_DIR / name).read_text(encoding="utf-8"))


def run(raw_dir: Path = RAW_DIR) -> dict:
    run_id = uuid.uuid4().hex[:12]
    con = connect()
    try:
        # 0. create schemas/tables if they do not exist yet
        for name in ["01_bronze.sql", "02_silver.sql", "03_gold.sql"]:
            run_sql_file(con, name)
        con.execute("INSERT INTO audit.pipeline_runs (run_id, status) VALUES (?, 'RUNNING')", [run_id])

        print(f"Run {run_id}")
        print("1) INGESTION -> BRONZE")
        files = ingest_to_bronze(con, raw_dir)

        print("2) BRONZE -> SILVER (validate / clean / de-duplicate)")
        con.execute("SET VARIABLE run_id = ?", [run_id])
        run_sql_file(con, "04_bronze_to_silver.sql")
        issues = dict(con.execute("SELECT severity, COUNT(*) FROM audit.dq_log WHERE run_id = ? GROUP BY 1",
                                  [run_id]).fetchall())
        print(f"  [silver] quarantined={issues.get('QUARANTINE', 0)} rejected={issues.get('REJECT', 0)} "
              f"warnings={issues.get('WARNING', 0)}  (details: audit.dq_log)")

        print("3) SILVER -> GOLD (star schema + KPI table)")
        run_sql_file(con, "05_silver_to_gold.sql")
        for table in ["fact_transaction", "fact_settlement", "fact_payment_event", "agg_merchant_daily"]:
            print(f"  [gold] {table}: {con.execute(f'SELECT COUNT(*) FROM gold.{table}').fetchone()[0]:,} rows")

        con.execute("UPDATE audit.pipeline_runs SET finished_at = current_timestamp, status = 'SUCCESS', "
                    "files_loaded = ?, rows_quarantined = ?, rows_rejected = ? WHERE run_id = ?",
                    [files, issues.get("QUARANTINE", 0), issues.get("REJECT", 0), run_id])
        print(f"Done: {files} new file(s) processed.")
        return {"run_id": run_id, "files": files, **issues}
    except Exception as exc:
        try:
            con.execute("ROLLBACK")          # undo a half-finished SQL file
        except Exception:
            pass                             # nothing was open
        con.execute("UPDATE audit.pipeline_runs SET finished_at = current_timestamp, status = 'FAILED', "
                    "error_message = ? WHERE run_id = ?", [str(exc)[:1000], run_id])
        raise
    finally:
        con.close()


if __name__ == "__main__":
    run()
