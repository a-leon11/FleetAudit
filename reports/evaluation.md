# Evaluation

Detection scored against the generator's answer key over 20 seeds (1 to 20). Each seed is a different book: different dealers, customers, rate path, programs and placement of every planted pattern.

## Planted patterns (contract level)

| Pattern | Rule | Planted | Caught by its rule | Medium or high | Statistical layer alone |
|---|---|---:|---:|---:|---:|
| authority_exceeded | R12 | 680 | 680 (100%) | 680 (100%) | 0 (0%) |
| backdating | R09 | 204 | 204 (100%) | 204 (100%) | 53 (26%) |
| backdating_short | R09 | 60 | 0 (0%) | 0 (0%) | 0 (0%) |
| duplicate_vin | R05 | 120 | 120 (100%) | 120 (100%) | 0 (0%) |
| exposure_breach | R10 | 178 | 178 (100%) | 178 (100%) | 0 (0%) |
| incentive_misuse | R07 | 200 | 200 (100%) | 200 (100%) | 0 (0%) |
| markup_over_cap | R01 | 300 | 300 (100%) | 300 (100%) | 1 (0%) |
| payment_mismatch | R03 | 240 | 240 (100%) | 240 (100%) | 48 (20%) |
| power_booking | R06 | 250 | 250 (100%) | 250 (100%) | 250 (100%) |
| residual_inflation | R02 | 240 | 240 (100%) | 240 (100%) | 19 (8%) |
| split_deal | R04 | 705 | 705 (100%) | 705 (100%) | 0 (0%) |
| split_deal_slow | R14 | 309 | 309 (100%) | 0 (0%) | 0 (0%) |
| tier_inflation | R08 | 252 | 252 (100%) | 252 (100%) | 28 (11%) |
| vin_near_duplicate | R13 | 60 | 60 (100%) | 60 (100%) | 0 (0%) |
| **All** | | **3798** | **3738 (98%)** | **3429 (90%)** | **399 (11%)** |

## Look-alikes (legal cases built to sit right next to a rule)

| Look-alike | Count | Any rule fired | Medium or high |
|---|---:|---:|---:|
| deal_at_authority | 250 | 0 | 0 |
| high_advance_within_cap | 100 | 0 | 0 |
| incentive_last_day | 80 | 0 | 0 |
| late_entry_no_benefit | 100 | 1 | 0 |
| markup_at_cap | 100 | 0 | 0 |
| near_limit_plus_small_order | 185 | 2 | 0 |
| payment_rounding | 100 | 1 | 0 |
| residual_within_tolerance | 100 | 1 | 0 |
| split_authorized | 319 | 0 | 0 |
| split_far_apart | 264 | 264 | 0 |
| tier_override_documented | 147 | 0 | 0 |
| vin_after_termination | 120 | 0 | 0 |

## Precision and entity-level checks

- Contracts at medium or high: 3429, of which **0 were not planted** (precision 100.0%).
- Low-only contracts: 1032, of which 723 were not planted. This is the review queue: the statistical layer's top 1% and the weak R14 signal.
- R14 (slow split) fired on 990 contracts; 309 were planted slow splits (31%). The rest are genuine repeat orders a few weeks apart, which is exactly why R14 only queues for review and never reaches medium on its own.
- Early-default dealers: 40 of 40 flagged, 0 false flags. The tiny dealer with one early default was flagged 0 times.
- Aggressive dealers: 40 of 40 on the watchlist, 28 in the top five by risk index.
- Dealer watchlist: 178 entries in total, 0 without any planted dealer-conduct pattern.
- Customers over limit: 60 of 60 flagged, 0 false flags; customers whose limit was raised before the big deal flagged 0 times.
- Data-quality failures across all seeds: 0.

## How to read this

The background book is generated inside policy, so the first-line rules score perfectly on the patterns they were written for. That shows the logic is right, not that it would hold on a real book, where messy data, exceptions and judgment calls add noise the generator does not model.

The three evasive variants are the honest part:

- **split_deal_slow** spreads the pieces 9 to 13 days apart, outside R04's 7-day window. R14 widens the window to 30 days and finds all of them, but it also finds every legitimate repeat order, so it stays a low-tier review signal. Widening R04 instead would trade a clean high-confidence rule for a noisy one.
- **vin_near_duplicate** changes one character of a VIN already on an open contract. Exact matching (R05) cannot see it; a Hamming-distance match on the same model and year (R13) can, with no false hits.
- **backdating_short** keeps the keying lag under the 15-day threshold. **Nothing catches it.** Lowering the threshold would start flagging ordinary paperwork delays, so this is a known blind spot to close with a process control (time-stamped contract capture at the dealer), not a rule.

The statistical column is the other comparison: an isolation forest on its own finds the patterns that make a contract numerically strange (power booking) and misses the ones that are only wrong in context (a VIN seen before, a deal split across days, a limit in force on a given date).
