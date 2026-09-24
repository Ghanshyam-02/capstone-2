"""SOURCE FILES -> INGESTION -> BRONZE.

1. PUT  : upload the CSV files from data/raw into the Snowflake stage @BRONZE.RAW_STAGE
2. COPY : load the staged files into the BRONZE tables (every column as text)

Snowflake remembers which files COPY has already loaded and skips them,
so running this again only loads NEW files (incremental ingestion).
"""
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

# The 4 source files and their columns (from the brief). Order matters:
# merchants before transactions, transactions before settlements and events.
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
SOURCES = list(COLUMNS)


def ingest_to_bronze(conn) -> int:
    cur = conn.cursor()
    new_files = 0
    for source in SOURCES:
        for path in sorted(RAW_DIR.glob(f"{source}_*.csv")):
            cur.execute(f"PUT 'file://{path.as_posix()}' @BRONZE.RAW_STAGE/{source}/ OVERWRITE=FALSE")

        cols = COLUMNS[source]
        positions = ", ".join(f"${i}" for i in range(1, len(cols) + 1))     # $1, $2, ... = CSV columns
        result = cur.execute(
            f"COPY INTO BRONZE.{source.upper()} ({', '.join(cols)}, SOURCE_FILE) "
            f"FROM (SELECT {positions}, METADATA$FILENAME FROM @BRONZE.RAW_STAGE/{source}/) "
            "FILE_FORMAT = (FORMAT_NAME = 'BRONZE.CSV_FMT') ON_ERROR = 'CONTINUE'").fetchall()
        for row in result:
            if len(row) > 5:                     # one row per loaded file
                new_files += 1
                print(f"  [bronze] {row[0]}: {row[3]}/{row[2]} rows loaded, {row[5]} errors")
    return new_files
