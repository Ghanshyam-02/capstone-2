# Bank of New York – Merchant Settlement Intelligence Platform

Explains the gap between **successful payments** and **settled amounts** and flags merchants with poor settlement.

```
CSV files → INGESTION → BRONZE → SILVER → GOLD → API (FastAPI) → Dashboard (HTML/JS)
                                   ↘ AUDIT.DQ_LOG (bad records, never lost)
```

**Stack:** Snowflake · Python · FastAPI + Pydantic · Chart.js · pytest · Docker · GitLab CI (design)

📄 Problem statement: [docs/00_problem_statement.pdf](docs/00_problem_statement.pdf)

👉 **Follow [GUIDE.md](GUIDE.md)**: step-by-step, with the theory to learn for every phase.

## Where each task is
| Brief task | Files |
|---|---|
| Task 1 – Specification | `docs/01_business_spec.md`, `docs/02_technical_spec.md`, `docs/03_acceptance.feature` |
| Task 2 – Data model + pipeline | `docs/04_data_model.md`, `sql/`, `pipeline/` |
| Task 3 – API + front-end | `api/`, `common/kpi.py`, `frontend/index.html` |
| Task 4 – Tests, security, deployment | `tests/`, `docs/05_security.md`, `Dockerfile`, `.gitlab-ci.yml`, `docs/06_deployment.md` |

## Commands
```powershell
python -m common.snowflake_conn              # test Snowflake connection
python -m pipeline.run_pipeline --init       # load Bronze -> Silver -> Gold
uvicorn api.main:app --reload                # API + dashboard on http://localhost:8000
pytest -v                                    # tests
```
