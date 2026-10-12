-- Data-quality gate. Each check returns how many rows break it.
-- Audit results are only trusted when every check returns 0: a rule that fires
-- on broken data is a data problem, not a finding.

CREATE OR REPLACE VIEW v_dq AS
WITH c AS (
    SELECT c.*, v.msrp
    FROM contracts c
    JOIN vehicle_catalog v USING (model_code, model_year)
)
SELECT 'funded_before_contract' AS check_name,
       count(*) FILTER (WHERE funded_date < contract_date) AS failures FROM c
UNION ALL
SELECT 'entered_before_contract',
       count(*) FILTER (WHERE entered_at < contract_date) FROM c
UNION ALL
SELECT 'amount_identity',            -- amount financed = cash price - down payment + add-ons
       count(*) FILTER (WHERE abs(amount_financed - (cash_price - down_payment + addons)) > 0.01) FROM c
UNION ALL
SELECT 'residual_value_identity',    -- residual value = MSRP x residual %
       count(*) FILTER (WHERE product = 'LEASE' AND abs(residual_value - msrp * residual_pct / 100) > 0.01) FROM c
UNION ALL
SELECT 'buy_rate_off_sheet',         -- non-program buy rate must come from that month's sheet
       count(*) FROM c
       JOIN rate_sheet rs ON rs.sheet_month = date_trunc('month', c.contract_date)
                         AND rs.tier = c.credit_tier AND rs.term_months = c.term_months
       WHERE c.program_id IS NULL AND abs(rs.buy_rate - c.buy_rate) > 1e-6
UNION ALL
SELECT 'program_rate_mismatch',
       count(*) FROM c JOIN incentive_programs p USING (program_id)
       WHERE abs(c.buy_rate - p.program_rate) > 1e-6
UNION ALL
SELECT 'missing_rate_sheet',
       count(*) FROM c
       LEFT JOIN rate_sheet rs ON rs.sheet_month = date_trunc('month', c.contract_date)
                              AND rs.tier = c.credit_tier AND rs.term_months = c.term_months
       WHERE rs.buy_rate IS NULL
UNION ALL
SELECT 'contract_before_dealer_onboarded',
       count(*) FROM c JOIN dealers d USING (dealer_id) WHERE c.contract_date < d.onboarded
UNION ALL
SELECT 'contract_without_customer_limit',
       count(*) FROM c
       WHERE NOT EXISTS (SELECT 1 FROM customer_limits l
                         WHERE l.customer_id = c.customer_id AND l.effective_date <= c.funded_date)
UNION ALL
SELECT 'payment_after_close',
       count(*) FROM payments p JOIN contracts c USING (contract_id)
       WHERE c.close_date IS NOT NULL AND p.due_date > c.close_date
UNION ALL
SELECT 'payment_amount_due_mismatch',
       count(*) FROM payments p JOIN contracts c USING (contract_id)
       WHERE abs(p.amount_due - c.monthly_payment) > 0.005
UNION ALL
SELECT 'payment_gap_in_schedule',    -- installments must run 1..n with no holes
       count(*) FROM (
           SELECT contract_id, max(installment) AS mx, count(*) AS n
           FROM payments GROUP BY contract_id
       ) WHERE mx <> n
UNION ALL
SELECT 'payment_due_after_as_of',
       count(*) FROM payments, policy WHERE due_date > policy.as_of;
