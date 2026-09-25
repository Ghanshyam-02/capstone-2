# Production evidence package

> "It worked" is not sufficient. The data engineers must prove it worked.

Every file here is **produced by a command in [../GUIDE.md](../GUIDE.md)**. Screenshots go in the same folder.

| # | Evidence | How it is produced | File(s) |
|---|---|---|---|
| 01 | Test results | Step 1 – `pytest ... --junitxml` | `01_test_results.txt`, `01_test_results.xml` |
| 02 | Security results | Step 3 – `day2\scripts\security_gate.ps1` | `02_security_results\` (summary + 4 reports) |
| 03 | GitLab pipeline | Step 4 – screenshot of the green pipeline | `03_gitlab_pipeline.png` |
| 04 | Jenkins pipeline | Step 5 – screenshot + console log | `04_jenkins_pipeline.png`, `04_jenkins_console.txt` |
| 05 | Docker image | Step 2 – `docker images settlement-api` | `05_docker_image.txt` |
| 06 | Deployment version | Step 6 – `/health` through the load balancer | `06_deployment_version.txt` |
| 07 | Blue-green status | Step 6 – written automatically by `switch.ps1` | `07_blue_green_status.txt` |
| 08 | Smoke test results | Step 6 – `smoke_test.py` | `08_smoke_test_results.txt` |
| 09 | KPI reconciliation | Step 6 – `python -m common.reconcile` inside the container | `09_kpi_reconciliation.txt` |

Incident evidence (midday) goes in [`../incident/evidence/`](../incident/).
