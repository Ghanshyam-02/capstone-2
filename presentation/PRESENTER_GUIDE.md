# Presenter Guide — Merchant Settlement Intelligence Platform

This guide covers the 14-slide deck (if you edit the deck, adjust the slide numbers here).
Aim for **12–15 minutes**, about 1 minute per slide. Each slide has three parts:
- **Say:** a script you can read or paraphrase.
- **How we did it:** the background you need if someone asks.
- **Likely questions:** short answers.

---

## Part 0 — The problem statement in plain words

**The story.** Bank of New York processes card and UPI payments for merchants: shops, fuel stations, e-commerce sites.
1. A customer pays, and the payment is either **successful** or **failed**.
2. For each successful payment, the bank later **settles** (sends) the money to the merchant.
3. Yesterday, ₹48 Cr of payments succeeded, but only ₹45.8 Cr was settled.
4. That leaves a **₹2.2 Cr gap**, and the Head of Payments asked: *"Where is this money, and why?"*

**Why nobody could answer:**
- The data sat in 4 separate places: **transactions**, **settlements**, **merchant risk**, and **payment events** (the lifecycle: created → authorised → captured → settled).
- The team only had nightly Excel reports.
- The data was messy:
  - duplicates
  - late events
  - events out of order
  - one payment settled in several parts
  - merchants whose risk rating changed over time

**What we were asked to build:**
1. A **data pipeline** that cleans and models the data (we used DuckDB with Bronze/Silver/Gold layers).
2. **KPIs**: settlement rate, settlement gap, SLA (settled within 30 min), exceptions, and risky merchants.
3. An **API** plus a **dashboard** so Operations can see this every day.
4. **Tests** and **security** so the platform is trustworthy.
5. **Production readiness**:
   - CI/CD pipelines (GitLab main, Jenkins backup)
   - Docker images
   - blue-green deployment
6. An **incident**: a faulty version is released. We had to detect it, decide what to do, roll back, and prove the fix with evidence.
7. Present it all to leadership, which is this deck.

**The key terms, in one line each:**

| Term | Meaning |
|---|---|
| Settlement rate | settled amount ÷ successful payment amount × 100 (ours: **93.72 %**, target 95 %) |
| Settlement gap | successful amount − settled amount (ours: **₹25.95 L**) |
| SLA rate | % of payments settled within 30 minutes (ours: **77.09 %**, target 90 %) |
| Exception | a payment that is UNSETTLED, PENDING, PARTIALLY_SETTLED or DELAYED |
| Risky merchant | a merchant with a poor settlement rate or SLA, or a HIGH risk rating (ours: **5**) |

Our dataset is a small, realistic sample: about 3,800 transactions for September.
That is why our gap is ₹25.95 L and not ₹2.2 Cr. **The method is the same at any scale.**
Say this if someone asks why the numbers are smaller.

---

## Slide 1 — Title

**Say:**
> "Good morning. Our task was to explain a settlement gap nobody could explain. Today I'll show how we built a platform that does it, how we made it safe to release using CI/CD and blue-green deployment, and what happened when a bad release reached production. We rolled it back in 3 seconds."

Point to the three numbers on the right:
- **93.72 %**: the settlement rate we can now explain
- **22 / 0**: 22 tests passed and 0 critical security findings
- **3 s**: the rollback time

**Tip:** don't rush this slide. Those three numbers are your whole story.

---

## Slide 2 — The problem

**Say:**
> "Yesterday ₹48 Cr of payments succeeded, but only ₹45.8 Cr reached merchants. That's ₹2.2 Cr missing, and Operations couldn't say why. The data was split across four systems and they only had nightly Excel. The gap could come from failed payments, pending settlements, delays, risky merchants, or simply bad data. So we set out to build one place that shows the KPIs, explains the gap, flags bad merchants, and does it automatically and reliably."

**Likely questions:**
- *Why not just fix the Excel?* Excel can't join 4 sources reliably every day, and it can't handle late or duplicate events. It also has no tests and no audit trail.

---

## Slide 3 — How the data flows (the architecture)

**Say:**
> "Data flows left to right. Four CSV files are loaded by a Python ingestion step, which only picks up new files. Inside DuckDB we have three layers:
> - **Bronze** is a raw copy, where we reject nothing, so we can always trace back.
> - **Silver** is validated: correct types, duplicates removed, bad rows sent to a log with a reason.
> - **Gold** is the star schema plus a daily KPI table.
>
> A FastAPI service reads Gold in read-only mode, and the dashboard reads only from the API."

**How we did it:**
- **DuckDB** is a full SQL database stored in one file. We used it instead of Snowflake: no server, no account, it runs anywhere.
- **Medallion architecture:** Bronze = what we received, Silver = what we can trust, Gold = what the business needs.
- **ELT** (Extract, Load, Transform): we load raw data first, then transform it with SQL inside the database. The SQL files are `01_bronze.sql` to `05_silver_to_gold.sql`, and Python (`run_pipeline.py`) just runs them in order.
- **Incremental loading:**
  - `audit.loaded_files` remembers which files were already loaded.
  - A **watermark** means only new rows are processed.
  - Only the **dates that changed** are recalculated in the KPI table.
  - The full pipeline takes about 3 seconds.
- **`audit.dq_log`:** every bad record is logged with its reason, so nothing disappears silently.

**Likely questions:**
- *Why keep Bronze if it has bad data?* For audit and replay: if a rule was wrong, we can re-run from Bronze without asking the source again.
- *What if the same file arrives twice?* It's recorded in `loaded_files` and skipped, and upserts (`INSERT OR REPLACE`) prevent duplicate rows.

---

## Slide 4 — Cleaning the data (five hidden problems)

**Say:**
> "The data had five traps. Each row of the table shows the problem and our fix."

| Problem | What we did | Explain it like this |
|---|---|---|
| One payment, several settlements | Sum the settlements per payment **before** joining | T1001 = ₹10,000 settled as 8,000 + 2,000. If you join first and then sum, you count the payment twice and get 20,000 (200 %). This exact bug came back in the incident. |
| Late events | Store both `event_ts` (when it happened) and `ingestion_ts` (when we got it). More than 5 min late = kept but flagged. | Late data is still real data, so we don't drop it. |
| Out-of-order events | Order by event time and sequence, not arrival | "Settled" can arrive before "captured". |
| Merchant risk changes | SCD Type 2, which keeps history | A merchant that was LOW in August and HIGH in September: each payment gets the risk valid **on its date**. |
| Dirty records | REJECT / QUARANTINE / WARNING, logged with a reason | See the theory box on the slide. |

The numbers on the right:
- **3,830 → 3,800** transactions (raw → trusted)
- **158** quarantined
- **28** rejected
- **372** late events kept and flagged

**Theory (the three data-quality classes):**
- **REJECT** = unusable, for example a missing id or an amount that isn't a number. It stays out.
- **QUARANTINE** = possibly valid but suspicious, for example an unknown merchant or a settlement with no matching payment. It is kept aside for review.
- **WARNING** = loaded but flagged, for example a late event.

**Likely questions:**
- *How did you detect bad types?* `TRY_CAST`: if the conversion fails it returns NULL, and NULL leads to REJECT with a reason.
- *How did you remove duplicates?* `QUALIFY row_number() OVER (PARTITION BY id ORDER BY ingestion_ts DESC) = 1` keeps the latest copy.

---

## Slide 5 — The data model (star schema)

**Say:**
> "In Gold we built a star schema. In the centre is `fact_transaction`, where one row is one payment attempt. Around it are the dimensions (date, merchant, customer) and two more facts: settlements and payment events. `agg_merchant_daily` holds pre-calculated KPIs per merchant per day, so the API is fast."

**Theory:**
- **Grain** = what ONE row means. Always write it down.
  - `fact_transaction`: one row = one payment.
  - `fact_settlement`: one row = one settlement record.
  - If you join them directly, one payment with 2 settlements becomes 2 rows and the amount doubles. Mixing grains is the classic bug.
- **Fact vs dimension:** facts are events with numbers (amounts); dimensions describe them (who, when, where).
- **SCD Type 2 (Slowly Changing Dimension):** when a merchant's risk changes, we don't overwrite it.
  - We close the old row (`valid_to`) and add a new row (`valid_from`), with a **surrogate key**.
- **Customer privacy:** the customer id is stored only as a **sha256 hash**, so we can count customers without knowing who they are.
- Constraints:
  - primary keys, foreign keys and CHECK rules (for example, amount ≥ 0)
  - indexes on date and merchant

**Likely questions:**
- *Where is the one-to-many fix?* In the view `v_txn_settlement`: it sums settlements per transaction first, then joins.

---

## Slide 6 — API and dashboard (the answer)

**Say:**
> "Here is the answer for September:
> - 3,383 successful payments worth ₹4.13 Cr
> - a settlement rate of 93.72 %, below the 95 % target
> - a gap of ₹25.95 L
> - only 77 % settled within 30 minutes, against a 90 % target
>
> The dark box breaks down the gap: ₹14.07 L was never settled, ₹8.10 L is still pending, and ₹3.79 L was only partly settled. The worst merchants are M117, M108 and M104. So we can now tell Operations exactly where the money is and who to call first."

**How we did it:**
- **FastAPI** (Python web framework) with **Pydantic** models (validation), which automatically produces **OpenAPI** docs at `/docs`.
- The endpoints:
  - `/api/v1/settlement-summary` returns the KPIs for a date range
  - `/api/v1/merchant-exceptions` returns the problem payments for a merchant
  - `/daily-trend` returns the chart data
  - `/merchants` returns the merchant list
  - `/health` shows the status, database file and version
- **Security:**
  - the **X-API-Key** header, compared with `secrets.compare_digest` (safe against timing attacks)
  - if no key is configured, the API **fails closed** (503)
  - a **read-only** database connection
  - **bind parameters (`?`)**, so SQL injection is impossible
  - the merchant id must match the regex `^M\d{3,6}$`, otherwise 422
- **Error codes:** 400 (bad date range), 401 (missing or wrong key), 404 (unknown merchant), 422 (invalid input).
- The **dashboard** (`frontend/index.html`) is plain HTML/JS that only calls the API, never the database.

**Likely questions:**
- *Why is the rate below 100 % and not simply the failed payments?* Failed payments are excluded from the denominator; the gap is only about **successful** payments that weren't fully settled.
- *Why read-only?* The dashboard should never be able to change money data.

---

## Slide 7 — CI/CD workflow (the table)

**Say:**
> "Before any change reaches users, it goes through these gates in order. If any gate fails, the pipeline stops."

Go through the table row by row, one sentence each:

| Stage | What to say |
|---|---|
| Validate | "First we check every Python file compiles: a cheap, fast check." |
| Automated tests | "22 pytest tests: KPI formulas, business rules, the pipeline, the data model, the API contract and security. All pass." |
| SAST: **Bandit** | "Static analysis reads our own code for insecure patterns, like SQL built from strings. 0 high findings. It flagged 3 medium ones, which we reviewed: they're constant table names, and the values use `?` parameters." |
| Secret scan: **Gitleaks** | "It searches every file and the whole git history for passwords or keys. None found: our API key is a masked variable, never in code." |
| SCA: **pip-audit** | "Software composition analysis checks the open-source libraries we use against public vulnerability databases (CVEs). None vulnerable." |
| Build: **Docker** | "We build one image containing the code, the data and the database, tagged with the commit id and pushed to the GitLab registry." |
| Container scan: **Trivy** | "It scans the whole image, including operating-system packages. 0 critical. The 44 high ones are in the base OS and have no fix yet, so they are documented." |
| Deploy to dev | "The image is started as a container and must answer." |
| Smoke test | "A quick check that's about business, not just health: the response is JSON, answers in under 500 ms, and the settlement rate is between 0 and 100 **and equals the 93.72 % baseline**." |
| Reconciliation | "The KPI table must match the raw facts exactly." |
| Deploy to production | "A person must press the button: manual approval. The image is tagged `:production`." |

**Theory (if asked):**
- **CI (Continuous Integration):** every push is automatically built, tested and scanned.
- **CD (Continuous Delivery):** the same tested image is promoted to dev and then production, with a human approval at the end.
- **SAST vs SCA vs container scan:** our code vs other people's libraries vs the whole packaged image.
- **Severity levels:** LOW → MEDIUM → HIGH → CRITICAL. The bank's rule is **0 critical**.
- The 22 tests by type:
  - Unit 2
  - Business rules 10
  - Pipeline 1
  - Data model 3
  - API 4
  - Security 2 (a request without a key gets 401, and SQL injection is blocked with 422)
- **The most important test:** a ₹10,000 payment settled as 8,000 + 2,000 must show 100 %, never 200 %.

**Likely questions:**
- *Why is the smoke test different from /health?* `/health` only says "I'm running". The smoke test asks "are my numbers right?", and that's what caught the incident.
- *Why doesn't the image contain the API key?* Secrets must never be baked into images. The key is passed at run time with `-e API_KEY`.

---

## Slide 8 — Pipelines in action (the evidence)

**Say:**
> "Here are the real runs. At the top, GitLab: 10 jobs green, 22 tests reported, and production approved manually. Below, Jenkins builds #1 and #2, both green. GitLab is our main path and Jenkins is the backup, and both build the same image from the same code."

**How we did it (Docker in CI):**
- **GitLab and Docker-in-Docker (dind):**
  - Each GitLab job runs in a fresh container.
  - To build a Docker image **inside** a container, the job uses the `docker:27` image plus a `docker:27-dind` service, a second Docker engine running beside it.
  - The build job pushes the image to the GitLab Container Registry.
  - The smoke test does `docker run -e API_KEY ...` and then calls the API.
- **Jenkins and docker.sock:**
  - Jenkins runs in its own container, built from a custom image with Python and the Docker CLI.
  - The host's `/var/run/docker.sock` is mounted into it, so Jenkins uses the **VM's Docker engine** directly (called "Docker-outside-of-Docker").
  - The pipeline is defined in a `Jenkinsfile` in the repo ("pipeline as code").
- **A problem we found and fixed:** in Jenkins build #1, pip-audit silently failed, because the `| tee` pipe hid its error. We fixed the Jenkinsfile to keep the exit code, and build #2 shows a real clean result. This is a nice honest story to tell.
- **Why keep Jenkins at all?**
  - Many banks still run older systems on it.
  - It's a backup if GitLab is down.
  - It lets us migrate gradually.

**Likely questions:**
- *Docker-in-Docker vs docker.sock?* dind gives the job its own isolated Docker engine, which is cleaner and safer. docker.sock reuses the host engine, which is simpler and faster but gives the container power over the host.
- *What's an artifact?* A file a job saves, such as test reports or scan results. They are our evidence.

---

## Slide 9 — Blue-green deployment

**Say:**
> "In production we run two copies of the app. **Blue** is V1 on port 8001, **green** is V2 on port 8002, and **Nginx** in front sends users to one of them.
>
> We deployed V2 to green while users were still on blue. We ran every check on green (health, API, database, pipelines, tests, smoke test, reconciliation), then switched Nginx at 21:41:52. No downtime, users now on V2 at 93.72 %, and blue kept running as our safety net."

**Theory:**
- **Blue-green:** two identical environments. Release to the idle one, test it with no users on it, then switch all traffic at once. **Rollback = switch back, in seconds.**
- **Docker Compose:** one YAML file (`deploy/docker-compose.yml`) starts blue, green and Nginx together on a private network, where they find each other by name.
- **The switch:**
  - `switch.ps1 green` rewrites `nginx/default.conf` to point at green.
  - It then runs `nginx -s reload`, which applies the change without dropping connections.
- **Cold start:** the first request after start-up is slow (about 1 second), so we warmed green up before the switch.

**Likely questions:**
- *Why not update in place?* If the new version is bad, users are hit immediately, and going back means redeploying. With blue-green, the old version is still running.
- *Downside?* You pay for two environments. Fine for a critical banking service.

---

## Slide 10 — The incident

**Say:**
> "Then, as the exercise, a faulty release, 2.0.1, replaced the green environment. Look at the dashboard:
> - a settlement rate of **103.98 %**, which is impossible, because you can't settle more than was paid
> - a **negative** gap of −₹16.5 L
> - 21 merchants showing more money settled than they were paid
> - 3 problem merchants disappeared from the list
>
> And the dangerous part: **/health still said OK**. Status 200, no errors in the logs. Only the business check caught it."

**Point at the /health screenshot:**
- version **2.0.1**
- database file **settlement_db_v2**, which is not the approved database

**Key message:** *"A healthy service can still give wrong answers. That's why we test business numbers, not just uptime."*

---

## Slide 11 — Finding the cause

**Say:**
> "We compared V1 and V2 side by side. The payment amount is identical, ₹4,13,42,329. But the settled amount jumped from ₹3.87 Cr to ₹4.30 Cr. Same input, different output, so the bug is in the calculation, not the data. Then we checked the code diff, the configuration and the logs, and found three defects."

| Defect | Explanation |
|---|---|
| **A: Grain bug** | The new SQL joined transactions to settlements **before** summing, so a payment split into 2 settlements was counted twice. This is the same trap from slide 4. |
| **C: Wrong config** | It read `settlement_db_v2` instead of the approved database. |
| **D: Missing guard** | The check that keeps the rate between 0 and 100 was removed, so the impossible number reached users. |
| **B: Date bug (checked)** | We suspected a timezone/date bug too, but the daily totals matched V1, so it wasn't there. Saying "we checked and ruled it out" shows discipline. |

**Theory (health check vs smoke test):**
- `/health` asks "is it running?"
- The smoke test and reconciliation ask "are the numbers right?" Both **failed**:
  - the smoke test got 103.98 % against the 93.72 % baseline
  - reconciliation found ₹4.30 Cr settled in the KPI table against ₹3.87 Cr in the facts

**How we detected it:**

```bash
python day2/scripts/smoke_test.py --url http://localhost:8090 --key <key> --expected-rate 93.72
```

We also ran `common.reconcile`, which exits with code 1 when there's a mismatch.

---

## Slide 12 — Decision and recovery

**Say (walk through the timeline):**
> - "22:05:24: the bad 2.0.1 goes live."
> - "22:06:25: the smoke test spots it, about a minute later."
> - "22:06:40: root cause found."
> - "22:13:39: we decided to roll back."
> - "22:13:42: V1 is live again, 3 seconds later."
> - "22:13:51: the smoke test and reconciliation confirm 93.72 % again."

**Why roll back instead of fixing it live:**
1. Wrong money numbers were in front of users **right now**.
2. V1 was proven that morning and was **still running** on blue.
3. There were several bugs at once, so a live patch was risky.
4. Switching back takes seconds; a proper fix takes hours plus testing.

**How:** we ran `switch.ps1 blue`, Nginx reloaded, and users were back on V1. The screenshot shows 93.72 % and a gap of ₹25,95,426 after the rollback.

**Likely questions:**
- *What about the green environment now?* It stays isolated for investigation. The fix goes through the full pipeline again, never straight to production.
- *MTTD / MTTR?* Mean Time To Detect was about 1 minute; Mean Time To Recover was 3 seconds from the decision.

---

## Slide 13 — Lessons learned (prevention)

**Say:**
> "Root cause, using 5 Whys:
> 1. Why did users see 103.98 %? Settled amounts were double-counted.
> 2. Why? The SQL joined before aggregating.
> 3. Why did that reach production? Nothing checked the business number before the switch.
> 4. Why not? The process only checked /health.
> 5. Why? Business validation wasn't part of the release gate.
>
> So we added controls. Three are already in place:
> - a **regression test** for split settlements
> - a **reconciliation gate**
> - a **business smoke test** in the pipeline
>
> Two are proposed:
> - a **KPI alert** when the rate jumps or goes outside 0–100 %
> - a **SQL review** for any change to Gold numbers."

**Theory:**
- **5 Whys:** keep asking "why" until you reach a process cause, not a person to blame.
- **Blameless postmortem:** we fix the system, not the individual.

---

## Slide 14 — Closing

**Say:**
> "To wrap up, the bank now has five things:
> 1. **Visibility**: daily KPIs instead of nightly Excel.
> 2. **Investigation**: the gap broken down by reason, merchant and day.
> 3. **Trust in data**: bad data logged, numbers reconciled.
> 4. **Safe releases**: tests, four security scans, approval, blue-green.
> 5. **Fast recovery**: a bad release rolled back in 3 seconds.
>
> Every number in this deck is backed by saved evidence: test reports, scan results, pipeline runs, smoke tests and the incident timeline. Thank you, happy to take questions."

---

## Quick-reference cheat sheet (memorise these)

| Thing | Value |
|---|---|
| Successful transactions | 3,383 |
| Payment volume | ₹4.13 Cr (₹4,13,42,329) |
| Settled | ₹3.87 Cr (₹3,87,46,904) |
| Settlement rate | 93.72 % (target 95 %) |
| Settlement gap | ₹25.95 L (₹25,95,426) |
| SLA within 30 min | 77.09 % (target 90 %) |
| Gap by reason | never settled ₹14.07 L · pending ₹8.10 L · partly settled ₹3.79 L |
| Risky merchants | 5 (M117, M108, M104 worst) |
| Data quality | 3,830 → 3,800 · 158 quarantined · 28 rejected · 372 late |
| Tests | 22 / 22 passed |
| Security | Bandit 0 high · Gitleaks none · pip-audit none · Trivy 0 critical |
| Cutover to V2 | 21:41:52 |
| Incident | 103.98 %, gap −₹16.5 L, v2.0.1, settlement_db_v2 |
| Rollback | 3 seconds (22:13:39 → 22:13:42) |

## Tools summary (if someone asks "what did you use?")

| Area | Tool |
|---|---|
| Language | Python 3.12 |
| Warehouse | DuckDB (Bronze / Silver / Gold in SQL) |
| API | FastAPI + Pydantic + Uvicorn |
| Dashboard | HTML + JavaScript |
| Tests | pytest (+ FastAPI TestClient) |
| SAST | Bandit |
| Secret scan | Gitleaks |
| SCA | pip-audit |
| Container scan | Trivy |
| Packaging | Docker |
| CI/CD main | GitLab CI (Docker-in-Docker, Container Registry) |
| CI backup | Jenkins (Jenkinsfile, docker.sock) |
| Production | Docker Compose + Nginx (blue-green) |

## Presenting tips
- Tell it as a **story**: problem → solution → prove it's safe → it broke → we recovered → lessons.
- On evidence slides, **point** at the screenshot while you talk.
- If you don't know an answer, say "I'd check the evidence folder; we saved every result," then move on.
- Practise slides 10–12 (the incident) twice. They're the most interesting part for leadership.
