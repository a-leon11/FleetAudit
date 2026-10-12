"""Command line: generate | audit | contract | dealer | evaluate."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import db, evaluate, report, score
from .generate import generate, write, write_truth

DATA = Path("data/book")
TRUTH = Path("data/ground_truth.json")
REPORTS = Path("reports")


def _seeds(text: str) -> list[int]:
    if "-" in text:
        a, b = text.split("-")
        return list(range(int(a), int(b) + 1))
    return [int(x) for x in text.split(",")]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="fleetaudit", description="Dealer fleet contract portfolio audit.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="build the synthetic book and its answer key")
    g.add_argument("--seed", type=int, default=7)
    g.add_argument("--out", type=Path, default=DATA)
    g.add_argument("--truth", type=Path, default=TRUTH)
    a = sub.add_parser("audit", help="run data quality, rules and scoring; write reports")
    a.add_argument("--data", type=Path, default=DATA)
    a.add_argument("--out", type=Path, default=REPORTS)
    c = sub.add_parser("contract", help="explain one contract")
    c.add_argument("contract_id")
    c.add_argument("--data", type=Path, default=DATA)
    d = sub.add_parser("dealer", help="explain one dealer")
    d.add_argument("dealer_id")
    d.add_argument("--data", type=Path, default=DATA)
    e = sub.add_parser("evaluate", help="score detection against the answer key over many seeds")
    e.add_argument("--seeds", type=_seeds, default=list(range(1, 21)))
    e.add_argument("--out", type=Path, default=REPORTS / "evaluation.md")
    args = ap.parse_args(argv)

    if args.cmd == "generate":
        book = generate(args.seed)
        write(book, args.out)
        write_truth(book, args.truth)
        print(f"{len(book.contracts):,} contracts written to {args.out}; answer key in {args.truth}")
        return 0

    if args.cmd == "evaluate":
        res = evaluate.run(args.seeds)
        evaluate.write_markdown(res, args.out)
        print(f"Evaluation over {len(args.seeds)} seeds written to {args.out}")
        return 0

    con = db.connect(args.data)
    audit = score.run(con)
    bad = [(n, f) for n, f in audit.dq if f]
    if bad:
        print("Data-quality gate failed; findings would not be trustworthy:")
        for n, f in bad:
            print(f"  {n}: {f}")
        return 2

    if args.cmd == "audit":
        report.write_all(audit, args.out)
        t = audit.contracts.tier.value_counts()
        print(f"DQ passed. {t.get('high', 0)} high, {t.get('medium', 0)} medium, {t.get('low', 0)} low. "
              f"{int(audit.dealers.watchlist.sum())} dealers on watchlist. Reports in {args.out}/")
        return 0

    if args.cmd == "contract":
        row = audit.contracts[audit.contracts.contract_id == args.contract_id]
        if row.empty:
            print(f"No contract {args.contract_id}")
            return 1
        r = row.iloc[0]
        f = con.execute("SELECT * FROM v_facts WHERE contract_id = ?", [args.contract_id]).df().iloc[0]
        print(f"{r.contract_id}  deal {r.deal_id}  dealer {r.dealer_id}  customer {r.customer_id}  "
              f"approver {r.approver_id}")
        print(f"  {f['product']} {f.model_code} {f.model_year}  VIN {f.vin}  term {f.term_months}  "
              f"dated {f.contract_date:%Y-%m-%d}  entered {f.entered_at:%Y-%m-%d}  funded {f.funded_date:%Y-%m-%d}")
        print(f"  price {f.cash_price:,.0f} (MSRP {f.msrp:,.0f})  down {f.down_payment:,.0f}  add-ons {f.addons:,.0f}"
              f"  financed {f.amount_financed:,.0f}")
        print(f"  score {f.credit_score} tier {f.credit_tier}  buy {f.buy_rate:.2f}%  contract {f.contract_rate:.2f}%"
              f"  program {f.program_id or '-'}  payment {f.monthly_payment:,.2f} (recomputed {f.expected_payment:,.2f})")
        print(f"  score {r.score} -> {r.tier}")
        for ev in filter(None, r.evidence.split(" | ")):
            print(f"    - {ev}")
        return 0

    if args.cmd == "dealer":
        row = audit.dealers[audit.dealers.dealer_id == args.dealer_id]
        if row.empty:
            print(f"No dealer {args.dealer_id}")
            return 1
        r = row.iloc[0]
        print(f"{r.dealer_id} {r['name']} ({r.region})  rank {row.index[0] + 1} of {len(audit.dealers)}")
        print(f"  {int(r.contracts)} contracts, {r.amount:,.0f} MXN financed, avg markup {r.avg_markup_bps:.0f} bps")
        print(f"  conduct findings on {int(r.conduct_contracts)} contracts ({r.conduct_rules or 'none'}), "
              f"{r.conduct_share:.1%} of volume")
        if pd_notna(r.seasoned):
            print(f"  early defaults {int(r.epd)}/{int(r.seasoned)} = {r.epd_rate:.1%} "
                  f"(95% low {r.wilson_low:.1%}, portfolio {r.portfolio_rate:.1%})"
                  f"{'  FLAGGED' if r.epd_flag else ''}")
        print(f"  risk index {r.risk_index:.1f}  {'WATCHLIST' if r.watchlist else ''}")
        return 0
    return 1


def pd_notna(v) -> bool:
    return v == v and v is not None


if __name__ == "__main__":
    sys.exit(main())
