# Day 2 – Theory to learn

Everything you need to understand for Day 2, one topic at a time, with examples from **our** project.
Read this before we implement Day 2. Each topic ends with **"Say it in the viva"**: one or two sentences
you should be able to say from memory.

| # | Topic | Day 2 task |
|---|---|---|
| 1 | Production readiness | whole day |
| 2 | Test gate | Task 1 |
| 3 | DevSecOps: SAST, secret scan, SCA, container scan | Task 2 |
| 4 | Docker | Tasks 2–5 |
| 5 | Docker Compose | Task 5 |
| 6 | Nginx as a load balancer | Task 5 |
| 7 | CI/CD and GitLab CI | Task 3 |
| 8 | Jenkins | Task 4 |
| 9 | Blue-green deployment | Task 5 |
| 10 | Smoke tests & KPI reconciliation | Task 5 |
| 11 | Evidence | Evidence package |
| 12 | Incident management | Midday |
| 13 | The 4 injected defects | Midday |
| 14 | Rollback vs fix forward | Midday |
| 15 | Root cause analysis (5 Whys) & preventive controls | Midday |
| 16 | Presenting to leadership & peer review | Afternoon |

---

## 1. Production readiness
**What:** proof that software can safely run for real users. Working on your laptop is not enough.
It must be **deployable** (automated pipeline), **observable** (health, logs, KPIs), **recoverable**
(rollback) and **secure** (scans, no secrets).

**Our project:** Day 1 already has tests, `/health` with a version, config from environment variables, and a
Docker image. Day 2 adds the gates, the pipelines, blue-green and the evidence.

**Say it in the viva:** *"Production-ready means I can prove, with evidence, that it is tested, secure,
deployable, observable and recoverable, not just that it runs."*

---

## 2. Test gate
**What:** a **gate** is an automatic check in the pipeline. If it fails, the pipeline stops and nothing is deployed.
Day 2 wants all test types in order: unit → data model → pipeline → API → business rules → security.

**Our project:** `day1/tests` already covers each group (22 tests). In CI we run `pytest --junitxml=report.xml`.
The XML is the evidence (`01_test_results`).

**Mandatory negative test:** "the system does **not** calculate an incorrect settlement rate when one transaction
has several settlements". Ours: `test_multiple_settlements_do_not_inflate_the_settlement_rate`.

**Say it in the viva:** *"The test gate stops a release automatically. 100 % of required tests must pass,
including a negative test for the one-to-many settlement trap."*

---

## 3. DevSecOps – the security gate
**DevSecOps** = security checks built into the pipeline, run on every change, instead of a review at the end.

| Check | Question it answers | Tool we use | Example finding |
|---|---|---|---|
| **SAST** (Static Application Security Testing) | Is my **code** written insecurely? | **Bandit** (Python) | SQL built with an f-string, use of `eval`, binding to all interfaces |
| **Secret scan** | Did anyone commit a **key or password**? | **Gitleaks** | `API_KEY=abc123…` in a file or in Git history |
| **SCA** (Software Composition Analysis) | Do my **libraries** have known vulnerabilities (CVEs)? | **pip-audit** | `fastapi 0.x` has CVE-XXXX, fixed in 0.y |
| **Container scan** | Does my **Docker image** (OS packages + libraries) have vulnerabilities? | **Trivy** | an old `openssl` in the base image |

**Severity:** CRITICAL > HIGH > MEDIUM > LOW. Bank rule: **0 critical findings**.
For each finding, write down: which dependency, severity, **does it block production?** (critical / high = yes),
and the **remediation** (upgrade the version, change the base image, or accept the risk with a reason).

**Say it in the viva:** *"SAST checks my code, secret scanning checks for credentials, SCA checks my
libraries, and the container scan checks the whole image. Critical findings block the release."*

---

## 4. Docker
**Image:** a packaged, read-only template: OS + Python + libraries + our code + our database.
**Container:** a running image. You can run many containers from one image.
**Tag:** a version label: `settlement-api:v1`, `settlement-api:v2`.
**Registry:** a store for images (GitLab Container Registry, Docker Hub).

**Commands:**
```
docker build -t settlement-api:v1 .       # build an image from the Dockerfile
docker images                             # list images
docker run -d -p 8001:8000 -e API_KEY=k --name blue settlement-api:v1
docker ps                                 # running containers (+ health status)
docker logs blue                          # application logs
docker stop blue && docker rm blue
```
**Our Dockerfile** (`day1/Dockerfile`): install requirements → copy code + CSVs → **run the pipeline inside the
image** (the database is baked in) → non-root user → HEALTHCHECK → start uvicorn.

**Say it in the viva:** *"The image is the release. The same image moves from DEV to PROD, so what we
tested is exactly what runs."*

---

## 5. Docker Compose
**What:** one YAML file that starts several containers together, with a shared network.
```yaml
services:
  blue:  { image: settlement-api:v1, environment: [API_KEY=${API_KEY}] }
  green: { image: settlement-api:v2, environment: [API_KEY=${API_KEY}] }
  lb:    { image: nginx, ports: ["8080:80"], volumes: ["./nginx.conf:/etc/nginx/nginx.conf"] }
```
`docker compose up -d` starts everything, `docker compose ps` shows status, `docker compose down` stops it.
Inside the network, containers reach each other by name: `http://blue:8000`.

**Say it in the viva:** *"Compose runs our whole production setup, blue, green and the load balancer,
on one machine with one command."*

---

## 6. Nginx as a load balancer / reverse proxy
**Reverse proxy:** users call Nginx, and Nginx forwards the request to the real app.
**Load balancer:** decides **which** app gets the traffic.
```nginx
upstream live { server blue:8000; }        # change to green:8000 for the cutover
server { listen 80; location / { proxy_pass http://live; } }
```
Switching blue → green = change one line + `nginx -s reload`. No downtime, and users keep the same URL.

**Say it in the viva:** *"Nginx is the switch. Users always call the same address, and I decide
behind it whether blue or green answers."*

---

## 7. CI/CD and GitLab CI
**CI (Continuous Integration):** every push is automatically built, tested and scanned.
**CD (Continuous Delivery):** the same artifact is automatically deployed to DEV, and to PROD after approval.

GitLab reads **`.gitlab-ci.yml` from the repo root**. A **runner** (a machine) executes the jobs.

| Keyword | Meaning | In our pipeline |
|---|---|---|
| `stages` | ordered phases | validate → test → security → build → package → deploy_dev → smoke_test → deploy_prod |
| job | a named task inside a stage | `unit_tests`, `bandit`, `docker_build` … |
| `script` | commands the job runs | `pytest --junitxml=report.xml` |
| `artifacts` | files a job keeps (download, pass to later jobs) | test report, security reports, SBOM |
| `cache` | files reused between pipelines to go faster | the pip download cache |
| `rules` | when a job runs | only on `main`, or only if `day1/**` changed |
| `needs` | start a job as soon as specific jobs finish (not the whole stage) | `smoke_test` needs `deploy_dev` |
| `variables` | settings. **Protected** = only on protected branches, **masked** = hidden in logs | `API_KEY` |
| `environment` | named target, with deployment history | `dev`, `production` |
| `when: manual` | a human must click ▶ | `deploy_prod` = the **controlled approval** |
| `image` / `services` | the Docker image the job runs in / helper containers | `python:3.12-slim`, `docker:dind` |

**Say it in the viva:** *"GitLab CI is our primary path: eight stages with artifacts as evidence, cache
for speed, rules and needs for control, protected variables for secrets, and a manual approval before
production."*

---

## 8. Jenkins
**What:** the older, very widely used automation server. A **Jenkinsfile** describes the pipeline in code:
```groovy
pipeline {
  agent any
  stages {
    stage('Checkout')             { steps { checkout scm } }
    stage('Install Dependencies') { steps { sh 'pip install -r day1/requirements-dev.txt' } }
    stage('Run Tests')            { steps { sh 'cd day1 && pytest --junitxml=report.xml' } }
    stage('Security Checks')      { steps { sh 'bandit -r day1 -ll' } }
    stage('Build Docker Image')   { steps { sh 'docker build -t settlement-api:$BUILD_NUMBER day1' } }
    stage('Publish Artifact')     { steps { archiveArtifacts 'day1/report.xml' } }
  }
  post { always { junit 'day1/report.xml' } }
}
```
We run Jenkins itself as a Docker container on the laptop.

**Why keep Jenkins alongside GitLab CI?** (a Day 2 question)
- Legacy workloads and teams already use Jenkins, and migrating everything at once is risky.
- A **secondary build path** means you can still build and ship if GitLab is down (business continuity).
- Jenkins has a huge plugin ecosystem, and some enterprise tools only integrate with Jenkins.
- Some regulated or on-premise environments only allow the approved Jenkins servers.
- Both paths produce the **same artifact**, so production doesn't care which one built it.

**Say it in the viva:** *"GitLab CI is primary. Jenkins is a secondary, independent path that builds the
same artifact, for resilience and because the enterprise still depends on it for legacy workloads."*

---

## 9. Blue-green deployment
**What:** two identical production environments.
**BLUE** = the current version (V1) with 100 % of traffic. **GREEN** = the new version (V2), deployed but getting no traffic.
1. Deploy V2 to green.
2. Run the **pre-cutover checks** on green: app health, API health, database connectivity, pipeline health,
   test suite, smoke test, KPI reconciliation.
3. Only if everything passes: switch 100 % of traffic → green.
4. Keep blue running. **Rollback = switch back**, which takes seconds.

**Compared with other strategies:** *rolling* replaces servers one by one (slow rollback). *Canary* sends a small
% of traffic first (needs more tooling). Blue-green has the **fastest, simplest rollback** but needs 2× the resources.

**Say it in the viva:** *"Blue-green lets me test the new version in production conditions before any user
sees it, and roll back in seconds by switching traffic back."*

---

## 10. Smoke tests & KPI reconciliation
**Smoke test:** a few quick, real calls after a deploy. Day 2 requires:
`GET /health`, `GET /api/v1/settlement-summary`, `GET /api/v1/merchant-exceptions`, and to verify
**HTTP 200, valid JSON, correct KPI values, acceptable response time**.

**The key lesson:** `/health` only proves the app is **alive**, not that it is **right**. In the incident the API
still returns 200 while the settlement rate is 103.7 % (103.98 % in our run). So the smoke test must check **business values**, e.g.
`0 ≤ settlement_rate ≤ 100`, and that it equals the baseline.

**KPI reconciliation:** calculate the KPIs **independently** with SQL straight on the database, and compare them
with what the API returns. They must match. Also check that settled ≤ successful per merchant.

**Say it in the viva:** *"A green health check is not proof. My smoke test checks the business numbers
and reconciles the API against the database."*

---

## 11. Evidence
*"It worked" is not sufficient – prove it.* For each claim, save a file: a report, a screenshot, a command output
or a log with a timestamp.
`01_test_results` · `02_security_results` · `03_gitlab_pipeline` · `04_jenkins_pipeline` · `05_docker_image` ·
`06_deployment_version` · `07_blue_green_status` · `08_smoke_test_results` · `09_kpi_reconciliation`.

**Say it in the viva:** *"Every statement on my slides points to an evidence file."*

---

## 12. Incident management
The flow Day 2 asks for:
```
Detect → Investigate → Assess impact → Decide → Rollback → Verify → Produce evidence
```
- **Detect:** notice the abnormality (settlement rate 103.7 %, settled > successful for some merchants).
  Compare **previous vs current production**: API response, logs, deployment version, KPIs, SQL output,
  pipeline artifacts.
- **Business impact:** which KPIs are wrong (settlement rate, gap, merchant exceptions)? Who is affected
  (Operations decisions, merchant escalations)? Which category is it: application, data, deployment, query,
  configuration or pipeline problem?
- **Timeline:** timestamped steps from deployment to recovery (real times from your evidence).
- **Incident report fields:** ID, date, application, version, what happened, business impact, detection
  method, technical root cause, evidence, decision, rollback performed, validation, preventive action,
  owner, due date.

**Say it in the viva:** *"I treated it like a real incident: detect with evidence, measure the business
impact, decide, recover, and prove the recovery."*

---

## 13. The 4 injected defects in Version 2
| Defect | What V2 does wrong | Symptom | Category |
|---|---|---|---|
| **A – Grain** | joins `fact_transaction` to `fact_settlement` **before** aggregating | settled amount inflated → rate > 100 % | query / data-model |
| **B – Date** | filters on `ingestion_ts` instead of `transaction_ts` | daily KPIs shift to other days | query |
| **C – Config** | points to `settlement_db_v2` instead of the approved database | wrong or stale numbers | configuration |
| **D – API calculation** | `settled_amount / transaction_count` instead of `/ successful_transaction_amount` | nonsense rate | application |

How each is detected: **A** by the reconciliation check (settled ≤ successful) and the rate > 100 %, **B** by comparing
daily totals with V1, **C** by `/health` showing a different database or version and by config diff, **D** by
recalculating the rate from the SQL output. Day 1's `v_txn_settlement` is exactly the fix for A.

**Say it in the viva:** *"The worst defects are the ones that return HTTP 200 with wrong numbers. Only
business-level checks catch them."*

---

## 14. Rollback vs fix forward
| | Rollback (go back to V1) | Fix forward (patch V2 in production) |
|---|---|---|
| Speed to correct numbers | seconds with blue-green | unknown: diagnose, code, test, deploy |
| Risk | low, V1 is proven | high, changing code under pressure |
| When to choose | wrong financial numbers, cause not fully understood, V1 available | tiny, well-understood fix, and rollback impossible |

For a bank showing wrong settlement figures, **rollback first**, then fix V2 calmly with a new test, and redeploy
through the full pipeline.
After rollback: remove traffic from green → blue serves 100 % → smoke tests → KPI validation (rate back to the
baseline from **our** dataset, 93.72 % for September) → production restored.

**Say it in the viva:** *"Wrong money numbers and a known-good V1 one switch away made rollback the lowest-risk
decision. We fix V2 afterwards, with evidence, through the normal pipeline."*

---

## 15. Root cause analysis (5 Whys) & preventive controls
**5 Whys:** keep asking "why?" until you reach a **process** cause, not just a code line.
```
Why was the settlement rate > 100 %?          → the settled amount was inflated
Why?                                          → several settlement rows were joined to each transaction
Why?                                          → V2 changed the Gold aggregation logic (join before aggregation)
Why was this not detected before production?  → the smoke test only checked /health, not KPI values
Why?                                          → no gate compared KPIs with the baseline / reconciliation
```
**Preventive controls (at least 3):**
1. A regression test for one transaction → multiple settlements (we already have it: make it a required gate).
2. A reconciliation gate: settled amount ≤ successful amount, API KPIs = SQL KPIs.
3. KPI anomaly monitoring: alert if the settlement rate moves more than X points or goes above 100 %.
4. Mandatory SQL / data-model review for any change to Gold-layer metrics.
5. Blue-green smoke tests on business KPIs, not only `/health`.

**Say it in the viva:** *"The root cause was not just a bad join. It was a pipeline that let unverified KPI changes
reach production. The controls close that gap permanently."*

---

## 16. Presenting to leadership & 360° peer review
**Leadership presentation (8–10 min, 8 slides):** problem → architecture → production readiness → incident →
decision → recovery → prevention → business outcome. Lead with **business impact**, back every claim with
**evidence**, and give one message per slide.

**360° peer review:** you score another team 1–5 on technical implementation, data modelling, testing, security,
CI/CD, incident response, communication, business understanding and collaboration. Then answer: what was strong,
the biggest risk, was the decision evidence-based, was the rollback adequate, and one improvement.
Be specific and kind: "The smoke test only checked /health" is better than "testing was weak".

**Say it in the viva:** *"Leadership cares about impact, risk and recovery time. Engineers care about the
details. The same evidence answers both."*
