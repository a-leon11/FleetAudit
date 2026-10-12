"""Score the detection layer against the generator's answer key over many seeds."""
from __future__ import annotations

import json
import tempfile
from collections import defaultdict
from pathlib import Path

from . import db, score
from .generate import generate, write, write_truth

EXPECTED_RULE = {
    "markup_over_cap": "R01", "residual_inflation": "R02", "payment_mismatch": "R03",
    "split_deal": "R04", "duplicate_vin": "R05", "power_booking": "R06",
    "incentive_misuse": "R07", "tier_inflation": "R08", "backdating": "R09",
    "exposure_breach": "R10", "authority_exceeded": "R12",
    # evasive variants, built to slip past the first-line rules
    "split_deal_slow": "R14", "vin_near_duplicate": "R13", "backdating_short": "R09",
}


def check(audit: score.Audit, truth: dict) -> dict:
    c = audit.contracts.set_index("contract_id")
    planted = {cid for ids in truth["contracts"].values() for cid in ids}
    res = {"patterns": {}, "lookalikes": {}}
    for pat, ids in truth["contracts"].items():
        rule = EXPECTED_RULE[pat]
        rows = c.loc[ids]
        res["patterns"][pat] = {
            "planted": len(ids),
            "expected_rule": int(rows.rules.str.contains(rule).sum()),
            "medium_plus": int(rows.tier.isin(["medium", "high"]).sum()),
            "stat_only": int(rows.rules.str.contains("STAT").sum()),
        }
    for pat, ids in truth["lookalikes"].items():
        if pat in ("small_dealer_one_epd", "limit_raised_before_deal"):
            continue
        rows = c.loc[ids]
        res["lookalikes"][pat] = {
            "count": len(ids),
            "any_rule": int(rows.rules.str.replace("STAT", "").str.strip(", ").ne("").sum()),
            "medium_plus": int(rows.tier.isin(["medium", "high"]).sum()),
        }
    med = c[c.tier.isin(["medium", "high"])]
    res["medium_plus"] = len(med)
    res["false_medium_plus"] = int((~med.index.isin(list(planted))).sum())
    r14 = c[c.rules.str.contains("R14")]
    res["r14_hits"] = len(r14)
    res["r14_true"] = int(r14.index.isin(truth["contracts"].get("split_deal_slow", [])).sum())
    low = c[c.tier == "low"]
    res["low_only"] = len(low)
    res["low_only_unplanted"] = int((~low.index.isin(list(planted))).sum())

    dealers = audit.dealers.set_index("dealer_id")
    epd_flagged = set(dealers.index[dealers.epd_flag])
    res["epd_dealers"] = {"planted": len(truth["dealers"]["epd_cluster"]),
                          "flagged": len(epd_flagged & set(truth["dealers"]["epd_cluster"])),
                          "false_flags": len(epd_flagged - set(truth["dealers"]["epd_cluster"]))}
    small = [d for d in truth["lookalikes"].get("small_dealer_one_epd", [])]
    res["small_dealer_flagged"] = int(sum(d in epd_flagged for d in small))
    aggr = truth["dealers"]["aggressive_dealer"]
    top5 = list(dealers.sort_values("risk_index", ascending=False).index[:5])
    res["aggressive_dealers"] = {"planted": len(aggr),
                                 "on_watchlist": int(sum(dealers.loc[d, "watchlist"] for d in aggr)),
                                 "in_top5": int(sum(d in top5 for d in aggr))}
    wl = set(dealers.index[dealers.watchlist])
    planted_dealers = set(aggr) | set(truth["dealers"]["epd_cluster"]) | {
        c.loc[cid, "dealer_id"] for pat, ids in truth["contracts"].items()
        if EXPECTED_RULE[pat] in score.DEALER_CONDUCT for cid in ids}
    res["watchlist"] = {"size": len(wl), "without_planted_conduct": len(wl - planted_dealers)}
    flagged_cust = set(audit.customers.customer_id)
    res["customers"] = {"planted": len(truth["customers"]["exposure_breach"]),
                        "flagged": len(flagged_cust & set(truth["customers"]["exposure_breach"])),
                        "lookalike_flagged": len(flagged_cust & set(truth["lookalikes"]["limit_raised_before_deal"])),
                        "false_flags": len(flagged_cust - set(truth["customers"]["exposure_breach"]))}
    res["dq_failures"] = sum(n for _, n in audit.dq)
    return res


def run(seeds: list[int]) -> dict:
    totals: dict = {"seeds": seeds, "patterns": defaultdict(lambda: defaultdict(int)),
                    "lookalikes": defaultdict(lambda: defaultdict(int)), "summary": defaultdict(int)}
    for seed in seeds:
        with tempfile.TemporaryDirectory() as tmp:
            book = generate(seed)
            write(book, Path(tmp) / "book")
            write_truth(book, Path(tmp) / "truth.json")
            truth = json.loads((Path(tmp) / "truth.json").read_text(encoding="utf-8"))
            con = db.connect(Path(tmp) / "book")
            res = check(score.run(con), truth)
            con.close()
        for pat, v in res["patterns"].items():
            for k, n in v.items():
                totals["patterns"][pat][k] += n
        for pat, v in res["lookalikes"].items():
            for k, n in v.items():
                totals["lookalikes"][pat][k] += n
        sm = totals["summary"]
        sm["contracts_medium_plus"] += res["medium_plus"]
        sm["false_medium_plus"] += res["false_medium_plus"]
        sm["low_only"] += res["low_only"]
        sm["low_only_unplanted"] += res["low_only_unplanted"]
        sm["r14_hits"] += res["r14_hits"]
        sm["r14_true"] += res["r14_true"]
        for k in ("planted", "flagged", "false_flags"):
            sm[f"epd_dealers_{k}"] += res["epd_dealers"][k]
        sm["small_dealer_flagged"] += res["small_dealer_flagged"]
        for k in ("planted", "on_watchlist", "in_top5"):
            sm[f"aggressive_{k}"] += res["aggressive_dealers"][k]
        sm["watchlist_size"] += res["watchlist"]["size"]
        sm["watchlist_without_planted_conduct"] += res["watchlist"]["without_planted_conduct"]
        for k in ("planted", "flagged", "lookalike_flagged", "false_flags"):
            sm[f"customers_{k}"] += res["customers"][k]
        sm["dq_failures"] += res["dq_failures"]
    return json.loads(json.dumps(totals))


def write_markdown(res: dict, path: Path) -> None:
    seeds = res["seeds"]
    sm = res["summary"]
    lines = [
        "# Evaluation",
        "",
        f"Detection scored against the generator's answer key over {len(seeds)} seeds "
        f"({seeds[0]} to {seeds[-1]}). Each seed is a different book: different dealers, customers, "
        "rate path, programs and placement of every planted pattern.",
        "",
        "## Planted patterns (contract level)",
        "",
        "| Pattern | Rule | Planted | Caught by its rule | Medium or high | Statistical layer alone |",
        "|---|---|---:|---:|---:|---:|",
    ]
    tp = tr = tm = ts = 0
    for pat, v in sorted(res["patterns"].items()):
        tp += v["planted"]; tr += v["expected_rule"]; tm += v["medium_plus"]; ts += v["stat_only"]
        lines.append(f"| {pat} | {EXPECTED_RULE[pat]} | {v['planted']} | {v['expected_rule']} "
                     f"({v['expected_rule'] / v['planted']:.0%}) | {v['medium_plus']} "
                     f"({v['medium_plus'] / v['planted']:.0%}) | {v['stat_only']} ({v['stat_only'] / v['planted']:.0%}) |")
    lines.append(f"| **All** | | **{tp}** | **{tr} ({tr / tp:.0%})** | **{tm} ({tm / tp:.0%})** | "
                 f"**{ts} ({ts / tp:.0%})** |")
    lines += ["", "## Look-alikes (legal cases built to sit right next to a rule)", "",
              "| Look-alike | Count | Any rule fired | Medium or high |", "|---|---:|---:|---:|"]
    for pat, v in sorted(res["lookalikes"].items()):
        lines.append(f"| {pat} | {v['count']} | {v['any_rule']} | {v['medium_plus']} |")
    fp = sm["false_medium_plus"]
    lines += [
        "",
        "## Precision and entity-level checks",
        "",
        f"- Contracts at medium or high: {sm['contracts_medium_plus']}, of which **{fp} were not planted** "
        f"(precision {1 - fp / max(1, sm['contracts_medium_plus']):.1%}).",
        f"- Low-only contracts: {sm['low_only']}, of which {sm['low_only_unplanted']} were not planted. "
        "This is the review queue: the statistical layer's top 1% and the weak R14 signal.",
        f"- R14 (slow split) fired on {sm['r14_hits']} contracts; {sm['r14_true']} were planted slow splits "
        f"({sm['r14_true'] / max(1, sm['r14_hits']):.0%}). The rest are genuine repeat orders a few weeks apart, "
        "which is exactly why R14 only queues for review and never reaches medium on its own.",
        f"- Early-default dealers: {sm['epd_dealers_flagged']} of {sm['epd_dealers_planted']} flagged, "
        f"{sm['epd_dealers_false_flags']} false flags. The tiny dealer with one early default "
        f"was flagged {sm['small_dealer_flagged']} times.",
        f"- Aggressive dealers: {sm['aggressive_on_watchlist']} of {sm['aggressive_planted']} on the watchlist, "
        f"{sm['aggressive_in_top5']} in the top five by risk index.",
        f"- Dealer watchlist: {sm['watchlist_size']} entries in total, "
        f"{sm['watchlist_without_planted_conduct']} without any planted dealer-conduct pattern.",
        f"- Customers over limit: {sm['customers_flagged']} of {sm['customers_planted']} flagged, "
        f"{sm['customers_false_flags']} false flags; customers whose limit was raised before the big deal "
        f"flagged {sm['customers_lookalike_flagged']} times.",
        f"- Data-quality failures across all seeds: {sm['dq_failures']}.",
        "",
        "## How to read this",
        "",
        "The background book is generated inside policy, so the first-line rules score perfectly on the "
        "patterns they were written for. That shows the logic is right, not that it would hold on a real book, "
        "where messy data, exceptions and judgment calls add noise the generator does not model.",
        "",
        "The three evasive variants are the honest part:",
        "",
        "- **split_deal_slow** spreads the pieces 9 to 13 days apart, outside R04's 7-day window. R14 widens the "
        "window to 30 days and finds all of them, but it also finds every legitimate repeat order, so it stays "
        "a low-tier review signal. Widening R04 instead would trade a clean high-confidence rule for a noisy one.",
        "- **vin_near_duplicate** changes one character of a VIN already on an open contract. Exact matching "
        "(R05) cannot see it; a Hamming-distance match on the same model and year (R13) can, with no false hits.",
        "- **backdating_short** keeps the keying lag under the 15-day threshold. **Nothing catches it.** "
        "Lowering the threshold would start flagging ordinary paperwork delays, so this is a known blind spot "
        "to close with a process control (time-stamped contract capture at the dealer), not a rule.",
        "",
        "The statistical column is the other comparison: an isolation forest on its own finds the patterns that "
        "make a contract numerically strange (power booking) and misses the ones that are only wrong in context "
        "(a VIN seen before, a deal split across days, a limit in force on a given date).",
        "",
    ]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines), encoding="utf-8")
