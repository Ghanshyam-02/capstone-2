# 2. Technical Specification

## Architecture
```
data/raw/*.csv ──read_csv──▶ BRONZE ──SQL rules──▶ SILVER ──SQL upsert──▶ GOLD ──▶ FastAPI ──▶ HTML dashboard
                                      └──▶ audit.dq_log (reject / quarantine / warning)
```
Database: **DuckDB**, a SQL database stored in one file (`data/warehouse/settlement.duckdb`).
Python runs the steps; all data logic is SQL in `sql/`.

## Data sources
| File | Grain | Key |
|---|---|---|
| transactions_NNN.csv | one payment attempt | transaction_id |
| settlements_NNN.csv | one settlement record (many per transaction) | settlement_id |
| merchant_NNN.csv | one merchant risk period (history) | merchant_id + effective_from |
| payment_events_NNN.csv | one lifecycle event (can be late / out of order / duplicated) | event_id |

## Fields (Silver types)
| File | Field → type |
|---|---|
| transactions | transaction_id VARCHAR · merchant_id VARCHAR · customer_id VARCHAR (hashed in Gold) · transaction_ts TIMESTAMP · amount DECIMAL(18,2) · currency = INR · status SUCCESS/FAILED/REVERSED · payment_channel POS/ONLINE/QR |
| settlements | settlement_id VARCHAR · transaction_id VARCHAR · settlement_ts TIMESTAMP · settlement_amount DECIMAL(18,2) ≥ 0 · settlement_status SETTLED/PENDING/FAILED · settlement_batch VARCHAR |
| merchant | merchant_id VARCHAR · merchant_name · merchant_category · country · risk_level LOW/MEDIUM/HIGH · effective_from DATE · effective_to DATE (empty = current) |
| payment_events | event_id VARCHAR · transaction_id VARCHAR · event_type CREATED/AUTHORIZED/SETTLED/FAILED · event_ts TIMESTAMP (business time) · ingestion_ts TIMESTAMP (processing time) · processing_ms INTEGER · + derived ingestion_delay_sec, is_late |

Every Bronze column is VARCHAR (raw). Types are applied in Silver.

## Processing
| Step | Where | What |
|---|---|---|
| Ingestion | `pipeline/ingest.py` | Each new CSV in `data/raw` is copied into its Bronze table as text, tagged with file name and `load_id`. `audit.loaded_files` stops a file being loaded twice. |
| Bronze → Silver | `sql/04_bronze_to_silver.sql` | New rows only (`load_id` > watermark). Clean, validate, de-duplicate. Bad rows → `audit.dq_log`. Good rows → Silver (latest version wins). One transaction. |
| Silver → Gold | `sql/05_silver_to_gold.sql` | SCD2 merchant dimension, facts with point-in-time risk, events ordered by business time, `agg_merchant_daily` rebuilt only for changed dates. |
| Incremental | `audit.loaded_files` + `audit.watermark` | Files loaded once. Silver and Gold only process new `load_id`s. |

## Storage
DuckDB schemas `bronze`, `silver`, `gold`, `audit` in one file. Model details and grain: [04_data_model.md](04_data_model.md).

## API (FastAPI + Pydantic, OpenAPI docs at `/docs`)
| Endpoint | Purpose |
|---|---|
| `GET /api/v1/settlement-summary?start_date&end_date&merchant_id` | KPI 1-5 (asked in the brief) |
| `GET /api/v1/merchant-exceptions` | rate < 95 % OR SLA < 90 % (asked in the brief) |
| `GET /api/v1/daily-trend?start_date&end_date` | data for dashboard chart 1 |
| `GET /api/v1/merchants?start_date&end_date` | data for dashboard chart 2 + table |
| `GET /health` | health check (database reachable + version) |

Errors: 400 invalid date, 401 missing API key, 404 unknown merchant, 422 invalid parameter.

## Front-end
`frontend/index.html` – plain HTML + JavaScript + Chart.js, served by FastAPI at `/`. Reads **only** the API.

## Validation
Rules in `sql/04_bronze_to_silver.sql` (see the business spec table). Tests in `tests/`: unit, business rules,
pipeline, data model, API, security (22 tests, all run locally in ~12 s).

## Monitoring
- `audit.pipeline_runs` – start/end/status/counts/error per run.
- `audit.dq_log` – every bad record with its reason.
- `/health` – database reachable + running version.

## Security
See [05_security.md](05_security.md): API key, read-only database for the API, parameterised SQL,
input validation, PII hashing, no secrets in Git, minimal logging.
