# 2. Technical Specification

## Architecture
```
CSV files ──PUT──▶ Snowflake stage ──COPY──▶ BRONZE ──Python rules──▶ SILVER ──SQL MERGE──▶ GOLD ──▶ FastAPI ──▶ HTML dashboard
                                                     └──▶ AUDIT.DQ_LOG (reject / quarantine / warning)
```

## Data sources
| File | Grain | Key |
|---|---|---|
| transactions_NNN.csv | one payment attempt | transaction_id |
| settlements_NNN.csv | one settlement record (many per transaction) | settlement_id |
| merchant_NNN.csv | one merchant risk period (history) | merchant_id + effective_from |
| payment_events_NNN.csv | one lifecycle event (can be late / out of order / duplicated) | event_id |

Fields: see the brief section 2; typed versions in `sql/02_silver_ddl.sql`.

## Processing
| Step | Where | What |
|---|---|---|
| Ingestion | `pipeline/ingest.py` | `PUT` files into `@BRONZE.RAW_STAGE`, `COPY INTO` Bronze tables. COPY skips files it already loaded. |
| Bronze | `sql/01_bronze_audit_ddl.sql` | All columns `VARCHAR` + `SOURCE_FILE` + `LOAD_TS`. Nothing is rejected. |
| Silver | `pipeline/silver.py` + `pipeline/rules.py` | Read rows newer than watermark → validate → de-duplicate → type → `MERGE`. Bad rows → `AUDIT.DQ_LOG`. Data + DQ log + watermark committed in one transaction. |
| Gold | `sql/04_gold_transform.sql` | SCD2 merchant dimension, facts with point-in-time risk, event sequencing by business time, `AGG_MERCHANT_DAILY` rebuilt only for affected dates. |
| Incremental | `AUDIT.WATERMARK` | One watermark per source file type + one for Gold. |

## Storage
Snowflake: database `SETTLEMENT_DB`, schemas `BRONZE`, `SILVER`, `GOLD`, `AUDIT`, warehouse `SETTLE_WH` (X-Small, auto-suspend 60 s).
Model details and grain: [04_data_model.md](04_data_model.md).

## API (FastAPI + Pydantic, OpenAPI docs at `/docs`)
| Endpoint | Purpose |
|---|---|
| `GET /api/v1/settlement-summary?start_date&end_date&merchant_id` | KPI 1-5 (asked in the brief) |
| `GET /api/v1/merchant-exceptions` | rate < 95 % OR SLA < 90 % (asked in the brief) |
| `GET /api/v1/daily-trend?start_date&end_date` | data for dashboard chart 1 |
| `GET /api/v1/merchants?start_date&end_date` | data for dashboard chart 2 + table |
| `GET /health` | health check for deployment |

Errors: 400 invalid date, 401 missing API key, 404 unknown merchant, 422 invalid parameter.

## Front-end
`frontend/index.html` – plain HTML + JavaScript + Chart.js, served by FastAPI at `/`. Reads **only** the API.

## Validation
Rules in `pipeline/rules.py` (see business spec table). Tests: `tests/unit` (rules, KPIs),
`tests/api` (contract), `tests/data_model` (grain, RI, reconciliation on Snowflake).

## Monitoring
- `AUDIT.PIPELINE_RUNS` – start/end/status/row counts/error per run.
- `AUDIT.DQ_LOG` – every bad record with its reason.
- `/health` endpoint for the container platform.

## Security
See [05_security.md](05_security.md): key-pair auth, least-privilege roles, API key, parameterised SQL,
PII hashing/masking, no secrets in Git, minimal logging.
