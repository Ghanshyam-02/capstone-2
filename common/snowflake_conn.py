"""One place that knows how to connect to Snowflake.

Run `python -m common.snowflake_conn` to test your .env settings.
"""
from pathlib import Path

import snowflake.connector

from common import config


def get_connection(role: str):
    params = {
        "account": config.required("SNOWFLAKE_ACCOUNT"),
        "user": config.required("SNOWFLAKE_USER"),
        "warehouse": config.required("SNOWFLAKE_WAREHOUSE"),
        "database": config.required("SNOWFLAKE_DATABASE"),
        "role": role,
        "application": "settlement-platform",
        "client_session_keep_alive": True,
    }
    key_path = config.env("SNOWFLAKE_PRIVATE_KEY_PATH")
    if key_path:
        # Key-pair auth: how service accounts log in in real companies.
        key_file = Path(key_path)
        if not key_file.is_absolute():
            key_file = config.PROJECT_ROOT / key_file
        params["authenticator"] = "SNOWFLAKE_JWT"
        params["private_key_file"] = str(key_file)
    else:
        params["password"] = config.required("SNOWFLAKE_PASSWORD")
    return snowflake.connector.connect(**params)


if __name__ == "__main__":
    for role in (config.SNOWFLAKE_PIPELINE_ROLE, config.SNOWFLAKE_API_ROLE):
        with get_connection(role) as conn:
            row = conn.cursor().execute(
                "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_WAREHOUSE(), CURRENT_VERSION()"
            ).fetchone()
            print(f"Connected OK -> user={row[0]} role={row[1]} warehouse={row[2]} version={row[3]}")
