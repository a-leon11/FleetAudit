"""Scoring layer: turn SQL rule hits into a ranked work queue.

Three views come out of one audit:
  * contracts  - points per contract, a tier (high / medium / low) and the evidence
  * dealers    - conduct findings and early-default quality per dealer
  * approvers  - internal-control findings per credit approver
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from .config import SCORING, Scoring

RULE_NAMES = {
    "R01": "Markup over cap",
    "R02": "Residual above table",
    "R03": "Payment does not reconcile",
    "R04": "Split deal under authority",
    "R05": "VIN financed twice",
    "R06": "Advance over policy",
    "R07": "Incentive outside program",
    "R08": "Tier better than score",
    "R09": "Backdated contract",
    "R10": "Customer over exposure limit",
    "R11": "Dealer early-default cluster",
    "R12": "Deal above approver authority",
    "R13": "Near-duplicate VIN",
    "R14": "Slow split across weeks",
    "STAT": "Statistical outlier",
}
# Who owns the failure: the dealer's conduct, or the lender's own controls.
DEALER_CONDUCT = {"R01", "R02", "R04", "R05", "R06", "R07", "R09", "R13", "R14"}
INTERNAL_CONTROL = {"R03", "R08", "R10", "R12"}


@dataclass
class Audit:
    contracts: pd.DataFrame      # every contract with score, tier, rules, evidence
    hits: pd.DataFrame           # raw rule hits with points
    dealers: pd.DataFrame        # dealer scorecard
    approvers: pd.DataFrame      # approver scorecard
    customers: pd.DataFrame      # customers with exposure breaches
    features: pd.DataFrame       # statistical layer inputs and outlier score
    dq: list[tuple[str, int]]
    portfolio: dict


def _points(rule: str, magnitude: float, s: Scoring) -> int:
    if rule == "R11":
        return s.dealer_epd_points
    if rule == "R03" and magnitude < 0:
        return s.understated_payment_points
    if rule == "R06":
        return s.points["R06"] + s.extra_advance_breach_points * (int(magnitude) - 1)
    return s.points[rule]


def outliers(features: pd.DataFrame, s: Scoring, seed: int = 0) -> pd.DataFrame:
    """Isolation forest over robust-scaled contract features. It never decides a
    finding on its own; it adds a small number of points to the most unusual 1%."""
    f = features.copy()
    x = f.drop(columns=["contract_id"]).astype(float).fillna(0.0)
    med = x.median()
    iqr = (x.quantile(0.75) - x.quantile(0.25)).replace(0, 1.0)
    z = ((x - med) / iqr).clip(-50, 50)
    forest = IsolationForest(n_estimators=300, random_state=seed).fit(z)
    f["outlier_score"] = -forest.score_samples(z)
    cut = f["outlier_score"].quantile(1 - s.outlier_share)
    f["outlier"] = f["outlier_score"] >= cut
    return f


def tier(score: int, s: Scoring) -> str:
    if score >= s.high:
        return "high"
    if score >= s.medium:
        return "medium"
    return "low" if score > 0 else "none"


def run(con, scoring: Scoring = SCORING, seed: int = 0) -> Audit:
    s = scoring
    dq = con.execute("SELECT check_name, failures FROM v_dq ORDER BY check_name").fetchall()
    hits = con.execute("SELECT * FROM v_rule_hits ORDER BY rule_id, entity_id").df()
    hits["points"] = [_points(r, m, s) for r, m in zip(hits.rule_id, hits.magnitude)]

    base = con.execute("""
        SELECT contract_id, deal_id, dealer_id, customer_id, approver_id, product, model_code,
               contract_date, amount_financed, subvention_mxn, status
        FROM contracts ORDER BY contract_id""").df()
    feats = outliers(con.execute("SELECT * FROM v_features ORDER BY contract_id").df(), s, seed)

    ch = hits[hits.entity_type == "contract"]
    stat = feats.loc[feats.outlier, ["contract_id", "outlier_score"]]
    stat_hits = pd.DataFrame({"entity_type": "contract", "entity_id": stat.contract_id, "rule_id": "STAT",
                              "magnitude": stat.outlier_score,
                              "evidence": [f"outlier score {v:.3f} (top {s.outlier_share:.0%})"
                                           for v in stat.outlier_score],
                              "points": s.outlier_points})
    allh = pd.concat([ch, stat_hits], ignore_index=True)
    agg = allh.groupby("entity_id").agg(
        score=("points", "sum"),
        rules=("rule_id", lambda r: ", ".join(sorted(set(r)))),
        evidence=("evidence", lambda e: " | ".join(e)),
    )
    out = base.merge(agg, left_on="contract_id", right_index=True, how="left")
    out["score"] = out["score"].fillna(0).astype(int)
    out["rules"] = out["rules"].fillna("")
    out["evidence"] = out["evidence"].fillna("")
    out["tier"] = [tier(v, s) for v in out.score]
    out = out.merge(feats[["contract_id", "outlier_score"]], on="contract_id")

    dealer_flags = set(hits.loc[hits.rule_id == "R11", "entity_id"])
    dealers = dealer_scorecard(con, out, hits, dealer_flags, s)
    approvers = approver_scorecard(out)
    customers = (con.execute("""
        SELECT customer_id, count(*) AS breach_fundings, max(limit_use) AS worst_limit_use,
               max(exposure) AS peak_exposure, any_value(limit_mxn) AS limit_mxn
        FROM v_exposure WHERE exposure > limit_mxn GROUP BY customer_id ORDER BY customer_id""").df())
    portfolio = con.execute("SELECT * FROM v_portfolio").df().iloc[0].to_dict()
    return Audit(out, hits, dealers, approvers, customers, feats, dq, portfolio)


def dealer_scorecard(con, scored: pd.DataFrame, hits: pd.DataFrame, epd_flags: set, s: Scoring) -> pd.DataFrame:
    names = con.execute("SELECT dealer_id, name, region FROM dealers").df()
    epd = con.execute("SELECT dealer_id, n AS seasoned, k AS epd, rate AS epd_rate, wilson_low, "
                      "portfolio_rate FROM v_dealer_epd").df()
    markup = con.execute("SELECT dealer_id, avg(markup_bps) AS avg_markup_bps FROM v_facts "
                         "WHERE program_id IS NULL GROUP BY dealer_id").df()
    ch = hits[(hits.entity_type == "contract") & hits.rule_id.isin(DEALER_CONDUCT)]
    ch = ch.merge(scored[["contract_id", "dealer_id", "amount_financed", "tier"]], left_on="entity_id",
                  right_on="contract_id")
    ch = ch[ch.tier.isin(["medium", "high"])]     # weak signals queue for review, they do not rank dealers
    conduct = ch.groupby("dealer_id").agg(
        conduct_contracts=("contract_id", "nunique"),
        conduct_rules=("rule_id", lambda r: ", ".join(sorted(set(r)))),
        distinct_rules=("rule_id", "nunique"),
    )
    flagged_amt = (ch.drop_duplicates("contract_id").groupby("dealer_id")["amount_financed"].sum()
                   .rename("conduct_amount"))
    vol = scored.groupby("dealer_id").agg(contracts=("contract_id", "count"),
                                          amount=("amount_financed", "sum"))
    d = (names.merge(vol, left_on="dealer_id", right_index=True, how="inner")
         .merge(conduct, left_on="dealer_id", right_index=True, how="left")
         .merge(flagged_amt, left_on="dealer_id", right_index=True, how="left")
         .merge(epd, on="dealer_id", how="left").merge(markup, on="dealer_id", how="left"))
    d[["conduct_contracts", "distinct_rules", "conduct_amount"]] = \
        d[["conduct_contracts", "distinct_rules", "conduct_amount"]].fillna(0)
    d["conduct_rules"] = d["conduct_rules"].fillna("")
    d["conduct_share"] = d.conduct_amount / d.amount
    d["epd_flag"] = d.dealer_id.isin(epd_flags)
    # risk index: share of the dealer's volume with conduct findings, breadth of
    # different findings, and an early-default cluster
    d["risk_index"] = (100 * d.conduct_share + 5 * d.distinct_rules
                       + s.dealer_epd_points * d.epd_flag).round(1)
    d["watchlist"] = (d.risk_index >= 20) | d.epd_flag
    return d.sort_values(["risk_index", "dealer_id"], ascending=[False, True]).reset_index(drop=True)


def approver_scorecard(scored: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for appr, g in scored.groupby("approver_id"):
        row = {"approver_id": appr, "contracts": len(g), "deals": g.deal_id.nunique(),
               "amount": g.amount_financed.sum()}
        for r in ("R04", "R08", "R10", "R12"):
            row[r] = int(g.rules.str.contains(r).sum())
        rows.append(row)
    a = pd.DataFrame(rows)
    a["control_findings"] = a[["R04", "R08", "R10", "R12"]].sum(axis=1)
    return a.sort_values(["control_findings", "approver_id"], ascending=[False, True]).reset_index(drop=True)
