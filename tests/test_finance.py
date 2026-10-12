from datetime import date

import pytest

from fleetaudit import finance as fin


def test_loan_payment_textbook_value():
    # 100,000 at 12% a year over 12 months
    assert fin.loan_payment(100_000, 12, 12) == pytest.approx(8_884.88, abs=0.01)


def test_zero_rate_loan_is_straight_line():
    assert fin.loan_payment(120_000, 0, 12) == 10_000


def test_lease_payment_is_depreciation_plus_rent():
    # (500k - 250k)/36 + (500k + 250k) * 9 / 2400
    assert fin.lease_payment(500_000, 250_000, 9, 36) == pytest.approx(6_944.44 + 2_812.50, abs=0.01)


def test_loan_balance_runs_to_zero():
    p = fin.loan_payment(800_000, 14.5, 48)
    assert fin.balance("LOAN", 800_000, None, 14.5, 48, p, 0) == pytest.approx(800_000)
    assert fin.balance("LOAN", 800_000, None, 14.5, 48, p, 48) == pytest.approx(0, abs=1e-6)
    assert fin.balance("LOAN", 800_000, None, 14.5, 48, p, 99) == pytest.approx(0, abs=1e-6)  # clamped


def test_lease_balance_runs_to_residual():
    p = fin.lease_payment(700_000, 300_000, 10, 36)
    assert fin.balance("LEASE", 700_000, 300_000, 10, 36, p, 36) == pytest.approx(300_000)


def test_understated_payment_leaves_more_balance():
    p = fin.loan_payment(500_000, 13, 36)
    assert fin.balance("LOAN", 500_000, None, 13, 36, p * 0.9, 36) > 0


def test_month_arithmetic():
    assert fin.months_between(date(2024, 1, 31), date(2024, 2, 1)) == 1
    assert fin.add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert fin.add_months(date(2023, 11, 15), 3) == date(2024, 2, 15)


def test_subvention_positive_only_when_program_is_cheaper():
    assert fin.subvention("LOAN", 900_000, None, 3.9, 13.5, 36) > 0
    assert fin.subvention("LOAN", 900_000, None, 13.5, 13.5, 36) == pytest.approx(0, abs=0.01)
    assert fin.subvention("LEASE", 900_000, 400_000, 5.9, 12.0, 36) > 0


def test_wilson_interval():
    lo, hi = fin.wilson_interval(0, 10)
    assert lo == pytest.approx(0, abs=1e-12) and 0.25 < hi < 0.35
    lo, hi = fin.wilson_interval(1, 4)          # 25% on four contracts proves little
    assert lo < 0.05
