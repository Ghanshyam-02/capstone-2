"""The ONLY place in the API that runs SQL.

- Every value goes in as a bind parameter (?) - never pasted into the SQL text -
  so SQL injection is impossible.
- The database is opened READ-ONLY: the API can never change data.
"""
from common.db import connect


class Repository:
    def query(self, sql: str, params: list | None = None) -> list[tuple]:
        con = connect(read_only=True)
        try:
            return con.execute(sql, params or []).fetchall()
        finally:
            con.close()

    def ping(self) -> bool:
        """Database is reachable AND the Gold KPI table has data."""
        return self.query("SELECT COUNT(*) FROM gold.agg_merchant_daily")[0][0] > 0

    def merchant_exists(self, merchant_id: str) -> bool:
        return bool(self.query("SELECT 1 FROM gold.dim_merchant WHERE merchant_id = ?", [merchant_id]))

    def totals(self, start, end, merchant_id=None) -> dict:
        sql = ("SELECT SUM(success_count), SUM(success_amount), SUM(settled_amount), SUM(sla_met_count) "
               "FROM gold.agg_merchant_daily WHERE txn_date BETWEEN ? AND ?")
        params = [start, end]
        if merchant_id:
            sql += " AND merchant_id = ?"
            params.append(merchant_id)
        count, amount, settled, sla = self.query(sql, params)[0]
        return {"count": int(count or 0), "amount": float(amount or 0),
                "settled": float(settled or 0), "sla_met": int(sla or 0)}

    def merchant_totals(self, start=None, end=None) -> list[dict]:
        sql = ("SELECT a.merchant_id, m.merchant_name, m.risk_level, SUM(a.success_count), "
               "       SUM(a.success_amount), SUM(a.settled_amount), SUM(a.sla_met_count) "
               "FROM gold.agg_merchant_daily a "
               "LEFT JOIN gold.dim_merchant m ON m.merchant_id = a.merchant_id AND m.is_current ")
        params = []
        if start and end:
            sql += "WHERE a.txn_date BETWEEN ? AND ? "
            params = [start, end]
        sql += "GROUP BY ALL"
        return [{"merchant_id": r[0], "merchant_name": r[1], "risk_level": r[2], "count": int(r[3]),
                 "amount": float(r[4]), "settled": float(r[5]), "sla_met": int(r[6])}
                for r in self.query(sql, params)]

    def daily(self, start, end) -> list[dict]:
        rows = self.query("SELECT txn_date, SUM(success_amount), SUM(settled_amount) FROM gold.agg_merchant_daily "
                          "WHERE txn_date BETWEEN ? AND ? GROUP BY txn_date ORDER BY txn_date", [start, end])
        return [{"date": r[0], "transaction_amount": float(r[1]), "settled_amount": float(r[2])} for r in rows]
