-- =====================================================================
-- 04_bronze_to_silver.sql - VALIDATE and CLEAN new Bronze rows.
--
-- For each source:
--   1. take only NEW rows (load_id > silver watermark)          -> incremental
--   2. clean values (trim, upper-case, convert to proper types)
--   3. give each row an "issue" (NULL = good row):
--        REJECT:...     unusable (no id, unreadable value, duplicate)
--        QUARANTINE:... suspicious, held for a human to review
--        WARNING:...    usable, but worth flagging (late event)
--   4. bad rows   -> audit.dq_log       (nothing disappears silently)
--      good rows  -> silver table       (INSERT OR REPLACE = latest version wins)
--
-- getvariable('run_id') is set by pipeline/run_pipeline.py before this runs.
-- =====================================================================

BEGIN TRANSACTION;

-- --------------------------------------------------------------- MERCHANT
CREATE OR REPLACE TEMP TABLE chk_merchant AS
SELECT *,
       CASE
         WHEN merchant_id IS NULL                            THEN 'REJECT:MISSING_MERCHANT_ID'
         WHEN eff_from IS NULL                               THEN 'REJECT:INVALID_EFFECTIVE_FROM'
         WHEN risk IS NULL OR risk NOT IN ('LOW', 'MEDIUM', 'HIGH') THEN 'QUARANTINE:INVALID_RISK_LEVEL'
       END AS issue
FROM (
  SELECT b.*,
         TRY_CAST(effective_from AS DATE) AS eff_from,
         TRY_CAST(effective_to AS DATE)   AS eff_to,
         UPPER(TRIM(risk_level))          AS risk
  FROM bronze.merchant b
  WHERE load_id > (SELECT last_load_id FROM audit.watermark WHERE layer = 'silver')
);

INSERT INTO audit.dq_log (run_id, source, record_key, severity, reason, raw_record)
SELECT getvariable('run_id'), 'merchant', merchant_id, split_part(issue, ':', 1), split_part(issue, ':', 2),
       to_json({merchant_id: merchant_id, risk_level: risk_level, effective_from: effective_from,
                source_file: source_file})
FROM chk_merchant WHERE issue IS NOT NULL;

INSERT OR REPLACE INTO silver.merchant
SELECT merchant_id, merchant_name, merchant_category, country, risk, eff_from, eff_to, source_file, load_id
FROM chk_merchant
WHERE issue IS NULL
QUALIFY row_number() OVER (PARTITION BY merchant_id, eff_from ORDER BY load_id DESC) = 1;

-- --------------------------------------------------------------- TRANSACTIONS
CREATE OR REPLACE TEMP TABLE chk_transactions AS
SELECT *,
       CASE
         WHEN transaction_id IS NULL                          THEN 'REJECT:MISSING_TRANSACTION_ID'
         WHEN ts IS NULL                                      THEN 'REJECT:INVALID_TIMESTAMP'
         WHEN amt IS NULL                                     THEN 'REJECT:INVALID_AMOUNT'
         WHEN mid IS NULL                                     THEN 'QUARANTINE:MISSING_MERCHANT_ID'
         WHEN mid NOT IN (SELECT merchant_id FROM silver.merchant) THEN 'QUARANTINE:UNKNOWN_MERCHANT'
         WHEN COALESCE(cur, '') <> 'INR'                      THEN 'QUARANTINE:INVALID_CURRENCY'
         WHEN amt <= 0                                        THEN 'QUARANTINE:NON_POSITIVE_AMOUNT'
         WHEN COALESCE(st, '') NOT IN ('SUCCESS', 'FAILED', 'REVERSED') THEN 'QUARANTINE:INVALID_STATUS'
       END AS issue
FROM (
  SELECT b.*,
         NULLIF(TRIM(merchant_id), '')          AS mid,
         TRY_CAST(transaction_ts AS TIMESTAMP)  AS ts,
         TRY_CAST(amount AS DECIMAL(18,2))      AS amt,
         UPPER(TRIM(currency))                  AS cur,     -- ' inr ' -> 'INR'
         UPPER(TRIM(status))                    AS st
  FROM bronze.transactions b
  WHERE load_id > (SELECT last_load_id FROM audit.watermark WHERE layer = 'silver')
);

INSERT INTO audit.dq_log (run_id, source, record_key, severity, reason, raw_record)
SELECT getvariable('run_id'), 'transactions', transaction_id, split_part(issue, ':', 1), split_part(issue, ':', 2),
       to_json({transaction_id: transaction_id, merchant_id: merchant_id, transaction_ts: transaction_ts,
                amount: amount, currency: currency, status: status, source_file: source_file})   -- no customer_id (PII)
FROM chk_transactions WHERE issue IS NOT NULL;

INSERT OR REPLACE INTO silver.transactions
SELECT transaction_id, mid, customer_id, ts, amt, cur, st, UPPER(TRIM(payment_channel)), source_file, load_id
FROM chk_transactions
WHERE issue IS NULL
QUALIFY row_number() OVER (PARTITION BY transaction_id ORDER BY load_id DESC) = 1;

-- --------------------------------------------------------------- SETTLEMENTS
CREATE OR REPLACE TEMP TABLE chk_settlements AS
SELECT *,
       CASE
         WHEN settlement_id IS NULL                           THEN 'REJECT:MISSING_SETTLEMENT_ID'
         WHEN ts IS NULL                                      THEN 'REJECT:INVALID_TIMESTAMP'
         WHEN amt IS NULL                                     THEN 'REJECT:INVALID_AMOUNT'
         WHEN amt < 0                                         THEN 'QUARANTINE:NEGATIVE_SETTLEMENT_AMOUNT'
         WHEN transaction_id IS NULL
              OR transaction_id NOT IN (SELECT transaction_id FROM silver.transactions)
                                                              THEN 'QUARANTINE:UNMATCHED_SETTLEMENT'
         WHEN COALESCE(st, '') NOT IN ('SETTLED', 'PENDING', 'FAILED') THEN 'QUARANTINE:INVALID_STATUS'
       END AS issue
FROM (
  SELECT b.*,
         TRY_CAST(settlement_ts AS TIMESTAMP)        AS ts,
         TRY_CAST(settlement_amount AS DECIMAL(18,2)) AS amt,
         UPPER(TRIM(settlement_status))              AS st
  FROM bronze.settlements b
  WHERE load_id > (SELECT last_load_id FROM audit.watermark WHERE layer = 'silver')
);

INSERT INTO audit.dq_log (run_id, source, record_key, severity, reason, raw_record)
SELECT getvariable('run_id'), 'settlements', settlement_id, split_part(issue, ':', 1), split_part(issue, ':', 2),
       to_json({settlement_id: settlement_id, transaction_id: transaction_id, settlement_ts: settlement_ts,
                settlement_amount: settlement_amount, settlement_status: settlement_status, source_file: source_file})
FROM chk_settlements WHERE issue IS NOT NULL;

-- A settlement can be sent again with a new status (PENDING -> SETTLED): the latest version wins.
INSERT OR REPLACE INTO silver.settlements
SELECT settlement_id, transaction_id, ts, amt, st, settlement_batch, source_file, load_id
FROM chk_settlements
WHERE issue IS NULL
QUALIFY row_number() OVER (PARTITION BY settlement_id ORDER BY load_id DESC) = 1;

-- --------------------------------------------------------------- PAYMENT EVENTS
CREATE OR REPLACE TEMP TABLE chk_events AS
SELECT *,
       CASE
         WHEN event_id IS NULL                                THEN 'REJECT:MISSING_EVENT_ID'
         WHEN ev_ts IS NULL OR in_ts IS NULL                  THEN 'REJECT:INVALID_TIMESTAMP'
         WHEN copy_no > 1                                     -- same id twice in this load
              OR event_id IN (SELECT event_id FROM silver.payment_events)   -- or loaded before
                                                              THEN 'REJECT:DUPLICATE_EVENT_ID'
         WHEN transaction_id IS NULL
              OR transaction_id NOT IN (SELECT transaction_id FROM silver.transactions)
                                                              THEN 'QUARANTINE:UNMATCHED_EVENT'
         WHEN delay_sec > 5 * 60                              THEN 'WARNING:LATE_EVENT'   -- arrived > 5 min late
       END AS issue
FROM (
  SELECT b.*,
         TRY_CAST(event_ts AS TIMESTAMP)      AS ev_ts,       -- business time
         TRY_CAST(ingestion_ts AS TIMESTAMP)  AS in_ts,       -- processing time
         date_diff('second', TRY_CAST(event_ts AS TIMESTAMP), TRY_CAST(ingestion_ts AS TIMESTAMP)) AS delay_sec,
         row_number() OVER (PARTITION BY event_id ORDER BY ingestion_ts) AS copy_no
  FROM bronze.payment_events b
  WHERE load_id > (SELECT last_load_id FROM audit.watermark WHERE layer = 'silver')
);

INSERT INTO audit.dq_log (run_id, source, record_key, severity, reason, raw_record)
SELECT getvariable('run_id'), 'payment_events', event_id, split_part(issue, ':', 1), split_part(issue, ':', 2),
       to_json({event_id: event_id, transaction_id: transaction_id, event_type: event_type, event_ts: event_ts,
                ingestion_ts: ingestion_ts, source_file: source_file})
FROM chk_events WHERE issue IS NOT NULL;

-- Good rows AND late rows (a warning) are kept.
INSERT INTO silver.payment_events
SELECT event_id, transaction_id, UPPER(TRIM(event_type)), ev_ts, in_ts,
       TRY_CAST(processing_ms AS INTEGER), delay_sec, delay_sec > 5 * 60, source_file, load_id
FROM chk_events
WHERE issue IS NULL OR issue LIKE 'WARNING:%';

-- --------------------------------------------------------------- WATERMARK
UPDATE audit.watermark
SET last_load_id = (SELECT COALESCE(MAX(load_id), 0) FROM audit.loaded_files)
WHERE layer = 'silver';

COMMIT;
