"""KPI reconciliation: are the numbers the API serves the SAME as the numbers in the facts?

    python -m common.reconcile                       (September 2026)
    python -m common.reconcile 2026-09-01 2026-09-15

It recalculates the settlement KPIs two independent ways:
  1. from the facts, via gold.v_txn_settlement  (settlements summed per transaction first)
  2. from gold.agg_merchant_daily               (the KPI table the API reads)
and checks that they match and that no merchant has settled more than it transacted.
Exit code 1 = reconciliation failed (used as a deployment gate).
"""
import sys

from common.db import connect


def main(start: str = "2026-09-01", end: str = "2026-09-30") -> int:
    con = connect(read_only=True)
    period = [start, end]
    f_amount, f_settled = con.execute(
        "SELECT SUM(amount), SUM(settled_amount) FROM gold.v_txn_settlement WHERE txn_date BETWEEN ? AND ?",
        period).fetchone()
    t_amount, t_settled = con.execute(
        "SELECT SUM(success_amount), SUM(settled_amount) FROM gold.agg_merchant_daily WHERE txn_date BETWEEN ? AND ?",
        period).fetchone()
    over = [r[0] for r in con.execute(
        "SELECT merchant_id FROM gold.agg_merchant_daily WHERE txn_date BETWEEN ? AND ? "
        "GROUP BY merchant_id HAVING SUM(settled_amount) > SUM(success_amount) ORDER BY 1", period).fetchall()]

    facts_rate = round(float(f_settled) / float(f_amount) * 100, 2)
    table_rate = round(float(t_settled) / float(t_amount) * 100, 2)
    checks = [
        ("successful amount: facts = KPI table", f_amount == t_amount, f"{f_amount} vs {t_amount}"),
        ("settled amount:    facts = KPI table", f_settled == t_settled, f"{f_settled} vs {t_settled}"),
        ("settlement rate:   facts = KPI table", facts_rate == table_rate, f"{facts_rate} % vs {table_rate} %"),
        ("no merchant settled > successful", not over, ", ".join(over) or "none"),
    ]
    print(f"KPI reconciliation {start} .. {end}")
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name:40s} {detail}")
    passed = all(ok for _, ok, _ in checks)
    print(f"RESULT: {'PASS' if passed else 'FAIL'}   (expected settlement rate = {facts_rate} %)")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
