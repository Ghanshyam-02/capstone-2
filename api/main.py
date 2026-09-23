"""Settlement Intelligence API (FastAPI).

    uvicorn api.main:app --reload
    -> dashboard:  http://localhost:8000/
    -> API docs :  http://localhost:8000/docs   (OpenAPI, generated automatically)
"""
import logging
import time
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from common import config  # noqa: F401  (loads .env)
from common import kpi
from api.models import (DailyPoint, DataQualityItem, DataRange, GapBucket, MerchantException,
                        MerchantPerformance, SettlementSummary)
from api.repository import SnowflakeRepository
from api.security import require_api_key

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("settlement-api")

MAX_RANGE_DAYS = 366
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(
    title="Merchant Settlement Intelligence API",
    version="1.0.0",
    description="Payment & settlement KPIs for Bank of New York payments operations.",
)

# ---------------------------------------------------------------- dependencies
_repo: SnowflakeRepository | None = None


def get_repo() -> SnowflakeRepository:
    """Tests replace this with a fake repository (app.dependency_overrides)."""
    global _repo
    if _repo is None:
        _repo = SnowflakeRepository()
    return _repo


Repo = Annotated[SnowflakeRepository, Depends(get_repo)]
# Strict format check -> anything else (e.g. "M1' OR '1'='1") is a 422 before it reaches the database.
MerchantId = Annotated[str | None, Query(pattern=r"^M\d{3,6}$", max_length=7, description="e.g. M1008")]


def parse_range(start_date: str, end_date: str) -> tuple[date, date]:
    """400 for dates that are not real dates or a range that makes no sense."""
    try:
        start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(400, "start_date and end_date must be valid dates (YYYY-MM-DD)")
    if end < start:
        raise HTTPException(400, "end_date must be on or after start_date")
    if (end - start).days > MAX_RANGE_DAYS:
        raise HTTPException(400, f"date range cannot exceed {MAX_RANGE_DAYS} days")
    return start, end


def check_merchant(repo, merchant_id: str | None):
    if merchant_id and not repo.merchant_exists(merchant_id):
        raise HTTPException(404, f"Unknown merchant: {merchant_id}")


def merchant_performance(repo, start: date, end: date) -> list[MerchantPerformance]:
    result = []
    for m in repo.merchant_totals(start, end):
        rate = kpi.settlement_rate(m["settled_amount"], m["success_amount"])
        sla = kpi.sla_rate(m["sla_met_count"], m["success_count"])
        result.append(MerchantPerformance(
            merchant_id=m["merchant_id"], merchant_name=m["merchant_name"], risk_level=m["risk_level"],
            transaction_count=m["success_count"], transaction_amount=round(m["success_amount"], 2),
            settled_amount=round(m["settled_amount"], 2), settlement_rate=rate, sla_rate=sla,
            settlement_gap=kpi.settlement_gap(m["success_amount"], m["settled_amount"]),
            is_exception=kpi.is_merchant_exception(rate, sla)))
    return sorted(result, key=lambda p: p.settlement_gap, reverse=True)


# ---------------------------------------------------------------- middleware
@app.middleware("http")
async def access_log(request: Request, call_next):
    """Log method, path, status and duration only - no query values, no bodies, no PII."""
    started = time.perf_counter()
    response = await call_next(request)
    log.info("%s %s -> %s (%.0f ms)", request.method, request.url.path, response.status_code,
             (time.perf_counter() - started) * 1000)
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.error("Unhandled error on %s: %s", request.url.path, type(exc).__name__)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ---------------------------------------------------------------- endpoints
@app.get("/health", tags=["ops"])
def health(repo: Repo):
    """Used by Docker / deployment health checks. No auth, no data."""
    try:
        repo.ping()
        return {"status": "ok", "database": "ok"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "degraded", "database": "unreachable"})


api = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)], tags=["settlement"])


@api.get("/settlement-summary", response_model=SettlementSummary)
def settlement_summary(repo: Repo, start_date: str, end_date: str, merchant_id: MerchantId = None):
    """KPI 1-5 for a date range, optionally for one merchant."""
    start, end = parse_range(start_date, end_date)
    check_merchant(repo, merchant_id)
    t = repo.totals(start, end, merchant_id)
    merchants = merchant_performance(repo, start, end)
    if merchant_id:
        merchants = [m for m in merchants if m.merchant_id == merchant_id]
    return SettlementSummary(
        start_date=start, end_date=end, merchant_id=merchant_id,
        transaction_count=t["success_count"],
        transaction_amount=round(t["success_amount"], 2),
        settled_amount=round(t["settled_amount"], 2),
        settlement_rate=kpi.settlement_rate(t["settled_amount"], t["success_amount"]),
        settlement_gap=kpi.settlement_gap(t["success_amount"], t["settled_amount"]),
        sla_rate=kpi.sla_rate(t["sla_met_count"], t["success_count"]),
        merchant_risk_count=sum(kpi.is_high_risk_merchant(m.settlement_rate, m.sla_rate) for m in merchants),
    )


@api.get("/merchant-exceptions", response_model=list[MerchantException])
def merchant_exceptions(repo: Repo, start_date: str | None = None, end_date: str | None = None):
    """Merchants with settlement_rate < 95% OR sla_rate < 90%. Default range = all data."""
    if start_date is None or end_date is None:
        lo, hi = repo.data_range()
        if lo is None:
            return []
        start_date, end_date = start_date or lo.isoformat(), end_date or hi.isoformat()
    start, end = parse_range(start_date, end_date)
    return [MerchantException(merchant_id=m.merchant_id, merchant_name=m.merchant_name,
                              settlement_rate=m.settlement_rate, sla_rate=m.sla_rate,
                              risk_level=m.risk_level, settlement_gap=m.settlement_gap)
            for m in merchant_performance(repo, start, end) if m.is_exception]


@api.get("/merchant-performance", response_model=list[MerchantPerformance])
def merchant_performance_endpoint(repo: Repo, start_date: str, end_date: str):
    """All merchants, largest settlement gap first (dashboard table + top-10 chart)."""
    start, end = parse_range(start_date, end_date)
    return merchant_performance(repo, start, end)


@api.get("/daily-trend", response_model=list[DailyPoint])
def daily_trend(repo: Repo, start_date: str, end_date: str, merchant_id: MerchantId = None):
    """Daily transaction amount vs daily settled amount (chart 1)."""
    start, end = parse_range(start_date, end_date)
    check_merchant(repo, merchant_id)
    return repo.daily(start, end, merchant_id)


@api.get("/gap-breakdown", response_model=list[GapBucket])
def gap_breakdown(repo: Repo, start_date: str, end_date: str, merchant_id: MerchantId = None):
    """WHY is there a gap? Split by partially settled / pending / failed / never settled."""
    start, end = parse_range(start_date, end_date)
    check_merchant(repo, merchant_id)
    return repo.gap_breakdown(start, end, merchant_id)


@api.get("/data-quality", response_model=list[DataQualityItem])
def data_quality(repo: Repo):
    """Counts of rejected / quarantined / warning records by reason."""
    return repo.data_quality()


@api.get("/data-range", response_model=DataRange)
def data_range(repo: Repo):
    lo, hi = repo.data_range()
    return DataRange(min_date=lo, max_date=hi)


app.include_router(api)

# Dashboard (HTML/JS) served from the same origin -> no CORS needed. Mounted last.
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
