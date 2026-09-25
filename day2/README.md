# Day 2 – Production Readiness, Blue-Green Cutover & Incident Recovery

📄 Problem statement: [00_problem_statement.pdf](00_problem_statement.pdf)

📚 Theory for every Day 2 topic: **[LEARN.md](LEARN.md)**
🎤 Leadership presentation / viva script with Q&A: **[VIVA_SCRIPT.md](VIVA_SCRIPT.md)**

👉 **Step-by-step (Windows VM with Docker): [GUIDE.md](GUIDE.md)**

> **Status:** implemented and tested on the VM: test gate, security gate, Jenkins pipeline, blue-green cutover,
> incident injection, detection and rollback. The GitLab pipeline (`../.gitlab-ci.yml`) is ready to run once the
> repo is imported into GitLab.

---

## 1. What Day 2 is about (in one paragraph)
Day 1 built the application. Day 2 does **not** rebuild it. It proves the application is **production-ready**:
ship it safely through a CI/CD pipeline with security gates, deploy a new version with **blue-green**
(two copies, switch traffic only when the new one is proven good), then handle a **deliberately broken
release**: detect it, decide, roll back, prove recovery with evidence, and present it all to leadership.

## 2. What is asked, part by part
| Time | Task | What you must deliver |
|---|---|---|
| Morning | **Task 1 – Test gate** | Full test suite green: unit → data model → pipeline → API → business rules → security. Includes the **mandatory negative test** (multiple settlements must not inflate the rate). |
| Morning | **Task 2 – Security gate** | SAST (insecure code), secret scan (no keys or passwords in the repo), SCA (vulnerable libraries: severity, blocks prod?, fix), container scan (Docker image) |
| Morning | **Task 3 – GitLab CI pipeline** | Stages `validate → test → security → build → package → deploy_dev → smoke_test → deploy_prod` (manual approval), using stages, jobs, artifacts, cache, rules, needs, protected variables, environments |
| Morning | **Task 4 – Jenkins** | A `Jenkinsfile`: checkout → install → test → security → build image → publish artifact. Explain why enterprises keep Jenkins next to GitLab CI. |
| Morning | **Task 5 – Blue-green** | BLUE = V1 gets 100 % traffic, GREEN = V2 is deployed. Pre-cutover checks + smoke test (`/health`, `/settlement-summary`, `/merchant-exceptions`: 200, valid JSON, correct KPIs, fast), then switch 100 % to GREEN. |
| Morning | **Evidence package** | `01_test_results … 09_kpi_reconciliation`. *"It worked" is not enough – prove it.* |
| Midday | **Incident** | After cutover the settlement rate shows **103.7 %** (was ~95 %) while the API still returns 200. Four hidden defects in V2: **A** grain join (settlements joined before aggregation), **B** filter on `ingestion_ts` instead of `transaction_ts`, **C** V2 points to `settlement_db_v2`, **D** API divides by transaction count instead of amount. *(Our faulty V2 injects A, C and D, which gives 103.98 %.)* |
| Midday | **Detect → Decide → Recover** | Compare V1 vs V2, business impact, root cause, decision (rollback vs fix forward), rollback GREEN → BLUE, smoke tests, KPI validation, timeline, incident report, 5 Whys, ≥ 3 preventive controls |
| Afternoon | **Task 6 – Presentation** | 8 slides: problem, architecture, production readiness, incident, decision, recovery, prevention, business outcome |
| Afternoon | **Task 7 – 360° peer review** | Score another team 1–5 on 9 areas and answer 5 questions |

## 3. Production requirements and how we will meet them
| Requirement | Target | How (Day 1 already gives us ✅) |
|---|---|---|
| Test suite | 100 % passing | ✅ 22 tests in `day1/tests` (all categories Day 2 lists), run in CI |
| Critical security findings | 0 | Bandit + Gitleaks + pip-audit + Trivy in CI, fix anything critical |
| API health | HTTP 200 | ✅ `/health` checks the database and returns the version |
| API response | < 500 ms | measured in the smoke test (the API currently answers in < 100 ms) |
| Deployment | GitLab CI | `.gitlab-ci.yml` at the repo root |
| Secondary build path | Jenkins | `day2/Jenkinsfile`, Jenkins running in Docker |
| Deployment strategy | Blue-Green | Docker Compose: `blue` + `green` containers behind **Nginx** |
| Rollback | Required | switch Nginx back to blue (one command) |
| Production secrets | none hard-coded | ✅ `.env` / CI variables, plus secret scan |
| Production smoke test | Mandatory | `day2/scripts/smoke_test.py` (status, JSON, KPI values, time) |
| Data reconciliation | Mandatory | `python -m common.reconcile` (facts vs KPI table) + smoke test `--expected-rate` (API vs reconciled value) |
| Evidence | Mandatory | `day2/evidence/01_… 09_…` + incident folder |

## 4. What to learn (in this order)

| # | Topic | Why Day 2 needs it | Learn these concepts | Time |
|---|---|---|---|---|
| 1 | **Docker** | Every step runs the app as an image (V1, V2) | image vs container, `Dockerfile`, `docker build / run / ps / logs / stop`, ports, env variables, image tags | 2–3 h |
| 2 | **Docker Compose** | Runs blue, green and the load balancer together | `docker-compose.yml`, services, networks, `up -d`, `down`, `logs` | 1 h |
| 3 | **Nginx (basics)** | The load balancer that sends traffic to blue or green | reverse proxy, `upstream`, `proxy_pass`, reload config | 1 h |
| 4 | **Blue-green deployment** | The deployment strategy required | two identical environments, cutover, instant rollback, vs rolling/canary | 30 min |
| 5 | **GitLab CI** | The primary production pipeline | `.gitlab-ci.yml`, stages, jobs, `artifacts`, `cache`, `rules`, `needs`, variables (protected / masked), `environment`, `when: manual`, runners | 3–4 h |
| 6 | **Jenkins** | The secondary build path | Jenkins in Docker, declarative `Jenkinsfile` (`pipeline`, `agent`, `stages`, `steps`, `post`), `archiveArtifacts`, credentials | 2–3 h |
| 7 | **DevSecOps tools** | The security gate | SAST = **Bandit**, secret scan = **Gitleaks**, SCA = **pip-audit**, container scan = **Trivy**; severity levels and "does it block prod?" | 2 h |
| 8 | **Smoke tests & reconciliation** | Prove a deployment is correct, not just "up" | health vs business smoke test, compare API KPIs to SQL, response time | 30 min |
| 9 | **Incident management** | The midday incident | detect → assess impact → decide → rollback → verify → evidence, incident timeline, incident report, **5 Whys**, preventive controls | 1 h |
| 10 | **Presenting to leadership** | Afternoon | business-first story, one message per slide, evidence over opinions | 1 h |

**Not needed:** Kubernetes, cloud accounts or Snowflake. Everything runs on your laptop with Docker, and
GitLab / Jenkins just run the same commands.

### Install / accounts needed on your device
| Tool | Why | Note |
|---|---|---|
| **Docker Desktop** | images, compose, Jenkins, Trivy | needs WSL2 on Windows (`wsl --install`, restart) |
| **GitLab account** (gitlab.com) | GitLab CI | import the GitHub repo into GitLab (*New project → Import → GitHub*). CI minutes on gitlab.com may ask you to verify your account. |
| **Jenkins** | secondary pipeline | runs as a Docker container, nothing to install |
| Python tools | bandit, pip-audit | `pip install bandit pip-audit` |
| Gitleaks, Trivy | secret and container scans | run as Docker images, nothing to install |

## 5. What is in this folder
```
day2/
├── README.md, GUIDE.md, LEARN.md, VIVA_SCRIPT.md
├── Jenkinsfile                   ← Task 4: secondary build path
├── jenkins/Dockerfile            ← Jenkins + Python + Docker CLI (runs as a container)
├── deploy/
│   ├── docker-compose.yml        ← blue (V1) + green (V2) + nginx load balancer
│   ├── nginx/default.conf        ← which colour is live
│   ├── switch.ps1                ← cutover / rollback in one command
│   └── .env.example              ← API key for the containers
├── scripts/
│   ├── smoke_test.py             ← /health, /settlement-summary, /merchant-exceptions: 200, JSON, KPI values, time
│   └── security_gate.ps1         ← Bandit, Gitleaks, pip-audit, Trivy
├── incident/
│   ├── v2-defects/               ← the faulty V2 release (defects A, C, D injected)
│   └── INCIDENT_REPORT.md        ← timeline, report, decision, 5 Whys, controls
└── evidence/                     ← 01_test_results … 09_kpi_reconciliation (you generate them)
../.gitlab-ci.yml                 ← Task 3: primary production pipeline (GitLab reads it from the root)
../day1/common/reconcile.py       ← KPI reconciliation (facts vs KPI table), used as a gate
```

## 6. Results on the VM (what you should see)
| Check | V1 / V2 (good) | Faulty V2 (incident) |
|---|---|---|
| `/health` | 200 · 1.0.0 / 2.0.0 · settlement.duckdb | **200** · 2.0.1 · **settlement_db_v2.duckdb** |
| Settlement rate | **93.72 %** | **103.98 %** |
| Smoke test | PASS | **FAIL** (rate outside 0–100, ≠ baseline) |
| Reconciliation | PASS | **FAIL** (21 merchants settled > successful) |
| Rollback time | – | ~1 second (`switch.ps1 blue`) |
| Security gate | SAST, secrets, SCA, container: PASS, 0 critical | – |
| Jenkins | SUCCESS (6 stages) | – |
