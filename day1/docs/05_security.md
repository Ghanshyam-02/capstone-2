# 5. Security

| Risk (from the brief) | What could go wrong | How this project prevents it | Where |
|---|---|---|---|
| **SQL injection** | `f"... WHERE merchant_id = '{merchant_id}'"` lets a caller run their own SQL | Every value is a **bind parameter** (`?`). `merchant_id` must also match `^M\d{3,6}$` or the API returns 422 before any SQL runs. Table names in f-strings come only from constants in the code. | `api/repository.py`, `api/main.py` |
| **Unrestricted API access** | Anyone on the network reads bank data | Every `/api/v1/*` call needs the `X-API-Key` header. The key is compared in constant time, and the server **fails closed** if no key is configured. | `api/security.py` |
| **Missing authorization** | The API could change or delete data | The API opens the database **read-only**. Only the pipeline can write. | `common/db.py`, `api/repository.py` |
| **Secrets in source code** | Keys leak via Git | The API key comes from `.env` / environment variables. `.env` is git-ignored and docker-ignored. CI uses masked GitLab variables. | `.gitignore`, `.dockerignore`, `.env.example` |
| **PII leakage** | Customer ids exposed | Gold stores `sha256(customer_id)`. The API never returns customer data. The DQ log leaves customer ids out. | `sql/05_silver_to_gold.sql`, `sql/04_bronze_to_silver.sql` |
| **Excessive logging** | Logs full of customer data | The API logs only method, path and status. The pipeline prints counts, never rows. | `api/main.py`, `pipeline/` |
| **XSS in dashboard** | A merchant name with `<script>` runs in the browser | Table cells use `textContent`, never `innerHTML`. | `frontend/index.html` |
| **Container** | Root process, secrets baked into the image | Runs as the non-root `appuser`. The API key is passed at runtime (`-e API_KEY=...`). | `Dockerfile` |

Proven by `tests/test_security.py`: 401 without a key, 422 for an injection attempt, the read-only database
refuses writes, no hard-coded secrets in the code, no customer ids in API responses.

Production improvements (Day 2 / future): SAST (Bandit), secret scan (Gitleaks), dependency scan (pip-audit),
container scan (Trivy), SSO/OAuth2 at an API gateway, rate limiting, a secret manager.
