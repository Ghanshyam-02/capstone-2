# 6. Deployment Design

```
GitLab (merge to main)
  │
  ▼
CI pipeline ── tests ── SAST ── dependency scan ── docker build & push (tag = commit SHA)
  │
  ▼
DEV  (automatic)  ──▶  TEST (manual click)  ──▶  PROD (manual click = approval)
```
File: [`../.gitlab-ci.yml`](../.gitlab-ci.yml) (Day 1 design; Day 2 builds the full production pipeline).

| Topic | Design |
|---|---|
| **Build** | `Dockerfile` installs the requirements, copies the code and the CSV files, and **runs the pipeline inside the image**. Every container of a version serves exactly the same validated data. |
| **Environment configuration** | The same image everywhere. Behaviour comes from environment variables: `API_KEY`, `APP_VERSION`, `SETTLEMENT_DB` (which database file to use). |
| **Secrets** | GitLab CI/CD variables (masked, protected, scoped per environment). Never in Git or in the image. |
| **Health check** | `GET /health` returns 200 with the version when the database is readable, 503 otherwise. Used by Docker `HEALTHCHECK` and the platform. |
| **Smoke test** | After each deploy, call `/health` and `/api/v1/merchant-exceptions` with the API key. A failure stops promotion. |
| **Rollback** | Every commit has its own image tag. Rolling back = starting the previous tag again. Because the data is built into the image, the old version comes back with its own data too. |
| **Pipeline schedule** | In production the pipeline (`python -m pipeline.run_pipeline`) would run on a schedule (cron / Airflow) as new files arrive. |

## Run the container locally
```bash
docker build -t settlement-api:1.0 .
docker run -p 8000:8000 -e API_KEY=my-key settlement-api:1.0
```
