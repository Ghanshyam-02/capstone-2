# Day 1 – Merchant Settlement Intelligence Platform

📄 Problem statement: [00_problem_statement.pdf](00_problem_statement.pdf)
👉 Step-by-step instructions with theory: **[GUIDE.md](GUIDE.md)**
🎤 Presentation / viva script with Q&A: **[VIVA_SCRIPT.md](VIVA_SCRIPT.md)**

---

## 1. The problem in one paragraph
Bank of New York processes card / QR / online payments for Indian merchants and then **settles** the money
(pays it to the merchant). The Head of Payments sees ₹48 Cr of successful payments but only ₹45.8 Cr settled,
and nobody can explain the gap, because the data sits in 4 separate systems and Operations only gets
nightly Excel reports. We must build a platform that **explains the gap**: which payments are not settled,
which are late, which merchants behave abnormally, and how much of it is bad data.

## 2. What the brief asks for
| Part | In simple words |
|---|---|
| Data | 4 CSV files: transactions, settlements, merchants (with risk history), payment events |
| Hidden problems | split settlements, late events, out-of-order events, changing merchant risk, dirty data |
| KPIs | volume, settlement rate, settlement gap, SLA (settled within 30 min), risky merchants |
| Architecture | Files → Ingestion → Bronze → Silver → Gold → API → Dashboard (not one big script) |
| Task 1 | Business spec, technical spec, at least 5 Gherkin scenarios |
| Task 2 | Star-schema data model with the grain of every table, DDL, keys, pipeline that never loses bad records, incremental loads |
| Task 3 | FastAPI endpoints `/settlement-summary` and `/merchant-exceptions`, HTML/JS dashboard |
| Task 4 | Unit, data-model and API tests, security review, deployment design |

## 3. What we built
```
data/raw/*.csv                                          (4 source files, Sep 2026)
      │  ① INGESTION  pipeline/ingest.py
      ▼
BRONZE   exact copy of every file (all text) + file name + load_id
      │  ② VALIDATE & CLEAN  sql/04_bronze_to_silver.sql
      ├──────────────▶ audit.dq_log   every bad row + reason (nothing is lost)
      ▼
SILVER   clean, typed, no duplicates
      │  ③ BUSINESS LOGIC  sql/05_silver_to_gold.sql
      ▼
GOLD     star schema: dim_date, dim_merchant (risk history), dim_customer,
         fact_transaction, fact_settlement, fact_payment_event
         + agg_merchant_daily (KPIs per merchant per day) + views
      │  ④ API  api/main.py (FastAPI, read-only)
      ▼
DASHBOARD  frontend/index.html (KPI cards, 2 charts, merchant table)
```
- **Database: DuckDB.** A real SQL database stored in one file (`data/warehouse/settlement.duckdb`).
  No server, account or password. Python runs the steps, and all the data logic is plain SQL in `sql/`.
- **Everything is automated and tested:** one command builds the database, and 46 tests check it.

## 4. How each hidden problem is solved
| Problem (brief) | Where in the data | Solution |
|---|---|---|
| **One transaction, many settlements** | `T1001` = 8,000 + 2,000 | Settlements are **summed per transaction first**, then joined (`gold.v_txn_settlement`). A direct join would count the 10,000 twice. |
| **Late events** | `E1LATE01`: happened 10:02:15, arrived 10:08:41 | Both times are kept. `event_ts` (business time) is used for reports, `ingestion_ts` (processing time) for lateness. Late = more than 5 min. |
| **Out-of-order events** | T1001's events arrive SETTLED → AUTHORIZED → CREATED | `event_seq` numbers events by `event_ts`, not arrival order |
| **Merchant risk changes** | M100 LOW→HIGH→MEDIUM, M101 LOW→HIGH on 15 Sep | **SCD Type 2** `dim_merchant`: one row per risk period. A transaction joins the row valid **on its date**. |
| **Dirty data** | missing / unknown merchant, bad currency, negative or orphan settlements, duplicate events, bad timestamps | Classified as **REJECT**, **QUARANTINE** or **WARNING** and written to `audit.dq_log` |
| **Payments never settled** | 162 unsettled, 97 pending, 85 partly settled | **Business exceptions** in `gold.v_settlement_exceptions` (also **DELAYED** = settled after 30 min) |

## 5. The answer it gives (batch 1, September 2026)
| KPI | Value |
|---|---|
| Successful transactions | 3,383 |
| Transaction volume | ₹4.13 Cr |
| Settlement rate | **93.72 %** (target 95 %) |
| Settlement gap | ₹25.95 lakh |
| SLA (settled ≤ 30 min) | **77.09 %** (target 90 %) |
| Risky merchants (rate < 95 % AND SLA < 90 %) | 5 |

**Why is there a gap?** ₹14.07 lakh was never settled, ₹8.10 lakh is still pending, and ₹3.79 lakh was only
partly settled. The biggest gaps are at M117, M108 and M104 (all HIGH risk). Delays spike on **15 Sep**
(a settlement incident), and M110 / M121 settle but always late.
On the data side, 30 transactions, 45 settlements and 83 events were held back as bad data, and 28 rows
were rejected. All of them are listed in `audit.dq_log`.

## 6. Folder map
| Path | What | Brief task |
|---|---|---|
| `docs/01_business_spec.md` | problem, users, KPIs, rules, acceptance criteria | Task 1 |
| `docs/02_technical_spec.md` | sources, fields, processing, API, monitoring, security | Task 1 |
| `docs/03_acceptance.feature` | 8 Gherkin scenarios | Task 1 |
| `docs/04_data_model.md` | star schema, grain, keys, why | Task 2 |
| `data/raw/`, `data/incoming/` | source CSVs (batch 1, and batch 2 for the incremental demo) | – |
| `sql/01..03_*.sql` | tables (DDL): Bronze, Silver, Gold, Audit | Task 2 |
| `sql/04_bronze_to_silver.sql` | data-quality rules | Task 2 |
| `sql/05_silver_to_gold.sql` | star schema + KPIs (incremental) | Task 2 |
| `sql/06_explore.sql` | queries that show every result above | – |
| `pipeline/` | `ingest.py` (files → Bronze), `run_pipeline.py` (runs everything) | Task 2 |
| `common/` | settings, database connection, KPI formulas, query tool | – |
| `api/` | FastAPI endpoints, response models, API key, SQL queries | Task 3 |
| `frontend/index.html` | dashboard | Task 3 |
| `tests/` | 46 tests: unit, business rules, pipeline, data model, API, security | Task 4 |
| `docs/05_security.md`, `docs/06_deployment.md`, `Dockerfile`, `.gitlab-ci.yml` | security and deployment | Task 4 |

## 7. Run it
```powershell
cd day1
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env
python -m pipeline.run_pipeline
python -m common.query sql/06_explore.sql
pytest
uvicorn api.main:app --reload
```
Details for every step, and the theory behind it, are in [GUIDE.md](GUIDE.md).
