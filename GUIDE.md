# Step-by-step guide with theory

Each phase has:
- **Theory to learn**: the ideas behind the step (what you explain in a review or interview)
- **Steps**: the exact commands
- **Check**: what you should see before moving on

Commands are for **Windows PowerShell** (in VS Code: *Terminal → New Terminal*).

| Phase | Brief task |
|---|---|
| 0. Set up Python | – |
| 1. Set up Snowflake | – |
| 2. Specification | Task 1 |
| 3. Look at the data | – |
| 4. Data model | Task 2 |
| 5. Pipeline: Bronze → Silver → Gold | Task 2 |
| 6. Incremental processing | Task 2 |
| 7. API | Task 3 A/B |
| 8. Dashboard | Task 3 C |
| 9. Testing | Task 4 A/B/C |
| 10. Security | Task 4 D |
| 11. Docker & deployment | Task 4 E |

At the end: a **checklist** mapping every requirement in the problem statement (`docs/00_problem_statement.pdf`) to where it is done.

---

## Phase 0: Set up Python

### Theory to learn
- **Virtual environment (`.venv`)**: a private folder of libraries for one project, so versions never clash with other projects.
- **`requirements.txt`**: the list of libraries the project needs. Anyone can install exactly the same set with one command.
- **`.env` file**: settings and secrets (account name, keys) kept **outside** the code. It is git-ignored, so it never reaches GitHub.

### Steps
```powershell
git clone https://github.com/Ghanshyam-02/capstone-2.git
cd capstone-2
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env
```
> If `activate` is blocked, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

### Check
The prompt starts with `(.venv)`. `pytest tests/unit -v` shows all tests passing. Unit tests need no database.

---

## Phase 1: Set up Snowflake

### Theory to learn
- **Warehouse vs database**: in Snowflake, *storage* (database) and *compute* (warehouse) are separate. You pay only while the warehouse runs. `AUTO_SUSPEND = 60` switches it off after 60 seconds of idle time, so your trial credits last.
- **Schema**: a folder inside a database. We use one per layer: `BRONZE`, `SILVER`, `GOLD`, plus `AUDIT` for logs.
- **Role**: a set of permissions. `PIPELINE_ROLE` can write everything. `API_ROLE` can only *read* Gold. This is the **least privilege** principle: every program gets only the rights it needs.
- **Key-pair authentication**: programs log in with a *private key* file instead of a password. Snowflake keeps only the matching *public key*. This is the standard way for service accounts (and scripts cannot answer MFA prompts).

### Steps
1. **Create the key pair** (in the normal PowerShell terminal, with `.venv` active):
   ```powershell
   python -m common.create_keys
   ```
   It creates `keys/rsa_key.p8` (private, never share it, git-ignored) and `keys/rsa_key.pub`, and prints the public key as **one line**.
2. **Run the setup SQL.** In Snowsight open *Projects → Worksheets → +* and paste `sql/00_setup.sql`. Replace `PASTE_YOUR_PUBLIC_KEY_HERE` with the one-line public key. Then click **Run All**.
3. **Find your account identifier.** In Snowsight, click your name (bottom-left), then *Account → View account details*, and copy the **Account identifier**.
4. **Fill in `.env`.**
   - Set `SNOWFLAKE_ACCOUNT` to the account identifier.
   - Set `API_KEY` to the output of:
     ```powershell
     python -c "import secrets; print(secrets.token_urlsafe(32))"
     ```
5. **Test the connection:**
   ```powershell
   python -m common.snowflake_conn
   ```

### Check
Two lines print: `Connected OK -> ... role=PIPELINE_ROLE` and `... role=API_ROLE`.

---

## Phase 2: Specification (Task 1)

### Theory to learn
- **Specification first**: agree on *what* to build (KPIs, rules, "done") before writing code. It avoids building the wrong thing.
- **Business spec vs technical spec**: the business spec says *what and why* (problem, users, KPIs, rules). The technical spec says *how* (sources, storage, API, validation, monitoring, security).
- **Acceptance criteria**: testable statements of "done".
- **Gherkin (Given / When / Then)**: acceptance tests written in plain English that business people can read:
  - *Given* is the starting situation
  - *When* is the action
  - *Then* is the expected result
- **Data-quality classes**: the brief asks you to decide which class each bad record belongs to:

  | Class | Meaning | Example |
  |---|---|---|
  | Reject | unusable, drop and log | no id, unreadable date, duplicate event |
  | Quarantine | suspicious, hold for a human | missing merchant, invalid currency, negative settlement, orphan settlement |
  | Warning | usable but notable, keep and log | late event |
  | Business exception | data is fine, the *business outcome* is bad | successful payment never settled |

### Steps
Read `docs/01_business_spec.md`, `docs/02_technical_spec.md` and `docs/03_acceptance.feature`.

### Check
You can explain why a negative settlement is *quarantined* (it may be a refund, so a human should decide) rather than *rejected*.

---

## Phase 3: Look at the data

### Theory to learn
- **Test data**: the brief gives only column lists, so realistic CSV files are provided in the repo. Every hidden problem from the brief is planted in them **on purpose**, so we can prove the pipeline handles it.
- **Two folders**:
  - `data/raw/`: batch 1 (Sep 2026). The pipeline loads this folder.
  - `data/incoming/`: batch 2 (1 Oct 2026). Kept aside for the incremental demo in Phase 6.

| Hidden problem | Where it is in the data |
|---|---|
| One-to-many settlement | `T1001`: 10,000 settled as 8,000 + 2,000 |
| Late event | `E1LATE01`: happened 10:02:15, received 10:08:41 |
| Out-of-order events | rows shuffled. T1001 arrives SETTLED → AUTHORIZED → CREATED |
| Risk history | M100 LOW → HIGH → MEDIUM. M101 LOW → HIGH on 15 Sep |
| Settlement incident | 15 Sep: many settlements late or pending → spike on the daily chart |
| Abnormal merchants | M104, M108, M117 often unsettled. M110, M121 settle late |
| Missing merchant, invalid currency, negative settlement, orphan settlement, duplicate events | a few rows of each |

| File | Rows |
|---|---|
| `data/raw/merchant_001.csv` | 31 (25 merchants + risk history) |
| `data/raw/transactions_001.csv` | 3,830 |
| `data/raw/settlements_001.csv` | 3,641 |
| `data/raw/payment_events_001.csv` | 10,833 |
| `data/incoming/*_002.csv` | 120 / 123 / 333 (batch 2) |

### Steps
Open `data/raw/transactions_001.csv` in VS Code or Excel and look around.

### Check
You can find a row with an empty merchant_id, and `T1001` in `transactions_001.csv`.

---

## Phase 4: Data model (Task 2)

### Theory to learn
- **Star schema**: *fact* tables in the middle (events you measure: transactions, settlements) and *dimension* tables around them (who/what/when: merchant, customer, date). Simple joins, fast reports.
- **Grain**: what **one row** of a table means. It is the most important decision in a model, and the brief makes it mandatory:
  - `FACT_TRANSACTION`: one payment attempt
  - `FACT_SETTLEMENT`: one settlement record
  - `FACT_PAYMENT_EVENT`: one lifecycle event
  - `DIM_MERCHANT`: one merchant per risk period
- **Primary key / foreign key**: a PK identifies a row uniquely. An FK points to a row in another table (a transaction points to its merchant).
- **Surrogate key**: an internal number (`MERCHANT_SK`) used instead of the business id, because one merchant id now has several history rows.
- **SCD Type 2 (Slowly Changing Dimension)**: keep **history**. Every time the risk level changes, add a new row with `EFFECTIVE_FROM` / `EFFECTIVE_TO`. A February transaction joins to the row valid in February.
- **One-to-many trap**: if you join a transaction (10,000) to its 2 settlements, the 10,000 appears twice, so the total becomes 20,000. The fix is to **sum settlements per transaction first**, then join (`GOLD.V_TXN_SETTLEMENT`).
- **Staging table**: a landing table that holds raw data before it is cleaned. Our BRONZE tables are the staging layer, and Silver uses a temporary `AUDIT.STAGING` table before its MERGE.
- **Snowflake specifics**:
  - PK/FK are *declared but not enforced* (only NOT NULL is), so tests must prove them.
  - There are *no indexes*. Snowflake prunes data automatically, and large tables use clustering keys.

### Steps
Read `docs/04_data_model.md`, then the DDL files `sql/01_*.sql`, `sql/02_*.sql` and `sql/03_*.sql`. Every table has its grain written above it.

### Check
You can draw the star: DIM_DATE, DIM_MERCHANT and DIM_CUSTOMER around FACT_TRANSACTION, with FACT_SETTLEMENT and FACT_PAYMENT_EVENT hanging off it.

---

## Phase 5: Pipeline, Bronze → Silver → Gold (Task 2)

### Theory to learn
- **Medallion architecture**:

  | Layer | Question | Rule |
  |---|---|---|
  | Bronze | What did we receive? | load everything as text, never reject, add source file + load time |
  | Silver | What can we trust? | validate, clean, remove duplicates, convert types. Bad rows go to `AUDIT.DQ_LOG` |
  | Gold | What does the business need? | star schema + KPI table |

  The brief's steps map onto it: *Raw → Validation → Clean → Business transformation → Gold*.
- **Stage, PUT and COPY**: a *stage* is a folder inside Snowflake. `PUT` uploads a file into it. `COPY INTO` loads it into a table.
- **MERGE (upsert)**: in one statement, *insert* new rows and *update* existing ones. Running it twice gives the same result, which is called **idempotent**.
- **Transaction (BEGIN / COMMIT)**: several statements that succeed or fail **together**. Silver data, the DQ log and the watermark are committed together.
- **Business time vs processing time**:
  - `event_ts` is when it *happened*. It is used for reports and ordering.
  - `ingestion_ts` is when *we received it*. It is used to detect late events.
- **Out-of-order events**: the arrival order is not the real order. `EVENT_SEQ = ROW_NUMBER() OVER (PARTITION BY transaction ORDER BY event_ts)` restores the real sequence.
- **"Invalid records should not silently disappear"**: every rejected or quarantined row is written to `AUDIT.DQ_LOG` with its reason.
- **Exception report**: `GOLD.V_SETTLEMENT_EXCEPTIONS` lists every successful payment that is UNSETTLED, PENDING, PARTIALLY_SETTLED or DELAYED (settled after 30 min, with `SETTLEMENT_DELAY_MIN`). Operations uses it to investigate the gap and the delays.

### Steps
```powershell
python -m pipeline.run_pipeline --init
```
(`--init` creates the tables. You only need it the first time.)

Then in Snowsight run the queries in `sql/05_explore_checks.sql` one by one:
- **C**: the data-quality log
- **D**: T1001, and the wrong-join demo
- **E**: late events
- **F**: M101's risk changing on 15 Sep
- **G**: *why is there a gap?* (unsettled / pending / partly settled)
- **H / H2**: the settlement exception report and **delayed settlements**. Which merchants are slow, and the 15 Sep spike.

### Check
The pipeline prints something like `[silver] transactions read=3830 loaded=3800 quarantined= 30 ...`, and query D shows T1001 settled = 10,000, not 20,000.

---

## Phase 6: Incremental processing (Task 2)

### Theory to learn
- **Incremental vs full reload**: processing only *new* data is faster and cheaper than reprocessing everything on every run.
- **COPY load history**: Snowflake remembers which files it already loaded and skips them.
- **Watermark**: a saved "last processed" timestamp (`AUDIT.WATERMARK`). Each run reads only rows newer than the watermark, then moves it forward.
- **Partial recalculation**: the KPI table is recalculated only for the dates that received new data.

### Steps
```powershell
python -m pipeline.run_pipeline
copy data\incoming\*.csv data\raw\
python -m pipeline.run_pipeline
```

### Check
- The first run loads **0 new files**.
- After batch 2, only the `*_002.csv` files load.
- Batch 2 (1 Oct) also turns 20 PENDING settlements from batch 1 into SETTLED, so the old days' settlement rate goes up.
- Look at `SELECT * FROM AUDIT.WATERMARK;` and `SELECT * FROM AUDIT.PIPELINE_RUNS;`

---

## Phase 7: API (Task 3 A/B)

### Theory to learn
- **REST API**: programs ask for data over HTTP (`GET /api/v1/settlement-summary?start_date=...`) and get JSON back.
- **FastAPI**: a Python framework. A decorated function becomes an endpoint.
- **Pydantic**: defines the exact shape of the response (the *contract*) and validates it. For example, `settlement_rate` must be between 0 and 100.
- **OpenAPI**: machine-readable API documentation. FastAPI generates it automatically at `/docs`.
- **HTTP status codes**:

  | Code | Meaning |
  |---|---|
  | 200 | OK |
  | 400 | bad request (invalid date) |
  | 401 | not logged in (missing or wrong API key) |
  | 404 | not found (unknown merchant) |
  | 422 | invalid parameter format |

- **Repository pattern**: all SQL lives in `api/repository.py`. The endpoints never write SQL, and tests can swap in a fake repository.
- **Pre-aggregation**: the API reads the small `AGG_MERCHANT_DAILY` table, so it answers in milliseconds.

### Steps
```powershell
uvicorn api.main:app --reload
```
Open http://localhost:8000/docs. In a **second** terminal:
```powershell
$h = @{ "X-API-Key" = "<API_KEY from your .env>" }
Invoke-RestMethod "http://localhost:8000/api/v1/settlement-summary?start_date=2026-09-01&end_date=2026-10-01" -Headers $h
Invoke-RestMethod "http://localhost:8000/api/v1/merchant-exceptions" -Headers $h
```

### Check
The summary has the 6 fields from the brief, plus `merchant_risk_count` (KPI 5). The exceptions list includes M104, M108, M117 (HIGH risk, low settlement rate) and M110, M121 (slow settlement, low SLA).

---

## Phase 8: Dashboard (Task 3 C)

### Theory to learn
- **Front-end consumes the API**: the page never reads CSVs or the database. There is one source of truth, so every user sees the same numbers and the same security rules apply.
- **`fetch()`**: the JavaScript function that calls the API.
- **Chart.js**: a library that draws charts from arrays of numbers.
- **Same origin**: FastAPI serves the HTML itself (at `/`), so the browser needs no extra CORS setup.

### Steps
With uvicorn running, open http://localhost:8000/, paste your API key, and click **Load**.

### Check
You see the KPI cards, the daily transaction vs settlement chart, the top-10 gap chart, and the merchant table. Bad values are shown in red.

---

## Phase 9: Testing (Task 4 A/B/C)

### Theory to learn
- **Unit test**: tests one small function in isolation (e.g. "a negative settlement is quarantined"). Fast, and needs no database.
- **TDD (Test-Driven Development)**: write the test first, see it fail, write the code, see it pass. The tests then protect you when you change code later.
- **Contract test**: checks the API keeps its promise (status codes, fields, 0 ≤ rate ≤ 100). It uses a **fake** (mock) repository instead of Snowflake.
- **Data-model tests**: run SQL on the real tables:
  - *grain*: no duplicate keys
  - *referential integrity*: no transaction points to a missing merchant
  - *reconciliation*: successful amount = settled + unsettled, and every successful transaction falls in exactly one settlement bucket

  Because Snowflake does not enforce keys, these tests are the proof.

### Steps
```powershell
pytest -v
$env:RUN_SNOWFLAKE_TESTS="1"; pytest tests/data_model -v
```

### Check
Everything is green. Try changing `SLA_SECONDS` in `pipeline/rules.py` and watch a test fail. That is the safety net working.

---

## Phase 10: Security (Task 4 D)

### Theory to learn
- **SQL injection**: if user input is pasted into SQL text, an attacker can send `x' OR '1'='1` and read every row. The fix is **bind parameters**: `execute("... WHERE MERCHANT_ID = %s", (merchant_id,))`. The value is sent separately and is never treated as SQL.
- **Input validation**: `merchant_id` must match `^M\d{3,6}$`, or the API returns 422 before any SQL runs.
- **Authentication vs authorization**:
  - *Authentication* is **who** you are (the API key).
  - *Authorization* is **what** you may do (`API_ROLE` can only read Gold).
- **Secrets management**: no passwords in code. Use `.env` locally and CI variables in pipelines, and keep both out of Git and Docker images.
- **PII (personal data)**: store only a hash of customer ids, never return them from the API, and mask them in logs.
- **Minimal logging**: log what happened (endpoint, status, row counts), never the data itself.

### Steps
Read `docs/05_security.md`, then try the injection attack (it returns 422):
```powershell
Invoke-RestMethod "http://localhost:8000/api/v1/settlement-summary?start_date=2026-09-01&end_date=2026-10-01&merchant_id=M100'%20OR%20'1'='1" -Headers $h
```

### Check
You can point to where each of the brief's 6 risks is handled.

---

## Phase 11: Docker & deployment (Task 4 E)

### Theory to learn
- **Docker image vs container**:
  - An *image* is a packaged app (OS + Python + libraries + code).
  - A *container* is a running image.
  - The same image runs identically on a laptop, in TEST and in PROD.
- **Dockerfile layers**: install requirements first and copy the code after, so rebuilding after a code change is fast.
- **Never bake secrets into images**: pass them in at start (`--env-file`) and mount the key read-only.
- **CI/CD**:
  - *Continuous Integration* runs tests, SAST (code security scan), a dependency scan and the Docker build on every push.
  - *Continuous Delivery* promotes the same image DEV → TEST → PROD, with manual approval for TEST and PROD.
- **Environment configuration**: one image, with different settings per environment (e.g. `SETTLEMENT_DB_DEV` / `_PROD`).
- **Health check**: `/health` tells the platform whether the app is alive.
- **Smoke test**: one quick real call after each deploy.
- **Rollback**: each commit has its own image tag, so going back means redeploying the previous tag. On the data side, Snowflake *Time Travel* can restore a table.

### Steps (on a machine with Docker Desktop)
```powershell
docker build -t settlement-api:1.0 .
docker run -p 8000:8000 --env-file .env -v "${PWD}/keys:/app/keys:ro" settlement-api:1.0
```
Read `docs/06_deployment.md` and `.gitlab-ci.yml` (the brief's GitLab design).

### Check
http://localhost:8000/ works from inside the container, and `docker ps` shows `(healthy)`.

---

## Troubleshooting
| Error | Fix |
|---|---|
| `Missing required environment variable` | fill in `.env` in the project root |
| `JWT token is invalid` | public key in Snowflake ≠ your private key. Run `ALTER USER SETTLE_SVC SET RSA_PUBLIC_KEY='...'` |
| `Object does not exist or not authorized` | run all of `sql/00_setup.sql`, then the pipeline with `--init` |
| Dashboard shows `401` | paste the same `API_KEY` that is in `.env` |
| Start from zero | run `sql/99_reset.sql` in Snowsight, then the pipeline again |

---

## Checklist against the problem statement

Every requirement in `docs/00_problem_statement.pdf`, and where it is done.

### 1. Business goals
| Operations must be able to… | Where |
|---|---|
| View payment and settlement performance | Dashboard KPI cards + daily chart, `/settlement-summary` |
| Identify settlement gaps | KPI 3, top-10 gap chart, `GOLD.V_TXN_SETTLEMENT` (`GAP_AMOUNT`), query G |
| Investigate delayed settlements | `SETTLEMENT_DELAY_MIN` + `GOLD.V_SETTLEMENT_EXCEPTIONS` (type DELAYED), query H2 |
| Identify merchants with abnormal settlement behaviour | `/merchant-exceptions`, merchant table (red values), KPI 5 |
| Expose the analytics through an API | `api/` (FastAPI) |
| Consume the API through a web dashboard | `frontend/index.html` |
| Process new data incrementally | COPY load history + `AUDIT.WATERMARK` + changed-dates rebuild (Phase 6) |
| Automatically test the implementation | `tests/` + test stage in `.gitlab-ci.yml` |

### 2–3. Data sources and hidden problems
| Item | Where |
|---|---|
| 4 CSV files with the given columns | `data/raw/`, `data/incoming/` |
| Issue 1: one-to-many settlement | settlements summed per transaction in `V_TXN_SETTLEMENT`, test `T1001` |
| Issue 2: late-arriving events | `event_ts` vs `ingestion_ts`, `IS_LATE`, `LATE_EVENT` warning |
| Issue 3: out-of-order events | `EVENT_SEQ` ordered by `event_ts` |
| Issue 4: merchant risk changes | SCD2 `DIM_MERCHANT`, `RISK_LEVEL_AT_TXN` |
| Issue 5: missing merchant, duplicate events, negative settlement, transaction without settlement, settlement without transaction, invalid currency, late events | `pipeline/rules.py` + classification table in `docs/01_business_spec.md` |
| Decide reject / quarantine / warning / business exception | `docs/01_business_spec.md` (business rules) |

### 4. KPIs
| KPI | Where |
|---|---|
| 1 Transaction volume · 2 Settlement rate · 3 Settlement gap · 4 SLA (30 min) · 5 Merchant risk (rate < 95% AND SLA < 90%) | `common/kpi.py`, `/settlement-summary`, dashboard cards |

### 5. Engineering requirement
| Requirement | Where |
|---|---|
| Not a single script; layers Source → Ingestion → Bronze → Silver → Gold → API → Front-end | `pipeline/ingest.py`, `pipeline/silver.py`, `sql/04_gold_transform.sql`, `api/`, `frontend/` |
| Incremental processing | Phase 6 |

### Task 1: Specification package
| Item | Where |
|---|---|
| Business spec: problem, objective, users, KPIs, scope, assumptions, business rules, acceptance criteria | `docs/01_business_spec.md` |
| Technical spec: data sources, fields, processing, storage, API, front-end, validation, monitoring, security | `docs/02_technical_spec.md` |
| At least 5 Gherkin scenarios | `docs/03_acceptance.feature` (8 scenarios) |

### Task 2: Data model + pipeline
| Item | Where |
|---|---|
| DIM_DATE, DIM_MERCHANT, DIM_CUSTOMER, FACT_TRANSACTION, FACT_SETTLEMENT, FACT_PAYMENT_EVENT | `sql/03_gold_ddl.sql` |
| Justify the model + grain of every fact table | `docs/04_data_model.md` |
| DDL, primary keys, foreign keys, constraints | `sql/01..03_*.sql` |
| Indexes / partitioning | `docs/04_data_model.md` (Snowflake micro-partitions, clustering key note) |
| Staging tables | Bronze tables + `AUDIT.STAGING` |
| Raw → Validation → Clean → Business transformation → Gold | Bronze → `rules.py` → Silver → Gold SQL |
| Invalid records must not silently disappear | `AUDIT.DQ_LOG` |

### Task 3: API + front-end
| Item | Where |
|---|---|
| `GET /api/v1/settlement-summary` (start_date, end_date, merchant_id) with the 6 response fields | `api/main.py` |
| `GET /api/v1/merchant-exceptions` (rate < 95% OR SLA < 90%) | `api/main.py` |
| FastAPI, Pydantic, OpenAPI | `api/main.py`, `api/models.py`, `/docs` |
| KPI cards: Transactions, ₹ Volume, Settlement Rate, Settlement Gap, SLA Rate | dashboard |
| Chart 1: daily transaction vs settlement amount | dashboard (`/daily-trend`) |
| Chart 2: top 10 merchants with settlement gaps | dashboard (`/merchants`) |
| Table: Merchant, Risk, Settlement Rate, SLA, Settlement Gap | dashboard |
| Front-end uses the API, not CSV files | `frontend/index.html` only calls `/api/v1/...` |

### Task 4: Testing, security, deployment
| Item | Where |
|---|---|
| Unit tests: successful, failed, duplicate event, missing merchant, unmatched settlement, negative settlement, late event, settlement calculation | `tests/unit/test_rules.py` |
| Data-model tests: grain, referential integrity, settlement reconciliation | `tests/data_model/test_data_model.py` |
| API contract tests: 200, 400, 404, 422, 0 ≤ settlement_rate ≤ 100 | `tests/api/test_api_contract.py` |
| Security: SQL injection, unrestricted access, secrets, PII, logging, authorization | `docs/05_security.md` |
| Parameterized queries | `api/repository.py` |
| Deployment: GitLab → CI (tests, SAST, dependency scan, docker build) → DEV → TEST → PROD | `.gitlab-ci.yml`, `Dockerfile` |
| Environment configuration, secrets, health check, smoke test, rollback | `docs/06_deployment.md` |

