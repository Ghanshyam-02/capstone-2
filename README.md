# Capstone 2 – Bank of New York Settlement Intelligence Platform

| Day | Folder | What | Status |
|---|---|---|---|
| **Day 1** | [`day1/`](day1/) | Build the platform: CSV → Bronze → Silver → Gold → FastAPI → dashboard, with tests, security and a deployment design | ✅ working |
| **Day 2** | [`day2/`](day2/) | Make it production-ready: CI/CD (GitLab + Jenkins), security gates, blue-green deployment, incident recovery, presentation | ✅ implemented (follow `day2/GUIDE.md` in the Docker VM) |

Each folder has its own problem statement (`00_problem_statement.pdf`) and:

| File | Day 1 | Day 2 |
|---|---|---|
| `README.md` | what we built and how | what is asked, what is in the folder, results |
| `GUIDE.md` | step-by-step + theory for every phase | step-by-step in the Windows VM with Docker |
| `LEARN.md` | – | theory for every Day 2 topic |
| `VIVA_SCRIPT.md` | presentation script + 30 viva Q&A | 8-slide leadership script + peer review + 20 viva Q&A |

## Quick start (Day 1)
Needs Python 3.10+ and Git.
```powershell
git clone https://github.com/Ghanshyam-02/capstone-2.git
cd capstone-2\day1
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env
python -m pipeline.run_pipeline          # build the database from the CSV files
python -m common.query sql/06_explore.sql
pytest                                   # 22 tests
uvicorn api.main:app --reload            # dashboard: http://localhost:8000
```

**Stack:** Python · DuckDB (SQL database in one file) · FastAPI + Pydantic · Chart.js · pytest · Docker · GitLab CI · Jenkins (Day 2)
