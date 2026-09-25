-- =====================================================================
-- 05_silver_to_gold.sql - build the GOLD star schema from SILVER.
-- Incremental: only Silver rows with load_id > gold watermark are used,
-- and only the affected dates of the KPI table are recalculated.
-- "INSERT ... ON CONFLICT DO UPDATE" = insert new rows, update existing ones
-- (an UPSERT), so running it again is safe.
-- =====================================================================

BEGIN TRANSACTION;

SET VARIABLE wm = (SELECT last_load_id FROM audit.watermark WHERE layer = 'gold');

-- 1. DIM_MERCHANT - SCD Type 2: one row per risk period (history comes from the source file)
INSERT INTO gold.dim_merchant
  (merchant_id, merchant_name, merchant_category, country, risk_level, effective_from, effective_to, is_current)
SELECT merchant_id, merchant_name, merchant_category, country, risk_level,
       effective_from, COALESCE(effective_to, DATE '9999-12-31'), FALSE
FROM silver.merchant
WHERE load_id > getvariable('wm')
ON CONFLICT (merchant_id, effective_from) DO UPDATE SET
  merchant_name = excluded.merchant_name, risk_level = excluded.risk_level, effective_to = excluded.effective_to;

UPDATE gold.dim_merchant SET is_current = (effective_to = DATE '9999-12-31');

-- 2. DIM_CUSTOMER - only a hash of the customer id is stored (PII)
INSERT OR IGNORE INTO gold.dim_customer
SELECT sha256(customer_id), MIN(CAST(transaction_ts AS DATE))
FROM silver.transactions
WHERE load_id > getvariable('wm') AND customer_id IS NOT NULL
GROUP BY 1;

-- 3. FACT_TRANSACTION - pick the merchant row whose risk period contains the transaction date
INSERT INTO gold.fact_transaction
SELECT t.transaction_id,
       CAST(strftime(t.transaction_ts, '%Y%m%d') AS INTEGER),
       m.merchant_sk,
       t.merchant_id,
       sha256(t.customer_id),
       t.transaction_ts, t.amount, t.currency, t.status, t.payment_channel,
       m.risk_level
FROM silver.transactions t
JOIN gold.dim_merchant m
  ON m.merchant_id = t.merchant_id
 AND CAST(t.transaction_ts AS DATE) BETWEEN m.effective_from AND m.effective_to
WHERE t.load_id > getvariable('wm')
ON CONFLICT (transaction_id) DO UPDATE SET
  status = excluded.status, amount = excluded.amount, risk_level_at_txn = excluded.risk_level_at_txn;

-- 4. FACT_SETTLEMENT - a settlement can change PENDING -> SETTLED, so existing rows are updated
INSERT INTO gold.fact_settlement
SELECT settlement_id, transaction_id, CAST(strftime(settlement_ts, '%Y%m%d') AS INTEGER),
       settlement_ts, settlement_amount, settlement_status, settlement_batch
FROM silver.settlements
WHERE load_id > getvariable('wm')
ON CONFLICT (settlement_id) DO UPDATE SET
  settlement_ts = excluded.settlement_ts, settlement_amount = excluded.settlement_amount,
  settlement_status = excluded.settlement_status, settlement_batch = excluded.settlement_batch;

-- 5. FACT_PAYMENT_EVENT - events never change, so insert only
INSERT OR IGNORE INTO gold.fact_payment_event
SELECT event_id, transaction_id, CAST(strftime(event_ts, '%Y%m%d') AS INTEGER), event_type,
       event_ts, ingestion_ts, processing_ms, ingestion_delay_sec, is_late, NULL
FROM silver.payment_events
WHERE load_id > getvariable('wm');

-- Out-of-order events: number them by BUSINESS time (event_ts), not by arrival order
UPDATE gold.fact_payment_event f
SET event_seq = x.seq
FROM (SELECT event_id, row_number() OVER (PARTITION BY transaction_id ORDER BY event_ts, event_id) AS seq
      FROM gold.fact_payment_event) x
WHERE f.event_id = x.event_id;

-- 6. KPI table - recalculate only the transaction dates that received new data
CREATE OR REPLACE TEMP TABLE changed_dates AS
SELECT DISTINCT CAST(transaction_ts AS DATE) AS d FROM silver.transactions WHERE load_id > getvariable('wm')
UNION
SELECT DISTINCT CAST(t.transaction_ts AS DATE)
FROM silver.settlements s JOIN silver.transactions t ON t.transaction_id = s.transaction_id
WHERE s.load_id > getvariable('wm');

DELETE FROM gold.agg_merchant_daily WHERE txn_date IN (SELECT d FROM changed_dates);

-- ⚠️ INJECTED DEFECT A (grain): Version 2 "simplified" the settled amount by joining
--    FACT_TRANSACTION to FACT_SETTLEMENT BEFORE aggregating. A transaction with two
--    settlement rows (8,000 + 2,000) now adds its full amount TWICE -> settled amount
--    inflated -> settlement rate above 100 %.
INSERT INTO gold.agg_merchant_daily
SELECT d.txn_date, d.merchant_id, d.merchant_name, d.risk_level, d.success_count, d.success_amount,
       COALESCE(s.settled_amount, 0), d.sla_met_count
FROM (SELECT txn_date, merchant_id, MAX(merchant_name) AS merchant_name, MAX(risk_level) AS risk_level,
             COUNT(*) AS success_count, SUM(amount) AS success_amount, SUM(sla_met) AS sla_met_count
      FROM gold.v_txn_settlement
      WHERE txn_date IN (SELECT d FROM changed_dates)
      GROUP BY txn_date, merchant_id) d
LEFT JOIN (SELECT CAST(t.transaction_ts AS DATE) AS txn_date, t.merchant_id, SUM(t.amount) AS settled_amount
           FROM gold.fact_transaction t
           JOIN gold.fact_settlement s ON s.transaction_id = t.transaction_id      -- join BEFORE aggregation
           WHERE t.status = 'SUCCESS' AND s.settlement_status = 'SETTLED'
           GROUP BY 1, 2) s
  ON s.txn_date = d.txn_date AND s.merchant_id = d.merchant_id;

-- 7. Remember how far Gold got
UPDATE audit.watermark
SET last_load_id = (SELECT last_load_id FROM audit.watermark WHERE layer = 'silver')
WHERE layer = 'gold';

COMMIT;
