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
| 3. Generate the data | – |
| 4. Data model | Task 2 |
| 5. Pipeline: Bronze → Silver → Gold | Task 2 |
| 6. Incremental processing | Task 2 |
| 7. API | Task 3 A/B |
| 8. Dashboard | Task 3 C |
| 9. Testing | Task 4 A/B/C |
| 10. Security | Task 4 D |
| 11. Docker & deployment | Task 4 E |

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
1. **Create the key pair.** Open *Git Bash* in the project folder:
   ```bash
   openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out keys/rsa_key.p8 -nocrypt
   openssl rsa -in keys/rsa_key.p8 -pubout -out keys/rsa_key.pub
   cat keys/rsa_key.pub
   ```
2. **Run the setup SQL.** In Snowsight open *Projects → Worksheets → +* and paste `sql/00_setup.sql`. Replace `PASTE_YOUR_PUBLIC_KEY_HERE` with the text between the BEGIN/END lines of the public key, all on one line. Then click **Run All**.
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

## Phase 3: Generate the data

### Theory to learn
- **Synthetic test data**: the brief gives only column lists, so we generate realistic CSVs. Every hidden problem is planted **on purpose**, so we can prove the pipeline handles it.
- **Fixed random seed**: the same "random" data every run, so results are repeatable.

| Hidden problem | Where it is in the data |
|---|---|
| One-to-many settlement | `T1001`: 10,000 settled as 8,000 + 2,000 |
| Late event | `E1LATE01`: happened 10:02:15, received 10:08:41 |
| Out-of-order events | rows shuffled. T1001 arrives SETTLED → AUTHORIZED → CREATED |
| Risk history | M100 LOW → HIGH → MEDIUM. M101 LOW → HIGH on 4 Sep |
| Missing merchant, invalid currency, negative settlement, orphan settlement, duplicate events | a few rows of each |

### Steps
```powershell
python -m pipeline.generate_data --batch 1
```

### Check
4 CSV files appear in `data/raw/`. Open `transactions_001.csv` and find a row with an empty merchant_id.

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

### Steps
```powershell
python -m pipeline.run_pipeline --init
```
(`--init` creates the tables. You only need it the first time.)

Then in Snowsight run the queries in `sql/05_explore_checks.sql` one by one:
- **C**: the data-quality log
- **D**: T1001, and the wrong-join demo
- **E**: late events
- **F**: M101's risk changing on 4 Sep
- **G**: *why is there a gap?*

### Check
The pipeline prints something like `[silver] transactions read= 176 loaded= 170 quarantined= 6 ...`, and query D shows T1001 settled = 10,000, not 20,000.

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
python -m pipeline.generate_data --batch 2
python -m pipeline.run_pipeline
```

### Check
- The first run loads **0 new files**.
- After batch 2, only the `*_002.csv` files load.
- Batch 2 also turns 4 PENDING settlements from batch 1 into SETTLED, so the old days' settlement rate goes up.
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
Invoke-RestMethod "http://localhost:8000/api/v1/settlement-summary?start_date=2026-09-01&end_date=2026-09-08" -Headers $h
Invoke-RestMethod "http://localhost:8000/api/v1/merchant-exceptions" -Headers $h
```

### Check
The summary has the 6 fields from the brief, plus `merchant_risk_count` (KPI 5). The exceptions list includes M104 and M108 (HIGH risk) and M110 (slow settlement).

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
  - *reconciliation*: successful = settled + unsettled

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
Invoke-RestMethod "http://localhost:8000/api/v1/settlement-summary?start_date=2026-09-01&end_date=2026-09-08&merchant_id=M100'%20OR%20'1'='1" -Headers $h
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
