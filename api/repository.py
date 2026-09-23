"""The ONLY place in the API that talks to Snowflake.

Every value goes in as a bind parameter (%s) - never pasted into the SQL text -
so SQL injection is impossible. The API logs in with API_ROLE (read-only on GOLD).
"""
from common import config
from common.snowflake_conn import get_connection


class SnowflakeRepository:
    def __init__(self):
        self.conn = None

    def query(self, sql: str, params: tuple = ()) -> list[tuple]:
        if self.conn is None or self.conn.is_closed():
            self.conn = get_connection(config.SNOWFLAKE_API_ROLE)
        return self.conn.cursor().execute(sql, params).fetchall()

    def ping(self) -> bool:
        return self.query("SELECT 1")[0][0] == 1

    def merchant_exists(self, merchant_id: str) -> bool:
        return bool(self.query("SELECT 1 FROM GOLD.DIM_MERCHANT WHERE MERCHANT_ID = %s", (merchant_id,)))

    def totals(self, start, end, merchant_id=None) -> dict:
        sql = ("SELECT SUM(SUCCESS_COUNT), SUM(SUCCESS_AMOUNT), SUM(SETTLED_AMOUNT), SUM(SLA_MET_COUNT) "
               "FROM GOLD.AGG_MERCHANT_DAILY WHERE TXN_DATE BETWEEN %s AND %s")
        params = (start, end)
        if merchant_id:
            sql += " AND MERCHANT_ID = %s"
            params += (merchant_id,)
        count, amount, settled, sla = self.query(sql, params)[0]
        return {"count": int(count or 0), "amount": float(amount or 0),
                "settled": float(settled or 0), "sla_met": int(sla or 0)}

    def merchant_totals(self, start=None, end=None) -> list[dict]:
        sql = ("SELECT a.MERCHANT_ID, m.MERCHANT_NAME, m.RISK_LEVEL, SUM(a.SUCCESS_COUNT), "
               "       SUM(a.SUCCESS_AMOUNT), SUM(a.SETTLED_AMOUNT), SUM(a.SLA_MET_COUNT) "
               "FROM GOLD.AGG_MERCHANT_DAILY a "
               "LEFT JOIN GOLD.DIM_MERCHANT m ON m.MERCHANT_ID = a.MERCHANT_ID AND m.IS_CURRENT ")
        params = ()
        if start and end:
            sql += "WHERE a.TXN_DATE BETWEEN %s AND %s "
            params = (start, end)
        sql += "GROUP BY 1, 2, 3"
        return [{"merchant_id": r[0], "merchant_name": r[1], "risk_level": r[2], "count": int(r[3]),
                 "amount": float(r[4]), "settled": float(r[5]), "sla_met": int(r[6])}
                for r in self.query(sql, params)]

    def daily(self, start, end) -> list[dict]:
        rows = self.query("SELECT TXN_DATE, SUM(SUCCESS_AMOUNT), SUM(SETTLED_AMOUNT) FROM GOLD.AGG_MERCHANT_DAILY "
                          "WHERE TXN_DATE BETWEEN %s AND %s GROUP BY 1 ORDER BY 1", (start, end))
        return [{"date": r[0], "transaction_amount": float(r[1]), "settled_amount": float(r[2])} for r in rows]
