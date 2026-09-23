"""Settlement API (FastAPI).

    uvicorn api.main:app --reload
    dashboard -> http://localhost:8000/
    API docs  -> http://localhost:8000/docs   (OpenAPI, generated automatically)
"""
import logging
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from common import config  # noqa: F401  (loads the .env file)
from common import kpi
from api.models import DailyPoint, Merchant, SettlementSummary
from api.repository import SnowflakeRepository
from api.security import require_api_key

logging.basicConfig(level=logging.INFO)     # uvicorn logs method, path and status only - no data

app = FastAPI(title="Merchant Settlement API", version="1.0.0")
repository = SnowflakeRepository()


def get_repo():
    """Tests swap this for a fake repository, so they run without Snowflake."""
    return repository


Repo = Annotated[SnowflakeRepository, Depends(get_repo)]
Auth = [Depends(require_api_key)]
# merchant_id must look like M1008. Anything else ("M1' OR '1'='1") -> 422 before any SQL runs.
MerchantId = Annotated[str | None, Query(pattern=r"^M\d{3,6}$")]


def parse_dates(start_date: str, end_date: str) -> tuple[date, date]:
    try:
        start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(400, "Dates must be real dates in YYYY-MM-DD format")
    if end < start:
        raise HTTPException(400, "end_date must be on or after start_date")
    return start, end


def to_merchant(m: dict) -> Merchant:
    return Merchant(merchant_id=m["merchant_id"], merchant_name=m["merchant_name"], risk_level=m["risk_level"],
                    settlement_rate=kpi.settlement_rate(m["settled"], m["amount"]),
                    sla_rate=kpi.sla_rate(m["sla_met"], m["count"]),
                    settlement_gap=kpi.settlement_gap(m["amount"], m["settled"]))


@app.get("/health")
def health(repo: Repo):
    """For Docker / deployment health checks. No key needed, returns no data."""
    try:
        repo.ping()
        return {"status": "ok"}
    except Exception:
        raise HTTPException(503, "database unreachable")


@app.get("/api/v1/settlement-summary", response_model=SettlementSummary, dependencies=Auth)
def settlement_summary(repo: Repo, start_date: str, end_date: str, merchant_id: MerchantId = None):
    start, end = parse_dates(start_date, end_date)
    if merchant_id and not repo.merchant_exists(merchant_id):
        raise HTTPException(404, f"Unknown merchant {merchant_id}")

    t = repo.totals(start, end, merchant_id)
    merchants = [to_merchant(m) for m in repo.merchant_totals(start, end)
                 if merchant_id is None or m["merchant_id"] == merchant_id]
    return SettlementSummary(
        transaction_count=t["count"],
        transaction_amount=round(t["amount"], 2),
        settled_amount=round(t["settled"], 2),
        settlement_rate=kpi.settlement_rate(t["settled"], t["amount"]),
        settlement_gap=kpi.settlement_gap(t["amount"], t["settled"]),
        sla_rate=kpi.sla_rate(t["sla_met"], t["count"]),
        merchant_risk_count=sum(kpi.is_high_risk_merchant(m.settlement_rate, m.sla_rate) for m in merchants),
    )


@app.get("/api/v1/merchant-exceptions", response_model=list[Merchant], dependencies=Auth)
def merchant_exceptions(repo: Repo):
    """Merchants with settlement_rate < 95% OR sla_rate < 90% (all data)."""
    merchants = [to_merchant(m) for m in repo.merchant_totals()]
    return [m for m in merchants if kpi.is_merchant_exception(m.settlement_rate, m.sla_rate)]


# ---- two small extra endpoints the dashboard needs for its charts and table
@app.get("/api/v1/merchants", response_model=list[Merchant], dependencies=Auth)
def merchants(repo: Repo, start_date: str, end_date: str):
    """All merchants, largest settlement gap first (chart 2 + table)."""
    start, end = parse_dates(start_date, end_date)
    result = [to_merchant(m) for m in repo.merchant_totals(start, end)]
    return sorted(result, key=lambda m: m.settlement_gap, reverse=True)


@app.get("/api/v1/daily-trend", response_model=list[DailyPoint], dependencies=Auth)
def daily_trend(repo: Repo, start_date: str, end_date: str):
    """Daily transaction amount vs daily settled amount (chart 1)."""
    start, end = parse_dates(start_date, end_date)
    return repo.daily(start, end)


# The dashboard is served by the same app, so the browser needs no CORS setup.
app.mount("/", StaticFiles(directory=Path(__file__).parent.parent / "frontend", html=True), name="frontend")
