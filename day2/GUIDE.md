# Day 2 – Step-by-step guide (Windows VM)

Everything runs in the **VM** (Docker Desktop running = "Engine running").
Use **PowerShell**. Theory for every step: [LEARN.md](LEARN.md). Evidence files: [evidence/README.md](evidence/README.md).

| Step | Brief task | Result |
|---|---|---|
| 0 | Set up | code + Python in the VM |
| 1 | Task 1 – Test gate | 22 tests green → evidence 01 |
| 2 | Build the release images | `settlement-api:v1`, `:v2` → evidence 05 |
| 3 | Task 2 – Security gate | SAST, secrets, SCA, container scan → evidence 02 |
| 4 | Task 3 – GitLab CI | primary pipeline → evidence 03 |
| 5 | Task 4 – Jenkins | secondary pipeline → evidence 04 |
| 6 | Task 5 – Blue-green | V1 → V2 cutover → evidence 06–09 |
| 7 | Midday – Incident | detect, decide, roll back, prove → `incident/` |
| 8 | Afternoon | presentation + peer review → [VIVA_SCRIPT.md](VIVA_SCRIPT.md) |

Ports used on the VM: **8001** blue · **8002** green · **8090** load balancer (what users call) · **8081** Jenkins.

---

## Step 0: Set up
```powershell
cd $HOME\Desktop
git clone https://github.com/Ghanshyam-02/capstone-2.git     # or: cd capstone-2; git pull
cd capstone-2
cd day1
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
cd ..
```
Allow PowerShell scripts (`.ps1`) to run, once:
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```
Stay in the **repo root** (`capstone-2`) with `(.venv)` active for all the steps below.

---

## Step 1: Test gate (Task 1)
**Theory:** a *gate* stops the release if any required test fails. The brief's order is
unit → data model → pipeline → API → business rules → security. *(LEARN.md §2)*

```powershell
cd day1
pytest -v tests/test_unit_kpi.py tests/test_data_model.py tests/test_pipeline.py tests/test_api.py tests/test_business_rules.py tests/test_security.py --junitxml=..\day2\evidence\01_test_results.xml | Tee-Object ..\day2\evidence\01_test_results.txt
cd ..
```
✅ `22 passed`. The **mandatory negative test** is `test_multiple_settlements_do_not_inflate_the_settlement_rate`.

---

## Step 2: Build the release images
**Theory:** the image *is* the release. V1 and V2 are the same app, built with a different version number. *(LEARN.md §4)*

```powershell
docker build -t settlement-api:v1 day1
docker build -t settlement-api:v2 --build-arg APP_VERSION=2.0.0 day1
docker images settlement-api | Tee-Object day2\evidence\05_docker_image.txt
```
✅ Two images, `v1` and `v2`. Each build runs the pipeline **inside** the image (look for `[bronze] ... rows loaded`).

---

## Step 3: Security gate (Task 2)
**Theory:** SAST = our code, secret scan = keys in the repo and git history, SCA = our libraries,
container scan = the whole image. Rule: **0 critical**. *(LEARN.md §3)*

```powershell
.\day2\scripts\security_gate.ps1
```
✅ The summary shows 4 × PASS. Reports are in `day2\evidence\02_security_results\`.

**Findings to write down** (the brief asks: dependency, severity, blocks production?, remediation):
| Check | Finding | Severity | Blocks? | Remediation |
|---|---|---|---|---|
| SAST (Bandit) | B608 "SQL built from strings" ×3 in `pipeline/` | Medium | No | false positive: only table names from constants are inserted, all values use `?` bind parameters |
| SAST (Bandit) | B110 try/except/pass in `run_pipeline.py` | Low | No | accepted: only used to ignore "no transaction to roll back" |
| Secret scan | none | – | No | – |
| SCA (pip-audit) | none known | – | No | re-run on every build |
| Container (Trivy) | ~44 HIGH in Debian base packages (util-linux, ncurses …), **0 CRITICAL** | High | No (rule is 0 critical) | rebuild on a patched `python:3.12-slim` when fixes are released |

*(Your numbers may differ slightly: new CVEs are published every day.)*

---

## Step 4: GitLab CI – primary path (Task 3)
**Theory:** stages, jobs, artifacts, cache, rules, needs, protected variables, environments, manual approval. *(LEARN.md §7)*
The pipeline is [`../.gitlab-ci.yml`](../.gitlab-ci.yml) (GitLab reads it from the repo root):
```
validate → test → security (sast, secret_scan, sca) → build → package (container scan)
        → deploy_dev → smoke_test → deploy_prod (manual)
```
1. On **gitlab.com**: *New project → Import project → GitHub* → select `capstone-2`
   (or *Repository by URL*: `https://github.com/Ghanshyam-02/capstone-2.git`).
2. *Settings → CI/CD → Variables → Add variable*: key `API_KEY`, any long value, tick **Masked** and **Protected**.
3. *Build → Pipelines → Run pipeline* (branch `main`).
4. When `smoke_test` is green, click ▶ on **deploy_prod**. That's the **manual approval**.
5. Screenshot the pipeline → `day2\evidence\03_gitlab_pipeline.png`. Download artifacts (test report, bandit, gitleaks, trivy, smoke test) from the jobs.

> GitLab.com may ask you to verify your account (phone or card) before shared runners run pipelines.

**Keywords – where to find them in the file:** `stages` (top) · `artifacts` (tests, sast …) · `cache` (default) ·
`rules` (workflow, `.main_only`, deploy_prod) · `needs` (every job) · protected variable `API_KEY` (smoke_test) ·
`environment` (deploy_dev, deploy_prod) · `when: manual` (deploy_prod).

---

## Step 5: Jenkins – secondary path (Task 4)
**Theory:** Jenkins independently builds the **same artifact**. Why keep it next to GitLab? Legacy workloads,
a backup path if GitLab is down, plugins, and a risky big-bang migration. *(LEARN.md §8)*

```powershell
docker build -t settlement-jenkins day2\jenkins
docker run -d --name jenkins -u root -p 8081:8080 -v jenkins_home:/var/jenkins_home -v //var/run/docker.sock:/var/run/docker.sock settlement-jenkins
```
Open **http://localhost:8081** (no login in this local setup), then:
1. **New Item** → name `settlement-platform` → **Pipeline** → OK.
2. *Pipeline* section → Definition **Pipeline script from SCM** → SCM **Git** →
   Repository URL `https://github.com/Ghanshyam-02/capstone-2.git` → Branch `*/main` →
   Script Path **`day2/Jenkinsfile`** → **Save**.
3. **Build Now** and wait about 2 minutes.

✅ **SUCCESS**, with stages Checkout → Install Dependencies → Run Tests → Security Checks → Build Docker Image → Publish Artifact.
Screenshot → `day2\evidence\04_jenkins_pipeline.png`. *Console Output* → save as `04_jenkins_console.txt`.
The built image is `settlement-api:jenkins-1` (`docker images settlement-api`).

---

## Step 6: Blue-green deployment (Task 5)
**Theory:** BLUE = V1 with 100 % of traffic. GREEN = V2 is deployed and checked first, then the traffic switch.
Rollback = switch back. *(LEARN.md §5, 6, 9, 10)*

```
Browser → http://localhost:8090 → Nginx (lb) → blue:8000 (V1)   ← live
                                             → green:8000 (V2)
```
Files: [deploy/docker-compose.yml](deploy/docker-compose.yml) · [deploy/nginx/default.conf](deploy/nginx/default.conf) · [deploy/switch.ps1](deploy/switch.ps1)

**6.1 Start BLUE (V1) behind the load balancer**
```powershell
cd day2\deploy
copy .env.example .env
docker compose up -d blue lb
docker compose ps
```
Wait until blue shows `(healthy)` (about 30 s). Open **http://localhost:8090**. The dashboard works (key: `change-me-to-a-long-random-string`).

**6.2 Deploy GREEN (V2): no traffic yet**
```powershell
docker compose up -d green
```

**6.3 Pre-cutover checks on GREEN**
| Brief check | Command |
|---|---|
| application + API health | `Invoke-RestMethod http://localhost:8002/health` |
| database connectivity | same output: `database ok`, `database_file settlement.duckdb` |
| pipeline health + test suite | Steps 1, 4, 5 are green |
| KPI reconciliation | `docker compose exec green python -m common.reconcile` |
| smoke test | `python ..\scripts\smoke_test.py --url http://localhost:8002 --key change-me-to-a-long-random-string --expected-rate 93.72` |

Save the evidence:
```powershell
docker compose exec green python -m common.reconcile | Tee-Object ..\evidence\09_kpi_reconciliation.txt
```
✅ Reconciliation `RESULT: PASS` (93.72 %) and smoke test `RESULT: PASS`.

**6.4 Cutover: 100 % traffic → GREEN**
```powershell
.\switch.ps1 green
Invoke-RestMethod http://localhost:8090/health | Tee-Object ..\evidence\06_deployment_version.txt
python ..\scripts\smoke_test.py --url http://localhost:8090 --key change-me-to-a-long-random-string --expected-rate 93.72 | Tee-Object ..\evidence\08_smoke_test_results.txt
```
✅ `version 2.0.0`, `live colour=green`, smoke test PASS. `evidence\07_blue_green_status.txt` records the switch.

📸 **The evidence package 01–09 is now complete.**

---

## Step 7: Midday – injected production incident
**Theory:** detect → investigate → assess impact → decide → roll back → verify → evidence. *(LEARN.md §12–15)*
Write the time of each step in [incident/INCIDENT_REPORT.md](incident/INCIDENT_REPORT.md) as you go.

```powershell
mkdir ..\incident\evidence
```

**7.1 Break production.** A faulty V2 release (2.0.1) replaces GREEN, which is live. See [incident/v2-defects/Dockerfile](incident/v2-defects/Dockerfile).
```powershell
docker build -t settlement-api:v2-incident ..\incident\v2-defects
$env:GREEN_IMAGE = "v2-incident"; docker compose up -d green; Remove-Item Env:GREEN_IMAGE
```

**7.2 Detect.** Open the dashboard at http://localhost:8090 → **Settlement Rate 103.98 %** 😱 (screenshot).
```powershell
Invoke-RestMethod http://localhost:8090/health | Tee-Object ..\incident\evidence\01_health_still_ok.txt
python ..\scripts\smoke_test.py --url http://localhost:8090 --key change-me-to-a-long-random-string --expected-rate 93.72 | Tee-Object ..\incident\evidence\02_smoke_test_FAIL.txt
docker compose exec green python -m common.reconcile | Tee-Object ..\incident\evidence\03_reconciliation_FAIL.txt
```
- `/health` still returns **200** → a health check alone does not catch it.
- But it shows **version 2.0.1** and **`settlement_db_v2.duckdb`**: a changed version and the **wrong database** (configuration defect).
- The smoke test **FAILS**: 103.98 %, outside 0–100 and not the 93.72 % baseline.
- The reconciliation **FAILS**: settled 42.99 M vs 38.75 M, and 21 merchants have settled > successful.

**7.3 Investigate: previous (BLUE, still running) vs current (GREEN)**
```powershell
Invoke-RestMethod "http://localhost:8001/api/v1/settlement-summary?start_date=2026-09-01&end_date=2026-09-30" -Headers @{ "X-API-Key" = "change-me-to-a-long-random-string" } | Tee-Object ..\incident\evidence\04a_v1_summary.txt
Invoke-RestMethod "http://localhost:8002/api/v1/settlement-summary?start_date=2026-09-01&end_date=2026-09-30" -Headers @{ "X-API-Key" = "change-me-to-a-long-random-string" } | Tee-Object ..\incident\evidence\04b_v2_summary.txt
docker compose logs green --tail 20
```
Same `transaction_amount`, but a different `settled_amount`, so the defect is in the **settled calculation**. Compare
[incident/v2-defects/sql/05_silver_to_gold.sql](incident/v2-defects/sql/05_silver_to_gold.sql) with `day1/sql/05_silver_to_gold.sql`.
It **joins settlements before aggregating** (defect A).

**7.4 Decide: rollback.** Wrong money numbers are live, V1 is proven and one switch away, and the cause spans several defects.

**7.5 Rollback and verify**
```powershell
.\switch.ps1 blue
python ..\scripts\smoke_test.py --url http://localhost:8090 --key change-me-to-a-long-random-string --expected-rate 93.72 | Tee-Object ..\incident\evidence\05_smoke_after_rollback_PASS.txt
docker compose exec blue python -m common.reconcile | Tee-Object ..\incident\evidence\06_reconciliation_after_rollback_PASS.txt
```
✅ `live colour=blue`, version 1.0.0, rate **93.72 %** = baseline → **production restored**.

**7.6 Write it up.** Complete [incident/INCIDENT_REPORT.md](incident/INCIDENT_REPORT.md): timeline, report, decision, 5 Whys, controls.

---

## Step 8: Afternoon
- **Task 6 – presentation:** [VIVA_SCRIPT.md](VIVA_SCRIPT.md), 8 slides. Put your evidence numbers in the `[ … ]`.
- **Task 7 – peer review:** the scoring table and 5 questions are at the end of VIVA_SCRIPT.md.

---

## Clean up (when finished)
```powershell
cd day2\deploy
docker compose down
docker rm -f jenkins
```

## Troubleshooting
| Problem | Fix |
|---|---|
| `port is already allocated` | another program uses the port: `netstat -ano \| findstr :8090`, or change the port in docker-compose.yml |
| `nginx: host not found in upstream "green"` | start green first (`docker compose up -d green`) before `switch.ps1 green` |
| smoke test `401` | the key must match `day2\deploy\.env` |
| blue/green `(unhealthy)` | `docker compose logs blue` |
| Jenkins `docker: permission denied` | the container must run with `-u root` and the `docker.sock` mount (Step 5) |
| `apt-get update` warning while building Jenkins | harmless (repository clock skew). The Dockerfile tolerates it. |
| Trivy is slow the first time | it downloads its vulnerability database (~few hundred MB) once |
