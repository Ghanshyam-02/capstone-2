-- =====================================================================
-- 06_explore.sql - queries to SEE what the pipeline did.
-- Run all:  python -m common.query sql/06_explore.sql
-- Run one:  python -m common.query "SELECT ..."
-- =====================================================================

-- A. Pipeline runs (monitoring)
SELECT run_id, started_at, status, files_loaded, rows_quarantined, rows_rejected FROM audit.pipeline_runs ORDER BY started_at;

-- B. Row counts per layer (Bronze -> Silver -> Gold)
SELECT 'bronze' AS layer, COUNT(*) AS transactions FROM bronze.transactions
UNION ALL SELECT 'silver', COUNT(*) FROM silver.transactions
UNION ALL SELECT 'gold', COUNT(*) FROM gold.fact_transaction;

-- C. Nothing disappeared silently: every bad row is logged with a reason
SELECT source, severity, reason, COUNT(*) AS records FROM audit.dq_log GROUP BY ALL ORDER BY source, severity;

-- D. Issue 1 - one-to-many settlement: T1001 = 8,000 + 2,000
SELECT transaction_id, settlement_id, settlement_amount, settlement_status FROM gold.fact_settlement WHERE transaction_id = 'T1001';

-- D2. Correct: settlements summed per transaction FIRST (counted once)
SELECT transaction_id, amount, settled_amount, settlement_records FROM gold.v_txn_settlement WHERE transaction_id = 'T1001';

-- D3. WRONG: direct join repeats the transaction amount once per settlement row
SELECT SUM(t.amount) AS wrong_total_amount FROM gold.fact_transaction t JOIN gold.fact_settlement s USING (transaction_id) WHERE t.transaction_id = 'T1001';

-- E. Issues 2 + 3 - late and out-of-order events (T1001 arrived SETTLED, AUTHORIZED, CREATED)
SELECT transaction_id, event_seq, event_type, event_ts, ingestion_ts, ingestion_delay_sec, is_late FROM gold.fact_payment_event WHERE transaction_id = 'T1001' ORDER BY event_seq;

-- F. Issue 4 - point-in-time risk: M101 is LOW until 14 Sep, HIGH from 15 Sep
SELECT merchant_sk, merchant_id, risk_level, effective_from, effective_to, is_current FROM gold.dim_merchant WHERE merchant_id IN ('M100', 'M101') ORDER BY merchant_id, effective_from;

-- F2. Transactions of M101 use the risk that was valid on their date
SELECT CAST(transaction_ts AS DATE) AS day, risk_level_at_txn, COUNT(*) AS txns FROM gold.fact_transaction WHERE merchant_id = 'M101' AND transaction_ts BETWEEN '2026-09-12' AND '2026-09-18' GROUP BY ALL ORDER BY day;

-- G. The Head of Payments' question: WHY is there a gap?
SELECT settlement_class, COUNT(*) AS transactions, SUM(gap_amount) AS gap_amount FROM gold.v_txn_settlement GROUP BY ALL ORDER BY gap_amount DESC;

-- H. Settlement exception report by type (unsettled / pending / partly settled / delayed)
SELECT exception_type, COUNT(*) AS transactions, SUM(gap_amount) AS gap_amount, ROUND(AVG(settlement_delay_min)) AS avg_delay_min FROM gold.v_settlement_exceptions GROUP BY ALL ORDER BY transactions DESC;

-- H2. Investigate delayed settlements: which merchants are slow?
SELECT merchant_id, merchant_name, COUNT(*) AS delayed, ROUND(AVG(settlement_delay_min)) AS avg_delay_min FROM gold.v_settlement_exceptions WHERE exception_type = 'DELAYED' GROUP BY ALL ORDER BY delayed DESC LIMIT 10;

-- H3. Which days are slow? (look at 15 Sep: the settlement incident)
SELECT CAST(transaction_ts AS DATE) AS day, COUNT(*) AS delayed FROM gold.v_settlement_exceptions WHERE exception_type = 'DELAYED' GROUP BY ALL ORDER BY delayed DESC LIMIT 5;

-- I. KPIs for the whole period
SELECT SUM(success_count) AS transactions, SUM(success_amount) AS volume, ROUND(SUM(settled_amount) / SUM(success_amount) * 100, 2) AS settlement_rate, SUM(success_amount) - SUM(settled_amount) AS settlement_gap, ROUND(SUM(sla_met_count) / SUM(success_count) * 100, 2) AS sla_rate FROM gold.agg_merchant_daily;

-- J. Watermarks (incremental processing)
SELECT * FROM audit.watermark;
