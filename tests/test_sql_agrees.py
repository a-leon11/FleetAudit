"""The SQL rules re-implement the contract math. Check both sides agree."""
import pytest

from fleetaudit import finance as fin


def test_expected_payment_matches_python(con, book):
    sql = dict(con.execute("SELECT contract_id, expected_payment FROM v_facts").fetchall())
    for c in book.contracts:
        py = fin.payment(c.product, c.amount_financed, c.residual_value, c.contract_rate, c.term_months)
        assert sql[c.contract_id] == pytest.approx(py, rel=1e-9)


def test_exposure_matches_python(con, book, truth):
    customers = truth["customers"]["exposure_breach"] + truth["lookalikes"]["limit_raised_before_deal"]
    for cid in customers:
        sql = dict(con.execute("SELECT event_date, exposure FROM v_exposure WHERE customer_id = ?", [cid]).fetchall())
        for d, total, _ in book.exposure_events(cid):
            assert sql[d] == pytest.approx(total, rel=1e-9)


def test_wilson_matches_python(con):
    for n, k, lo in con.execute("SELECT n, k, wilson_low FROM v_dealer_epd").fetchall():
        assert lo == pytest.approx(fin.wilson_interval(int(k), int(n))[0], abs=1e-12)


def test_score_tier_uses_policy_boundaries(con):
    rows = con.execute("SELECT credit_score, score_tier FROM v_facts").fetchall()
    for s, t in rows:
        expected = "A" if s >= 720 else "B" if s >= 680 else "C" if s >= 640 else "D"
        assert t == expected
