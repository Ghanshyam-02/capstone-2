# Day 1 – Viva / Presentation Script

A spoken script for a **10–12 minute** presentation, then the questions examiners usually ask, with answers.
Read it aloud a few times. Keep the numbers, and say the rest in your own words.

> **Tip:** have 3 windows open: the dashboard (`uvicorn api.main:app`), a terminal in `day1`, and VS Code.
> Show, don't just tell.

---

## Part 1 – The problem (1 min)

> "Bank of New York runs payment acquiring for merchants in India: card, QR and online payments.
> After a payment succeeds, the bank must **settle** it, which means paying the money to the merchant.
>
> The Head of Payments had a problem: yesterday ₹48 crore of payments succeeded, but only ₹45.8 crore was
> settled, and nobody could say why ₹2.2 crore was missing. The data sits in four systems: transactions,
> settlements, merchant risk and payment events. Operations only gets nightly Excel reports.
>
> The gap could be failed payments, pending settlements, delays, risky merchants or simply bad data.
> My job was to build a platform that **explains** that gap, exposes it through an API and a dashboard,
> processes new data incrementally, and is automatically tested."

## Part 2 – What was asked (1 min)

> "The brief had four tasks:
> 1. **Specification:** business spec, technical spec and Gherkin acceptance scenarios.
> 2. **Data model and pipeline:** a star schema with the grain of every table, and a Bronze-Silver-Gold
>    pipeline that never loses bad records and only processes new data.
> 3. **API and dashboard:** FastAPI endpoints for the settlement summary and merchant exceptions, and an HTML dashboard.
> 4. **Testing, security and deployment:** unit, data-model and API tests, a security review and a CI/CD design.
>
> It also warned about five **hidden data problems**, which I will come back to, because they are the heart
> of the task."

## Part 3 – Architecture (1.5 min)

*(Show the diagram in `README.md`.)*

> "The data flows through layers, not one script:
>
> - **Source files:** four CSVs, 3,830 transactions for September 2026.
> - **Ingestion into Bronze:** each file is copied exactly as received, as text, with the file name and a load id.
>   Bronze never rejects anything, so history can always be replayed.
> - **Silver:** SQL rules clean and validate every row. Good rows go to Silver with proper types.
>   Bad rows go to an **audit log with a reason**, so nothing disappears silently.
> - **Gold:** a star schema with dimensions for date, merchant and customer, and facts for transactions,
>   settlements and payment events, plus a small daily KPI table per merchant.
> - **API:** FastAPI reads Gold **read-only** and returns JSON.
> - **Dashboard:** plain HTML and JavaScript. It calls only the API, never the database.
>
> The database is **DuckDB**: a real SQL database stored in one file. It needs no server and supports primary
> keys, foreign keys and CHECK constraints. Python only orchestrates, and all the data logic is readable SQL."

## Part 4 – Specification (1 min)

*(Open `docs/01_business_spec.md`.)*

> "Before coding I wrote the spec. The key decision was **how to classify each bad record**:
> - **Reject:** unusable, like a missing id, an unreadable timestamp or a duplicate event.
> - **Quarantine:** suspicious, needs a human. For example a missing or unknown merchant, an invalid currency,
>   a negative settlement (it could be a refund) or a settlement with no transaction.
> - **Warning:** usable but noted, like a late event.
> - **Business exception:** the data is correct, but the business outcome is bad, like a payment never
>   settled or settled late.
>
> The technical spec covers sources, fields, processing, storage, API, validation, monitoring and security.
> I wrote eight Gherkin scenarios in Given-When-Then form."

## Part 5 – Data model (1.5 min)

*(Open `docs/04_data_model.md`, the ER diagram.)*

> "The most important modelling word is **grain**, what one row means:
> - `fact_transaction`: one payment attempt
> - `fact_settlement`: one settlement record, and one transaction can have several
> - `fact_payment_event`: one lifecycle event
> - `dim_merchant`: one merchant **per risk period**, because risk is historical
>
> For merchants I used **SCD Type 2**: when a merchant's risk changes, a new row is added with
> effective-from and effective-to dates, and each transaction joins the row valid on its own date.
>
> Keys: primary keys on every table, foreign keys from facts to dimensions, CHECK constraints such as
> 'settlement amount can't be negative', and indexes on date and merchant for the API's filters.
> DuckDB enforces all of them."

## Part 6 – The five hidden problems (2 min) ⭐ most important

*(Run `python -m common.query sql/06_explore.sql` and scroll to D, E, F.)*

> "**One: one-to-many settlement.** Transaction T1001 is ₹10,000, settled as ₹8,000 plus ₹2,000. If you join
> transactions to settlements directly, the ₹10,000 appears twice and the total becomes ₹20,000.
> Query D3 shows exactly that wrong answer. My fix is to **sum settlements per transaction first**, then
> join (view `v_txn_settlement`). The settled amount is ₹10,000, counted once.
>
> **Two: late events.** One event happened at 10:02:15 but arrived at 10:08:41. I keep both times.
> **Business time**, `event_ts`, is used for reporting. **Processing time**, `ingestion_ts`, is used to detect
> lateness. Anything more than five minutes late is kept but flagged.
>
> **Three: out-of-order events.** T1001's events arrive as SETTLED, AUTHORIZED, CREATED. I number them
> with `row_number()` ordered by event time, so the real sequence is restored.
>
> **Four: risk history.** Merchant M101 is LOW until the 14th of September and HIGH from the 15th.
> Query F2 shows its transactions switch risk exactly on the 15th. That's SCD Type 2 working.
>
> **Five: data quality.** Missing and unknown merchants, invalid currency, negative and orphan settlements,
> duplicate events and bad timestamps are all caught: 158 quarantined, 28 rejected and 372 late-event warnings,
> every one in the audit log with its reason."

## Part 7 – Incremental processing (45 s)

> "The pipeline doesn't reprocess everything. First, a file-tracking table means a file is never loaded twice.
> Second, a **watermark** stores the last load id each layer processed, so the next run only takes newer rows.
> Third, the KPI table is recalculated only for dates that changed.
>
> *(Demo if time: run the pipeline → '0 new files'. Copy batch 2 → only 3 files load.)*
> Batch 2 even completes 20 settlements that were pending, and September's settlement rate rises from
> 93.72 to 94.08 percent. Updates flow through correctly because every write is an **upsert**."

## Part 8 – The answer: API and dashboard (1.5 min)

*(Show the dashboard.)*

> "For September:
> - **3,383** successful transactions, **₹4.13 crore** in volume
> - settlement rate **93.72%**, below the 95% target
> - settlement gap **₹25.95 lakh**
> - SLA **77.09%**: only 77% were settled within 30 minutes, against a 90% target
> - **5 risky merchants**, with both rate below 95% and SLA below 90%
>
> **Why is there a gap?** ₹14.07 lakh was never settled, ₹8.10 lakh is still pending, and ₹3.79 lakh was
> only partly settled. The biggest gaps are at M117, M108 and M104, all HIGH-risk merchants. The daily chart
> dips on the **15th of September**, when many settlements were delayed. M110 and M121 always settle late.
>
> The API has the two required endpoints, `/settlement-summary` and `/merchant-exceptions`, plus two small
> ones for the charts. Pydantic defines the response contract and FastAPI generates OpenAPI docs at `/docs`.
> Status codes are 400 for a bad date, 404 for an unknown merchant, 422 for an invalid parameter
> and 401 without an API key."

## Part 9 – Testing (1 min)

*(Run `pytest -v`.)*

> "There are 46 automated tests in six groups:
> - **unit tests** for the KPI formulas
> - **business-rule tests**, one per case in the brief: they feed a few hand-written rows through the real
>   pipeline and check the result
> - **pipeline tests** for re-runs and incremental loads
> - **data-model tests** on the full dataset: no duplicate keys (grain), no orphans (referential integrity),
>   and reconciliation, meaning successful equals settled plus unsettled
> - **API tests** for every status code, values that match the database, and responses under 500 ms
> - **security tests**
>
> My favourite is the **negative test**: 8,000 plus 2,000 on a 10,000 transaction must give 100%, not 200%.
> They all run in about 11 seconds, each on its own temporary database."

## Part 10 – Security and deployment (1 min)

> "Security:
> - **SQL injection** is blocked by bind parameters, and merchant ids must match a pattern, so
>   `M100' OR '1'='1` gets a 422 before any SQL runs.
> - The **API key** is required and read from environment variables. `.env` is never committed.
> - The API opens the database **read-only**, so it can't change data. That's authorization.
> - Customer ids are hashed, never returned and never logged.
> - Logs contain only method, path and status.
>
> Deployment design: a Docker image that builds the database inside the image, and a GitLab CI pipeline:
> tests, SAST, dependency scan, image build, then DEV, TEST, and PROD with manual approval.
> Health check, smoke test, and rollback by redeploying the previous image tag."

## Part 11 – Close (20 s)

> "To sum up: the platform turns four messy files into a trusted, tested answer to 'why is there a settlement
> gap'. It shows how much, why, which merchants and which days, and it never hides bad data.
> Day 2 takes this to production. Thank you."

---

## Likely viva questions – with answers

### Architecture & choices
1. **Why Bronze, Silver, Gold instead of one script?** Each layer has one job: Bronze keeps the raw truth (replayable), Silver makes it trustworthy, Gold makes it useful. When something breaks, you know which layer to look at, and you can rebuild a layer without re-reading the sources.
2. **Why DuckDB?** It's a real SQL database in a single file: no server or accounts, very fast for analytics, and it enforces keys and constraints. The same SQL ideas work on Snowflake or Postgres in a company.
3. **Why is the logic in SQL and not Python?** SQL runs inside the database, which is fast and set-based. It's also the language data teams review. Python only runs the steps in order (orchestration). This is called **ELT**.
4. **What does the API read?** The small `gold.agg_merchant_daily` table (one row per merchant per day), so every call takes milliseconds.

### Data model
5. **What is grain and why does it matter?** What one row represents. If you mix grains, for example by joining transactions (one per payment) with settlements (many per payment), amounts get multiplied.
6. **Fact vs dimension?** Facts are measurable events (amounts, counts). Dimensions describe them (who, what, when).
7. **What is SCD Type 2?** You keep history by adding a new row per change, with `effective_from`/`effective_to`. SCD Type 1 would overwrite, and February transactions would then wrongly show today's risk.
8. **Why a surrogate key (`merchant_sk`)?** One merchant id has several history rows, so the id alone isn't unique. The surrogate key is.
9. **Where are the staging tables?** Bronze is the staging layer. Silver also uses temporary `chk_*` tables while validating.

### Hidden problems
10. **How did you stop split settlements being double counted?** Aggregate settlements per `transaction_id` first (CTE `s` in `v_txn_settlement`), then join one row per transaction. Test `test_multiple_settlements_do_not_inflate_the_settlement_rate` proves it.
11. **Business time vs processing time?** `event_ts` is when it happened, used for reports and ordering. `ingestion_ts` is when we received it, used to detect lateness. Mixing them shifts daily numbers.
12. **Is a late event rejected?** No. It's valid, just late, so it's kept with `is_late = true` and a WARNING in the DQ log.
13. **Why quarantine a negative settlement instead of rejecting it?** It might be a legitimate refund or reversal, so a human should decide. Rejecting would hide it.
14. **What happens to a settlement whose transaction was quarantined?** It becomes UNMATCHED_SETTLEMENT (quarantined too). Once the transaction is fixed and reloaded, it can be replayed.

### Pipeline & incremental
15. **How is it incremental?** `audit.loaded_files` (a file is loaded once), `audit.watermark` (the last `load_id` per layer), and a KPI table rebuilt only for changed dates.
16. **What is idempotent?** Running it twice gives the same result. Upserts (`INSERT … ON CONFLICT DO UPDATE`) make that true.
17. **What if the pipeline crashes half-way?** Each layer runs in a transaction (BEGIN … COMMIT), so a failure rolls it back and the watermark isn't moved. The run is marked FAILED in `audit.pipeline_runs`.
18. **A settlement changes from PENDING to SETTLED – what happens?** The same `settlement_id` arrives again, the upsert updates the row, and the dates it affects are recalculated.

### KPIs
19. **How is the settlement rate calculated?** Settled amount ÷ successful amount × 100. Only SUCCESS transactions count, and the settled amount per transaction is capped at the transaction amount.
20. **How is the SLA defined?** A successful transaction is SLA-met if it's fully settled and its last SETTLED record is within 30 minutes of the transaction.
21. **Exception vs risky merchant?** An exception is rate < 95% **OR** SLA < 90% (the `/merchant-exceptions` list). KPI 5 "risky" is rate < 95% **AND** SLA < 90%.

### Testing
22. **Unit vs integration tests here?** KPI tests are pure unit tests. Business-rule tests run the real pipeline on tiny data, which makes them small integration tests. Data-model tests check the whole dataset.
23. **What is a negative test?** It proves a wrong thing does *not* happen, e.g. the rate never goes above 100% with multiple settlements.
24. **How do you know the API numbers are right?** `test_200_valid_request_returns_the_contract` compares the API's answer with a direct SQL query on the database.

### Security
25. **How do you prevent SQL injection?** Bind parameters (`?`) plus input validation (regex, returning 422). User input never becomes SQL text.
26. **Authentication vs authorization?** Authentication is who you are (API key). Authorization is what you can do (read-only database access).
27. **Where are the secrets?** In `.env` locally and in CI variables in pipelines. Both are git-ignored and docker-ignored, and a test scans the code for hard-coded secrets.

### Deployment
28. **How would you roll back?** Every commit builds its own image tag, so you deploy the previous tag. The data is inside the image, so it comes back too.
29. **Health check vs smoke test?** The health check asks whether the app is alive. The smoke test makes real business calls after a deploy to check the answers are right. (Day 2 shows why that matters.)
30. **What would you improve?** Scheduling (Airflow), alerting on KPI anomalies, SSO instead of an API key, and partitioning for much bigger data.
