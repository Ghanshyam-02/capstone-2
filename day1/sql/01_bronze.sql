-- =====================================================================
-- 01_bronze.sql - schemas, BRONZE tables and AUDIT tables
-- BRONZE = the data exactly as received. Every column is text and nothing
-- is rejected here, so history can always be replayed.
-- (Safe to run again: everything is "IF NOT EXISTS".)
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;
CREATE SCHEMA IF NOT EXISTS audit;

-- Every loaded file gets a number (load_id). Later layers use it to find NEW rows.
CREATE SEQUENCE IF NOT EXISTS audit.load_id_seq;

CREATE TABLE IF NOT EXISTS bronze.merchant (
  merchant_id VARCHAR, merchant_name VARCHAR, merchant_category VARCHAR, country VARCHAR,
  risk_level VARCHAR, effective_from VARCHAR, effective_to VARCHAR,
  source_file VARCHAR, load_id INTEGER, load_ts TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS bronze.transactions (
  transaction_id VARCHAR, merchant_id VARCHAR, customer_id VARCHAR, transaction_ts VARCHAR,
  amount VARCHAR, currency VARCHAR, status VARCHAR, payment_channel VARCHAR,
  source_file VARCHAR, load_id INTEGER, load_ts TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS bronze.settlements (
  settlement_id VARCHAR, transaction_id VARCHAR, settlement_ts VARCHAR, settlement_amount VARCHAR,
  settlement_status VARCHAR, settlement_batch VARCHAR,
  source_file VARCHAR, load_id INTEGER, load_ts TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS bronze.payment_events (
  event_id VARCHAR, transaction_id VARCHAR, event_type VARCHAR, event_ts VARCHAR,
  ingestion_ts VARCHAR, processing_ms VARCHAR,
  source_file VARCHAR, load_id INTEGER, load_ts TIMESTAMP DEFAULT current_timestamp
);

-- ---------------------------------------------------------------------
-- AUDIT
-- ---------------------------------------------------------------------

-- Which files are already loaded (so a file is never loaded twice).
CREATE TABLE IF NOT EXISTS audit.loaded_files (
  file_name  VARCHAR PRIMARY KEY,
  load_id    INTEGER NOT NULL,
  row_count  INTEGER,
  loaded_at  TIMESTAMP DEFAULT current_timestamp
);

-- Incremental processing: the last load_id each layer has already processed.
CREATE TABLE IF NOT EXISTS audit.watermark (
  layer         VARCHAR PRIMARY KEY,      -- silver / gold
  last_load_id  INTEGER NOT NULL
);
INSERT OR IGNORE INTO audit.watermark VALUES ('silver', 0), ('gold', 0);

-- Invalid records never disappear: every rejected / quarantined / warning row lands here.
CREATE TABLE IF NOT EXISTS audit.dq_log (
  run_id      VARCHAR NOT NULL,
  source      VARCHAR NOT NULL,           -- transactions / settlements / ...
  record_key  VARCHAR,                    -- id of the bad record (if it had one)
  severity    VARCHAR NOT NULL,           -- REJECT / QUARANTINE / WARNING
  reason      VARCHAR NOT NULL,           -- e.g. MISSING_MERCHANT_ID
  raw_record  VARCHAR,                    -- the original row as JSON (customer id left out)
  logged_at   TIMESTAMP DEFAULT current_timestamp
);

-- Monitoring: one row per pipeline run.
CREATE TABLE IF NOT EXISTS audit.pipeline_runs (
  run_id            VARCHAR PRIMARY KEY,
  started_at        TIMESTAMP DEFAULT current_timestamp,
  finished_at       TIMESTAMP,
  status            VARCHAR,              -- RUNNING / SUCCESS / FAILED
  files_loaded      INTEGER,
  rows_quarantined  INTEGER,
  rows_rejected     INTEGER,
  error_message     VARCHAR
);
