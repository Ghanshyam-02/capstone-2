# Day 2 – Production Readiness, Blue-Green Cutover & Incident Recovery

📄 Problem statement: [00_problem_statement.pdf](00_problem_statement.pdf)

> **Status:** plan + learning path. Implementation comes next, step by step, once you are comfortable
> with the tools below.

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
| Midday | **Incident** | After cutover the settlement rate shows **103.7 %** (was ~95 %) while the API still returns 200. Four hidden defects in V2: **A** grain join (settlements joined before aggregation), **B** filter on `ingestion_ts` instead of `transaction_ts`, **C** V2 points to `settlement_db_v2`, **D** API divides by transaction count instead of amount. |
| Midday | **Detect → Decide → Recover** | Compare V1 vs V2, business impact, root cause, decision (rollback vs fix forward), rollback GREEN → BLUE, smoke tests, KPI validation, timeline, incident report, 5 Whys, ≥ 3 preventive controls |
| Afternoon | **Task 6 – Presentation** | 8 slides: problem, architecture, production readiness, incident, decision, recovery, prevention, business outcome |
| Afternoon | **Task 7 – 360° peer review** | Score another team 1–5 on 9 areas and answer 5 questions |

## 3. Production requirements and how we will meet them
| Requirement | Target | How (Day 1 already gives us ✅) |
|---|---|---|
| Test suite | 100 % passing | ✅ 46 tests in `day1/tests` (all categories Day 2 lists), run in CI |
| Critical security findings | 0 | Bandit + Gitleaks + pip-audit + Trivy in CI, fix anything critical |
| API health | HTTP 200 | ✅ `/health` checks the database and returns the version |
| API response | < 500 ms | ✅ tested in `test_api.py`, measured again in the smoke test |
| Deployment | GitLab CI | `.gitlab-ci.yml` at the repo root |
| Secondary build path | Jenkins | `day2/Jenkinsfile`, Jenkins running in Docker |
| Deployment strategy | Blue-Green | Docker Compose: `blue` + `green` containers behind **Nginx** |
| Rollback | Required | switch Nginx back to blue (one command) |
| Production secrets | none hard-coded | ✅ `.env` / CI variables, plus secret scan |
| Production smoke test | Mandatory | `day2/scripts/smoke_test.py` (status, JSON, KPI values, time) |
| Data reconciliation | Mandatory | `day2/scripts/kpi_reconciliation.py`: API KPIs vs direct SQL |
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

## 5. Planned structure
```
day2/
├── README.md                  ← this plan
├── GUIDE.md                   ← step-by-step with theory (like Day 1)
├── Jenkinsfile                ← Task 4
├── deploy/
│   ├── docker-compose.yml     ← blue (V1) + green (V2) + nginx
│   ├── nginx.conf             ← which colour gets the traffic
│   └── switch.ps1 / .sh       ← cutover and rollback in one command
├── v2/                        ← Version 2 WITH the 4 injected defects (A, B, C, D)
├── scripts/
│   ├── smoke_test.py          ← /health, /settlement-summary, /merchant-exceptions checks
│   ├── kpi_reconciliation.py  ← API KPIs vs direct SQL on the database
│   └── security_gate.ps1      ← bandit, gitleaks, pip-audit, trivy
├── evidence/                  ← 01_test_results … 09_kpi_reconciliation
├── incident/                  ← timeline, incident report, 5 Whys, preventive controls
└── presentation/              ← 8-slide outline + 360° peer-review template
.gitlab-ci.yml (repo root)     ← Task 3 production pipeline (GitLab reads it from the root)
```

## 6. Implementation plan (we will do these together)
1. **Test gate:** run `day1` tests and save the report (JUnit XML) as evidence. Add a CI regression check that the settlement rate is ≤ 100 %.
2. **Security gate:** run Bandit, Gitleaks, pip-audit and Trivy. Record the findings and whether each blocks production.
3. **GitLab CI:** write the root `.gitlab-ci.yml` with all 8 stages and the required keywords, then run it on gitlab.com.
4. **Jenkins:** start Jenkins in Docker, add the `Jenkinsfile`, and run it to produce the same image as an artifact.
5. **Blue-green:** build `settlement-api:v1` and `:v2`, start compose (100 % → blue), run pre-cutover checks + smoke test on green, then switch.
6. **Incident:** V2 shows ~103.7 %. Detect it with the KPI smoke test (not `/health`), compare against V1, find defects A–D, **roll back** to blue, re-run the smoke test and reconciliation, and write the timeline, incident report and 5 Whys.
7. **Prevention:** add the controls to the pipeline: the multiple-settlement regression test, a reconciliation gate (settled ≤ successful), a KPI-based smoke test, and SQL review for Gold changes.
8. **Presentation + peer review:** fill in the slide outline with your real evidence.

Start with topics 1–4 (Docker, Compose, Nginx, blue-green). They are needed first and take about half a day.
