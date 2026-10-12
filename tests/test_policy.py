"""Thresholds live in the policy table, not in the SQL. Changing policy must change findings."""
from dataclasses import replace

from fleetaudit import db, score
from fleetaudit.config import POLICY


def _r(con, view):
    return {r[0] for r in con.execute(f"SELECT entity_id FROM {view}").fetchall()}


def test_tighter_markup_cap_flags_contracts_at_the_old_cap(data_dir, truth):
    con = db.connect(data_dir / "book", replace(POLICY, markup_cap_loan_bps=150, markup_cap_lease_bps=75))
    hits = _r(con, "r01_markup_over_cap")
    assert set(truth["lookalikes"]["markup_at_cap"]) <= hits
    con.close()


def test_wider_split_window_turns_slow_splits_into_r04(data_dir, truth):
    con = db.connect(data_dir / "book", replace(POLICY, split_window_days=30))
    assert set(truth["contracts"]["split_deal_slow"]) <= _r(con, "r04_split_deal")
    con.close()


def test_shorter_backdate_lag_closes_the_blind_spot(data_dir, truth):
    con = db.connect(data_dir / "book", replace(POLICY, backdate_lag_days=1))
    assert set(truth["contracts"]["backdating_short"]) <= _r(con, "r09_backdated")
    con.close()


def test_scoring_is_deterministic(con):
    a, b = score.run(con), score.run(con)
    assert a.contracts[["contract_id", "score", "rules"]].equals(b.contracts[["contract_id", "score", "rules"]])


def test_epd_uses_the_wilson_bound_not_the_raw_rate(data_dir, truth):
    """With the size floors removed, the tiny dealer's raw rate clears the bar but its
    Wilson lower bound does not. Pick a ratio between the two and check it stays clear."""
    small = truth["lookalikes"]["small_dealer_one_epd"][0]
    con = db.connect(data_dir / "book")
    rate, low, pf = con.execute("SELECT rate, wilson_low, portfolio_rate FROM v_dealer_epd WHERE dealer_id = ?",
                                [small]).fetchone()
    con.close()
    ratio = (low / pf + rate / pf) / 2
    con = db.connect(data_dir / "book", replace(POLICY, epd_min_seasoned=1, epd_min_count=1, epd_ratio=ratio))
    assert small not in _r(con, "r11_dealer_epd")
    con.close()
