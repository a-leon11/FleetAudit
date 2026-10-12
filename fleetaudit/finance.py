"""Contract math shared by the generator, the Python checks and the tests.

The SQL rules re-implement the same formulas; tests/test_sql_agrees.py checks
that both sides give the same answers.
"""
import calendar
import math
from datetime import date


def loan_payment(principal: float, rate_pct: float, n: int) -> float:
    r = rate_pct / 1200
    if r == 0:
        return principal / n
    return principal * r / (1 - (1 + r) ** -n)


def lease_payment(cap_cost: float, residual: float, rate_pct: float, n: int) -> float:
    """Standard lease payment: depreciation plus rent charge (money factor = rate / 2400)."""
    return (cap_cost - residual) / n + (cap_cost + residual) * rate_pct / 2400


def payment(product: str, amount: float, residual: float | None, rate_pct: float, n: int) -> float:
    if product == "LOAN":
        return loan_payment(amount, rate_pct, n)
    return lease_payment(amount, residual or 0.0, rate_pct, n)


def months_between(start: date, end: date) -> int:
    """Month boundaries crossed, same as DuckDB datediff('month', start, end)."""
    return (end.year - start.year) * 12 + (end.month - start.month)


def add_months(d: date, k: int) -> date:
    m = d.month - 1 + k
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def balance(product: str, amount: float, residual: float | None, rate_pct: float,
            n: int, pmt: float, k: int) -> float:
    """Outstanding balance after k scheduled payments, using the booked payment."""
    k = max(0, min(k, n))
    if product == "LOAN":
        r = rate_pct / 1200
        if r == 0:
            return amount - pmt * k
        g = (1 + r) ** k
        return amount * g - pmt * (g - 1) / r
    return amount - (amount - (residual or 0.0)) * k / n


def subvention(product: str, amount: float, residual: float | None,
               program_rate: float, market_rate: float, n: int) -> float:
    """What the manufacturer pays the lender so a program rate earns the market rate:
    principal minus the present value, at the market rate, of the program cash flows."""
    rm = market_rate / 1200
    pmt = payment(product, amount, residual, program_rate, n)
    annuity = (1 - (1 + rm) ** -n) / rm if rm else n
    pv = pmt * annuity
    if product == "LEASE":
        pv += (residual or 0.0) / (1 + rm) ** n
    return max(0.0, amount - pv)


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - spread) / denom, (centre + spread) / denom
