"""SOURCE FILES -> INGESTION -> BRONZE.

Every CSV in data/raw that was not loaded before is copied into its Bronze
table exactly as it is (all columns as text), tagged with the file name and a
load_id. audit.loaded_files remembers loaded files, so a file is never loaded
twice (incremental ingestion).
"""
from pathlib import Path

from common.config import PROJECT_ROOT

RAW_DIR = PROJECT_ROOT / "data" / "raw"

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


def ingest_to_bronze(con, raw_dir: Path = RAW_DIR) -> int:
    """Load new CSV files into Bronze. Returns the number of new files."""
    new_files = 0
    for source, cols in COLUMNS.items():
        for path in sorted(raw_dir.glob(f"{source}_*.csv")):
            if con.execute("SELECT 1 FROM audit.loaded_files WHERE file_name = ?", [path.name]).fetchone():
                continue                                            # already loaded -> skip

            load_id = con.execute("SELECT nextval('audit.load_id_seq')").fetchone()[0]
            col_list = ", ".join(cols)
            # table/column names come from the COLUMNS constant above (never from user input)
            con.execute(
                f"INSERT INTO bronze.{source} ({col_list}, source_file, load_id) "
                f"SELECT {col_list}, ?, ? FROM read_csv(?, header = true, all_varchar = true)",
                [path.name, load_id, str(path)])
            rows = con.execute(f"SELECT COUNT(*) FROM bronze.{source} WHERE load_id = ?", [load_id]).fetchone()[0]
            con.execute("INSERT INTO audit.loaded_files (file_name, load_id, row_count) VALUES (?, ?, ?)",
                        [path.name, load_id, rows])
            print(f"  [bronze] {path.name}: {rows:,} rows loaded")
            new_files += 1
    return new_files
