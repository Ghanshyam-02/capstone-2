-- =====================================================================
-- 03_gold.sql - GOLD star schema (dimensions + facts), KPI table, views.
-- The GRAIN (what one row means) of every table is written above it.
-- DuckDB ENFORCES primary keys, foreign keys and CHECK constraints.
-- =====================================================================

-- GRAIN: one row = one calendar day
CREATE TABLE IF NOT EXISTS gold.dim_date (
  date_key    INTEGER PRIMARY KEY,           -- 20260901
  cal_date    DATE    NOT NULL,
  year        INTEGER NOT NULL,
  month       INTEGER NOT NULL,
  day         INTEGER NOT NULL,
  day_name    VARCHAR NOT NULL,
  is_weekend  BOOLEAN NOT NULL
);

INSERT OR IGNORE INTO gold.dim_date
SELECT CAST(strftime(d, '%Y%m%d') AS INTEGER), d, year(d), month(d), day(d), dayname(d), isodow(d) >= 6
FROM (SELECT CAST(range AS DATE) AS d FROM range(DATE '2025-01-01', DATE '2028-01-01', INTERVAL 1 DAY));

-- GRAIN: one row = one merchant for one risk period (SCD Type 2).
-- A merchant whose risk changed LOW -> HIGH -> MEDIUM has 3 rows.
CREATE SEQUENCE IF NOT EXISTS gold.merchant_sk_seq;
CREATE TABLE IF NOT EXISTS gold.dim_merchant (
  merchant_sk        INTEGER PRIMARY KEY DEFAULT nextval('gold.merchant_sk_seq'),   -- surrogate key
  merchant_id        VARCHAR NOT NULL,                                               -- business key
  merchant_name      VARCHAR,
  merchant_category  VARCHAR,
  country            VARCHAR,
  risk_level         VARCHAR NOT NULL CHECK (risk_level IN ('LOW', 'MEDIUM', 'HIGH')),
  effective_from     DATE    NOT NULL,
  effective_to       DATE    NOT NULL,                                               -- 9999-12-31 = open
  is_current         BOOLEAN NOT NULL,
  UNIQUE (merchant_id, effective_from)
);

-- GRAIN: one row = one customer. Only a hash of customer_id is stored (PII).
CREATE TABLE IF NOT EXISTS gold.dim_customer (
  customer_key     VARCHAR PRIMARY KEY,      -- sha256(customer_id)
  first_seen_date  DATE
);

-- GRAIN: one row = one payment transaction attempt
CREATE TABLE IF NOT EXISTS gold.fact_transaction (
  transaction_id     VARCHAR PRIMARY KEY,
  date_key           INTEGER       NOT NULL REFERENCES gold.dim_date (date_key),
  merchant_sk        INTEGER       NOT NULL REFERENCES gold.dim_merchant (merchant_sk),
  merchant_id        VARCHAR       NOT NULL,
  customer_key       VARCHAR       REFERENCES gold.dim_customer (customer_key),
  transaction_ts     TIMESTAMP     NOT NULL,
  amount             DECIMAL(18,2) NOT NULL CHECK (amount > 0),
  currency           VARCHAR       NOT NULL CHECK (currency = 'INR'),
  status             VARCHAR       NOT NULL CHECK (status IN ('SUCCESS', 'FAILED', 'REVERSED')),
  payment_channel    VARCHAR,
  risk_level_at_txn  VARCHAR       NOT NULL     -- risk that was valid ON the transaction date
);
CREATE INDEX IF NOT EXISTS idx_fact_transaction_date ON gold.fact_transaction (date_key);
CREATE INDEX IF NOT EXISTS idx_fact_transaction_merchant ON gold.fact_transaction (merchant_id);

-- GRAIN: one row = one settlement record (a transaction can have many)
CREATE TABLE IF NOT EXISTS gold.fact_settlement (
  settlement_id      VARCHAR PRIMARY KEY,
  transaction_id     VARCHAR       NOT NULL REFERENCES gold.fact_transaction (transaction_id),
  date_key           INTEGER       NOT NULL REFERENCES gold.dim_date (date_key),
  settlement_ts      TIMESTAMP     NOT NULL,
  settlement_amount  DECIMAL(18,2) NOT NULL CHECK (settlement_amount >= 0),
  settlement_status  VARCHAR       NOT NULL,
  settlement_batch   VARCHAR
);
CREATE INDEX IF NOT EXISTS idx_fact_settlement_txn ON gold.fact_settlement (transaction_id);

-- GRAIN: one row = one payment lifecycle event
CREATE TABLE IF NOT EXISTS gold.fact_payment_event (
  event_id             VARCHAR PRIMARY KEY,
  transaction_id       VARCHAR   NOT NULL REFERENCES gold.fact_transaction (transaction_id),
  date_key             INTEGER   NOT NULL REFERENCES gold.dim_date (date_key),
  event_type           VARCHAR   NOT NULL,
  event_ts             TIMESTAMP NOT NULL,
  ingestion_ts         TIMESTAMP NOT NULL,
  processing_ms        INTEGER,
  ingestion_delay_sec  INTEGER,
  is_late              BOOLEAN   NOT NULL,
  event_seq            INTEGER               -- 1,2,3 in BUSINESS order (event_ts), not arrival order
);

-- GRAIN: one row = one merchant for one transaction date.
-- Small pre-calculated table, so the API answers in milliseconds.
CREATE TABLE IF NOT EXISTS gold.agg_merchant_daily (
  txn_date        DATE    NOT NULL,
  merchant_id     VARCHAR NOT NULL,
  merchant_name   VARCHAR,
  risk_level      VARCHAR,
  success_count   INTEGER,           -- successful transactions
  success_amount  DECIMAL(18,2),     -- KPI 1
  settled_amount  DECIMAL(18,2),     -- for KPI 2 and 3
  sla_met_count   INTEGER,           -- for KPI 4
  PRIMARY KEY (txn_date, merchant_id)
);

-- ---------------------------------------------------------------------
-- v_txn_settlement - GRAIN: one row = one SUCCESSFUL transaction.
-- Solves the ONE-TO-MANY problem: settlements are SUMMED PER TRANSACTION
-- first (the "s" part), and only then joined. A direct join would repeat
-- the transaction amount once per settlement row.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.v_txn_settlement AS
WITH s AS (
  SELECT transaction_id,
         SUM(CASE WHEN settlement_status = 'SETTLED' THEN settlement_amount ELSE 0 END) AS settled_raw,
         MAX(CASE WHEN settlement_status = 'SETTLED' THEN settlement_ts END)             AS last_settled_ts,
         count_if(settlement_status = 'PENDING')                                         AS pending_cnt,
         COUNT(*)                                                                        AS settlement_records
  FROM gold.fact_settlement
  GROUP BY transaction_id
)
SELECT t.transaction_id,
       t.merchant_id,
       m.merchant_name,
       t.risk_level_at_txn                                      AS risk_level,
       t.transaction_ts,
       CAST(t.transaction_ts AS DATE)                           AS txn_date,
       t.amount,
       COALESCE(s.settlement_records, 0)                        AS settlement_records,
       LEAST(COALESCE(s.settled_raw, 0), t.amount)              AS settled_amount,   -- never above 100%
       t.amount - LEAST(COALESCE(s.settled_raw, 0), t.amount)   AS gap_amount,
       date_diff('minute', t.transaction_ts, s.last_settled_ts) AS settlement_delay_min,
       CASE WHEN COALESCE(s.settled_raw, 0) >= t.amount THEN 'SETTLED'
            WHEN COALESCE(s.settled_raw, 0) > 0         THEN 'PARTIALLY_SETTLED'
            WHEN COALESCE(s.pending_cnt, 0) > 0         THEN 'PENDING'
            ELSE 'UNSETTLED' END                                AS settlement_class,
       CASE WHEN COALESCE(s.settled_raw, 0) >= t.amount
             AND date_diff('second', t.transaction_ts, s.last_settled_ts) <= 1800
            THEN 1 ELSE 0 END                                   AS sla_met
FROM gold.fact_transaction t
LEFT JOIN s                   ON s.transaction_id = t.transaction_id
LEFT JOIN gold.dim_merchant m ON m.merchant_sk = t.merchant_sk
WHERE t.status = 'SUCCESS';          -- FAILED / REVERSED payments are never settled or counted

-- Settlement exception report: successful payments NOT settled, only PARTLY
-- settled, PENDING, or settled LATE (after the 30-minute SLA = DELAYED).
CREATE OR REPLACE VIEW gold.v_settlement_exceptions AS
SELECT transaction_id, merchant_id, merchant_name, risk_level, transaction_ts,
       amount, settled_amount, gap_amount, settlement_delay_min,
       CASE WHEN settlement_class = 'SETTLED' THEN 'DELAYED' ELSE settlement_class END AS exception_type
FROM gold.v_txn_settlement
WHERE settlement_class <> 'SETTLED' OR sla_met = 0;
