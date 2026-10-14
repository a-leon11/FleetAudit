# Case and proposal: a second look at a fleet credit book

*A portfolio case based on my experience as a Dealer Sales Analyst at GMF. The process is described in general terms. Every dealer, customer, document, rate, threshold and contract in this repo is invented, and no GMF data, documents, systems or policies are used.*

## 1. Summary

Fleet financing runs on a chain of careful decisions, each made on one file at a time. A reviewer checks the applicant's documents against a checklist. A credit team sets the limit. Someone books the contract. The money goes to a dealer. Some problems cannot be seen at any one of those steps and only appear when the whole book is read together.

This case asks what that second look would add. FleetAudit is the prototype: 14 rules in SQL, run on an invented portfolio of 2,262 contracts, flag 199 of them (MXN 132.3M of the MXN 1,844.5M financed). Of those, 87 trace to the lender's own controls (limits, signing authority, credit tiers, payments keyed wrong) and 112 to dealer conduct. The counts come from the problems I planted, so they show that the method works. They do not say what a real book looks like.

The case ends with a proposal: a four-week, read-only pilot on one closed quarter of real contracts, run with the credit and dealer teams, to find out which of these checks earn a place in a monthly routine.

## 2. The process as I knew it

Fleet customers come in three kinds: individuals, individuals with business activity (PFAE, *persona física con actividad empresarial*) and companies. Each kind sends a different set of documents. The lender's public requirements page for vehicle credit shows the pattern:

| Applicant | What the public page asks for, in summary |
|---|---|
| Individual | Application, official ID, proof of address and proof of income (payroll receipts or bank statements with payroll deposits; a bank statement if self-employed) |
| PFAE | The same, with a bank statement, plus the tax ID certificate (CIF) |
| Company | Application, legal representative's ID, proof of address, bank statement, incorporation deed and powers, financial statements, CIF, and a beneficial-owner declaration with the owners' ID and proof of address |

*Source: the lender's public page "Requisitos de contratación para el Crédito de Vehículos GMF", summarized, not quoted.*

For businesses, the checklist I worked from was longer than that page: income statement, balance sheet, cash flows, tax returns and, where required, audited statements (*estados financieros dictaminados*).

The chain then ran like this:

1. **Package review.** I checked each applicant's package against the checklist for its kind. The result was a yes or no.
2. **Limit.** Smaller fleet requests stayed on the fleet track. Larger ones moved to a commercial credit team, which set the limit from the income the applicant stated. (Single cars and small sums belong to consumer credit, a separate process this case does not touch.)
3. **Booking.** Approved contracts were keyed into the loan system by hand, one at a time. On the larger requests the commercial team also checked the entries.
4. **Funding.** The loan is not paid to the applicant. The money goes to a dealer, often one outside the manufacturer's own network, and the lender buys the vehicles from that dealer directly.
5. **Servicing.** Payments come in, some late, a few never.

Two things follow. The applicant's file can be perfect and the money can still be mispriced or misdirected at the dealer, because the dealer's paper sets the price, the add-ons, the rate markup and the incentive program each contract uses. And every check in the chain is a person looking at one file.

## 3. What a file-by-file chain cannot show

None of this is a criticism of those checks. A reviewer can spot a forged statement or an income that does not add up, and no rule here can. A second look has different strengths: it sees the whole book at once, it applies the same test to every contract, and it can recompute what a person typed. Three kinds of problem sit in its reach.

**Patterns across files.** The same vehicle on two contracts. A customer's exposure across several contracts: in the simulation, all 7 contracts that took customers past their limit were small on their own (MXN 0.7M to 1.1M against limits of MXN 2.9M to 4.7M), so a check of the new contract's amount against the limit passes every one. The breach exists only once the customer's other open balances are added. A deal cut into pieces: the 9 split deals in the simulation each used 75% to 94% of their signer's authority, and together they were above the highest authority of anyone who signed.

**Dealers over time.** One high markup, one inflated residual or one program used out of its window can be explained on a single contract. A pattern across many contracts from the same dealer cannot. The same goes for early defaults: a few bad deals prove nothing, while a dealer whose early-default rate is too high to be chance proves something.

**The keyed record.** A manual step is where a wrong payment, a better tier than the score earns or a wrong date can enter. All three can be recomputed from the contract terms, the score bands and the rate sheet, for every contract, in seconds.

## 4. Approach: FleetAudit as the prototype

FleetAudit rebuilds the second look as an analytics step on an invented book of fleet contracts. It answers three questions in order: can the data be trusted, what breaks policy, and what should a person look at first. [`methodology.md`](methodology.md) has the reasoning behind each rule.

| Stage of the chain | What the second look asks | Where FleetAudit looks |
|---|---|---|
| Package review | Is the file complete, consistent and current? | Not built yet (section 8) |
| Limit and authority | Was the customer funded inside the limit in force that day? Did someone with enough authority sign? Does the tier match the score? | R10, R12, R08 |
| Booking | Is the keyed record consistent with the contract terms, the rate sheet and the dates? | 13 data-quality checks, R03, R09 |
| Funding to the dealer | Did the dealer's paper stay inside the price, add-on, markup, residual and program rules? Was a vehicle financed twice, or a deal split? | R01, R02, R04, R05, R06, R07, R13, R14 |
| Servicing | Do one dealer's customers default early more often than chance allows? | R11, vintage and concentration views |

Three design choices carry over to a real version:

- **Data first.** A gate of 13 checks runs before any rule, and the audit refuses to report if one fails. A rule that fires on broken data is a data problem, not a finding.
- **Evidence, not scores.** Every hit carries the numbers a reviewer needs to confirm it by hand. The statistical layer adds a few points and can queue an unusual contract for a look, but it can never push one to medium on its own.
- **Two owners.** Findings are split into dealer conduct and the lender's own controls, because the fix differs: a chargeback on one side, a second signature on the other.

## 5. What the simulation finds

![Where the flagged money sits](../reports/rule_exposure.png)

On the default invented book, 199 contracts reach medium or high (13 high, 186 medium). They split cleanly by who owns the fix:

| Owner | Rules | Contracts | Financed |
|---|---|---:|---:|
| The lender's own controls | R03, R08, R10, R12 | 87 | MXN 55.7M |
| Dealer conduct | R01, R02, R04, R05, R06, R07, R09, R13 | 112 | MXN 76.6M |

- The largest single item is internal: 4 deals (56 contracts, MXN 30.6M) signed above the signer's authority. An audit aimed only at dealers would have missed it.
- On the dealer side, split deals (R04) and markup over the cap (R01) lead. 7 dealers reach the watchlist, 2 of them for early defaults.
- 3 customers were funded past their exposure limit, and MXN 1.9M of manufacturer subvention sits on contracts with program problems and may be clawed back.
- 73 more contracts sit in a low-priority review queue: slow splits, which are often genuine repeat orders, and the statistical layer's most unusual 1%.

Because the generator knows what it planted, detection can be scored. Over 20 different generated books ([`evaluation.md`](../reports/evaluation.md)), every first-line pattern was caught by its rule, and none of the 3,429 contracts at medium or high was an unplanted one. The same evaluation shows where detection falls short, which is the subject of section 7.

The one-page result for the default book is [`findings.md`](../reports/findings.md).

## 6. Proposal: a four-week, read-only pilot

If I were proposing this inside a lender, I would not start with a platform. I would start with a pilot that answers one question: **which of these checks find real problems in our booked fleet contracts, at a volume the credit and dealer teams can review?**

**Scope.** One closed quarter of booked fleet contracts. Read-only: nothing changes in the loan system, and no finding triggers action until a person has reviewed it.

**Plan.**

| Week | Work | Output |
|---|---|---|
| 1 | Agree a read-only extract: contracts, payments, rate sheets, program terms, approval authority and limit history. Run the data-quality gate and fix or document every failure. | A clean extract, or a list of what is wrong with the data |
| 2 | Run the rules with thresholds taken from the written policy and kept in one table. | The review queue, a dealer watchlist and the internal-control findings |
| 3 | The credit and dealer teams label a sample of each rule's hits as *confirmed*, *explained* (a legal exception the policy table does not encode) or *wrong*. | Precision per rule, and a list of exceptions to add to the policy table as data |
| 4 | Keep the rules that hold, retune or drop the rest, and decide whether a monthly run is worth the reviewer time. | A go or no-go, and a one-page summary |

**Order of work.** Start with the checks that need only data the lender already holds: limits, authority, tiers and payment recomputation. They need no conversation with a dealer. The dealer rules come second, because every dealer finding needs a person to ask the dealer.

**How success is measured.**

- Share of reviewed hits that were confirmed, per rule. The target is agreed with the reviewers before the run, not after.
- Reviewer minutes per confirmed hit.
- Money in confirmed hits: price or rate corrected, subvention not claimed, exposure brought back inside the limit.
- Days from booking to detection.

**What the pilot needs.** The extract, a named owner for each policy threshold, a few hours of reviewer time in week 3, and agreement that a finding is a lead, not a verdict.

**What it does not do.** It does not make credit decisions, review applicant documents or change a booking.

**Known risks.**

- Real books carry legal exceptions the policy table does not encode. The week 3 labels are how they get found, and they go into the table as data, not into the code.
- A noisy rule can bury a good one. Tiers keep weak signals in a separate queue, and any rule that stays under the precision target is dropped.
- One blind spot cannot be closed by a rule. Backdating with a keying lag under the threshold is caught by nothing in the prototype. It needs a process control, a time stamp at capture, and the pilot would say so rather than lower a threshold.

## 7. Limits of this case

- **Invented data.** The generator builds a clean book inside policy and then plants problems, so the rules score close to perfectly on it. That shows the logic is sound, not that it would hold on real data, which carries noise, exceptions and judgment calls the generator does not model.
- **Two known weak spots.** Backdating with a short keying lag is caught by nothing (60 of 60 planted cases missed over 20 books). Slow splits are caught only by R14, where 31% of hits were planted and 69% were genuine repeat orders, so it queues for review and never ranks a dealer.
- **Tests that miss some edits.** In a mutation pass (appendix), I changed one rule at a time on a copy of the repo, and the suite caught 10 of 16 edits. The six it missed are branches and boundaries the generated books never exercise. Each needs a planted case and a test.
- **A date order the gate does not test.** The generator draws the keying lag and the funding lag independently, so 71 of 2,262 contracts (3.1%) were funded before they were entered. That is an artifact, not a planted finding. On a real book it would be worth chasing, so the check belongs in the data-quality gate.
- **Simplifications.** The approval levels (four levels, up to MXN 250M) are invented and do not copy any real matrix. All 220 simulated customers are companies, so individuals and PFAE are not modeled. Dealers are generic: whether a dealer belongs to the manufacturer's network is not modeled, and neither is the vehicle purchase from the dealer.
- **The front half is missing.** The package review is not in this repo yet (section 8).

## 8. Next: the front half

FleetAudit covers the back half of the chain. The front half, the part I worked on, is the next module. It is **planned and not built**, and everything in it will use invented data:

- Invented applicant packages for the three kinds of applicant, each with its own checklist, plus planted problems and legal look-alikes with an answer key, as in the main audit.
- Routing by request size, and a yes or no with the reasons behind it.
- Arithmetic checks on the financial statements an applicant sends: the balance sheet balances, the income statement adds up, the cash flow ties to the change in cash, and revenue agrees across the statements, the tax returns and the audited statements.
- A limit rule based on stated income (an invented rule, not a copy of any real one).
- An approved-versus-booked reconciliation that mirrors the manual booking step: what was approved against what was keyed.

The applicants will link to the existing customers, so a package can be followed through to the contracts booked for it.

## Appendix: mutation pass

Each row is one edit to a rule in `sql/03_rules.sql`, made by hand on a copy of the repo and followed by the full test suite. "Caught" means at least one test failed. For the six misses I also compared the rule hits with the unedited rules on four generated books (seeds 7, 1, 2 and 3). Nothing changed, which is why no test noticed.

| Edit | Result | What the generated books lack, when missed |
|---|---|---|
| R01: cap comparison `>` becomes `>=` | Caught | |
| R02: residual tolerance dropped | Caught | |
| R02: mileage adjustment dropped from the test | Caught | |
| R03: tolerance takes the smaller of the two limits instead of the larger | **Missed** | A payment error between MXN 2 and 0.25% of the payment |
| R04: window doubled | Caught | |
| R04: one near-limit deal is enough | Caught | |
| R05: ignores whether the first contract is still open | Caught | |
| R06: price check removed | Caught | |
| R07: term check removed | **Missed** | A program contract with a term longer than the program allows |
| R08: override accepted at any approver level | **Missed** | An override signed below the required level |
| R09: proof of benefit removed, so lag alone flags | Caught | |
| R10: smallest limit ever used instead of the limit in force | Caught | |
| R11: raw rate instead of the Wilson lower bound | Caught | |
| R12: `>` becomes `>=` | **Missed** | A deal exactly at its signer's authority |
| R13: distance of 1 widened to 1 to 3 characters | **Missed** | VINs two or three characters apart |
| R13: model year ignored in the match | **Missed** | One-character VIN neighbors across model years |

Closing the six gaps means planting those cases in the generator and adding a test for each. That is the natural companion to the front-half module.
