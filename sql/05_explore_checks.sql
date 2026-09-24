-- =====================================================================
-- 05_explore_checks.sql - paste these into Snowsight one at a time to
-- SEE what the pipeline did. (Role: SYSADMIN or ACCOUNTADMIN)
-- =====================================================================
USE DATABASE SETTLEMENT_DB;
USE WAREHOUSE SETTLE_WH;

-- A. Pipeline runs (monitoring)
SELECT * FROM AUDIT.PIPELINE_RUNS ORDER BY STARTED_AT DESC;

-- B. Row counts per layer
SELECT 'bronze' AS layer, COUNT(*) FROM BRONZE.TRANSACTIONS
UNION ALL SELECT 'silver', COUNT(*) FROM SILVER.TRANSACTIONS
UNION ALL SELECT 'gold',   COUNT(*) FROM GOLD.FACT_TRANSACTION;

-- C. Nothing disappeared silently: every bad row is here with a reason
SELECT SOURCE, SEVERITY, REASON, COUNT(*) FROM AUDIT.DQ_LOG GROUP BY 1, 2, 3 ORDER BY 1, 2;
SELECT * FROM AUDIT.DQ_LOG WHERE SEVERITY = 'QUARANTINE' LIMIT 20;

-- D. Issue 1 - one-to-many settlement (T1001 = 8,000 + 2,000)
SELECT * FROM GOLD.FACT_SETTLEMENT WHERE TRANSACTION_ID = 'T1001';
SELECT * FROM GOLD.V_TXN_SETTLEMENT WHERE TRANSACTION_ID = 'T1001';
--    The WRONG way (direct join) - see the amount counted twice:
SELECT SUM(t.AMOUNT) AS wrong_total_amount
FROM GOLD.FACT_TRANSACTION t JOIN GOLD.FACT_SETTLEMENT s ON s.TRANSACTION_ID = t.TRANSACTION_ID
WHERE t.TRANSACTION_ID = 'T1001';

-- E. Issue 2 + 3 - late and out-of-order events
SELECT TRANSACTION_ID, EVENT_SEQ, EVENT_TYPE, EVENT_TS, INGESTION_TS, INGESTION_DELAY_SEC, IS_LATE
FROM GOLD.FACT_PAYMENT_EVENT WHERE IS_LATE ORDER BY TRANSACTION_ID, EVENT_SEQ LIMIT 20;

-- F. Issue 4 - point-in-time risk (M101 is LOW until 14-Sep, HIGH from 15-Sep)
SELECT * FROM GOLD.DIM_MERCHANT WHERE MERCHANT_ID IN ('M100', 'M101') ORDER BY 2, EFFECTIVE_FROM;
SELECT TRANSACTION_TS::DATE, RISK_LEVEL_AT_TXN, COUNT(*)
FROM GOLD.FACT_TRANSACTION WHERE MERCHANT_ID = 'M101' GROUP BY 1, 2 ORDER BY 1;

-- G. The Head of Payments' question: WHY is there a gap?
SELECT SETTLEMENT_CLASS, COUNT(*) AS transactions, SUM(GAP_AMOUNT) AS gap_amount
FROM GOLD.V_TXN_SETTLEMENT
GROUP BY SETTLEMENT_CLASS ORDER BY gap_amount DESC;

-- H. Settlement exception report (unsettled / pending / partly settled / delayed)
SELECT EXCEPTION_TYPE, COUNT(*) AS transactions, SUM(GAP_AMOUNT) AS gap_amount
FROM GOLD.V_SETTLEMENT_EXCEPTIONS GROUP BY 1 ORDER BY 2 DESC;
SELECT * FROM GOLD.V_SETTLEMENT_EXCEPTIONS ORDER BY GAP_AMOUNT DESC LIMIT 50;

-- H2. Investigate delayed settlements: which merchants and which days are slow?
SELECT MERCHANT_ID, MERCHANT_NAME, COUNT(*) AS delayed, ROUND(AVG(SETTLEMENT_DELAY_MIN)) AS avg_delay_min
FROM GOLD.V_SETTLEMENT_EXCEPTIONS WHERE EXCEPTION_TYPE = 'DELAYED'
GROUP BY 1, 2 ORDER BY delayed DESC;
SELECT TRANSACTION_TS::DATE AS day, COUNT(*) AS delayed, ROUND(AVG(SETTLEMENT_DELAY_MIN)) AS avg_delay_min
FROM GOLD.V_SETTLEMENT_EXCEPTIONS WHERE EXCEPTION_TYPE = 'DELAYED'
GROUP BY 1 ORDER BY 1;      -- look at 15 Sep: the settlement incident

-- I. Watermarks (incremental processing)
SELECT * FROM AUDIT.WATERMARK;
