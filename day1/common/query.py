"""Run SQL against the database and print the result as a table.

    python -m common.query "SELECT * FROM audit.dq_log LIMIT 5"
    python -m common.query sql/06_explore.sql          # runs every query in the file
"""
import sys
from pathlib import Path

from common import config
from common.db import connect


def main():
    sys.stdout.reconfigure(encoding="utf-8")        # Windows terminals: print table borders correctly
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    arg = sys.argv[1]
    path = config.PROJECT_ROOT / arg
    text = path.read_text(encoding="utf-8") if arg.endswith(".sql") and path.exists() else arg

    con = connect(read_only=True)
    for statement in [s.strip() for s in text.split(";") if s.strip()]:
        comments = [line for line in statement.splitlines() if line.strip().startswith("--")]
        sql = "\n".join(line for line in statement.splitlines() if not line.strip().startswith("--"))
        if not sql.strip():
            continue
        print("\n" + (comments[-1] if comments else sql))         # the query's title line
        con.sql(sql).show(max_rows=30, max_width=200)


if __name__ == "__main__":
    main()
