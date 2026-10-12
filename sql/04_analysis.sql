-- Portfolio context: what the book looks like before anyone asks what is wrong with it.

-- Originations by quarter and product, with subtotals per quarter and a grand total.
CREATE OR REPLACE VIEW v_originations AS
SELECT
    CASE WHEN GROUPING(quarter) = 1 THEN 'TOTAL' ELSE quarter END AS quarter,
    CASE WHEN GROUPING(product) = 1 THEN 'ALL'   ELSE product END AS product,
    count(*)                                            AS contracts,
    count(DISTINCT deal_id)                             AS deals,
    sum(amount_financed)                                AS amount_mxn,
    sum(amount_financed * contract_rate) / sum(amount_financed) AS wavg_rate,
    avg((program_id IS NOT NULL)::INTEGER)             AS program_share
FROM (
    SELECT *, strftime(contract_date, '%Y') || '-Q' || quarter(contract_date) AS quarter FROM contracts
)
GROUP BY GROUPING SETS ((quarter, product), (quarter), ())
ORDER BY quarter, product;


-- Rate stack by tier: buy rate, dealer markup and what the customer pays.
CREATE OR REPLACE VIEW v_rate_stack AS
SELECT credit_tier, product,
       count(*)                                   AS contracts,
       round(avg(buy_rate), 2)                    AS avg_buy_rate,
       round(avg(markup_bps), 0)                  AS avg_markup_bps,
       round(avg(contract_rate), 2)               AS avg_contract_rate,
       round(quantile_cont(markup_bps, 0.9), 0)   AS p90_markup_bps
FROM v_facts
WHERE program_id IS NULL
GROUP BY ALL
ORDER BY credit_tier, product;


-- Vintage curves: cumulative share of contracts that have had an installment
-- 30+ days late, by origination quarter and months on book.
CREATE OR REPLACE VIEW v_vintage AS
WITH inst AS (
    SELECT p.contract_id, p.installment,
           (p.paid_date IS NULL AND p.due_date + INTERVAL 30 DAY <= pol.as_of)
           OR p.paid_date > p.due_date + INTERVAL 30 DAY AS late30
    FROM payments p CROSS JOIN policy pol
),
per_contract AS (
    SELECT c.contract_id,
           strftime(c.contract_date, '%Y') || '-Q' || quarter(c.contract_date) AS vintage,
           max(i.installment)                          AS months_observed,
           min(i.installment) FILTER (WHERE i.late30)  AS first_late
    FROM contracts c JOIN inst i USING (contract_id)
    GROUP BY ALL
),
mob AS (SELECT unnest(range(1, 37)) AS m)
SELECT vintage, m AS months_on_book,
       count(*) FILTER (WHERE months_observed >= m)                       AS observed,
       count(*) FILTER (WHERE months_observed >= m AND first_late <= m)   AS ever_30_late,
       ever_30_late / nullif(observed, 0)                                 AS cumulative_rate
FROM per_contract CROSS JOIN mob
GROUP BY vintage, m
HAVING observed >= 20
ORDER BY vintage, m;


-- Concentration at the as-of date: open balance by customer and its share of the book.
CREATE OR REPLACE VIEW v_concentration AS
WITH bal AS (
    SELECT c.customer_id,
           sum(CASE WHEN c.product = 'LOAN' THEN
                   c.amount_financed * pow(1 + c.contract_rate / 1200, k)
                   - c.monthly_payment * (pow(1 + c.contract_rate / 1200, k) - 1) / (c.contract_rate / 1200)
               ELSE c.amount_financed - (c.amount_financed - c.residual_value) * k / c.term_months END) AS balance
    FROM (
        SELECT c.*, least(datediff('month', c.contract_date, pol.as_of), c.term_months) AS k
        FROM contracts c CROSS JOIN policy pol WHERE c.status = 'ACTIVE'
    ) c
    GROUP BY c.customer_id
)
SELECT customer_id, balance,
       balance / sum(balance) OVER ()                                          AS share,
       sum(balance) OVER (ORDER BY balance DESC ROWS UNBOUNDED PRECEDING)
         / sum(balance) OVER ()                                                AS cumulative_share,
       rank() OVER (ORDER BY balance DESC)                                     AS rnk
FROM bal;


-- One-row portfolio summary used by the report header.
CREATE OR REPLACE VIEW v_portfolio AS
SELECT
    (SELECT count(*) FROM contracts)                                   AS contracts,
    (SELECT count(DISTINCT deal_id) FROM contracts)                    AS deals,
    (SELECT count(DISTINCT dealer_id) FROM contracts)                  AS dealers,
    (SELECT count(DISTINCT customer_id) FROM contracts)                AS customers,
    (SELECT sum(amount_financed) FROM contracts)                       AS originated_mxn,
    (SELECT sum(balance) FROM v_concentration)                         AS open_balance_mxn,
    (SELECT min(contract_date) FROM contracts)                         AS first_contract,
    (SELECT max(contract_date) FROM contracts)                         AS last_contract,
    (SELECT sum(share * share) FROM v_concentration)                   AS customer_hhi,
    (SELECT max(cumulative_share) FILTER (WHERE rnk <= 10) FROM v_concentration) AS top10_share,
    (SELECT as_of FROM policy)                                         AS as_of;
