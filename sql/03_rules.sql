-- Anomaly rules. Each view answers one question about the book and returns
--   entity_type | entity_id | rule_id | magnitude | evidence
-- The SQL decides WHAT is wrong; fleetaudit/score.py decides how much it matters.
-- Every threshold comes from the policy tables, nothing is hard-coded here.

-- Contract facts: one wide row per contract with everything the rules compare against.
CREATE OR REPLACE VIEW v_facts AS
SELECT
    c.*,
    v.segment, v.msrp, v.invoice,
    a.level         AS approver_level,
    a.authority_mxn,
    tp.tier_rank,
    tp.ltv_cap,
    st.tier         AS score_tier,
    st.tier_rank    AS score_rank,
    round((c.contract_rate - c.buy_rate) * 100)::INTEGER AS markup_bps,
    CASE WHEN c.program_id IS NOT NULL THEN p.markup_cap_program_bps
         WHEN c.product = 'LEASE'      THEN p.markup_cap_lease_bps
         ELSE p.markup_cap_loan_bps END AS markup_cap_bps,
    CASE WHEN c.product = 'LOAN' THEN
             CASE WHEN c.contract_rate = 0 THEN c.amount_financed / c.term_months
                  ELSE c.amount_financed * (c.contract_rate / 1200)
                       / (1 - pow(1 + c.contract_rate / 1200, -c.term_months)) END
         ELSE (c.amount_financed - c.residual_value) / c.term_months
              + (c.amount_financed + c.residual_value) * c.contract_rate / 2400
    END AS expected_payment,
    datediff('day', c.contract_date, c.entered_at) AS entry_lag_days,
    datediff('day', c.contract_date, c.funded_date) AS days_to_fund
FROM contracts c
JOIN vehicle_catalog v USING (model_code, model_year)
JOIN approvers a       USING (approver_id)
JOIN tier_policy tp    ON tp.tier = c.credit_tier
ASOF JOIN tier_policy st ON c.credit_score >= st.min_score   -- tier the score actually earns
CROSS JOIN policy p;


-- R01 Dealer markup above the cap (no markup at all on subvented programs).
CREATE OR REPLACE VIEW r01_markup_over_cap (entity_type, entity_id, rule_id, magnitude, evidence) AS
SELECT 'contract' AS entity_type, contract_id AS entity_id, 'R01' AS rule_id,
       (markup_bps - markup_cap_bps)::DOUBLE AS magnitude,
       format('markup {} bps vs cap {} bps', markup_bps, markup_cap_bps) AS evidence
FROM v_facts
WHERE markup_bps > markup_cap_bps;


-- R02 Lease residual booked above the residual table (lower payment, more balloon risk).
CREATE OR REPLACE VIEW r02_residual_inflation (entity_type, entity_id, rule_id, magnitude, evidence) AS
SELECT 'contract', f.contract_id, 'R02',
       f.residual_pct - (rt.residual_pct + CASE WHEN f.annual_km > p.high_mileage_km
                                                THEN p.high_mileage_adj_pp ELSE 0 END),
       format('residual {}% vs table {}%', f.residual_pct,
              rt.residual_pct + CASE WHEN f.annual_km > p.high_mileage_km THEN p.high_mileage_adj_pp ELSE 0 END)
FROM v_facts f
JOIN residual_table rt ON rt.segment = f.segment AND rt.term_months = f.term_months
CROSS JOIN policy p
WHERE f.product = 'LEASE'
  AND f.residual_pct > rt.residual_pct
                       + CASE WHEN f.annual_km > p.high_mileage_km THEN p.high_mileage_adj_pp ELSE 0 END
                       + p.residual_tolerance_pp;


-- R03 Booked payment does not reconcile with amount, rate, term and residual.
CREATE OR REPLACE VIEW r03_payment_mismatch (entity_type, entity_id, rule_id, magnitude, evidence) AS
SELECT 'contract', f.contract_id, 'R03',
       (f.monthly_payment - f.expected_payment) / f.expected_payment,
       format('booked {:.2f} vs recomputed {:.2f}', f.monthly_payment, f.expected_payment)
FROM v_facts f CROSS JOIN policy p
WHERE abs(f.monthly_payment - f.expected_payment)
      > greatest(p.payment_tolerance_abs, p.payment_tolerance_pct * f.expected_payment);


-- Deals: one row per submission, sized against the approver who signed it.
CREATE OR REPLACE VIEW v_deals AS
SELECT d.*, a.authority_mxn, a.level,
       d.total / a.authority_mxn AS authority_use
FROM (
    SELECT deal_id, any_value(customer_id) AS customer_id, any_value(dealer_id) AS dealer_id,
           any_value(approver_id) AS approver_id, min(contract_date) AS deal_date,
           sum(amount_financed) AS total, count(*) AS units
    FROM contracts GROUP BY deal_id
) d JOIN approvers a USING (approver_id);


-- R04 Split deal: same customer and dealer, several near-limit deals inside the
-- window, together above the highest authority among the people who signed them.
CREATE OR REPLACE VIEW r04_split_deal (entity_type, entity_id, rule_id, magnitude, evidence) AS
WITH win AS (
    SELECT d.deal_id,
           count(*) FILTER (WHERE w.authority_use >= p.split_near_limit AND w.authority_use <= 1) AS near_deals,
           sum(w.total)          AS window_total,
           max(w.authority_mxn)  AS max_authority,
           string_agg(w.deal_id, ', ' ORDER BY w.deal_id) AS deals
    FROM v_deals d
    JOIN v_deals w ON w.customer_id = d.customer_id AND w.dealer_id = d.dealer_id
    CROSS JOIN policy p
    WHERE abs(datediff('day', d.deal_date, w.deal_date)) <= p.split_window_days
      AND d.authority_use >= p.split_near_limit AND d.authority_use <= 1
    GROUP BY d.deal_id
)
SELECT 'contract' AS entity_type, c.contract_id AS entity_id, 'R04' AS rule_id,
       win.window_total / win.max_authority AS magnitude,
       format('{} near-limit deals ({}) total {:,.0f} vs top authority {:,.0f}',
              win.near_deals, win.deals, win.window_total, win.max_authority) AS evidence
FROM win JOIN contracts c USING (deal_id)
WHERE win.near_deals >= 2 AND win.window_total > win.max_authority;


-- R05 Same VIN financed again while the first contract was still open.
CREATE OR REPLACE VIEW r05_duplicate_vin (entity_type, entity_id, rule_id, magnitude, evidence) AS
SELECT 'contract', b.contract_id, 'R05', 1.0,
       format('VIN {} already on {} (funded {}, {})', b.vin, a.contract_id, a.funded_date, a.status)
FROM contracts b
JOIN contracts a ON a.vin = b.vin AND a.contract_id <> b.contract_id
WHERE (a.funded_date, a.contract_id) < (b.funded_date, b.contract_id)
  AND (a.close_date IS NULL OR a.close_date >= b.contract_date);


-- R06 Advance above policy: amount over the tier's LTV cap, add-ons over cap,
-- or a cash price above sticker. Magnitude = number of breaches.
CREATE OR REPLACE VIEW r06_advance_over_policy (entity_type, entity_id, rule_id, magnitude, evidence) AS
WITH b AS (
    SELECT f.contract_id, f.amount_financed / f.invoice AS ltv, f.ltv_cap,
           f.addons / f.cash_price AS addon_share, f.cash_price / f.msrp AS price_ratio,
           (f.amount_financed > f.ltv_cap * f.invoice + 0.5)::INTEGER
         + (f.addons > p.addon_cap * f.cash_price + 0.5)::INTEGER
         + (f.cash_price > p.price_cap * f.msrp)::INTEGER AS breaches
    FROM v_facts f CROSS JOIN policy p
)
SELECT 'contract', contract_id, 'R06', breaches::DOUBLE,
       format('LTV {:.0f}% (cap {:.0f}%), add-ons {:.0f}%, price {:.0f}% of MSRP',
              ltv * 100, ltv_cap * 100, addon_share * 100, price_ratio * 100)
FROM b WHERE breaches > 0;


-- R07 Program rate used outside the program: wrong dates, wrong model or term too long.
CREATE OR REPLACE VIEW r07_incentive_misuse (entity_type, entity_id, rule_id, magnitude, evidence) AS
SELECT 'contract', f.contract_id, 'R07', 1.0,
       format('{} ({} to {}) on {} {} dated {}, term {}', f.program_id, pr.start_date, pr.end_date,
              f.model_code, CASE WHEN pm.model_code IS NULL THEN '(not eligible)' ELSE '' END,
              f.contract_date, f.term_months)
FROM v_facts f
JOIN incentive_programs pr USING (program_id)
LEFT JOIN program_models pm ON pm.program_id = f.program_id AND pm.model_code = f.model_code
WHERE f.contract_date NOT BETWEEN pr.start_date AND pr.end_date
   OR pm.model_code IS NULL
   OR f.term_months > pr.max_term;


-- R08 Credit tier better than the score earns, without a documented override
-- signed at a high enough level.
CREATE OR REPLACE VIEW r08_tier_inflation (entity_type, entity_id, rule_id, magnitude, evidence) AS
SELECT 'contract', f.contract_id, 'R08', (f.score_rank - f.tier_rank)::DOUBLE,
       format('score {} earns tier {}, booked tier {}, override {}, approver L{}',
              f.credit_score, f.score_tier, f.credit_tier, coalesce(f.override_code, 'none'), f.approver_level)
FROM v_facts f CROSS JOIN policy p
WHERE f.tier_rank < f.score_rank
  AND (f.override_code IS NULL OR f.approver_level < p.override_min_level);


-- R09 Backdated contract: keyed in long after its date AND the old date bought
-- something (a program that had closed, or a cheaper rate sheet).
CREATE OR REPLACE VIEW r09_backdated (entity_type, entity_id, rule_id, magnitude, evidence) AS
SELECT 'contract', f.contract_id, 'R09', f.entry_lag_days::DOUBLE,
       CASE WHEN f.program_id IS NOT NULL
            THEN format('entered {} days after contract date; {} closed {}', f.entry_lag_days, f.program_id, pr.end_date)
            ELSE format('entered {} days after contract date; sheet then {:.2f}% vs booked {:.2f}%',
                        f.entry_lag_days, rs.buy_rate, f.buy_rate) END
FROM v_facts f
CROSS JOIN policy p
LEFT JOIN incentive_programs pr USING (program_id)
LEFT JOIN rate_sheet rs ON rs.sheet_month = date_trunc('month', f.entered_at)
                       AND rs.tier = f.credit_tier AND rs.term_months = f.term_months
WHERE f.entry_lag_days > p.backdate_lag_days
  AND (   (f.program_id IS NOT NULL AND f.entered_at > pr.end_date)
       OR (f.program_id IS NULL AND rs.buy_rate >= f.buy_rate + p.backdate_rate_gain - 1e-6));


-- Customer exposure at every funding date: scheduled balance of every open
-- contract, compared with the limit in force that day.
CREATE OR REPLACE VIEW v_exposure AS
WITH events AS (
    SELECT DISTINCT customer_id, funded_date AS event_date FROM contracts
),
bal AS (
    SELECT e.customer_id, e.event_date, c.contract_id,
           least(greatest(datediff('month', c.contract_date, e.event_date), 0), c.term_months) AS k,
           c.product, c.amount_financed AS amt, c.residual_value AS res,
           c.contract_rate / 1200 AS r, c.term_months AS n, c.monthly_payment AS pmt
    FROM events e
    JOIN contracts c ON c.customer_id = e.customer_id
                    AND c.funded_date <= e.event_date
                    AND (c.close_date IS NULL OR c.close_date > e.event_date)
),
agg AS (
    SELECT customer_id, event_date,
           sum(CASE WHEN product = 'LOAN' THEN
                        CASE WHEN r = 0 THEN amt - pmt * k
                             ELSE amt * pow(1 + r, k) - pmt * (pow(1 + r, k) - 1) / r END
                    ELSE amt - (amt - res) * k / n END) AS exposure,
           count(*) AS open_contracts
    FROM bal GROUP BY customer_id, event_date
)
SELECT agg.*, l.limit_mxn, agg.exposure / l.limit_mxn AS limit_use
FROM agg
ASOF JOIN customer_limits l ON l.customer_id = agg.customer_id AND agg.event_date >= l.effective_date;


-- R10 Funding that took the customer above the exposure limit in force that day.
CREATE OR REPLACE VIEW r10_exposure_breach (entity_type, entity_id, rule_id, magnitude, evidence) AS
SELECT 'contract', c.contract_id, 'R10', e.limit_use,
       format('{} exposure {:,.0f} vs limit {:,.0f} on {}', e.customer_id, e.exposure, e.limit_mxn, e.event_date)
FROM v_exposure e
JOIN contracts c ON c.customer_id = e.customer_id AND c.funded_date = e.event_date
WHERE e.exposure > e.limit_mxn;


-- R11 Dealer whose early-payment-default rate is too high to be chance.
-- EPD = 2 of the first 3 installments missed or paid 30+ days late.
-- Flag when the 95% Wilson lower bound beats the portfolio rate by epd_ratio.
CREATE OR REPLACE VIEW v_dealer_epd AS
WITH first3 AS (
    SELECT p.contract_id, count(*) AS due,
           count(*) FILTER (WHERE (p.paid_date IS NULL AND p.due_date + INTERVAL 30 DAY <= pol.as_of)
                               OR p.paid_date > p.due_date + INTERVAL 30 DAY) AS missed,
           max(p.due_date) AS third_due
    FROM payments p CROSS JOIN policy pol
    WHERE p.installment <= 3
    GROUP BY p.contract_id
),
seasoned AS (
    SELECT c.dealer_id, f.contract_id, (f.missed >= 2)::INTEGER AS epd
    FROM first3 f JOIN contracts c USING (contract_id) CROSS JOIN policy pol
    WHERE f.due = 3 AND f.third_due + INTERVAL 30 DAY <= pol.as_of
),
portfolio AS (SELECT avg(epd) AS rate FROM seasoned),
dealer AS (
    SELECT dealer_id, count(*) AS n, sum(epd) AS k, avg(epd) AS rate FROM seasoned GROUP BY dealer_id
)
SELECT d.*, pf.rate AS portfolio_rate,
       (d.rate + 1.96^2 / (2 * d.n) - 1.96 * sqrt(d.rate * (1 - d.rate) / d.n + 1.96^2 / (4 * d.n^2)))
         / (1 + 1.96^2 / d.n) AS wilson_low
FROM dealer d CROSS JOIN portfolio pf;

CREATE OR REPLACE VIEW r11_dealer_epd (entity_type, entity_id, rule_id, magnitude, evidence) AS
SELECT 'dealer', e.dealer_id, 'R11', e.wilson_low / e.portfolio_rate,
       format('EPD {}/{} = {:.1f}% (95% low {:.1f}%) vs portfolio {:.1f}%',
              e.k, e.n, e.rate * 100, e.wilson_low * 100, e.portfolio_rate * 100)
FROM v_dealer_epd e CROSS JOIN policy p
WHERE e.n >= p.epd_min_seasoned AND e.k >= p.epd_min_count
  AND e.wilson_low > p.epd_ratio * e.portfolio_rate;


-- R12 Deal signed above the approver's authority.
CREATE OR REPLACE VIEW r12_authority_exceeded (entity_type, entity_id, rule_id, magnitude, evidence) AS
SELECT 'contract', c.contract_id, 'R12', d.authority_use,
       format('{} total {:,.0f} signed by {} (L{}, authority {:,.0f})',
              d.deal_id, d.total, d.approver_id, d.level, d.authority_mxn)
FROM v_deals d JOIN contracts c USING (deal_id)
WHERE d.total > d.authority_mxn;


-- R13 VIN one character away from another open contract on the same model and
-- year: a cloned or mis-keyed VIN that an exact match (R05) cannot see.
CREATE OR REPLACE VIEW r13_near_duplicate_vin (entity_type, entity_id, rule_id, magnitude, evidence) AS
SELECT 'contract', b.contract_id, 'R13', hamming(a.vin, b.vin)::DOUBLE,
       format('VIN {} differs by one character from {} on {} ({} {})', b.vin, a.vin, a.contract_id,
              a.model_code, a.model_year)
FROM contracts b
JOIN contracts a ON a.model_code = b.model_code AND a.model_year = b.model_year
                AND a.contract_id <> b.contract_id AND hamming(a.vin, b.vin) = 1
WHERE (a.funded_date, a.contract_id) < (b.funded_date, b.contract_id)
  AND (a.close_date IS NULL OR a.close_date >= b.contract_date);


-- R14 Slow split: the R04 test over a 30-day window, for deals R04 did not catch.
-- Weak on purpose: legitimate repeat orders look the same, so it only queues for review.
CREATE OR REPLACE VIEW r14_slow_split (entity_type, entity_id, rule_id, magnitude, evidence) AS
WITH win AS (
    SELECT d.deal_id,
           count(*) FILTER (WHERE w.authority_use >= p.split_near_limit AND w.authority_use <= 1) AS near_deals,
           sum(w.total)         AS window_total,
           max(w.authority_mxn) AS max_authority,
           max(abs(datediff('day', d.deal_date, w.deal_date))) AS span_days
    FROM v_deals d
    JOIN v_deals w ON w.customer_id = d.customer_id AND w.dealer_id = d.dealer_id
    CROSS JOIN policy p
    WHERE abs(datediff('day', d.deal_date, w.deal_date)) <= p.slow_split_window_days
      AND w.authority_use >= p.split_near_limit AND w.authority_use <= 1
      AND d.authority_use >= p.split_near_limit AND d.authority_use <= 1
    GROUP BY d.deal_id
)
SELECT 'contract', c.contract_id, 'R14', win.window_total / win.max_authority,
       format('{} near-limit deals within {} days total {:,.0f} vs top authority {:,.0f}',
              win.near_deals, win.span_days, win.window_total, win.max_authority)
FROM win JOIN contracts c USING (deal_id)
WHERE win.near_deals >= 2 AND win.window_total > win.max_authority
  AND c.contract_id NOT IN (SELECT entity_id FROM r04_split_deal);


CREATE OR REPLACE VIEW v_rule_hits AS
SELECT * FROM r01_markup_over_cap
UNION ALL SELECT * FROM r02_residual_inflation
UNION ALL SELECT * FROM r03_payment_mismatch
UNION ALL SELECT * FROM r04_split_deal
UNION ALL SELECT * FROM r05_duplicate_vin
UNION ALL SELECT * FROM r06_advance_over_policy
UNION ALL SELECT * FROM r07_incentive_misuse
UNION ALL SELECT * FROM r08_tier_inflation
UNION ALL SELECT * FROM r09_backdated
UNION ALL SELECT * FROM r10_exposure_breach
UNION ALL SELECT * FROM r11_dealer_epd
UNION ALL SELECT * FROM r12_authority_exceeded
UNION ALL SELECT * FROM r13_near_duplicate_vin
UNION ALL SELECT * FROM r14_slow_split;


-- Features for the statistical layer (one row per contract, numeric only).
CREATE OR REPLACE VIEW v_features AS
SELECT
    f.contract_id,
    f.markup_bps - f.markup_cap_bps                         AS markup_vs_cap_bps,
    f.amount_financed / (f.ltv_cap * f.invoice)             AS advance_vs_cap,
    f.cash_price / f.msrp                                   AS price_to_msrp,
    f.addons / f.cash_price                                 AS addon_share,
    coalesce(f.residual_pct - rt.residual_pct
             - CASE WHEN f.annual_km > p.high_mileage_km THEN p.high_mileage_adj_pp ELSE 0 END, 0)
                                                            AS residual_vs_table,
    (f.monthly_payment - f.expected_payment) / f.expected_payment AS payment_gap,
    f.entry_lag_days,
    f.days_to_fund,
    f.score_rank - f.tier_rank                              AS tier_gap,
    f.amount_financed / median(f.amount_financed) OVER (PARTITION BY f.segment) AS amount_vs_segment
FROM v_facts f
CROSS JOIN policy p
LEFT JOIN residual_table rt ON rt.segment = f.segment AND rt.term_months = f.term_months;
