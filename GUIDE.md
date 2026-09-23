# Step-by-step guide (beginner friendly)

Every phase has three parts:
- **Theory** – what we are doing and why (this is what you explain in a review or interview)
- **Do it** – the exact commands
- **Check** – what you should see before moving on

Commands are for **Windows PowerShell** (inside VS Code: *Terminal → New Terminal*).
On macOS/Linux use `source .venv/bin/activate` instead of `.venv\Scripts\activate`.

| Phase | Covers brief task | Time |
|---|---|---|
| 0. Clone & Python setup | – | 10 min |
| 1. Snowflake setup | – | 25 min |
| 2. Read the specification | Task 1 | 15 min |
| 3. Generate the data | – | 5 min |
| 4. Run the pipeline (Bronze → Silver → Gold) | Task 2 | 30 min |
| 5. Incremental run | Task 2 | 10 min |
| 6. API | Task 3A/B | 20 min |
| 7. Dashboard | Task 3C | 10 min |
| 8. Tests | Task 4A/B/C | 20 min |
| 9. Security review | Task 4D | 10 min |
| 10. Docker | Task 4E | 20 min |
| 11. CI/CD & deployment design | Task 4E | 15 min |

---

## Phase 0 – Clone the project and set up Python

**Theory.** A *virtual environment* (`.venv`) is a private folder of Python libraries for this project only,
so versions never clash with other projects. `requirements.txt` lists what the app needs;
`requirements-dev.txt` adds testing/security tools.

**Do it**
```powershell
git clone https://github.com/Ghanshyam-02/capstone-2.git
cd capstone-2
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env
code .
```
> If `activate` is blocked: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then retry.

**Check:** the prompt starts with `(.venv)`, and `pytest tests/unit -q` shows all tests passing.
(Unit tests need no database – that is the point of them.)

---

## Phase 1 – Snowflake setup

**Theory.**
- Snowflake separates **storage** (database) from **compute** (warehouse). You pay only while a warehouse
  runs; `AUTO_SUSPEND = 60` stops it after 60 s idle, so the trial credits last.
- **Schemas per layer** (BRONZE / SILVER / GOLD / AUDIT) make the medallion architecture visible.
- **Least privilege:** `PIPELINE_ROLE` can write everything; `API_ROLE` can only read GOLD. If the API were
  hacked it still could not change or see raw data.
- **Key-pair authentication:** programs (service users) log in with a private key, not a password.
  Snowflake keeps only the public key. This is how production systems connect – and Snowflake blocks
  simple password logins for scripts when MFA is on.

**Do it**
1. **Create a key pair** (in the project folder – Git Bash has `openssl`; on Windows open *Git Bash* here):
   ```bash
   openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out keys/rsa_key.p8 -nocrypt
   openssl rsa -in keys/rsa_key.p8 -pubout -out keys/rsa_key.pub
   cat keys/rsa_key.pub
   ```
   `keys/` is git-ignored – the private key never goes to GitHub.
2. **Run the setup SQL:** Snowsight → *Projects → Worksheets → +* → paste `sql/00_setup.sql`.
   Replace `PASTE_YOUR_PUBLIC_KEY_HERE` with the text between the `BEGIN/END PUBLIC KEY` lines (one line,
   no line breaks). Select all → **Run All** (Ctrl+Shift+Enter).
3. **Find your account identifier:** Snowsight → bottom-left your name → *Account* → *View account details*
   → copy **Account identifier** (looks like `ABCDEFG-XY12345`).
4. **Edit `.env`:** set `SNOWFLAKE_ACCOUNT` to that value. Generate an API key and paste it into `API_KEY`:
   ```powershell
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
5. **Test the connection:**
   ```powershell
   python -m common.snowflake_conn
   ```

**Check:** two lines `Connected OK -> user=SETTLE_SVC role=PIPELINE_ROLE ...` and `... role=API_ROLE ...`.
If you get `JWT token is invalid`, the public key in Snowflake does not match – re-run
`ALTER USER SETTLE_SVC SET RSA_PUBLIC_KEY='...';`.

---

## Phase 2 – Read the specification (Task 1)

**Theory.** In industry nobody writes code before the *what* is agreed. The spec defines KPIs, rules and
"done". The Gherkin scenarios are acceptance tests written in plain English that business people can read.

**Do it** – read, in this order (they are short):
1. `docs/01_business_spec.md` – problem, users, KPIs, assumptions, **how each bad record is classified**
2. `docs/02_technical_spec.md` – architecture, processing, API, monitoring
3. `docs/03_acceptance.feature` – 7 Gherkin scenarios
4. `docs/04_data_model.md` – grain of every table

**Check:** you can answer: *"What is the difference between a quarantined record and a business exception?"*
(Quarantine = the data is wrong, held back. Business exception = the data is right, but the business
outcome is bad, e.g. a successful payment that was never settled.)

---

## Phase 3 – Generate the data

**Theory.** The brief gives column lists but no files, so `pipeline/generate_data.py` creates small,
realistic CSVs and **plants every hidden problem** on purpose. A fixed random seed means you get the same
data every time.

| Planted problem | Example in the data |
|---|---|
| One-to-many settlement | `T1001` = 10,000 settled as 8,000 + 2,000 (plus ~10 % random splits) |
| Late events | `E1LATE01`: event 10:02:15, ingested 10:08:41; ~5 % of others |
| Out-of-order events | event rows shuffled; T1001's arrive SETTLED → AUTHORIZED → CREATED |
| Merchant risk history | M100 LOW→HIGH→MEDIUM (the brief); M101 LOW→HIGH on 4 Sep (inside our data) |
| Missing / unknown merchant | 3 blank merchant ids, 1 `M999` |
| Invalid currency | `XYZ`, blank; `" inr "` is messy-but-valid |
| Negative settlement | 2 × −500 |
| Settlement without transaction | `T199998`, `T199999` |
| Duplicate event ids | 5 duplicates |
| Unreadable timestamp | `2026-09-31 25:61:00` |
| Abnormal merchants | M104, M108 (often unsettled), M110 (settles late → SLA breach) |

**Do it**
```powershell
python -m pipeline.generate_data --batch 1
```
**Check:** 4 files in `data/raw/`. Open `transactions_001.csv` in Excel and find a blank merchant id.

---

## Phase 4 – Run the pipeline: Bronze → Silver → Gold (Task 2)

### Theory – the medallion layers
| Layer | Question it answers | Rule |
|---|---|---|
| **Bronze** | "What exactly did we receive?" | Load everything as text. Never reject. Add `SOURCE_FILE`, `LOAD_TS`. You can always replay. |
| **Silver** | "Which data can we trust?" | Validate, clean, type, de-duplicate. Bad rows → `AUDIT.DQ_LOG` with a reason (never silently dropped). |
| **Gold** | "What does the business need?" | Star schema + KPI table, business logic (settlement roll-up, SLA, risk as of date). |

### Theory – how each hidden problem is solved
1. **One-to-many settlement** – `GOLD.V_TXN_SETTLEMENT` first **sums settlements per transaction**, then
   joins. A direct join repeats the 10,000 transaction twice (= 20,000). See query D in
   `sql/05_explore_checks.sql` for the wrong result side by side.
2. **Late events** – we keep **both** times. `EVENT_TS` = business time (reports, ordering).
   `INGESTION_TS` = processing time (lateness: `IS_LATE`, `INGESTION_DELAY_SEC`).
3. **Out-of-order events** – `EVENT_SEQ = ROW_NUMBER() OVER (PARTITION BY transaction ORDER BY EVENT_TS)`.
   File order is ignored.
4. **Risk history (SCD Type 2)** – `DIM_MERCHANT` has one row per risk period with
   `EFFECTIVE_FROM/TO`. The fact joins on `transaction_date BETWEEN effective_from AND effective_to`
   and stores the risk that was valid that day.
5. **Data quality** – `pipeline/rules.py` decides OK / WARNING / QUARANTINE / REJECT per row.

### Theory – Snowflake specifics
- **Stage + COPY:** `PUT` uploads a file into an internal stage (a folder inside Snowflake); `COPY INTO`
  loads it into a table. COPY **remembers loaded files** and skips them next time → incremental ingestion.
- **PK/FK are not enforced** in Snowflake (only NOT NULL). We declare them for documentation and
  **prove** them with tests.
- **No indexes** – Snowflake prunes micro-partitions automatically; big tables use clustering keys.
- **MERGE** = insert new rows, update changed rows, in one statement → re-running is safe (*idempotent*).

### Do it
```powershell
python -m pipeline.run_pipeline --init
```
`--init` creates all tables and views (only needed the first time or after you change the DDL).

**Check:** the output looks like
```
1) INGESTION -> BRONZE
  [bronze] merchant/merchant_001.csv.gz: LOADED, 15/15 rows loaded
  ...
2) BRONZE -> SILVER (validate / clean / de-duplicate)
  [silver] transactions    read= 176 loaded= 170 quarantined=  6 rejected=  0 warnings=  0
  ...
3) SILVER -> GOLD (star schema + KPI table)
Done. ...
```
Now open Snowsight, paste `sql/05_explore_checks.sql` and run the queries **one by one** (set the role
to `SYSADMIN` at the top of the worksheet). Look at: the DQ log (C), T1001 (D), late events (E), M101's
risk switching on 4 Sep (F), and the gap breakdown (G) – that last query **answers the Head of
Payments' question**.

---

## Phase 5 – Incremental processing

**Theory.** Reprocessing everything every run is slow and expensive. Three mechanisms keep it incremental:
1. **COPY load history** – a file is loaded into Bronze only once.
2. **Watermarks** (`AUDIT.WATERMARK`) – Silver reads only Bronze rows with `LOAD_TS` > last watermark.
   Gold reads only Silver rows with `LOADED_AT` > Gold watermark. Data and watermark are committed in
   the **same transaction**, so a crash can never skip or double-load rows.
3. **Affected dates** – `AGG_MERCHANT_DAILY` is rebuilt only for dates that received new rows.

Batch 2 contains a new day (8 Sep) **plus** 4 settlements from batch 1 that changed PENDING → SETTLED
(same settlement id) and a duplicate of an old event.

**Do it**
```powershell
python -m pipeline.run_pipeline            # nothing new -> 0 files, 0 rows
python -m pipeline.generate_data --batch 2
python -m pipeline.run_pipeline            # only batch 2 is processed
```
**Check:** the first run loads 0 files. The second loads only `*_002.csv`. In Snowsight:
`SELECT * FROM AUDIT.WATERMARK;` and `SELECT * FROM AUDIT.PIPELINE_RUNS ORDER BY STARTED_AT DESC;`.
The old dates' settlement rate went up (the pending settlements were completed).

> Want to start from zero? Run `sql/99_reset.sql` in Snowsight, then the pipeline again.

---

## Phase 6 – API (Task 3A/B)

**Theory.**
- **FastAPI** turns Python functions into HTTP endpoints. **Pydantic** models (`api/models.py`) define the
  exact response shape and validate it (e.g. `settlement_rate` must be 0–100). FastAPI generates the
  **OpenAPI** documentation automatically at `/docs`.
- **Layers inside the API:** `main.py` (HTTP + validation) → `common/kpi.py` (formulas) →
  `repository.py` (the only code that runs SQL). This separation lets tests replace the database with a fake.
- The API reads the small `AGG_MERCHANT_DAILY` table, so answers take milliseconds.
- **Status codes:** 200 OK · 400 bad date/range · 401 no/wrong API key · 404 unknown merchant ·
  422 invalid parameter (bad merchant format, missing parameter).

**Do it**
```powershell
uvicorn api.main:app --reload
```
Open http://localhost:8000/docs to see the generated OpenAPI documentation of every endpoint.
Every `/api/v1` call needs the `X-API-Key` header, so test them from a **second terminal**:
```powershell
$h = @{ "X-API-Key" = "<your API_KEY from .env>" }
Invoke-RestMethod "http://localhost:8000/api/v1/settlement-summary?start_date=2026-09-01&end_date=2026-09-08" -Headers $h
Invoke-RestMethod "http://localhost:8000/api/v1/merchant-exceptions" -Headers $h
Invoke-RestMethod "http://localhost:8000/api/v1/settlement-summary?start_date=2026-09-01&end_date=2026-09-08&merchant_id=M999" -Headers $h   # 404
```
**Check:** the summary has `transaction_count`, `transaction_amount`, `settled_amount`, `settlement_rate`,
`settlement_gap`, `sla_rate`. Exceptions include M104, M108 (HIGH risk) and M110 (low SLA).

---

## Phase 7 – Dashboard (Task 3C)

**Theory.** The dashboard is one HTML file with JavaScript. It calls the API with `fetch()` and draws
charts with Chart.js. It **never reads CSV or Snowflake directly** – the API is the single source of
truth, so every consumer sees the same numbers and the same security rules apply.
FastAPI serves the file from the same address (`/`), so no CORS setup is needed.

**Do it:** with uvicorn running, open http://localhost:8000/ → paste your API key → **Load**.

**Check:** 6 KPI cards, the daily line chart, top-10 gap bar chart, merchant table (exceptions have a red
edge), the "why is there a gap?" table and the data-quality table.

---

## Phase 8 – Tests (Task 4A/B/C)

**Theory – the test pyramid**
| Type | Folder | Needs Snowflake? | What it proves |
|---|---|---|---|
| Unit (TDD) | `tests/unit` | No | each rule: success, failed, duplicate, missing merchant, unmatched/negative settlement, late event, settlement calculation, risk as-of |
| API contract | `tests/api` | No (fake repository) | 200 / 400 / 401 / 404 / 422, rate between 0 and 100, response shape |
| Data model | `tests/data_model` | **Yes** | grain (no duplicate keys), referential integrity, reconciliation (successful = settled + gap), T1001 counted once, point-in-time risk |

Fast tests run on every commit; database tests run after the pipeline. Because Snowflake does not
enforce PK/FK, the data-model tests are the real guarantee.

**Do it**
```powershell
pytest -v                                                   # unit + API (data-model tests are skipped)
$env:RUN_SNOWFLAKE_TESTS="1"; pytest tests/data_model -v    # against Snowflake
```
**Check:** everything green. Try breaking something (e.g. change `SLA_SECONDS` in `pipeline/rules.py`)
and watch a test fail – that is TDD's safety net.

---

## Phase 9 – Security review (Task 4D)

**Theory.** Read `docs/05_security.md` – a table of each risk from the brief and where it is handled.
The key one is **SQL injection**:
```python
# BAD - the brief's example. merchant_id = "x' OR '1'='1" returns every merchant
query = f"SELECT * FROM transactions WHERE merchant_id = '{merchant_id}'"

# GOOD - value sent separately from the SQL text (bind parameter), plus strict format validation
cur.execute("SELECT ... WHERE MERCHANT_ID = %s", (merchant_id,))
```
**Do it:** run the injection attempt – it is rejected before reaching the database:
```powershell
Invoke-RestMethod "http://localhost:8000/api/v1/settlement-summary?start_date=2026-09-01&end_date=2026-09-08&merchant_id=M100'%20OR%20'1'='1" -Headers $h
```
And run the static security scanner:
```powershell
bandit -r api common pipeline -ll
```
**Check:** 422 for the injection; Bandit reports no medium/high issues.

---

## Phase 10 – Docker (Task 4E)

**Theory.**
- An **image** is a packaged app: OS + Python + libraries + code. A **container** is a running image.
  "Works on my machine" problems disappear because every environment runs the same image.
- `Dockerfile` steps: base image → install requirements (cached layer) → copy code → run as non-root →
  health check → start uvicorn.
- **Secrets are never inside the image.** They are passed when the container starts (`--env-file`)
  and the private key is mounted read-only (`-v ...:ro`). `.dockerignore` keeps `.env`, keys and data out.

**Do it** (Docker Desktop running)
```powershell
docker build -t settlement-api:1.0 .
docker run -p 8000:8000 --env-file .env -v "${PWD}/keys:/app/keys:ro" settlement-api:1.0
```
(stop uvicorn first if it is still using port 8000)

**Check:** http://localhost:8000/ works exactly as before. `docker ps` shows the container as `(healthy)`
after ~30 s.

---

## Phase 11 – CI/CD and deployment design (Task 4E)

**Theory.**
- **CI (continuous integration):** on every push a server runs tests, a SAST scan (Bandit / GitLab SAST),
  a dependency scan (pip-audit) and builds the Docker image. Broken code never reaches an environment.
- **CD (continuous delivery):** the same image moves DEV → TEST → PROD. TEST and PROD need a manual click
  (approval). Only configuration differs per environment.
- **Health check, smoke test, rollback** – see `docs/06_deployment.md`.

**Do it**
- GitHub already runs `.github/workflows/ci.yml` on every push → open the repo's **Actions** tab.
- Read `.gitlab-ci.yml` – the brief's GitLab design (tests → SAST → dependency scan → docker build →
  DEV → TEST → PROD + rollback job).

**Check:** a green tick next to your latest commit on GitHub.

---

## How to present it (2-minute story)
1. **Problem:** ₹2.2 Cr gap, nobody knows why.
2. **Architecture:** CSV → Bronze (raw) → Silver (trusted) → Gold (business) → API → dashboard, on Snowflake.
3. **Hidden problems** and the fix for each (one-to-many, late, out-of-order, SCD2 risk, DQ classes).
4. **Answer:** the gap-breakdown shows how much is pending, failed, partially settled or never settled,
   and the exceptions list shows which merchants cause it.
5. **Engineering:** incremental loads, nothing silently dropped, tests (unit/API/data model),
   least-privilege roles, parameterised SQL, Docker + CI/CD with rollback.

## Troubleshooting
| Error | Fix |
|---|---|
| `Missing required environment variable` | `.env` not filled in / not in project root |
| `JWT token is invalid` | public key in Snowflake ≠ your `keys/rsa_key.p8` → `ALTER USER SETTLE_SVC SET RSA_PUBLIC_KEY='...'` |
| `Object does not exist or not authorized` | run `sql/00_setup.sql` fully; run the pipeline with `--init` |
| `No active warehouse` | `SNOWFLAKE_WAREHOUSE=SETTLE_WH` in `.env` |
| Dashboard: `401` | paste the same `API_KEY` as in `.env` |
| Dashboard empty | run the pipeline first; check `GET /api/v1/data-range` |
| `docker: port is already allocated` | stop uvicorn (Ctrl+C) or use `-p 8001:8000` |
