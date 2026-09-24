-- =====================================================================
-- 02_silver.sql - SILVER tables: validated, cleaned, typed, no duplicates.
-- PRIMARY KEY = no two rows with the same id (DuckDB enforces it).
-- load_id tells which Bronze load a row came from (used for incremental Gold).
-- =====================================================================

CREATE TABLE IF NOT EXISTS silver.merchant (
  merchant_id        VARCHAR NOT NULL,
  merchant_name      VARCHAR,
  merchant_category  VARCHAR,
  country            VARCHAR,
  risk_level         VARCHAR NOT NULL,
  effective_from     DATE    NOT NULL,
  effective_to       DATE,                         -- NULL = still active
  source_file        VARCHAR,
  load_id            INTEGER,
  PRIMARY KEY (merchant_id, effective_from)
);

CREATE TABLE IF NOT EXISTS silver.transactions (
  transaction_id   VARCHAR PRIMARY KEY,
  merchant_id      VARCHAR       NOT NULL,
  customer_id      VARCHAR,
  transaction_ts   TIMESTAMP     NOT NULL,         -- business time
  amount           DECIMAL(18,2) NOT NULL,
  currency         VARCHAR       NOT NULL,
  status           VARCHAR       NOT NULL,
  payment_channel  VARCHAR,
  source_file      VARCHAR,
  load_id          INTEGER
);

CREATE TABLE IF NOT EXISTS silver.settlements (
  settlement_id      VARCHAR PRIMARY KEY,
  transaction_id     VARCHAR       NOT NULL,
  settlement_ts      TIMESTAMP     NOT NULL,
  settlement_amount  DECIMAL(18,2) NOT NULL,
  settlement_status  VARCHAR       NOT NULL,
  settlement_batch   VARCHAR,
  source_file        VARCHAR,
  load_id            INTEGER
);

CREATE TABLE IF NOT EXISTS silver.payment_events (
  event_id             VARCHAR PRIMARY KEY,
  transaction_id       VARCHAR   NOT NULL,
  event_type           VARCHAR   NOT NULL,
  event_ts             TIMESTAMP NOT NULL,         -- business time: when it happened
  ingestion_ts         TIMESTAMP NOT NULL,         -- processing time: when we received it
  processing_ms        INTEGER,
  ingestion_delay_sec  INTEGER,
  is_late              BOOLEAN   NOT NULL,
  source_file          VARCHAR,
  load_id              INTEGER
);
