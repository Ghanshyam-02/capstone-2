# Presenter Guide — Merchant Settlement Intelligence Platform

This guide follows the **13-slide deck**. Aim for **12–15 minutes**, about 1 minute per slide.

Each slide has three parts:
- **Say:** a script you can read or paraphrase.
- **How we did it:** the background you need if someone asks.
- **Likely questions:** short answers.

For the incident in full depth, see [INCIDENT_DEEP_DIVE.md](INCIDENT_DEEP_DIVE.md).

| # | Slide | Time |
|---|---|---|
| 1 | Title | 0:30 |
| 2 | Problem Statement | 1:00 |
| 3 | DQ test and Data cleaning | 1:15 |
| 4 | Data Flow and Data Model | 1:30 |
| 5 | Dashboard and API | 1:00 |
| 6 | CICD workflow | 1:30 |
| 7 | Gitlab Pipeline | 1:00 |
| 8 | Jenkins Pipeline | 1:00 |
| 9 | Blue-Green Deployment | 1:00 |
| 10 | Bad Release Incident | 1:00 |
| 11 | Finding the cause | 1:30 |
| 12 | Rollback Scenario | 1:00 |
| 13 | Summary | 0:45 |

---

## Part 0 — The problem statement in plain words

**The story.** Bank of New York processes card and UPI payments for merchants.
1. A customer pays, and the payment is **successful** or **failed**.
2. For each successful payment, the bank later **settles** (sends) the money to the merchant.
3. Yesterday, ₹48 Cr of payments succeeded, but only ₹45.8 Cr was settled.
4. That leaves a **₹2.2 Cr gap**, and the Head of Payments asked: *"Where is this money, and why?"*

**Why nobody could answer:**
- The data sat in 4 places: **transactions**, **settlements**, **merchant risk**, and **payment events** (created → authorised → captured → settled).
- The team only had nightly Excel reports.
- The data was messy:
  - duplicates
  - late events
  - events out of order
  - one payment settled in several parts
  - merchant risk changing over time

**What we were asked to build:**
1. A data pipeline that cleans and models the data (DuckDB, Bronze/Silver/Gold).
2. KPIs: settlement rate, gap, SLA, exceptions, risky merchants.
3. An API and a dashboard.
4. Tests and security.
5. Production readiness: CI/CD (GitLab main, Jenkins backup), Docker, blue-green deployment.
6. An incident: a bad release goes live, and we detect, decide, roll back and verify it with evidence.

**The key terms:**

| Term | Meaning | Ours |
|---|---|---|
| Settlement rate | settled ÷ successful amount × 100 | **93.72 %** (target 95 %) |
| Settlement gap | successful − settled amount | **₹25.95 L** |
| SLA rate | % settled within 30 minutes | **77.09 %** (target 90 %) |
| Exception | an UNSETTLED / PENDING / PARTIALLY_SETTLED / DELAYED payment | 11 merchants |
| Risky merchant | rate < 95 % **and** SLA < 90 % | **5** |

Our data is a realistic sample: about 3,800 transactions for September. That's why our gap is ₹25.95 L, not ₹2.2 Cr. **The method is the same at any scale.** Say this if asked.

---

## Slide 1 — Title

**Say:**
> "Good morning. Our task was to explain a settlement gap nobody could explain. I'll show how we turned four messy source files into a tested, secure platform, shipped it with CI/CD and blue-green deployment, and what happened when a bad release reached production: we recovered in 3 seconds."

**Tip:** keep this to 30 seconds. The story is: problem → solution → safe releases → incident → recovery.

---

## Slide 2 — Problem Statement

**Say:**
> "Yesterday ₹48 Cr of payments succeeded, but only ₹45.8 Cr reached merchants, so ₹2.2 Cr is missing. Operations couldn't explain it: the data was spread across four systems, they only had nightly Excel, and the gap could come from failed payments, pending settlements, delays, risky merchants or bad data.
>
> The requirement was to show payment and settlement KPIs in one place, explain the gap, flag merchants that settle badly, and serve it all through an API and dashboard that loads new data incrementally and is tested automatically."

**Likely questions:**
- *Why not fix the Excel?* Excel can't reliably join 4 sources every day, handle late or duplicate events, or give tests and an audit trail.

---

## Slide 3 — DQ test and Data cleaning

**Say:**
> "Before we could trust any number, we had to clean the data. We found five traps. The left column is the problem, the right column our solution."

Walk through the table:

| Problem | Solution | How to explain it |
|---|---|---|
| One payment, several settlements | Sum the settlements per payment **before** joining | T1001 = ₹10,000 settled as 8,000 + 2,000. Join first, then sum, and you count it twice: 200 %. **This exact bug came back in the incident.** |
| Late events | Keep `event_ts` (when it happened) and `ingestion_ts` (when we got it); more than 5 min late = kept but flagged | Late data is still real data, so we don't drop it. |
| Wrong order | Order by event time, not arrival | "Settled" can arrive before "captured". |
| Merchant risk changes | SCD Type 2 keeps history | Each payment gets the risk valid **on its date**. |
| Dirty records | REJECT / QUARANTINE / WARNING, with a reason | See below. |

The numbers on the right:
- **3,830 → 3,800** payments (raw → trusted)
- **158** quarantined
- **28** rejected
- **372** late events kept and flagged

**Theory (the three data-quality classes):**
- **REJECT:** unusable (missing id, amount not a number). It stays out.
- **QUARANTINE:** suspicious but possibly valid (unknown merchant, a settlement with no payment). It is kept aside for review.
- **WARNING:** loaded but flagged (a late event).
- Every bad record is written to `audit.dq_log` with its reason, so **nothing disappears silently**.

**Likely questions:**
- *How did you catch bad types?* `TRY_CAST` returns NULL when a conversion fails, and a NULL leads to REJECT with a reason.
- *How did you remove duplicates?* `QUALIFY row_number() OVER (PARTITION BY id ORDER BY ingestion_ts DESC) = 1` keeps the latest copy.

---

## Slide 4 — Data Flow and Data Model

**Say (top half, the flow):**
> "Data flows left to right. Four CSV files are loaded by a Python ingestion step, which only picks up new files. Inside DuckDB we have three layers:
> - **Bronze** is a raw copy.
> - **Silver** is validated, correctly typed and de-duplicated.
> - **Gold** is the star schema plus a daily KPI table.
>
> FastAPI reads Gold in read-only mode, and the dashboard only talks to the API."

**Say (bottom half, the model):**
> "The Gold layer is a star schema. In the centre is `fact_transaction`, where one row is one payment attempt. Around it are the dimensions (date, merchant with history, hashed customer) and the other facts: settlements and payment events. `agg_merchant_daily` pre-calculates the KPIs per merchant per day, so the API is fast."

**How we did it:**
- **DuckDB** is a full SQL database in one file. No server or account needed; it runs anywhere.
- **Medallion architecture:** Bronze = what we received, Silver = what we can trust, Gold = what the business needs.
- **ELT:** load raw data first, then transform it with SQL inside the database (`01_bronze.sql` … `05_silver_to_gold.sql`). Python (`run_pipeline.py`) only runs the steps.
- **Incremental loading:**
  - `audit.loaded_files` stops the same file being loaded twice.
  - A watermark means only new rows are processed.
  - Only the dates that changed are recalculated.
  - The full run takes about 3 seconds.
- **Grain** = what ONE row means. Write it down for every table. Joining payments (one per row) to settlements (many per payment) duplicates rows.
- **SCD Type 2:** when a merchant's risk changes, close the old row (`valid_to`) and add a new one (`valid_from`), with a surrogate key.
- **Privacy:** the customer id is stored only as a sha256 hash.
- **Constraints:** primary and foreign keys, CHECK rules (for example amount ≥ 0), and indexes on date and merchant.

**Likely questions:**
- *Why keep Bronze if it has bad data?* For audit and replay: re-run from Bronze if a rule changes.
- *Where is the one-to-many fix?* In the view `v_txn_settlement`: it sums settlements per transaction first, then joins.

---

## Slide 5 — Dashboard and API

**Say:**
> "Here's the answer for September:
> - 3,383 successful payments worth ₹4.13 Cr
> - a settlement rate of 93.72 %, below the 95 % target
> - a gap of ₹25.95 L
> - only 77 % settled within 30 minutes, against a 90 % target
>
> The gap breaks down into ₹14.07 L never settled, ₹8.10 L still pending, and ₹3.79 L only partly settled. The worst merchants are M117, M108 and M104, so Operations knows exactly who to call first."

**How we did it:**
- **FastAPI + Pydantic** (input and output validation) + **OpenAPI** (automatic docs at `/docs`).
- The endpoints:
  - `/api/v1/settlement-summary` returns the KPIs for a date range
  - `/api/v1/merchant-exceptions` returns the problem payments
  - `/daily-trend` returns the chart data
  - `/merchants` returns the merchant list
  - `/health` shows the status, database file and version
- **Security:**
  - the **X-API-Key** header, compared with `secrets.compare_digest`
  - if no key is configured, the API **fails closed** (503)
  - a **read-only** database connection
  - **bind parameters (`?`)**, which prevent SQL injection
  - the merchant id is checked with the regex `^M\d{3,6}$`
- **Errors:** 400 bad date range · 401 missing or wrong key · 404 unknown merchant · 422 invalid input.
- The dashboard is plain HTML/JS that only calls the API.

**Likely questions:**
- *Why read-only?* A dashboard must never be able to change money data.

---

## Slide 6 — CICD workflow

**Say:**
> "Before any change reaches users it passes these gates, in order. If any gate fails, the pipeline stops."

Go row by row, one sentence each:

| Stage | Tool | What to say |
|---|---|---|
| Validate | python -m compileall | "Every Python file must compile: fast and cheap." |
| Automated tests | pytest | "22 tests covering KPI formulas, business rules, pipeline, data model, API and security. All pass." |
| SAST | **Bandit** | "Reads **our** code for insecure patterns, like SQL built from strings. 0 high. The 3 medium ones were reviewed: constant table names, with values passed as `?` parameters." |
| Secret scan | **Gitleaks** | "Searches every file **and the whole git history** for keys and passwords. None: the API key is a masked CI variable." |
| SCA | **pip-audit** | "Checks the open-source libraries we use against public vulnerability lists (CVEs). None found." |
| Build | **Docker** | "Code, data and database packed into one image, tagged with the commit id and pushed to the registry." |
| Container scan | **Trivy** | "Scans the whole image including OS packages. 0 critical; the 44 high ones are base-OS packages with no fix yet." |
| Deploy to dev | GitLab service | "The image starts and must answer." |
| Smoke test | smoke_test.py | "Business check: JSON, under 500 ms, rate between 0 and 100 **and equal to the 93.72 % baseline**." |
| Reconciliation | reconcile.py | "The KPI table must match the raw facts exactly." |
| Deploy to production | manual job | "A person approves; the image is tagged `:production`." |

**Theory:**
- **SAST vs SCA vs container scan:** our code vs other people's libraries vs the whole packaged image.
- **Severity levels:** LOW → MEDIUM → HIGH → CRITICAL. The bank's rule is **0 critical**, and every finding is reviewed.
- **The 22 tests:**
  - Unit 2
  - Business rules 10
  - Pipeline 1
  - Data model 3
  - API 4
  - Security 2 (a request without a key gets 401; SQL injection is blocked with 422)
- **The most important test:** a ₹10,000 payment settled as 8,000 + 2,000 must show 100 %, never 200 %.

**Likely questions:**
- *Smoke test vs /health?* `/health` says "I'm running". The smoke test asks "are my numbers right?", and that's what caught the incident.
- *Why isn't the API key in the image?* Secrets are never baked into images. It's passed at run time with `-e API_KEY`.

---

## Slide 7 — Gitlab Pipeline

**Say:**
> "GitLab CI is our main path. The chevrons are the 8 stages, from compile to manual approval. The screenshot is our real run: 10 jobs green, 22 tests reported, production approved. Every job runs in a fresh container, and the image is built only after all the checks pass."

**How we did it:**
- The pipeline is defined in `.gitlab-ci.yml` in the repo (pipeline as code).
- **Every job runs in a fresh container** on a GitLab runner (the Docker executor):
  - the tests use `python:3.12-slim`
  - the container is thrown away after each job
- **The build uses Docker-in-Docker (dind):**
  - The job runs in `docker:27` (the Docker CLI) with a `docker:27-dind` **service**: a second container running its own Docker engine.
  - `docker build` sends the `day1/` folder to that engine, which follows our Dockerfile:
    - `python:3.12-slim` base
    - pip install
    - copy the code and CSVs
    - run the pipeline to build the database
    - non-root user and HEALTHCHECK
  - The dind engine is thrown away after the job, so the image is **pushed to the GitLab Container Registry**, tagged with the commit id.
  - Later jobs pull it back:
    - Trivy scans it from the registry
    - the smoke test runs it with `docker run -e API_KEY ...` in another dind
    - `deploy_prod` tags it `:production`
- **Key keywords:**
  - `needs:` means the build waits for tests, SAST, secret scan and SCA
  - `rules:` means deploy only from `main`
  - `artifacts:` keeps the reports as evidence
  - `cache:` reuses pip downloads
  - `environment:` tracks dev and production
- **The API key** is a masked, protected CI/CD variable, available only on `main`.

**Theory (CI vs CD):**
- **CI (Continuous Integration):** every push is automatically built, tested and scanned.
- **CD (Continuous Delivery):** the same tested image is promoted from dev to production, with a person approving the last step.

**Likely questions:**
- *Why Docker-in-Docker?* Shared runners can't give you the host's Docker engine, which would be unsafe. dind gives each job its own isolated, disposable engine. The downsides: it needs privileged mode, has no cache between jobs, and images must go through the registry.
- *Does GitLab always use Docker to run tests?* It depends on the runner's **executor**. GitLab.com uses the Docker executor, so every job is a container. A self-hosted **shell** runner would run tests directly on the server.

---

## Slide 8 — Jenkins Pipeline

**Say:**
> "Jenkins is our backup path. It runs six stages: checkout, install, tests, security checks, build image, publish artifact. Builds #1 and #2 are both green. It builds the same image from the same code and Dockerfile, so production doesn't care which tool built it."

**How we did it:**
- **The Jenkins container:**
  - a custom image (`day2/jenkins/Dockerfile`): `jenkins/jenkins:lts-jdk17` plus **python3**, **python3-venv** and **docker-cli**
  - plugins: workflow-aggregator (Jenkinsfile), git, junit
  - the job is "Pipeline script from SCM", reading `day2/Jenkinsfile` from GitHub (pipeline as code)
- **How the tests run** (no container per job, unlike GitLab):
  1. `checkout scm` clones the repo into the workspace, inside the Jenkins container.
  2. `python3 -m venv .venv` creates a **virtual environment**: a private Python with its own libraries.
  3. `.venv/bin/pip install -r day1/requirements-dev.txt bandit pip-audit` installs the dependencies.
  4. `cd day1 && ../.venv/bin/pytest --junitxml=test-report.xml` runs the 22 tests (on Python 3.13 here, versus 3.12 in GitLab).
  5. `junit 'day1/test-report.xml'` shows "22 passed" in the Jenkins UI.
- **Security stage:** Bandit fails the build on HIGH findings; pip-audit audits the `.venv` and keeps its exit code.
- **How the image is built** (the Docker socket, not Docker-in-Docker):
  - The Jenkins container is started with `-v /var/run/docker.sock:/var/run/docker.sock` and `-u root`.
  - Its `docker` CLI talks to the **VM's own Docker engine** through that socket ("Docker-outside-of-Docker").
  - `docker build -t settlement-api:jenkins-<n> day1` builds the image **directly on the VM**. There's no push; the image id is saved in `image-id.txt`.
  - It's faster, because the host cache is reused. But Jenkins can control every container on the VM, which is fine on a private VM and risky on shared machines.
- **Something we caught:** in build #1, pip-audit silently failed because the `| tee` pipe hid its error code. We fixed the Jenkinsfile (upgraded pip, audit the venv, keep the exit code), and build #2 shows a real, clean result.

**Why keep Jenkins next to GitLab?**
- Many bank systems still run on it.
- It's a backup if GitLab is down.
- It has plugins for tools GitLab doesn't cover.
- It lets us migrate gradually.

**Likely questions:**
- *GitLab dind vs Jenkins docker.sock?*

  | | GitLab (dind) | Jenkins (docker.sock) |
  |---|---|---|
  | Engine | its own per job | the VM's engine |
  | Image | pushed to the registry | stored on the VM |
  | Isolation | high | low |
  | Speed | slower, no cache | faster, cached |

  The Dockerfile and the resulting image are the same.
- *Same tests on both?* Yes: the same 22 tests, passing on Python 3.12 (GitLab) and 3.13 (Jenkins).

---

## Slide 9 — Blue-Green Deployment

**Say:**
> "In production we run two copies of the app with Docker Compose. **Blue** is V1 on port 8001, **green** is V2 on port 8002, and **Nginx** on port 8090 sends users to one of them. We deployed V2 to green while users stayed on blue, and ran every check on the right-hand side against green. Then at 21:41:52 we switched Nginx to green with no downtime. Blue kept running as our safety net."

**How we did it:**
- `deploy/docker-compose.yml` starts blue, green and Nginx on one private network, where they find each other by name.
- **The switch:**
  - `switch.ps1 green` rewrites `nginx/default.conf` to point at green.
  - It then runs `nginx -s reload`, a graceful reload: requests in progress finish, and no connection is dropped.
- **Cold start:** the first request after start-up is slower (about 1 s), so we warmed green up before switching.

**Theory:** blue-green = two identical environments. Release to the idle one, test it with no users on it, switch all traffic at once. **Rollback = switch back, in seconds.**

**Likely questions:**
- *Why not update in place?* Users would be hit by a bad version immediately, and going back means redeploying.
- *Downside?* You pay for two environments. Worth it for a critical banking service.
- *Blue-green vs canary?* Canary sends a small % of users (5 % → 25 % → 100 %) to the new version first. Blue-green switches everyone at once.

---

## Slide 10 — Bad Release Incident

**Say:**
> "Then, as the exercise, a faulty release, 2.0.1, replaced the live green environment. The dashboard showed a settlement rate of **103.98 %**, which is impossible because you can't settle more than was paid, and a **negative** gap of −₹16.5 L. 21 merchants showed more money settled than paid, and 3 risky merchants disappeared from the list.
>
> But look at the /health screenshot: **200 OK**. The logs had no errors. The service was up, but wrong. Only a business check could catch it."

**Point at:** version **2.0.1** and database **settlement_db_v2** on /health. That's the first clue.

**How we created it:**
- We didn't change the data; we created a **bad release**.
- `day2/incident/v2-defects/Dockerfile` starts from the good V2 image and swaps 3 files and 1 setting (defects A, C and D).
- It was deployed straight to green, bypassing the pipeline, to simulate a bad release reaching production.

**Why "risky merchants dropped to 3" is the worst part:** the inflated rates pushed merchants above 95 %, so they vanished from the risk list. The bug didn't just show a wrong number, **it hid real problems**.

---

## Slide 11 — Finding the cause

**Say:**
> "Our business smoke test caught it about one minute after release: 103.98 % against the 93.72 % baseline. Reconciliation showed the settled amount in the KPI table didn't match the fact tables. Blue was still running, so we compared V1 and V2 side by side: the payment amount is identical, but the settled amount jumped from ₹3.87 Cr to ₹4.30 Cr. Same payments in, different settled amount out, so the bug is in the calculation, not the data. The code diff and config showed three defects."

| Defect | Explanation |
|---|---|
| **A: Grain bug** | The new SQL joined settlements **before** adding them up, so a payment split into 2 settlements was counted twice. This is the trap from slide 3. |
| **C: Wrong config** | It read `settlement_db_v2` instead of the approved database. |
| **D: Missing guard** | The 0–100 % limit was removed, so the impossible number reached users. With the guard, the API would have returned an error instead of a wrong number. |
| **B: Date bug (checked)** | Daily totals matched V1 for all 30 days, so dates weren't shifted. We tested the hypothesis and ruled it out. |

**Theory (health check vs smoke test):**
- `/health` asks "is it running?"
- The smoke test and reconciliation ask "are the numbers right?" Both **failed**.

**How we detected it** (run by hand on the VM, with the same scripts the GitLab pipeline uses):

```bash
python day2/scripts/smoke_test.py --url http://localhost:8090 --key <key> --expected-rate 93.72
python -m common.reconcile
```

**Likely questions:**
- *Did GitLab find it?* No. The bad release bypassed the pipeline, and we detected it with the same scripts run by hand. Had it gone through GitLab, it would have been stopped **twice**:
  - the regression test `test_multiple_settlements_do_not_inflate_the_settlement_rate` would fail (settled = 20,000, not 10,000)
  - the smoke test with `--expected-rate 93.72` would fail
  - Lesson: **no deployment outside the pipeline.**

---

## Slide 12 — Rollback Scenario

**Say:**
> - "22:05:24: the bad release goes live."
> - "22:06:25: spotted, one minute later."
> - "22:06:40: cause found."
> - "22:13:39: we decided to roll back."
> - "22:13:42: V1 live again, **3 seconds** later."
> - "22:13:51: numbers confirmed.
>
> As the paragraph says, with wrong money figures live and V1 proven and one switch away, we rolled back instead of patching live. `switch.ps1 blue` pointed Nginx back to blue and reloaded it without dropping requests. We re-ran the smoke test and reconciliation, both passed at 93.72 %, and kept green isolated for investigation."

**Why roll back rather than fix live:**
1. Wrong money numbers were live right now.
2. V1 was proven and still running.
3. There were several defects at once, so a live patch was risky.
4. Switching back takes seconds; a fix takes hours.

**Key metrics:**
- **MTTD** (time to detect) ≈ 1 minute
- **MTTR** (time to recover) = 3 seconds from the decision
- total user impact ≈ 8 minutes

**Likely questions:**
- *Why wait 7 minutes after finding the cause?* We gathered evidence first. Honestly, in real production you should **roll back first and investigate after**, since blue is still there to compare against. That would cut the impact to about 1 minute.
- *Is this automated in real production?* Usually partly:
  - A post-deploy **verification job** (our smoke test and reconciliation) runs automatically.
  - On failure, the pipeline runs a **rollback job**, or pages an on-call engineer for one-click approval, which is common in banks for business-number anomalies.
  - Canary tools (Argo Rollouts, Flagger, AWS CodeDeploy) can roll back by themselves when metrics get worse.
  - Monitoring (Prometheus/Grafana, Datadog) plus a **KPI alert** would catch a jump in the rate.
- *What next for green?* Fix all three defects and push through the full pipeline (tests, scans, smoke test against the baseline, reconciliation, approval). Then deploy to the idle environment and cut over again.
- *What did we learn? (5 Whys)*
  1. Why did users see 103.98 %? Settlements were double-counted.
  2. Why? The SQL joined before aggregating.
  3. Why did it reach production? Nothing checked the business number before the switch.
  4. Why? Only /health was checked.
  5. Why? Business validation wasn't part of the release gate.

  Controls in place: the regression test, the reconciliation gate, and the business smoke test. Proposed: a KPI alert and SQL review for Gold-layer changes. This is a **blameless postmortem**: we fix the process, not the person.

---

## Slide 13 — Summary

**Say (paraphrase the paragraph):**
> "To sum up: Operations couldn't explain a ₹2.2 Cr gap. We built a Bronze–Silver–Gold pipeline in DuckDB that loads incrementally, logs every bad record, and handles the traps in the data. A star schema feeds a secure API and dashboard, which show a 93.72 % rate, a ₹25.95 L gap and the merchants behind it.
>
> Every change passes 22 tests, four security scans, a Docker build, a business smoke test and reconciliation in GitLab, with Jenkins as backup, before a manual approval and blue-green release. When a bad release showed 103.98 % while /health said OK, our business checks caught it within a minute and we rolled back in 3 seconds.
>
> The bank now has clear visibility, numbers backed by evidence, and releases that are safe to ship and quick to undo. Thank you, happy to take questions."

Point at the four numbers at the bottom: **93.72 %**, **22/22**, **0 critical**, **3 s**.

---

## Quick-reference cheat sheet

| Thing | Value |
|---|---|
| Successful transactions | 3,383 |
| Payment volume | ₹4.13 Cr (₹4,13,42,329) |
| Settled | ₹3.87 Cr (₹3,87,46,904) |
| Settlement rate | 93.72 % (target 95 %) |
| Settlement gap | ₹25.95 L (₹25,95,426) |
| SLA within 30 min | 77.09 % (target 90 %) |
| Gap by reason | never settled ₹14.07 L · pending ₹8.10 L · partly settled ₹3.79 L |
| Risky merchants | 5 (worst: M117, M108, M104) |
| Data quality | 3,830 → 3,800 · 158 quarantined · 28 rejected · 372 late |
| Tests | 22 / 22 passed (Python 3.12 in GitLab, 3.13 in Jenkins) |
| Security | Bandit 0 high · Gitleaks none · pip-audit none · Trivy 0 critical |
| GitLab run | 10 jobs green, production approved |
| Jenkins | builds #1 and #2 green |
| Cutover to V2 | 21:41:52 |
| Incident | v2.0.1, settlement_db_v2, 103.98 %, gap −₹16.5 L, risky merchants 5 → 3 |
| Detected | 22:06:25 (≈ 1 min) |
| Rollback | 22:13:39 → 22:13:42 (3 s), confirmed 22:13:51 |

## Tools summary

| Area | Tool |
|---|---|
| Language | Python |
| Warehouse | DuckDB (Bronze / Silver / Gold in SQL) |
| API | FastAPI + Pydantic + Uvicorn |
| Dashboard | HTML + JavaScript |
| Tests | pytest + FastAPI TestClient |
| SAST | Bandit |
| Secret scan | Gitleaks |
| SCA | pip-audit |
| Container scan | Trivy |
| Packaging | Docker (image = code + data + database) |
| CI/CD main | GitLab CI (Docker executor, Docker-in-Docker, Container Registry) |
| CI backup | Jenkins (Jenkinsfile, Python venv, VM Docker via docker.sock) |
| Production | Docker Compose + Nginx (blue-green) |

## Presenting tips
- Tell it as a **story**: problem → clean data → answer → safe releases → it broke → we recovered.
- **One message ties it all together:** *a healthy service can still give wrong answers, so we check business numbers, not just uptime.* It links slide 3 (the join trap), slide 6 (the smoke test) and slides 10–12 (the incident).
- On screenshot slides, **point** at the part you're talking about.
- If you don't know an answer: "We saved every result in the evidence folder; I can show you after." Then move on.
- Practise slides 10–12 twice. They're what leadership will remember.
