import pytest

from fleetaudit.evaluate import EXPECTED_RULE

BLIND_SPOTS = {"backdating_short"}        # documented: nothing catches it
REVIEW_ONLY = {"split_deal_slow"}         # caught, but only as a low-tier signal


def rows(audit, ids):
    return audit.contracts.set_index("contract_id").loc[ids]


@pytest.mark.parametrize("pattern", sorted(EXPECTED_RULE))
def test_each_pattern_hits_its_rule(audit, truth, pattern):
    r = rows(audit, truth["contracts"][pattern])
    caught = r.rules.str.contains(EXPECTED_RULE[pattern])
    if pattern in BLIND_SPOTS:
        assert not caught.any()
    else:
        assert caught.all(), r.loc[~caught, ["rules", "evidence"]]


@pytest.mark.parametrize("pattern", sorted(set(EXPECTED_RULE) - BLIND_SPOTS - REVIEW_ONLY))
def test_planted_patterns_reach_medium(audit, truth, pattern):
    assert rows(audit, truth["contracts"][pattern]).tier.isin(["medium", "high"]).all()


def test_slow_splits_stay_low(audit, truth):
    assert (rows(audit, truth["contracts"]["split_deal_slow"]).tier == "low").all()


@pytest.mark.parametrize("pattern", ["deal_at_authority", "high_advance_within_cap", "incentive_last_day",
                                     "late_entry_no_benefit", "markup_at_cap", "near_limit_plus_small_order",
                                     "payment_rounding",
                                     "residual_within_tolerance", "split_authorized", "split_far_apart",
                                     "tier_override_documented", "vin_after_termination"])
def test_lookalikes_never_reach_medium(audit, truth, pattern):
    assert not rows(audit, truth["lookalikes"][pattern]).tier.isin(["medium", "high"]).any()


def test_no_unplanted_contract_reaches_medium(audit, truth):
    planted = {c for ids in truth["contracts"].values() for c in ids}
    med = audit.contracts[audit.contracts.tier.isin(["medium", "high"])]
    assert set(med.contract_id) <= planted


def test_epd_dealers_flagged_small_dealer_not(audit, truth):
    flagged = set(audit.dealers.loc[audit.dealers.epd_flag, "dealer_id"])
    assert flagged == set(truth["dealers"]["epd_cluster"])
    assert not flagged & set(truth["lookalikes"]["small_dealer_one_epd"])


def test_aggressive_dealers_on_watchlist(audit, truth):
    wl = set(audit.dealers.loc[audit.dealers.watchlist, "dealer_id"])
    assert set(truth["dealers"]["aggressive_dealer"]) <= wl


def test_exposure_customers(audit, truth):
    flagged = set(audit.customers.customer_id)
    assert flagged == set(truth["customers"]["exposure_breach"])


def test_duplicate_vin_flags_the_later_contract_only(con, truth):
    flagged = {r[0] for r in con.execute("SELECT entity_id FROM r05_duplicate_vin").fetchall()}
    assert flagged == set(truth["contracts"]["duplicate_vin"])


def test_power_booking_breaks_all_three_advance_limits(con, truth):
    ids = truth["contracts"]["power_booking"]
    mags = dict(con.execute("SELECT entity_id, magnitude FROM r06_advance_over_policy").fetchall())
    assert all(mags[c] == 3 for c in ids)


def test_residual_breach_measured_against_mileage_adjusted_table(con, book, truth):
    mags = dict(con.execute("SELECT entity_id, magnitude FROM r02_residual_inflation").fetchall())
    by_id = {c.contract_id: c for c in book.contracts}
    for cid in truth["contracts"]["residual_inflation"]:
        c = by_id[cid]
        assert mags[cid] == pytest.approx(c.residual_pct - book.table_residual(c))
