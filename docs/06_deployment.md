# 6. Deployment Design

```
GitLab (merge to main)
  │
  ▼
CI pipeline ── unit + API tests ── SAST (GitLab SAST / Bandit) ── dependency scan (pip-audit) ── docker build & push (tag = commit SHA)
  │
  ▼
DEV  (automatic)  ──▶  TEST (manual click)  ──▶  PROD (manual click = approval)
```
File: [`.gitlab-ci.yml`](../.gitlab-ci.yml). The same checks also run on GitHub: [`.github/workflows/ci.yml`](../.github/workflows/ci.yml).

| Topic | Design |
|---|---|
| **Environment configuration** | Same image everywhere; behaviour comes from env variables. Each env has its own Snowflake database: `SETTLEMENT_DB_DEV`, `_TEST`, `_PROD`. TEST can be a **zero-copy clone** of PROD (`CREATE DATABASE SETTLEMENT_DB_TEST CLONE SETTLEMENT_DB_PROD`) – instant, no extra storage. |
| **Secrets** | GitLab CI/CD variables (masked, protected, scoped per environment). Private key as a *File* variable, mounted read-only into the container. Never in Git or in the image. |
| **Health check** | `GET /health` → 200 when the API and Snowflake are reachable, 503 otherwise. Used by Docker `HEALTHCHECK` and the platform's readiness probe. |
| **Smoke test** | After each deploy CI calls `/health` and `/api/v1/data-range` with the API key; failure stops promotion. |
| **Rollback** | Every commit has its own image tag. `rollback_prod` job redeploys a previous tag (`ROLLBACK_TAG`). Data side: Snowflake **Time Travel** (`CREATE TABLE x CLONE x AT (OFFSET => -3600)`) restores a table to before a bad pipeline run. |
| **Pipeline schedule** | `python -m pipeline.run_pipeline` as a scheduled job (GitLab schedule / Airflow / Snowflake Task) every N minutes. |

## Run the container locally
```bash
docker build -t settlement-api:1.0 .
docker run -p 8000:8000 --env-file .env -v "${PWD}/keys:/app/keys:ro" settlement-api:1.0
```
