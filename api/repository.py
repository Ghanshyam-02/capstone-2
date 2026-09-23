"""Data access for the API - the ONLY place that talks to Snowflake.

Every query uses bind parameters (%s). User input is never pasted into SQL,
so SQL injection is impossible. The API connects with API_ROLE, which can
only SELECT from the GOLD schema.
"""
import threading
from datetime import date

from common import config
from common.snowflake_conn import get_connection


def _f(value) -> float:
    return float(value or 0)


def _i(value) -> int:
    return int(value or 0)


class SnowflakeRepository:
    def __init__(self):
        self._conn = None
        self._lock = threading.Lock()

    def _connection(self):
        with self._lock:
            if self._conn is None or self._conn.is_closed():
                self._conn = get_connection(config.SNOWFLAKE_API_ROLE)
            return self._conn

    def _query(self, sql: str, params: tuple = ()) -> list[tuple]:
        cur = self._connection().cursor()
        try:
            return cur.execute(sql, params).fetchall()
        finally:
            cur.close()

    # ------------------------------------------------------------------
    def ping(self) -> bool:
        return self._query("SELECT 1")[0][0] == 1

    def merchant_exists(self, merchant_id: str) -> bool:
        rows = self._query("SELECT 1 FROM GOLD.DIM_MERCHANT WHERE MERCHANT_ID = %s LIMIT 1", (merchant_id,))
        return bool(rows)

    def data_range(self) -> tuple[date | None, date | None]:
        row = self._query("SELECT MIN(TXN_DATE), MAX(TXN_DATE) FROM GOLD.AGG_MERCHANT_DAILY")[0]
        return row[0], row[1]

    def totals(self, start: date, end: date, merchant_id: str | None) -> dict:
        sql = ("SELECT SUM(SUCCESS_COUNT), SUM(SUCCESS_AMOUNT), SUM(SETTLED_AMOUNT), SUM(SLA_MET_COUNT) "
               "FROM GOLD.AGG_MERCHANT_DAILY WHERE TXN_DATE BETWEEN %s AND %s")
        params: tuple = (start, end)
        if merchant_id:
            sql += " AND MERCHANT_ID = %s"
            params += (merchant_id,)
        c, amt, settled, sla = self._query(sql, params)[0]
        return {"success_count": _i(c), "success_amount": _f(amt), "settled_amount": _f(settled),
                "sla_met_count": _i(sla)}

    def merchant_totals(self, start: date, end: date) -> list[dict]:
        rows = self._query(
            "SELECT a.MERCHANT_ID, m.MERCHANT_NAME, m.RISK_LEVEL, SUM(a.SUCCESS_COUNT), SUM(a.SUCCESS_AMOUNT), "
            "       SUM(a.SETTLED_AMOUNT), SUM(a.SLA_MET_COUNT) "
            "FROM GOLD.AGG_MERCHANT_DAILY a "
            "LEFT JOIN GOLD.DIM_MERCHANT m ON m.MERCHANT_ID = a.MERCHANT_ID AND m.IS_CURRENT "
            "WHERE a.TXN_DATE BETWEEN %s AND %s "
            "GROUP BY a.MERCHANT_ID, m.MERCHANT_NAME, m.RISK_LEVEL",
            (start, end))
        return [{"merchant_id": r[0], "merchant_name": r[1], "risk_level": r[2], "success_count": _i(r[3]),
                 "success_amount": _f(r[4]), "settled_amount": _f(r[5]), "sla_met_count": _i(r[6])}
                for r in rows]

    def daily(self, start: date, end: date, merchant_id: str | None) -> list[dict]:
        sql = ("SELECT TXN_DATE, SUM(SUCCESS_AMOUNT), SUM(SETTLED_AMOUNT) FROM GOLD.AGG_MERCHANT_DAILY "
               "WHERE TXN_DATE BETWEEN %s AND %s")
        params: tuple = (start, end)
        if merchant_id:
            sql += " AND MERCHANT_ID = %s"
            params += (merchant_id,)
        sql += " GROUP BY TXN_DATE ORDER BY TXN_DATE"
        return [{"date": r[0], "transaction_amount": _f(r[1]), "settled_amount": _f(r[2])}
                for r in self._query(sql, params)]

    def gap_breakdown(self, start: date, end: date, merchant_id: str | None) -> list[dict]:
        sql = ("SELECT SUM(PARTIAL_COUNT), SUM(GAP_PARTIAL_AMT), SUM(PENDING_COUNT), SUM(GAP_PENDING_AMT), "
               "       SUM(SETTLE_FAILED_COUNT), SUM(GAP_FAILED_AMT), SUM(UNSETTLED_COUNT), SUM(GAP_UNSETTLED_AMT) "
               "FROM GOLD.AGG_MERCHANT_DAILY WHERE TXN_DATE BETWEEN %s AND %s")
        params: tuple = (start, end)
        if merchant_id:
            sql += " AND MERCHANT_ID = %s"
            params += (merchant_id,)
        r = self._query(sql, params)[0]
        names = ["PARTIALLY_SETTLED", "PENDING", "SETTLEMENT_FAILED", "UNSETTLED"]
        return [{"category": n, "transaction_count": _i(r[i * 2]), "amount": _f(r[i * 2 + 1])}
                for i, n in enumerate(names)]

    def data_quality(self) -> list[dict]:
        rows = self._query("SELECT SOURCE, SEVERITY, REASON, RECORD_COUNT FROM GOLD.V_DQ_SUMMARY "
                           "ORDER BY RECORD_COUNT DESC")
        return [{"source": r[0], "severity": r[1], "reason": r[2], "record_count": _i(r[3])} for r in rows]
