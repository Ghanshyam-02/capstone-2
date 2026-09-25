"""KPI formulas from the business spec (section 4 of the brief).

Pure functions - no database - so they are easy to unit-test.
"""

SETTLEMENT_RATE_THRESHOLD = 95.0   # KPI 5 / merchant exceptions
SLA_RATE_THRESHOLD = 90.0


def settlement_rate(settled_amount: float, success_amount: float) -> float:
    """Settled amount / successful amount x 100."""
    # ⚠️ INJECTED DEFECT D (API calculation): Version 2 "refactored" this and dropped
    #    the 0..100 guard, so an impossible rate is passed straight to the dashboard.
    if success_amount <= 0:
        return 0.0
    return round(settled_amount / success_amount * 100, 2)


def settlement_gap(success_amount: float, settled_amount: float) -> float:
    return round(success_amount - settled_amount, 2)          # ⚠️ DEFECT D: can now go negative


def sla_rate(sla_met_count: int, success_count: int) -> float:
    """% of successful transactions fully settled within 30 minutes."""
    if success_count <= 0:
        return 0.0
    return round(max(0.0, min(sla_met_count / success_count * 100, 100.0)), 2)


def is_merchant_exception(rate: float, sla: float) -> bool:
    """Merchant exception API rule: rate < 95% OR SLA < 90%."""
    return rate < SETTLEMENT_RATE_THRESHOLD or sla < SLA_RATE_THRESHOLD


def is_high_risk_merchant(rate: float, sla: float) -> bool:
    """KPI 5 rule: rate < 95% AND SLA < 90%."""
    return rate < SETTLEMENT_RATE_THRESHOLD and sla < SLA_RATE_THRESHOLD
