-- =====================================================================
-- 03_gold_ddl.sql
-- GOLD = star schema (dimensions + facts) + pre-computed KPI table.
-- The GRAIN (what one row means) of every table is written above it.
-- =====================================================================

-- GRAIN: one row = one calendar day
CREATE TABLE IF NOT EXISTS GOLD.DIM_DATE (
  DATE_KEY    NUMBER(8)   NOT NULL PRIMARY KEY,   -- 20260901
  CAL_DATE    DATE        NOT NULL,
  YEAR        NUMBER(4)   NOT NULL,
  MONTH       NUMBER(2)   NOT NULL,
  DAY         NUMBER(2)   NOT NULL,
  DAY_NAME    VARCHAR(3)  NOT NULL,
  IS_WEEKEND  BOOLEAN     NOT NULL
);

INSERT INTO GOLD.DIM_DATE
SELECT TO_NUMBER(TO_CHAR(d, 'YYYYMMDD')), d, YEAR(d), MONTH(d), DAY(d), DAYNAME(d), DAYOFWEEKISO(d) >= 6
FROM (SELECT DATEADD(DAY, ROW_NUMBER() OVER (ORDER BY SEQ4()) - 1, '2025-01-01'::DATE) AS d
      FROM TABLE(GENERATOR(ROWCOUNT => 1096)))
WHERE (SELECT COUNT(*) FROM GOLD.DIM_DATE) = 0;

-- GRAIN: one row = one merchant for one risk period (SCD Type 2).
-- A merchant whose risk changed LOW -> HIGH -> MEDIUM has 3 rows.
CREATE TABLE IF NOT EXISTS GOLD.DIM_MERCHANT (
  MERCHANT_SK        NUMBER AUTOINCREMENT NOT NULL PRIMARY KEY,   -- surrogate key
  MERCHANT_ID        VARCHAR(20)  NOT NULL,                       -- business key
  MERCHANT_NAME      VARCHAR(200),
  MERCHANT_CATEGORY  VARCHAR(100),
  COUNTRY            VARCHAR(60),
  RISK_LEVEL         VARCHAR(10)  NOT NULL,
  EFFECTIVE_FROM     DATE         NOT NULL,
  EFFECTIVE_TO       DATE         NOT NULL,                       -- 9999-12-31 = open
  IS_CURRENT         BOOLEAN      NOT NULL,
  CONSTRAINT UQ_DIM_MERCHANT UNIQUE (MERCHANT_ID, EFFECTIVE_FROM)
);

-- GRAIN: one row = one customer. customer_id is hashed (PII minimisation).
CREATE TABLE IF NOT EXISTS GOLD.DIM_CUSTOMER (
  CUSTOMER_KEY     VARCHAR(64) NOT NULL PRIMARY KEY,   -- SHA2 of customer_id
  FIRST_SEEN_DATE  DATE
);

-- GRAIN: one row = one payment transaction attempt
CREATE TABLE IF NOT EXISTS GOLD.FACT_TRANSACTION (
  TRANSACTION_ID     VARCHAR(30)   NOT NULL PRIMARY KEY,
  DATE_KEY           NUMBER(8)     NOT NULL,
  MERCHANT_SK        NUMBER        NOT NULL,
  MERCHANT_ID        VARCHAR(20)   NOT NULL,
  CUSTOMER_KEY       VARCHAR(64),
  TRANSACTION_TS     TIMESTAMP_NTZ NOT NULL,
  AMOUNT             NUMBER(18,2)  NOT NULL,
  CURRENCY           VARCHAR(3)    NOT NULL,
  STATUS             VARCHAR(10)   NOT NULL,
  PAYMENT_CHANNEL    VARCHAR(10)   NOT NULL,
  RISK_LEVEL_AT_TXN  VARCHAR(10)   NOT NULL,   -- risk that was valid ON the transaction date
  UPDATED_AT         TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP(),
  CONSTRAINT FK_FT_DATE     FOREIGN KEY (DATE_KEY)     REFERENCES GOLD.DIM_DATE (DATE_KEY),
  CONSTRAINT FK_FT_MERCHANT FOREIGN KEY (MERCHANT_SK)  REFERENCES GOLD.DIM_MERCHANT (MERCHANT_SK),
  CONSTRAINT FK_FT_CUSTOMER FOREIGN KEY (CUSTOMER_KEY) REFERENCES GOLD.DIM_CUSTOMER (CUSTOMER_KEY)
);
-- Snowflake has no indexes. On big tables you would add a clustering key:
--   ALTER TABLE GOLD.FACT_TRANSACTION CLUSTER BY (DATE_KEY)
-- Not needed for our small data (and it costs credits).

-- GRAIN: one row = one settlement record (a transaction can have many)
CREATE TABLE IF NOT EXISTS GOLD.FACT_SETTLEMENT (
  SETTLEMENT_ID      VARCHAR(30)   NOT NULL PRIMARY KEY,
  TRANSACTION_ID     VARCHAR(30)   NOT NULL,
  DATE_KEY           NUMBER(8)     NOT NULL,
  SETTLEMENT_TS      TIMESTAMP_NTZ NOT NULL,
  SETTLEMENT_AMOUNT  NUMBER(18,2)  NOT NULL,
  SETTLEMENT_STATUS  VARCHAR(10)   NOT NULL,
  SETTLEMENT_BATCH   VARCHAR(30),
  UPDATED_AT         TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP(),
  CONSTRAINT FK_FS_TXN  FOREIGN KEY (TRANSACTION_ID) REFERENCES GOLD.FACT_TRANSACTION (TRANSACTION_ID),
  CONSTRAINT FK_FS_DATE FOREIGN KEY (DATE_KEY)       REFERENCES GOLD.DIM_DATE (DATE_KEY)
);

-- GRAIN: one row = one payment lifecycle event
CREATE TABLE IF NOT EXISTS GOLD.FACT_PAYMENT_EVENT (
  EVENT_ID             VARCHAR(30)   NOT NULL PRIMARY KEY,
  TRANSACTION_ID       VARCHAR(30)   NOT NULL,
  DATE_KEY             NUMBER(8)     NOT NULL,
  EVENT_TYPE           VARCHAR(15)   NOT NULL,
  EVENT_TS             TIMESTAMP_NTZ NOT NULL,
  INGESTION_TS         TIMESTAMP_NTZ NOT NULL,
  PROCESSING_MS        NUMBER,
  INGESTION_DELAY_SEC  NUMBER,
  IS_LATE              BOOLEAN       NOT NULL,
  EVENT_SEQ            NUMBER,        -- 1,2,3 in BUSINESS order (event_ts), not arrival order
  CONSTRAINT FK_FE_TXN  FOREIGN KEY (TRANSACTION_ID) REFERENCES GOLD.FACT_TRANSACTION (TRANSACTION_ID),
  CONSTRAINT FK_FE_DATE FOREIGN KEY (DATE_KEY)       REFERENCES GOLD.DIM_DATE (DATE_KEY)
);

-- GRAIN: one row = one merchant for one transaction date.
-- Small pre-computed table, so the API answers in milliseconds.
CREATE TABLE IF NOT EXISTS GOLD.AGG_MERCHANT_DAILY (
  TXN_DATE        DATE         NOT NULL,
  MERCHANT_ID     VARCHAR(20)  NOT NULL,
  MERCHANT_NAME   VARCHAR(200),
  RISK_LEVEL      VARCHAR(10),
  SUCCESS_COUNT   NUMBER,          -- successful transactions
  SUCCESS_AMOUNT  NUMBER(18,2),    -- KPI 1
  SETTLED_AMOUNT  NUMBER(18,2),    -- for KPI 2 and 3
  SLA_MET_COUNT   NUMBER,          -- for KPI 4
  CONSTRAINT PK_AGG_MERCHANT_DAILY PRIMARY KEY (TXN_DATE, MERCHANT_ID)
);

-- ---------------------------------------------------------------------
-- V_TXN_SETTLEMENT - GRAIN: one row = one transaction.
-- Solves the ONE-TO-MANY problem: settlements are SUMMED PER TRANSACTION
-- first (the "s" part), and only then joined. A direct join would repeat
-- the transaction amount once per settlement row.
-- Same logic as summarize_settlement() in pipeline/rules.py.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW GOLD.V_TXN_SETTLEMENT AS
WITH s AS (
  SELECT TRANSACTION_ID,
         SUM(IFF(SETTLEMENT_STATUS = 'SETTLED', SETTLEMENT_AMOUNT, 0)) AS SETTLED_RAW,
         MAX(IFF(SETTLEMENT_STATUS = 'SETTLED', SETTLEMENT_TS, NULL))  AS LAST_SETTLED_TS,
         COUNT_IF(SETTLEMENT_STATUS = 'PENDING')                       AS PENDING_CNT,
         COUNT(*)                                                      AS SETTLEMENT_RECORDS
  FROM GOLD.FACT_SETTLEMENT
  GROUP BY TRANSACTION_ID
)
SELECT t.TRANSACTION_ID,
       t.MERCHANT_ID,
       m.MERCHANT_NAME,
       t.RISK_LEVEL_AT_TXN                                    AS RISK_LEVEL,
       t.TRANSACTION_TS,
       t.TRANSACTION_TS::DATE                                 AS TXN_DATE,
       t.AMOUNT,
       t.STATUS,
       COALESCE(s.SETTLEMENT_RECORDS, 0)                      AS SETTLEMENT_RECORDS,
       LEAST(COALESCE(s.SETTLED_RAW, 0), t.AMOUNT)            AS SETTLED_AMOUNT,   -- never above 100%
       t.AMOUNT - LEAST(COALESCE(s.SETTLED_RAW, 0), t.AMOUNT) AS GAP_AMOUNT,
       CASE WHEN COALESCE(s.SETTLED_RAW, 0) >= t.AMOUNT THEN 'SETTLED'
            WHEN COALESCE(s.SETTLED_RAW, 0) > 0         THEN 'PARTIALLY_SETTLED'
            WHEN COALESCE(s.PENDING_CNT, 0) > 0         THEN 'PENDING'
            ELSE 'UNSETTLED' END                              AS SETTLEMENT_CLASS,
       DATEDIFF('minute', t.TRANSACTION_TS, s.LAST_SETTLED_TS)      AS SETTLEMENT_DELAY_MIN,
       IFF(COALESCE(s.SETTLED_RAW, 0) >= t.AMOUNT
           AND DATEDIFF('second', t.TRANSACTION_TS, s.LAST_SETTLED_TS) <= 1800, 1, 0) AS SLA_MET
FROM GOLD.FACT_TRANSACTION t
LEFT JOIN s                   ON s.TRANSACTION_ID = t.TRANSACTION_ID
LEFT JOIN GOLD.DIM_MERCHANT m ON m.MERCHANT_SK = t.MERCHANT_SK
WHERE t.STATUS = 'SUCCESS';          -- FAILED / REVERSED payments are never settled or counted

-- Settlement exception report: successful payments that are NOT settled,
-- only PARTLY settled, or settled LATE (after the 30-minute SLA = delayed settlement).
CREATE OR REPLACE VIEW GOLD.V_SETTLEMENT_EXCEPTIONS AS
SELECT TRANSACTION_ID, MERCHANT_ID, MERCHANT_NAME, RISK_LEVEL, TRANSACTION_TS,
       AMOUNT, SETTLED_AMOUNT, GAP_AMOUNT, SETTLEMENT_DELAY_MIN,
       IFF(SETTLEMENT_CLASS = 'SETTLED', 'DELAYED', SETTLEMENT_CLASS) AS EXCEPTION_TYPE
FROM GOLD.V_TXN_SETTLEMENT
WHERE SETTLEMENT_CLASS <> 'SETTLED' OR SLA_MET = 0;
