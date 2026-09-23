"""Run the whole pipeline:  SOURCE FILES -> BRONZE -> SILVER -> GOLD

    python -m pipeline.run_pipeline --init     # first time: create all tables, then run
    python -m pipeline.run_pipeline            # every next time (only new data is processed)
"""
import argparse
import uuid
from pathlib import Path

from common import config
from common.snowflake_conn import get_connection
from pipeline.ingest import ingest_to_bronze
from pipeline.silver import build_silver

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def run_sql_file(conn, name: str):
    conn.execute_string((SQL_DIR / name).read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true", help="create all tables and views first")
    args = parser.parse_args()

    run_id = uuid.uuid4().hex[:12]
    conn = get_connection(config.SNOWFLAKE_PIPELINE_ROLE)
    cur = conn.cursor()
    try:
        if args.init:
            for name in ["01_bronze_audit_ddl.sql", "02_silver_ddl.sql", "03_gold_ddl.sql"]:
                print(f"[init] {name}")
                run_sql_file(conn, name)

        cur.execute("INSERT INTO AUDIT.PIPELINE_RUNS (RUN_ID, STATUS) VALUES (%s, 'RUNNING')", (run_id,))

        print("1) INGESTION -> BRONZE")
        files = ingest_to_bronze(conn)
        print("2) BRONZE -> SILVER")
        stats = build_silver(conn, run_id)
        print("3) SILVER -> GOLD")
        run_sql_file(conn, "04_gold_transform.sql")

        cur.execute("UPDATE AUDIT.PIPELINE_RUNS SET FINISHED_AT = CURRENT_TIMESTAMP(), STATUS = 'SUCCESS', "
                    "FILES_LOADED = %s, ROWS_LOADED = %s, ROWS_QUARANTINED = %s, ROWS_REJECTED = %s "
                    "WHERE RUN_ID = %s",
                    (files, stats["loaded"], stats["QUARANTINE"], stats["REJECT"], run_id))
        print(f"Done: {files} new files, {stats['loaded']} rows to Silver, "
              f"{stats['QUARANTINE']} quarantined, {stats['REJECT']} rejected, {stats['WARNING']} warnings")
    except Exception as exc:
        cur.execute("ROLLBACK")
        cur.execute("UPDATE AUDIT.PIPELINE_RUNS SET FINISHED_AT = CURRENT_TIMESTAMP(), STATUS = 'FAILED', "
                    "ERROR_MESSAGE = %s WHERE RUN_ID = %s", (str(exc)[:1000], run_id))
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
