-- FleetAudit schema (DuckDB).
-- Reference data first, then the contract book. Constraints catch bad loads early;
-- the policy tables hold every threshold the rules in 03_rules.sql use.

CREATE TABLE policy (
    markup_cap_loan_bps     INTEGER NOT NULL,
    markup_cap_lease_bps    INTEGER NOT NULL,
    markup_cap_program_bps  INTEGER NOT NULL,
    addon_cap               DOUBLE  NOT NULL,
    price_cap               DOUBLE  NOT NULL,
    residual_tolerance_pp   DOUBLE  NOT NULL,
    high_mileage_km         INTEGER NOT NULL,
    high_mileage_adj_pp     DOUBLE  NOT NULL,
    payment_tolerance_abs   DOUBLE  NOT NULL,
    payment_tolerance_pct   DOUBLE  NOT NULL,
    split_window_days       INTEGER NOT NULL,
    split_near_limit        DOUBLE  NOT NULL,
    slow_split_window_days  INTEGER NOT NULL,
    backdate_lag_days       INTEGER NOT NULL,
    backdate_rate_gain      DOUBLE  NOT NULL,
    epd_min_seasoned        INTEGER NOT NULL,
    epd_ratio               DOUBLE  NOT NULL,
    epd_min_count           INTEGER NOT NULL,
    override_min_level      INTEGER NOT NULL,
    as_of                   DATE    NOT NULL
);

CREATE TABLE tier_policy (
    tier       VARCHAR PRIMARY KEY,
    min_score  INTEGER NOT NULL,
    tier_rank  INTEGER NOT NULL UNIQUE,
    ltv_cap    DOUBLE  NOT NULL CHECK (ltv_cap > 1)
);

CREATE TABLE dealers (
    dealer_id  VARCHAR PRIMARY KEY,
    name       VARCHAR NOT NULL,
    region     VARCHAR NOT NULL,
    city       VARCHAR NOT NULL,
    onboarded  DATE    NOT NULL
);

CREATE TABLE customers (
    customer_id VARCHAR PRIMARY KEY,
    name        VARCHAR NOT NULL UNIQUE,
    industry    VARCHAR NOT NULL,
    region      VARCHAR NOT NULL,
    onboarded   DATE    NOT NULL
);

CREATE TABLE customer_limits (
    customer_id    VARCHAR NOT NULL REFERENCES customers (customer_id),
    effective_date DATE    NOT NULL,
    limit_mxn      DOUBLE  NOT NULL CHECK (limit_mxn > 0),
    PRIMARY KEY (customer_id, effective_date)
);

CREATE TABLE approvers (
    approver_id   VARCHAR PRIMARY KEY,
    name          VARCHAR NOT NULL,
    level         INTEGER NOT NULL CHECK (level BETWEEN 1 AND 4),
    authority_mxn DOUBLE  NOT NULL CHECK (authority_mxn > 0)
);

CREATE TABLE vehicle_catalog (
    model_code VARCHAR NOT NULL,
    model_year INTEGER NOT NULL,
    segment    VARCHAR NOT NULL,
    msrp       DOUBLE  NOT NULL CHECK (msrp > 0),
    invoice    DOUBLE  NOT NULL CHECK (invoice > 0 AND invoice < msrp),
    PRIMARY KEY (model_code, model_year)
);

CREATE TABLE residual_table (
    segment      VARCHAR NOT NULL,
    term_months  INTEGER NOT NULL,
    residual_pct DOUBLE  NOT NULL CHECK (residual_pct BETWEEN 0 AND 100),
    PRIMARY KEY (segment, term_months)
);

CREATE TABLE rate_sheet (
    sheet_month DATE    NOT NULL,          -- first day of the month the sheet applies to
    tier        VARCHAR NOT NULL REFERENCES tier_policy (tier),
    term_months INTEGER NOT NULL,
    buy_rate    DOUBLE  NOT NULL CHECK (buy_rate > 0),
    PRIMARY KEY (sheet_month, tier, term_months)
);

CREATE TABLE incentive_programs (
    program_id   VARCHAR PRIMARY KEY,
    name         VARCHAR NOT NULL,
    start_date   DATE    NOT NULL,
    end_date     DATE    NOT NULL,
    program_rate DOUBLE  NOT NULL CHECK (program_rate >= 0),
    max_term     INTEGER NOT NULL,
    CHECK (end_date >= start_date)
);

CREATE TABLE program_models (
    program_id VARCHAR NOT NULL REFERENCES incentive_programs (program_id),
    model_code VARCHAR NOT NULL,
    PRIMARY KEY (program_id, model_code)
);

CREATE TABLE contracts (
    contract_id     VARCHAR PRIMARY KEY,
    deal_id         VARCHAR NOT NULL,
    dealer_id       VARCHAR NOT NULL REFERENCES dealers (dealer_id),
    customer_id     VARCHAR NOT NULL REFERENCES customers (customer_id),
    approver_id     VARCHAR NOT NULL REFERENCES approvers (approver_id),
    product         VARCHAR NOT NULL CHECK (product IN ('LOAN', 'LEASE')),
    model_code      VARCHAR NOT NULL,
    model_year      INTEGER NOT NULL,
    vin             VARCHAR NOT NULL CHECK (length(vin) = 17),
    contract_date   DATE    NOT NULL,
    entered_at      DATE    NOT NULL,
    funded_date     DATE    NOT NULL,
    term_months     INTEGER NOT NULL CHECK (term_months IN (24, 36, 48, 60, 72)),
    cash_price      DOUBLE  NOT NULL CHECK (cash_price > 0),
    down_payment    DOUBLE  NOT NULL CHECK (down_payment >= 0),
    addons          DOUBLE  NOT NULL CHECK (addons >= 0),
    amount_financed DOUBLE  NOT NULL CHECK (amount_financed > 0),
    residual_pct    DOUBLE,
    residual_value  DOUBLE,
    annual_km       INTEGER,
    credit_score    INTEGER NOT NULL CHECK (credit_score BETWEEN 300 AND 850),
    credit_tier     VARCHAR NOT NULL REFERENCES tier_policy (tier),
    override_code   VARCHAR,
    buy_rate        DOUBLE  NOT NULL,
    contract_rate   DOUBLE  NOT NULL,
    program_id      VARCHAR REFERENCES incentive_programs (program_id),
    subvention_mxn  DOUBLE  NOT NULL DEFAULT 0,
    monthly_payment DOUBLE  NOT NULL CHECK (monthly_payment > 0),
    status          VARCHAR NOT NULL CHECK (status IN ('ACTIVE', 'PAID_OFF', 'MATURED',
                                                       'TERMINATED_EARLY', 'CHARGED_OFF')),
    close_date      DATE,
    FOREIGN KEY (model_code, model_year) REFERENCES vehicle_catalog (model_code, model_year),
    -- leases carry a residual, loans never do
    CHECK ((product = 'LEASE') = (residual_pct IS NOT NULL)),
    CHECK ((product = 'LEASE') = (residual_value IS NOT NULL)),
    -- closed contracts have a close date, open ones do not
    CHECK ((status = 'ACTIVE') = (close_date IS NULL))
);

CREATE TABLE payments (
    contract_id VARCHAR NOT NULL REFERENCES contracts (contract_id),
    installment INTEGER NOT NULL CHECK (installment >= 1),
    due_date    DATE    NOT NULL,
    amount_due  DOUBLE  NOT NULL,
    paid_date   DATE,
    amount_paid DOUBLE  NOT NULL,
    PRIMARY KEY (contract_id, installment)
);
