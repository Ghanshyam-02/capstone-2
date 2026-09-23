"""Pydantic response models = the API contract (they also generate the OpenAPI docs).

ge/le constraints guarantee e.g. settlement_rate is always between 0 and 100 -
if a bug ever produced 105, the API would fail loudly instead of lying.
"""
import datetime as dt
from typing import Annotated

from pydantic import BaseModel, Field

Percent = Annotated[float, Field(ge=0, le=100)]


class SettlementSummary(BaseModel):
    start_date: dt.date
    end_date: dt.date
    merchant_id: str | None = None
    transaction_count: int = Field(ge=0, description="Successful transactions")
    transaction_amount: float = Field(ge=0, description="KPI 1 - successful payment value (INR)")
    settled_amount: float = Field(ge=0)
    settlement_rate: float = Field(ge=0, le=100, description="KPI 2 - settled / successful x 100")
    settlement_gap: float = Field(ge=0, description="KPI 3 - successful - settled (INR)")
    sla_rate: float = Field(ge=0, le=100, description="KPI 4 - % settled within 30 minutes")
    merchant_risk_count: int = Field(ge=0, description="KPI 5 - merchants with rate < 95% AND SLA < 90%")


class MerchantPerformance(BaseModel):
    merchant_id: str
    merchant_name: str | None
    risk_level: str | None
    transaction_count: int
    transaction_amount: float
    settled_amount: float
    settlement_rate: Percent
    sla_rate: Percent
    settlement_gap: float
    is_exception: bool


class MerchantException(BaseModel):
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


class GapBucket(BaseModel):
    category: str
    transaction_count: int
    amount: float


class DataQualityItem(BaseModel):
    source: str
    severity: str
    reason: str
    record_count: int


class DataRange(BaseModel):
    min_date: dt.date | None
    max_date: dt.date | None
