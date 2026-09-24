"""Pydantic response models = the API contract. FastAPI also uses them for the OpenAPI docs.

Field(ge=0, le=100) guarantees a rate is always between 0 and 100.
"""
import datetime as dt
from typing import Annotated

from pydantic import BaseModel, Field

Percent = Annotated[float, Field(ge=0, le=100)]


class SettlementSummary(BaseModel):
    transaction_count: int              # successful transactions
    transaction_amount: float           # KPI 1
    settled_amount: float
    settlement_rate: Percent            # KPI 2
    settlement_gap: float               # KPI 3
    sla_rate: Percent                   # KPI 4
    merchant_risk_count: int            # KPI 5


class Merchant(BaseModel):
    merchant_id: str
    merchant_name: str | None
    settlement_rate: Percent
    sla_rate: Percent
    risk_level: str | None
    settlement_gap: float


class DailyPoint(BaseModel):
    date: dt.date
    transaction_amount: float
    settled_amount: float
