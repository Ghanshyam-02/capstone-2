"""All configuration comes from environment variables (or a local .env file).

Nothing secret is written in source code - see docs/05_security.md.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def env(name: str, default: str | None = None) -> str | None:
    return os.getenv(name, default)


def required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name} (see .env.example)")
    return value


SNOWFLAKE_PIPELINE_ROLE = env("SNOWFLAKE_PIPELINE_ROLE", "PIPELINE_ROLE")
SNOWFLAKE_API_ROLE = env("SNOWFLAKE_API_ROLE", "API_ROLE")
LATE_EVENT_THRESHOLD_MIN = int(env("LATE_EVENT_THRESHOLD_MIN", "5"))
