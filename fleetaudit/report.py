"""Outputs: CSV work queues, two charts and the one-page findings report."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from .score import DEALER_CONDUCT, RULE_NAMES, Audit  # noqa: E402

BLUE, GRAY = "#2a78d6", "#c3c2b7"
SURFACE, INK, INK2 = "#fcfcfb", "#0b0b0b", "#52514e"


def mxn(v: float) -> str:
    if abs(v) >= 1e6:
        return f"MXN {v / 1e6:,.1f}M"
    return f"MXN {v:,.0f}"


def rule_summary(a: Audit) -> pd.DataFrame:
    h = a.hits[a.hits.entity_type == "contract"].merge(
        a.contracts[["contract_id", "amount_financed", "subvention_mxn", "tier"]],
        left_on="entity_id", right_on="contract_id")
    h = h[h.tier.isin(["medium", "high"])]          # review-queue signals are reported separately
    g = h.groupby("rule_id").agg(contracts=("contract_id", "nunique"),
                                 amount=("amount_financed", "sum"),
                                 subvention=("subvention_mxn", "sum")).reset_index()
    g["rule"] = g.rule_id.map(RULE_NAMES)
    g["owner"] = ["Dealer conduct" if r in DEALER_CONDUCT else "Internal control" for r in g.rule_id]
    return g.sort_values("amount", ascending=False).reset_index(drop=True)


def write_csvs(a: Audit, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    q = a.contracts[a.contracts.tier != "none"].sort_values(["score", "amount_financed"], ascending=False)
    q[["contract_id", "deal_id", "dealer_id", "customer_id", "approver_id", "contract_date", "product",
       "model_code", "amount_financed", "score", "tier", "rules", "evidence"]].to_csv(
        out / "findings.csv", index=False, float_format="%.2f")
    a.dealers.to_csv(out / "dealer_scorecard.csv", index=False, float_format="%.4f")
    a.approvers.to_csv(out / "approver_scorecard.csv", index=False, float_format="%.2f")


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRAY)
    ax.tick_params(colors=INK2, length=0)
    ax.xaxis.grid(True, color="#e8e7e3", linewidth=0.8)
    ax.set_axisbelow(True)


def chart_rules(a: Audit, path: Path) -> None:
    g = rule_summary(a).sort_values("amount")
    fig, ax = plt.subplots(figsize=(8, 4.2), facecolor=SURFACE)
    _style(ax)
    labels = [f"{r}  {RULE_NAMES[r]}" for r in g.rule_id]
    colors = [BLUE if r in DEALER_CONDUCT else INK2 for r in g.rule_id]
    ax.barh(labels, g.amount / 1e6, color=colors, height=0.62)
    for y, (v, n) in enumerate(zip(g.amount / 1e6, g.contracts)):
        ax.text(v + g.amount.max() / 1e6 * 0.01, y, f"{v:,.1f}M  ({n})", va="center", fontsize=8.5, color=INK)
    ax.set_xlabel("Amount financed on flagged contracts, MXN millions (contracts in brackets)",
                  color=INK2, fontsize=9)
    ax.set_xlim(0, g.amount.max() / 1e6 * 1.22)
    ax.tick_params(axis="y", labelsize=9, labelcolor=INK)
    ax.set_title("Where the flagged money sits", loc="left", color=INK, fontsize=12, fontweight="bold", pad=22)
    ax.text(0, 1.02, "Blue: dealer conduct    Gray: the lender's own controls", transform=ax.transAxes,
            fontsize=8.5, color=INK2)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def chart_dealers(a: Audit, path: Path, top: int = 12) -> None:
    d = a.dealers.head(top).iloc[::-1]
    fig, ax = plt.subplots(figsize=(8, 4.4), facecolor=SURFACE)
    _style(ax)
    colors = [BLUE if w else GRAY for w in d.watchlist]
    ax.barh(d.dealer_id, d.risk_index, color=colors, height=0.62)
    for y, (v, rules, epd) in enumerate(zip(d.risk_index, d.conduct_rules, d.epd_flag)):
        tag = ", ".join(x for x in [rules, "early defaults" if epd else ""] if x)
        ax.text(v + 0.6, y, f"{v:.0f}  {tag}", va="center", fontsize=8.5, color=INK)
    ax.set_xlim(0, d.risk_index.max() * 1.55)
    ax.set_xlabel("Dealer risk index (share of volume with conduct findings, breadth, early defaults)",
                  color=INK2, fontsize=9)
    ax.tick_params(axis="y", labelsize=9, labelcolor=INK)
    ax.set_title("Dealer watchlist", loc="left", color=INK, fontsize=12, fontweight="bold", pad=22)
    ax.text(0, 1.02, f"Top {top} of {len(a.dealers)} dealers. Blue: on the watchlist",
            transform=ax.transAxes, fontsize=8.5, color=INK2)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def write_markdown(a: Audit, path: Path) -> None:
    p = a.portfolio
    c = a.contracts
    flagged = c[c.tier.isin(["medium", "high"])]
    rs = rule_summary(a)
    wl = a.dealers[a.dealers.watchlist]
    dq_bad = [n for n, f in a.dq if f]
    sub = c.loc[c.rules.str.contains("R07|R09") & (c.subvention_mxn > 0), "subvention_mxn"].sum()
    L = [
        "# Findings: fleet contract portfolio audit",
        "",
        f"*Simulated book as of {p['as_of']:%d %b %Y}. All data invented.*  ",
        f"*{p['contracts']:,} contracts in {p['deals']:,} deals, {p['dealers']} dealers, {p['customers']} fleet "
        f"customers, {mxn(p['originated_mxn'])} originated {p['first_contract']:%b %Y} to "
        f"{p['last_contract']:%b %Y}, {mxn(p['open_balance_mxn'])} still open.*",
        "",
        "## Headline",
        "",
        f"- **{len(flagged)} contracts need review** ({(c.tier == 'high').sum()} high, "
        f"{(c.tier == 'medium').sum()} medium), carrying **{mxn(flagged.amount_financed.sum())}** "
        f"of financing ({flagged.amount_financed.sum() / p['originated_mxn']:.1%} of originations).",
        f"- **{len(wl)} dealers on the watchlist**, {int(wl.epd_flag.sum())} of them for early defaults "
        "that are too frequent to be chance.",
        f"- **{len(a.customers)} customers were funded past their exposure limit**; "
        f"{mxn(sub)} of manufacturer subvention sits on contracts with program problems and may be clawed back.",
        f"- A further **{(c.tier == 'low').sum()} contracts sit in the review queue**: weak signals (slow splits "
        "that are often genuine repeat orders) and the statistical layer's most unusual 1%.",
        f"- Data-quality gate: {'all 13 checks passed' if not dq_bad else 'FAILED: ' + ', '.join(dq_bad)}.",
        "",
        "## By rule",
        "",
        "| Rule | Finding | Owner | Contracts (medium or high) | Financed |",
        "|---|---|---|---:|---:|",
    ]
    for r in rs.itertuples():
        L.append(f"| {r.rule_id} | {r.rule} | {r.owner} | {r.contracts} | {mxn(r.amount)} |")
    L += ["", "![Where the flagged money sits](rule_exposure.png)", "",
          "## Strongest example of each finding", "",
          "| Rule | Contract | Dealer | Score | Evidence |", "|---|---|---|---:|---|"]
    ranked = flagged.sort_values(["score", "amount_financed", "contract_id"], ascending=[False, False, True])
    hits = a.hits[a.hits.entity_type == "contract"].set_index("entity_id")
    seen = set()
    for rule in rs.rule_id:
        for r in ranked[ranked.rules.str.contains(rule)].itertuples():
            if r.deal_id in seen:
                continue
            seen.add(r.deal_id)
            ev = hits.loc[[r.contract_id]]
            ev = ev.loc[ev.rule_id == rule, "evidence"].iloc[0]
            L.append(f"| {rule} | {r.contract_id} | {r.dealer_id} | {r.score} | {ev} |")
            break
    L += ["", "## Dealer watchlist", "", "| Dealer | Risk index | Conduct findings | Early defaults |",
          "|---|---:|---|---|"]
    for r in wl.head(8).itertuples():
        epd = f"{int(r.epd)}/{int(r.seasoned)} (flagged)" if r.epd_flag else (
            f"{int(r.epd)}/{int(r.seasoned)}" if pd.notna(r.seasoned) else "n/a")
        L.append(f"| {r.dealer_id} {r.name} | {r.risk_index:.0f} | "
                 f"{int(r.conduct_contracts)} contract{'s' if r.conduct_contracts != 1 else ''} "
                 f"({r.conduct_rules or 'none'}) | {epd} |")
    ap = a.approvers[a.approvers.control_findings > 0].head(3)
    L += ["", "![Dealer watchlist](dealer_watchlist.png)", "", "## What I would do on Monday", "",
          f"1. Put the watchlist dealers on enhanced funding review and pull deal jackets for their "
          f"{int(wl.conduct_contracts.sum())} flagged contracts, starting with VIN duplicates and split deals.",
          "2. Re-price or recover: markup and residual breaches get dealer chargebacks; program misuse and "
          "backdating get reported to the manufacturer before the subvention claim is paid.",
          "3. Fix the controls that let it through: " + ", ".join(
              f"{r.approver_id} ({int(r.control_findings)} findings)" for r in ap.itertuples())
          + " need a second signature, and limit checks must run at funding, not at approval.",
          "", "Full queue: `findings.csv`. Dealer and approver detail: `dealer_scorecard.csv`, "
          "`approver_scorecard.csv`. Detection quality on 20 books: `evaluation.md`.", ""]
    Path(path).write_text("\n".join(L), encoding="utf-8")


def write_all(a: Audit, out: Path) -> None:
    out = Path(out)
    write_csvs(a, out)
    chart_rules(a, out / "rule_exposure.png")
    chart_dealers(a, out / "dealer_watchlist.png")
    write_markdown(a, out / "findings.md")
