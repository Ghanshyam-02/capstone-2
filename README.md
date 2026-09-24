# Capstone 2 – Bank of New York Settlement Intelligence Platform

| Day | Folder | What | Status |
|---|---|---|---|
| **Day 1** | [`day1/`](day1/) | Build the platform: CSV → Bronze → Silver → Gold → FastAPI → dashboard, with tests, security and a deployment design | ✅ working |
| **Day 2** | [`day2/`](day2/) | Make it production-ready: CI/CD (GitLab + Jenkins), security gates, blue-green deployment, incident recovery, presentation | 📋 plan + learning path |

Each folder has its own problem statement (`00_problem_statement.pdf`) and a `README.md`. Day 1 also has
a `GUIDE.md` with step-by-step instructions and the theory to learn for every phase.

## Quick start (Day 1)
```powershell
cd day1
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env
python -m pipeline.run_pipeline          # build the database from the CSV files
python -m common.query sql/06_explore.sql
pytest                                   # 46 tests
uvicorn api.main:app --reload            # dashboard: http://localhost:8000
```

**Stack:** Python · DuckDB (SQL database in one file) · FastAPI + Pydantic · Chart.js · pytest · Docker · GitLab CI · Jenkins (Day 2)
