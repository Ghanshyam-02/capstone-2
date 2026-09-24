# Day 1 – Step-by-step guide with theory

Each phase has:
- **Theory to learn**: the ideas behind the step (what you explain in a review or interview)
- **Steps**: the exact commands
- **Check**: what you should see before moving on

Run every command in **VS Code → Terminal (PowerShell)**, inside the `day1` folder, with `(.venv)` active.

| Phase | Brief task |
|---|---|
| 0. Set up | – |
| 1. Specification | Task 1 |
| 2. Look at the data | – |
| 3. Data model | Task 2 |
| 4. Run the pipeline (Bronze → Silver → Gold) | Task 2 |
| 5. Explore the results | Task 2 |
| 6. Incremental processing | Task 2 |
| 7. API | Task 3 A/B |
| 8. Dashboard | Task 3 C |
| 9. Tests | Task 4 A/B/C |
| 10. Security | Task 4 D |
| 11. Docker & deployment design | Task 4 E |

At the end: a **checklist** mapping every requirement of the problem statement to where it is done.

---

## Phase 0: Set up

### Theory to learn
- **Virtual environment (`.venv`)**: a private folder of Python libraries for one project, so versions never clash with other projects.
- **`requirements.txt`**: the list of libraries the project needs. `requirements-dev.txt` adds the test tools.
- **`.env` file**: settings and secrets kept **outside** the code. It is git-ignored, so it never reaches GitHub.
- **DuckDB**: a SQL database that lives in **one file** on your computer. No server, account or password. It is built for analytics (fast GROUP BY / joins), like a mini data warehouse.

### Steps
```powershell
git pull
cd day1
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env
```
> If `activate` is blocked, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.
> If you already have a `.venv` in the repo root from before, you can delete it and create a new one here.

Open `.env` and set your own API key (any long random text). You can generate one with:
```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Check
The prompt starts with `(.venv)`, and `pip list` shows `duckdb` and `fastapi`.

---

## Phase 1: Specification (Task 1)

### Theory to learn
- **Specification first**: agree on *what* to build (KPIs, rules, "done") before writing code.
- **Business spec vs technical spec**: the business spec says *what and why* (problem, users, KPIs, rules). The technical spec says *how* (sources, storage, API, validation, monitoring, security).
- **Acceptance criteria**: testable statements of "done".
- **Gherkin (Given / When / Then)**: acceptance tests in plain English that business people can read. *Given* is the situation, *When* is the action, *Then* is the expected result.
- **Data-quality classes** (the brief asks you to decide them):

  | Class | Meaning | Example |
  |---|---|---|
  | Reject | unusable, drop and log | no id, unreadable date, duplicate event |
  | Quarantine | suspicious, hold for a human | missing merchant, invalid currency, negative settlement, orphan settlement |
  | Warning | usable but notable, keep and log | late event |
  | Business exception | data is fine, the *business outcome* is bad | successful payment never settled, or settled late |

### Steps
Read `00_problem_statement.pdf`, then `docs/01_business_spec.md`, `docs/02_technical_spec.md` and `docs/03_acceptance.feature`.

### Check
You can explain why a negative settlement is *quarantined* (it may be a refund, so a human decides) rather than *rejected*.

---

## Phase 2: Look at the data

### Theory to learn
- **Test data**: the brief gives only column lists, so realistic CSV files are provided. Every hidden problem from the brief is planted in them **on purpose**, so we can prove the pipeline handles it.
- `data/raw/` holds batch 1 (September 2026), which the pipeline loads. `data/incoming/` holds batch 2 (1 Oct 2026), kept aside for the incremental demo in Phase 6.

| File | Rows |
|---|---|
| `data/raw/merchant_001.csv` | 31 (25 merchants + risk history) |
| `data/raw/transactions_001.csv` | 3,830 |
| `data/raw/settlements_001.csv` | 3,641 |
| `data/raw/payment_events_001.csv` | 10,833 |
| `data/incoming/*_002.csv` | 120 / 123 / 333 |

| Hidden problem | Where it is in the data |
|---|---|
| One-to-many settlement | `T1001`: 10,000 settled as 8,000 + 2,000 |
| Late event | `E1LATE01`: happened 10:02:15, received 10:08:41 |
| Out-of-order events | rows shuffled. T1001 arrives SETTLED → AUTHORIZED → CREATED |
| Risk history | M100 LOW → HIGH → MEDIUM. M101 LOW → HIGH on 15 Sep |
| Settlement incident | 15 Sep: many settlements late or pending |
| Abnormal merchants | M104, M108, M117 often unsettled. M110, M121 settle late |
| Dirty data | missing/unknown merchant, invalid currency, negative settlement, orphan settlement, duplicate events, bad timestamp |

### Steps
Open `data/raw/transactions_001.csv` in VS Code or Excel and look around.

### Check
You can find a row with an empty merchant_id, and `T1001`.

---

## Phase 3: Data model (Task 2)

### Theory to learn
- **Star schema**: *fact* tables in the middle (things you measure: transactions, settlements, events) and *dimension* tables around them (who / what / when: merchant, customer, date). Simple joins, fast reports.
- **Grain**: what **one row** of a table means. It is the most important modelling decision, and the brief makes it mandatory:
  - `fact_transaction`: one payment attempt
  - `fact_settlement`: one settlement record
  - `fact_payment_event`: one lifecycle event
  - `dim_merchant`: one merchant per risk period
- **Primary key (PK)**: uniquely identifies a row. **Foreign key (FK)**: points to a row in another table (a settlement points to its transaction). **CHECK**: a rule a value must pass (`settlement_amount >= 0`). DuckDB **enforces** all of them.
- **Surrogate key**: an internal number (`merchant_sk`) used instead of the business id, because one merchant id has several history rows.
- **SCD Type 2 (Slowly Changing Dimension)**: keep **history**. When a merchant's risk changes, add a new row with `effective_from` / `effective_to`. A February transaction joins to the row valid in February.
- **One-to-many trap**: joining a transaction (10,000) to its 2 settlements repeats the 10,000 twice, giving 20,000. The fix is to **sum settlements per transaction first**, then join (`gold.v_txn_settlement`).
- **Index**: a lookup structure that makes filters and joins faster (like a book index).
- **Staging table**: a landing table that holds raw data before it is cleaned. Our Bronze tables are the staging layer.

### Steps
Read `docs/04_data_model.md`, then `sql/01_bronze.sql`, `sql/02_silver.sql` and `sql/03_gold.sql`. Every table has its grain written above it.

### Check
You can draw the star: dim_date, dim_merchant and dim_customer around fact_transaction, with fact_settlement and fact_payment_event hanging off it.

---

## Phase 4: Run the pipeline, Bronze → Silver → Gold (Task 2)

### Theory to learn
- **Medallion architecture**:

  | Layer | Question | Rule |
  |---|---|---|
  | Bronze | What did we receive? | load everything as text, never reject, add file name + load id |
  | Silver | What can we trust? | validate, clean, remove duplicates, convert types. Bad rows go to `audit.dq_log` |
  | Gold | What does the business need? | star schema + KPI table |

  This is the brief's *Raw → Validation → Clean → Business transformation → Gold*.
- **ELT**: we **L**oad raw data first, then **T**ransform it with SQL inside the database. Python only orchestrates (runs the steps in order).
- **TRY_CAST**: converts text to a type, and returns NULL instead of crashing when the value is bad. That is how an unreadable date becomes a REJECT instead of breaking the pipeline.
- **UPSERT** (`INSERT ... ON CONFLICT DO UPDATE`, `INSERT OR REPLACE`): insert new rows, update existing ones. Running it twice gives the same result, which is called **idempotent**.
- **Transaction (BEGIN / COMMIT)**: many statements that succeed or fail **together**. If Silver fails half-way, nothing is saved.
- **Business time vs processing time**: `event_ts` is when it *happened* (used for reports and ordering). `ingestion_ts` is when *we received it* (used to detect late events).
- **Window function** (`row_number() OVER (PARTITION BY ... ORDER BY ...)`): numbers rows inside groups. Used to find duplicates and to order events.
- **"Invalid records should not silently disappear"**: every bad row is written to `audit.dq_log` with its reason.

### Steps
```powershell
python -m pipeline.run_pipeline
```

### Check
```
1) INGESTION -> BRONZE
  [bronze] merchant_001.csv: 31 rows loaded
  [bronze] transactions_001.csv: 3,830 rows loaded
  ...
2) BRONZE -> SILVER (validate / clean / de-duplicate)
  [silver] quarantined=158 rejected=28 warnings=372  (details: audit.dq_log)
3) SILVER -> GOLD (star schema + KPI table)
  [gold] fact_transaction: 3,800 rows
  ...
```
The file `data/warehouse/settlement.duckdb` now exists: that is your database.

---

## Phase 5: Explore the results

### Theory to learn
- **Explain the numbers with SQL**: every claim ("T1001 counted once", "15 Sep was slow") can be proved by a query. This is the habit Day 2 asks for: *prove it worked*.
- **View**: a saved query that behaves like a table (`gold.v_txn_settlement`, `gold.v_settlement_exceptions`).

### Steps
Run all the explore queries:
```powershell
python -m common.query sql/06_explore.sql
```
Or run any single query:
```powershell
python -m common.query "SELECT * FROM audit.dq_log LIMIT 5"
```

### Check
| Query | What you see |
|---|---|
| C | every bad row type with its count (nothing lost) |
| D / D2 / D3 | T1001 = 8,000 + 2,000 → settled 10,000 counted once. The wrong join gives 20,000 |
| E | T1001's events in business order, with the late one flagged |
| F / F2 | M101 is LOW until 14 Sep and HIGH from 15 Sep, and its transactions follow that |
| G | **why the gap exists**: unsettled ₹14.07 L, pending ₹8.10 L, partly settled ₹3.79 L |
| H / H2 / H3 | exception report, the slowest merchants, and the 15 Sep spike |
| I | KPIs: rate 93.72 %, gap ₹25.95 L, SLA 77.09 % |

---

## Phase 6: Incremental processing (Task 2)

### Theory to learn
- **Incremental vs full reload**: process only *new* data, which is faster and cheaper than reprocessing everything each run.
- **File tracking**: `audit.loaded_files` remembers which files were loaded, so a file is never loaded twice.
- **Watermark**: `audit.watermark` stores the last `load_id` each layer has processed. The next run only takes rows with a higher `load_id`.
- **Partial recalculation**: the KPI table is recalculated only for dates that received new data.

### Steps
```powershell
python -m pipeline.run_pipeline
copy data\incoming\*.csv data\raw\
python -m pipeline.run_pipeline
python -m common.query "SELECT * FROM audit.watermark"
```

### Check
- The first run says `Done: 0 new file(s) processed.`
- After copying, only the three `*_002.csv` files load.
- Batch 2 also completes 20 settlements that were PENDING in batch 1 (same settlement id, now SETTLED), so September's settlement rate rises from 93.72 % to about 94.1 %.

> To start again from zero: delete the `data\warehouse` folder and the `*_002.csv` files in `data\raw`, then run the pipeline.

---

## Phase 7: API (Task 3 A/B)

### Theory to learn
- **REST API**: programs ask for data over HTTP (`GET /api/v1/settlement-summary?start_date=...`) and get JSON back.
- **FastAPI**: a Python framework. A decorated function becomes an endpoint.
- **Pydantic**: defines the exact shape of the response (the **contract**) and validates it, e.g. `settlement_rate` must be between 0 and 100.
- **OpenAPI**: machine-readable API documentation. FastAPI generates it automatically at `/docs`.
- **HTTP status codes**: 200 OK · 400 bad request (invalid date) · 401 missing or wrong API key · 404 unknown merchant · 422 invalid parameter.
- **Repository pattern**: all SQL lives in `api/repository.py`, and the endpoints never write SQL.
- **Pre-aggregation**: the API reads the small `agg_merchant_daily` table, so it answers in milliseconds.

### Steps
```powershell
uvicorn api.main:app --reload
```
Open http://localhost:8000/docs. Then, in a **second** terminal:
```powershell
$h = @{ "X-API-Key" = "<API_KEY from your .env>" }
Invoke-RestMethod "http://localhost:8000/api/v1/settlement-summary?start_date=2026-09-01&end_date=2026-09-30" -Headers $h
Invoke-RestMethod "http://localhost:8000/api/v1/merchant-exceptions" -Headers $h
Invoke-RestMethod "http://localhost:8000/health"
```

### Check
The summary has the 6 fields from the brief plus `merchant_risk_count` (KPI 5). The exceptions list includes M104, M108, M117 (HIGH risk, low settlement rate) and M110, M121 (low SLA).

---

## Phase 8: Dashboard (Task 3 C)

### Theory to learn
- **The front-end consumes the API**: the page never reads CSVs or the database. There is one source of truth, and the same security rules apply to everyone.
- **`fetch()`**: the JavaScript function that calls the API.
- **Chart.js**: a library that draws charts from arrays of numbers.
- **Same origin**: FastAPI serves the HTML itself (at `/`), so the browser needs no extra CORS setup.

### Steps
With uvicorn running, open http://localhost:8000/, paste your API key, and click **Load**.

### Check
You see 6 KPI cards, the daily chart (look for the dip on 15 Sep), the top-10 gap chart (M117, M108 on top), and the merchant table. Values below target are shown in red.

---

## Phase 9: Tests (Task 4 A/B/C)

### Theory to learn
- **Unit test**: tests one small piece in isolation (a KPI formula). Very fast.
- **Business-rule test**: feeds a few hand-written rows through the real pipeline and checks the result (e.g. "a negative settlement is quarantined").
- **TDD (Test-Driven Development)**: write the test first, see it fail, write the code, see it pass.
- **Data-model tests** on the full dataset:
  - *grain*: no duplicate keys
  - *referential integrity*: no orphans
  - *reconciliation*: successful = settled + unsettled, and the KPI table matches the facts
- **Contract test**: checks the API keeps its promise (status codes, fields, 0 ≤ rate ≤ 100, response time).
- **Negative test**: proves something wrong does **not** happen, e.g. multiple settlements must not push the rate above 100 %.
- **Fixture** (pytest): prepared test setup that tests reuse, e.g. a database built in a temporary folder.

| File | Covers |
|---|---|
| `tests/test_unit_kpi.py` | settlement rate, gap, SLA, merchant exception logic |
| `tests/test_business_rules.py` | success, failed, duplicate event, missing merchant, invalid currency, unmatched and negative settlement, late event, out-of-order events, settlement calculation, **multiple settlements (negative test)**, SLA |
| `tests/test_pipeline.py` | re-run changes nothing, a new batch is incremental, PENDING → SETTLED |
| `tests/test_data_model.py` | grain, duplicates, referential integrity, reconciliation, invalid data handling, SCD2 |
| `tests/test_api.py` | 200 / 400 / 404 / 422, values match the database, < 500 ms |
| `tests/test_security.py` | 401, SQL injection, read-only database, no hard-coded secrets, no customer ids |

### Steps
```powershell
pytest -v
```
The tests build their own temporary databases, so your `data/warehouse` database is never touched.

### Check
`46 passed`. Try breaking something (e.g. change `1800` to `18` in `sql/03_gold.sql`) and watch the tests fail. That is the safety net working.

---

## Phase 10: Security (Task 4 D)

### Theory to learn
- **SQL injection**: if user input is pasted into SQL text, an attacker can send `x' OR '1'='1` and read everything. The fix is **bind parameters**, `execute("... WHERE merchant_id = ?", [merchant_id])`: the value is sent separately and is never treated as SQL.
- **Input validation**: `merchant_id` must match `^M\d{3,6}$`, or the API returns 422 before any SQL runs.
- **Authentication vs authorization**: *authentication* is **who** you are (the API key). *Authorization* is **what** you may do (the API opens the database **read-only**, so it can never change data).
- **Secrets management**: no keys or passwords in code. Use `.env` locally and CI variables in pipelines, and keep both out of Git and Docker images.
- **PII (personal data)**: store only a hash of customer ids, and never return or log them.
- **Minimal logging**: log what happened (endpoint, status, counts), never the data itself.

### Steps
Read `docs/05_security.md`. Then, with the API running, try the injection attack. It returns 422:
```powershell
Invoke-RestMethod "http://localhost:8000/api/v1/settlement-summary?start_date=2026-09-01&end_date=2026-09-30&merchant_id=M100'%20OR%20'1'='1" -Headers $h
```

### Check
You can point to where each of the brief's 6 security risks is handled.

---

## Phase 11: Docker & deployment design (Task 4 E)

### Theory to learn
- **Docker image vs container**: an *image* is a packaged app (OS + Python + libraries + code + data). A *container* is a running image. The same image runs identically everywhere.
- **Dockerfile**: the recipe for the image. Ours installs the requirements, copies the code and CSVs, and **builds the database inside the image**.
- **CI/CD**: *Continuous Integration* runs tests and scans on every push. *Continuous Delivery* promotes the same image DEV → TEST → PROD, with a manual approval for PROD.
- **Health check**: `/health` tells the platform whether the app is alive.
- **Smoke test**: one quick real call after each deploy.
- **Rollback**: each version is its own image tag, so rolling back means starting the previous image.

### Steps
Read `docs/06_deployment.md` and `.gitlab-ci.yml` (the Day 1 design).
If Docker Desktop is installed:
```powershell
docker build -t settlement-api:1.0 .
docker run -p 8000:8000 -e API_KEY=my-key settlement-api:1.0
```
(Docker is covered properly on Day 2.)

### Check
You can explain the path: push → tests → scans → image → DEV → TEST → PROD, plus health check, smoke test and rollback.

---

## Checklist against the problem statement

### Business goals (section 1)
| Operations must be able to… | Where |
|---|---|
| View payment and settlement performance | dashboard + `/settlement-summary` |
| Identify settlement gaps | KPI 3, top-10 gap chart, `gold.v_txn_settlement`, explore query G |
| Investigate delayed settlements | `settlement_delay_min`, `gold.v_settlement_exceptions` (DELAYED), queries H2 / H3 |
| Identify merchants with abnormal settlement behaviour | `/merchant-exceptions`, merchant table, KPI 5 |
| Expose the analytics through an API | `api/` |
| Consume the API through a web dashboard | `frontend/index.html` |
| Process new data incrementally | `audit.loaded_files` + `audit.watermark` + changed-dates rebuild (Phase 6) |
| Automatically test the implementation | `tests/` (46 tests) + test stage in `.gitlab-ci.yml` |

### Data and hidden problems (sections 2–3)
| Item | Where |
|---|---|
| 4 CSV files with the given columns | `data/raw`, `data/incoming` |
| Issue 1: one-to-many settlement | `gold.v_txn_settlement`, negative test |
| Issue 2: late events | `event_ts` vs `ingestion_ts`, `is_late`, LATE_EVENT warning |
| Issue 3: out-of-order events | `event_seq` by `event_ts` |
| Issue 4: merchant risk changes | SCD2 `gold.dim_merchant`, `risk_level_at_txn` |
| Issue 5: data-quality problems + their classification | `sql/04_bronze_to_silver.sql`, `docs/01_business_spec.md` |

### KPIs (section 4) and engineering (section 5)
| Item | Where |
|---|---|
| KPI 1–5 | `common/kpi.py`, `/settlement-summary`, dashboard |
| Layers Source → Ingestion → Bronze → Silver → Gold → API → Front-end | `pipeline/`, `sql/`, `api/`, `frontend/` |
| Incremental processing | Phase 6 |

### Task 1–4
| Item | Where |
|---|---|
| Business spec (problem, objective, users, KPIs, scope, assumptions, rules, acceptance criteria) | `docs/01_business_spec.md` |
| Technical spec (sources, fields, processing, storage, API, front-end, validation, monitoring, security) | `docs/02_technical_spec.md` |
| ≥ 5 Gherkin scenarios | `docs/03_acceptance.feature` (8) |
| Dimensions and facts, justified, grain of every fact | `sql/03_gold.sql`, `docs/04_data_model.md` |
| DDL, PK, FK, constraints, indexes, staging tables | `sql/01..03_*.sql` |
| Raw → Validation → Clean → Business transformation → Gold; invalid records never disappear | `sql/04`, `sql/05`, `audit.dq_log` |
| `/api/v1/settlement-summary`, `/api/v1/merchant-exceptions`, FastAPI, Pydantic, OpenAPI | `api/` |
| KPI cards, chart 1, chart 2, merchant table, uses the API only | `frontend/index.html` |
| Unit tests (8 cases from the brief) | `tests/test_business_rules.py` |
| Data-model tests: grain, referential integrity, reconciliation | `tests/test_data_model.py` |
| API contract tests: 200, 400, 404, 422, 0 ≤ rate ≤ 100 | `tests/test_api.py` |
| Security: injection, access, secrets, PII, logging, authorization | `docs/05_security.md`, `tests/test_security.py` |
| Deployment design: GitLab CI, DEV → TEST → PROD, config, secrets, health, smoke test, rollback | `.gitlab-ci.yml`, `docs/06_deployment.md`, `Dockerfile` |

---

## Troubleshooting
| Error | Fix |
|---|---|
| `No module named 'duckdb'` | activate `.venv` and run `pip install -r requirements-dev.txt` |
| `No module named 'pipeline'` | run commands from inside the `day1` folder |
| `settlement.duckdb not found` | run `python -m pipeline.run_pipeline` first |
| `Could not set lock on file` | another program has the database open (e.g. the API while running the pipeline). Stop uvicorn, then run the pipeline. |
| Dashboard shows `401` | paste the same `API_KEY` that is in `.env` |
