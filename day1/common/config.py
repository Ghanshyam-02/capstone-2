"""All settings come from environment variables (or the local .env file).

Nothing secret is written in the code - see docs/05_security.md.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def db_path() -> Path:
    """Path of the DuckDB database file (read at call time, so tests can change it)."""
    path = Path(os.getenv("SETTLEMENT_DB", "data/warehouse/settlement.duckdb"))
    return path if path.is_absolute() else PROJECT_ROOT / path


def app_version() -> str:
    return os.getenv("APP_VERSION", "1.0.0")
