"""One place that opens the DuckDB database.

DuckDB is a SQL database that lives in a single file on your computer
(like SQLite, but built for analytics). No server, no account, no password.
"""
import duckdb

from common import config


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    path = config.db_path()
    if read_only and not path.exists():
        raise FileNotFoundError(f"{path} not found - run: python -m pipeline.run_pipeline")
    path.parent.mkdir(parents=True, exist_ok=True)
    # read_only=True: the API can read but can never change data (least privilege)
    return duckdb.connect(str(path), read_only=read_only)
