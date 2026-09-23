"""INGESTION -> BRONZE.

1. PUT   : upload local CSV files into the Snowflake stage @BRONZE.RAW_STAGE
2. COPY  : load staged files into BRONZE tables (all columns as text)

Incremental for free: Snowflake remembers which files COPY already loaded
(load metadata) and skips them next time.
"""
from pathlib import Path

from pipeline.generate_data import COLUMNS

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

# Processing order matters: merchants before transactions before settlements/events.
SOURCES = ["merchant", "transactions", "settlements", "payment_events"]


def bronze_table(source: str) -> str:
    return f"BRONZE.{source.upper()}"


def ingest_to_bronze(conn) -> int:
    """Returns number of NEW files loaded."""
    cur = conn.cursor()
    files_loaded = 0
    for source in SOURCES:
        files = sorted(RAW_DIR.glob(f"{source}_*.csv"))
        for path in files:
            # OVERWRITE=FALSE: a file already in the stage is not uploaded again.
            cur.execute(f"PUT 'file://{path.as_posix()}' @BRONZE.RAW_STAGE/{source}/ "
                        "AUTO_COMPRESS=TRUE OVERWRITE=FALSE")

        # Identifiers come from the fixed SOURCES/COLUMNS lists above, never from
        # user input, so building this statement with an f-string is safe.
        cols = COLUMNS[source]
        select = ", ".join(f"${i}" for i in range(1, len(cols) + 1))
        sql = (f"COPY INTO {bronze_table(source)} ({', '.join(cols)}, SOURCE_FILE) "  # nosec B608
               f"FROM (SELECT {select}, METADATA$FILENAME FROM @BRONZE.RAW_STAGE/{source}/) "
               "FILE_FORMAT = (FORMAT_NAME = 'BRONZE.CSV_FMT') ON_ERROR = 'CONTINUE'")
        for row in cur.execute(sql).fetchall():
            if len(row) < 6:          # "Copy executed with 0 files processed."
                continue
            file, status, parsed, loaded, errors = row[0], row[1], row[2], row[3], row[5]
            files_loaded += 1
            print(f"  [bronze] {file}: {status}, {loaded}/{parsed} rows loaded")
            if errors:
                # Rows Snowflake could not even parse are reported, not hidden.
                print(f"  [bronze] WARNING {errors} unparseable rows in {file}: {row[6]}")
    return files_loaded
