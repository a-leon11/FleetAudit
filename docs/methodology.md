# Methodology

## Why this shape

A portfolio review at a captive lender is three questions asked in order:

1. **Can I trust the data?** If the amount financed does not equal price minus down payment plus
   add-ons, or a buy rate does not match the rate sheet, every rule downstream is measuring noise.
   The data-quality gate runs first and blocks the report if anything fails.
2. **What breaks policy?** Rules, written in SQL, each answering one question with evidence a
   reviewer can check by hand.
3. **What do I look at first?** Points, tiers and scorecards turn a list of hits into a work queue,
   and separate what a dealer did from what our own controls let through.

## Rule notes

**R01 Markup.** Dealer reserve is the spread between the buy rate (what the lender charges the
dealer) and the contract rate (what the customer pays). Caps differ by product, and subvented
programs allow none, because the manufacturer is already paying to buy the rate down.

**R02 Residual.** A higher residual lowers the lease payment and wins the deal, but leaves the
lender holding a vehicle worth less than booked at maturity. The table is reduced for high-mileage
leases, so the comparison is against the mileage-adjusted value.

**R03 Payment.** The payment is recomputed from the contract terms (standard amortization for
loans; depreciation plus rent charge for leases, money factor = rate / 2400). A tolerance absorbs
rounding. An understated payment scores higher than an overstated one: it is the direction that
costs money.

**R04 / R14 Splits.** A deal split into pieces that each sit just under one analyst's authority,
but together exceed the highest authority of anyone who signed. R04 uses a 7-day window and is
precise. R14 repeats the test over 30 days to catch slower splits, and is deliberately weak: real
fleets reorder every few weeks, and on the evaluation books only 31% of R14 hits are planted. It
queues for review; it never ranks a dealer.

**R05 / R13 VINs.** The same vehicle financed twice while the first contract is open is double
funding. A VIN re-financed after the first contract terminated is legal and is planted as a
look-alike. R13 widens the match to one character on the same model and year, which catches a
cloned or mis-keyed VIN without false hits.

**R06 Power booking.** Inflating the price over sticker and loading add-ons to raise the advance.
Each of the three caps counts separately so a contract breaking all three scores higher.

**R07 / R09 Programs and backdating.** R07 is a program used outside its window, model or term.
R09 is subtler: the contract date is inside the window, but the deal was keyed in weeks later,
after the program closed or the rate sheet went up. Lag alone is not enough (paperwork is late all
the time); the rule also needs proof that the old date bought something. Backdating with a lag
under the threshold is a known blind spot.

**R08 Tier.** The tier a score earns is found with an `ASOF JOIN` on the score bands. A better
tier needs a documented override signed at L3 or above.

**R10 Exposure.** At every funding date, the scheduled balance of every open contract for that
customer is computed (same formula as the generator, checked by tests) and compared with the limit
in force that day, taken from the limit history with an `ASOF JOIN`. A limit raised before a big
deal is legal and is planted as a look-alike.

**R11 Early defaults.** Early-payment default: two of the first three installments missed or paid
30+ days late. A raw rate is misleading on small dealers (one bad deal out of four is 25%), so the
rule compares the 95% Wilson lower bound with twice the portfolio rate, and needs at least 12
seasoned contracts and 3 defaults.

**R12 Authority.** A deal total above the signer's authority: an internal control failure, not a
dealer one.

## Scoring

Points are additive. Medium (25+) means a person should look; high (50+) means two or more
independent problems on the same contract. The isolation forest adds 10 points to the top 1% of
contracts by outlier score, which can push a minor finding into medium but cannot create one alone.

Dealer risk index = 100 x share of volume with medium-or-high conduct findings + 5 x number of
different conduct rules + 40 if the dealer has an early-default cluster. Watchlist at 20 or an
early-default flag.

## Choices and trade-offs

- **DuckDB** over a server database: the whole audit runs in memory from CSVs, with window
  functions, `ASOF JOIN`, `GROUPING SETS` and `hamming()` available in plain SQL.
- **Rules first, model second.** Rules give evidence a reviewer can act on; a model gives a score
  that needs explaining. The evaluation shows the model alone misses everything that is only wrong
  in context.
- **Policy in a table.** Tests change the policy and check the findings change with it, which is
  how a rule change would be reviewed in practice.
- **Look-alikes for every rule.** A rule that only sees bad cases is easy to write; the hard part is
  staying quiet on the legal case next to it.

## What a real book would add

Data errors that are not fraud, legitimate exceptions the policy table does not encode,
manufacturer program amendments, partial payments and restructures, and dealer groups under
common ownership. Each would need its own handling before these rules could be trusted on
production data.
