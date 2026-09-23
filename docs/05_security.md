# 5. Security

| Risk (from the brief) | What could go wrong | How this project prevents it | Where |
|---|---|---|---|
| **SQL injection** | `f"... WHERE merchant_id = '{merchant_id}'"` lets a caller run their own SQL | All values are **bind parameters** (`%s`). `merchant_id` must also match `^M\d{3,6}$` or the API returns 422 before touching the DB. Table names in f-strings come only from constants in the code. | `api/repository.py`, `api/main.py` |
| **Unrestricted API access** | Anyone on the network reads bank data | Every `/api/v1/*` call needs `X-API-Key`; compared in constant time; server **fails closed** if no key is configured. | `api/security.py` |
| **Missing authorization** | API could modify or read raw data | API connects as `API_ROLE`, which has **SELECT on GOLD only** – it cannot see Bronze/Silver/Audit or write anything. Pipeline uses `PIPELINE_ROLE`. | `sql/00_setup.sql` |
| **Secrets in source code** | Password leaks via Git | Key-pair auth (no password). Private key + `.env` are git-ignored and docker-ignored. CI uses masked GitLab variables. | `.gitignore`, `.dockerignore`, `.env.example` |
| **PII leakage** | Customer ids exposed | Gold stores `SHA2(customer_id)`. API never returns customer data. DQ log masks `customer_id`. | `04_gold_transform.sql`, `silver.py` |
| **Excessive logging** | Logs full of customer data | API logs only method, path and status. Pipeline prints counts, never rows. | `api/main.py`, `pipeline/` |
| **XSS in dashboard** | Merchant name with `<script>` runs in browser | Table cells set with `textContent`, never `innerHTML`. | `frontend/index.html` |
| **Container** | Root process, secrets baked into image | Runs as non-root `appuser`; key mounted read-only at runtime. | `Dockerfile` |

Automated checks in the CI design: **SAST** (code scan) and **dependency scan** – see `.gitlab-ci.yml`.

Production improvements (not in scope): SSO/OAuth2 at an API gateway, rate limiting, Snowflake network
policies, dynamic data masking policies, secret manager (Vault / AWS Secrets Manager), key rotation.
