"""UNIT TESTS - the KPI formulas in common/kpi.py (no database)."""
from common import kpi


def test_settlement_rate_and_gap_match_the_brief_example():
    # brief: 482,500,000 successful, 458,700,000 settled -> 95.07 %, gap 23,800,000
    assert kpi.settlement_rate(458_700_000, 482_500_000) == 95.07
    assert kpi.settlement_gap(482_500_000, 458_700_000) == 23_800_000


def test_settlement_rate_is_never_below_0_or_above_100():
    assert kpi.settlement_rate(0, 0) == 0.0
    assert kpi.settlement_rate(150, 100) == 100.0


def test_sla_rate():
    assert kpi.sla_rate(9, 10) == 90.0
    assert kpi.sla_rate(5, 0) == 0.0


def test_merchant_exception_logic():
    # exception = rate < 95 OR sla < 90 ; high risk (KPI 5) = rate < 95 AND sla < 90
    assert kpi.is_merchant_exception(94.9, 99) and not kpi.is_high_risk_merchant(94.9, 99)
    assert kpi.is_merchant_exception(99, 89.9) and not kpi.is_high_risk_merchant(99, 89.9)
    assert kpi.is_high_risk_merchant(88.4, 72.5)
    assert not kpi.is_merchant_exception(95, 90)
