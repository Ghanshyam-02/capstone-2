"""Run the whole pipeline:  SOURCE FILES -> BRONZE -> SILVER -> GOLD

    python -m pipeline.run_pipeline --init     # first time: create tables, then run
    python -m pipeline.run_pipeline            # every next time (incremental)
"""
import argparse
import sys
import uuid
from pathlib import Path

from common import config
from common.snowflake_conn import get_connection
from pipeline.ingest import ingest_to_bronze
from pipeline.silver import build_silver

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"
DDL_FILES = ["01_bronze_audit_ddl.sql", "02_silver_ddl.sql", "03_gold_ddl.sql"]


def run_sql_file(conn, name: str):
    conn.execute_string((SQL_DIR / name).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true", help="create/refresh all tables and views first")
    args = parser.parse_args()

    run_id = uuid.uuid4().hex[:12]
    conn = get_connection(config.SNOWFLAKE_PIPELINE_ROLE)
    cur = conn.cursor()
    try:
        if args.init:
            for name in DDL_FILES:
                print(f"[init] running {name}")
                run_sql_file(conn, name)

        cur.execute("INSERT INTO AUDIT.PIPELINE_RUNS (RUN_ID, STARTED_AT, STATUS) "
                    "VALUES (%s, CURRENT_TIMESTAMP(), 'RUNNING')", (run_id,))
        print(f"Run {run_id}")

        print("1) INGESTION -> BRONZE")
        files = ingest_to_bronze(conn)

        print("2) BRONZE -> SILVER (validate / clean / de-duplicate)")
        stats = build_silver(conn, run_id)

        print("3) SILVER -> GOLD (star schema + KPI table)")
        run_sql_file(conn, "04_gold_transform.sql")

        cur.execute("UPDATE AUDIT.PIPELINE_RUNS SET FINISHED_AT = CURRENT_TIMESTAMP(), STATUS = 'SUCCESS', "
                    "FILES_LOADED = %s, ROWS_TO_SILVER = %s, ROWS_QUARANTINED = %s, ROWS_REJECTED = %s, "
                    "ROWS_WARNING = %s WHERE RUN_ID = %s",
                    (files, stats["loaded"], stats["quarantined"], stats["rejected"], stats["warnings"], run_id))
        print(f"Done. new files={files} silver rows={stats['loaded']} quarantined={stats['quarantined']} "
              f"rejected={stats['rejected']} warnings={stats['warnings']}")
        return 0
    except Exception as exc:
        # Log only the error type/message - never row data.
        print(f"Pipeline FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        try:
            cur.execute("UPDATE AUDIT.PIPELINE_RUNS SET FINISHED_AT = CURRENT_TIMESTAMP(), STATUS = 'FAILED', "
                        "ERROR_MESSAGE = %s WHERE RUN_ID = %s", (str(exc)[:1000], run_id))
        except Exception:
            pass
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
