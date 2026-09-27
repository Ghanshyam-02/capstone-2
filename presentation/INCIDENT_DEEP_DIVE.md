# Incident Deep Dive: Slides 10, 11 and 12

Every number here comes from the saved evidence in `day2/incident/evidence/`.

---

## Background: what was running before the incident

| | Blue | Green |
|---|---|---|
| Version | V1 1.0.0 | V2 2.0.0 (good) |
| Port | 8001 | 8002 |
| Database | `settlement.duckdb` | approved database |
| Status | standby (kept running for rollback) | **LIVE**: all traffic since the cutover at 21:41:52 |

Nginx (port 8090) sent 100 % of users to green. The settlement rate was **93.72 %**, which is the **baseline**: the number we know is correct because reconciliation proved it.

## How we created the incident (the exercise)

We did **not** create bad data. The CSV files were exactly the same. We created a **bad release**, meaning wrong code and configuration:

- File: `day2/incident/v2-defects/Dockerfile`
- It starts `FROM settlement-api:v2`, the good V2 image.
- It replaces only **3 files** and **1 setting**:

| Defect | File or setting | What was changed |
|---|---|---|
| **A: grain** | `sql/05_silver_to_gold.sql` | Settled amount calculated by joining transactions to settlements **before** summing |
| **C: configuration** | `SETTLEMENT_DB` env variable | Points to `settlement_db_v2.duckdb`, not the approved database |
| **D: API guard** | `common/kpi.py` and `api/models.py` | The rule that keeps the rate between 0 and 100 was removed |

- Version label: `APP_VERSION=2.0.1`.
- The pipeline re-runs inside the image, so the wrong numbers are baked into its database.

**Why do it this way?** This is how real incidents happen: the data is fine, and a new release computes it wrong. It also mirrors real deployments, where the image is replaced and nothing else changes.

Then we deployed it to **green**, which was **live**. At that moment every user was on the bad version.

---

# Slide 10: The incident ("/health still said OK")

## What users saw (22:05:24 onwards)

| KPI | Correct (V1) | Bad release (2.0.1) |
|---|---|---|
| Settlement rate | 93.72 % | **103.98 %** |
| Settlement gap | ₹25,95,426 | **−₹16,46,536** (negative) |
| Risky merchants | 5 | **3** |
| Merchants with exceptions | 11 | **8** |
| Merchants with settled > paid | 0 | **21** |

**Why each number is a red flag:**

1. **103.98 % is impossible.**
   - The settlement rate is settled ÷ paid × 100.
   - You cannot pay a merchant more than the customer paid.
   - Anything above 100 % is a sign of **double counting**, not good performance.
2. **The gap is negative.**
   - Gap = paid − settled = ₹4,13,42,329 − ₹4,29,88,865 = **−₹16,46,536**.
   - That would mean the bank sent ₹16 L *more* than it collected.
   - If Operations believed this, they might start chasing merchants to *return* money that was never overpaid.
3. **Risky merchants dropped from 5 to 3.**
   - A risky merchant is one with a settlement rate below 95 % **AND** an SLA below 90 %.
   - The inflated rates pushed some merchants above 95 %, so they disappeared from the risk list.
   - **This is the most dangerous effect.** It doesn't just show a wrong number, it **hides real problems**.
   - Operations would stop following up on merchants who still have unsettled money.
4. **Exceptions dropped from 11 to 8**, for the same reason (rate < 95 % **OR** SLA < 90 %).
5. **21 merchants show more settled than paid.**
   - M100, M101, M102, M103, M105 and others (see `03_reconciliation_FAIL.txt`).

**What did NOT change** (this helps later, to find the cause):
- the number of transactions: 3,383 in both
- the transaction amount: ₹4,13,42,329 in both
- the SLA rate: 77.09 % in both

## The dangerous part: everything looked "healthy"

- **`/health`** (`01_health_still_ok.txt`) returned:

  ```
  status        : ok
  database      : ok
  database_file : settlement_db_v2.duckdb
  version       : 2.0.1
  ```

- **Logs** (`08_green_logs.txt`): every request got `200 OK`, and there were no errors or exceptions.
- **The container** was running and its Docker HEALTHCHECK passed.

So any **technical** monitoring (uptime, HTTP status, error rate, CPU) would say "all good". The service was **up**, but it was **wrong**.

**What to say:**
> "This is the key lesson of the incident. A health check tells you the service is *running*. It doesn't tell you the service is *right*. Only a check that knows what the business number should be can catch this."

**One clue was visible on /health:** `database_file: settlement_db_v2.duckdb` and version `2.0.1`. That's defect C, and it's why we expose the version and database file on /health: so you can see **what** is running.

## Evidence for slide 10

| File | What it proves |
|---|---|
| `incident_dashboard.PNG` | What users saw: 103.98 %, a negative gap, 3 risky merchants |
| `api_health.PNG` / `01_health_still_ok.txt` | Health said OK, and shows v2.0.1 on settlement_db_v2 |
| `08_green_logs.txt` | Only 200 OK in the logs, no errors |

---

# Slide 11: Finding the cause

## Step 1: Detection, at 22:06:25 (about 1 minute after release)

We ran our **business smoke test** against the live URL:

```bash
python day2/scripts/smoke_test.py --url http://localhost:8090 --key <key> --expected-rate 93.72
```

The result (`02_smoke_test_FAIL.txt`):

```
PASS  GET /health -> 200
PASS  GET /settlement-summary -> 200
PASS    valid JSON with settlement_rate          103.98
FAIL    response time < 500 ms                   734 ms
FAIL    settlement_rate between 0 and 100        103.98 %
FAIL    settlement_rate = reconciled baseline    103.98 % vs expected 93.72 %
PASS  GET /merchant-exceptions -> 200
FAIL    every merchant rate between 0 and 100
RESULT: FAIL
```

**How to read it:**
- All the **technical** checks PASS: status 200 and valid JSON.
- The **business** checks FAIL:
  - the rate is outside 0–100 %
  - the rate doesn't match the baseline
  - merchant rates are above 100 %
- The response-time failure (734 ms) was a **cold start**: the first requests after a container starts are slow. It is **not** the cause of the incident. Say so if asked, and don't hide it.

**Second check: reconciliation** (`03_reconciliation_FAIL.txt`), run with `python -m common.reconcile`:

```
PASS  successful amount: facts = KPI table     41342329.17 vs 41342329.17
FAIL  settled amount:    facts = KPI table     38746903.53 vs 42988864.94
FAIL  settlement rate:   facts = KPI table     93.72 % vs 103.98 %
FAIL  no merchant settled > successful         M100, M101, ... (21 merchants)
RESULT: FAIL
```

**What reconciliation does:**
- It recalculates the totals straight from the **fact tables** (the raw truth) and compares them with the **KPI table** the API serves (`agg_merchant_daily`).
- If they differ, the calculation that builds the KPI table is wrong.

**What it tells us:**
- The successful amount matches, so the payments data is fine.
- The settled amount doesn't match, so **the settled-amount calculation is broken**.
- The bug is narrowed down to one number and one step before we even open the code.

## Step 2: Compare previous production against current production (22:06:35)

Blue (V1) was still running, so we called **both** APIs and compared them (`04_v1_vs_v2_summary.txt`):

| KPI | V1 blue (previous) | V2 green (current) | Same? |
|---|---|---|---|
| transaction_count | 3,383 | 3,383 | ✅ |
| transaction_amount | 41,342,329.17 | 41,342,329.17 | ✅ |
| settled_amount | 38,746,903.53 | 42,988,864.94 | ❌ |
| settlement_rate | 93.72 | 103.98 | ❌ |
| settlement_gap | 2,595,425.64 | −1,646,535.77 | ❌ |
| sla_rate | 77.09 | 77.09 | ✅ |
| merchant_risk_count | 5 | 3 | ❌ |

**Conclusion:** the **same input** gives a **different output**. Only the settled amount and everything computed from it changed, so the bug is in **how settlements are calculated**, not in the data and not in the transactions.

**Why this comparison is powerful:** blue-green gave us a **known-good reference running side by side**. Without it we'd be guessing what the right number is.

## Step 3: Check version and config (`05_version_and_config.txt`)

```
blue : version 1.0.0  database_file settlement.duckdb
green: version 2.0.1  database_file settlement_db_v2.duckdb
V1 exceptions: 11   V2 exceptions: 8
```

**This is defect C, the wrong configuration.** Green reads `settlement_db_v2.duckdb`, not the approved database. In a real bank that could be a test database or a stale copy. Even if the SQL were right, reading an unapproved database means the numbers can't be trusted.

## Step 4: Look at the code diff (`07_code_diff_gold_sql.txt`), which is defect A

**Correct V1 logic** (`day1/sql/03_gold.sql`, view `v_txn_settlement`):

```sql
-- 1) Sum settlements PER TRANSACTION first
WITH s AS (
  SELECT transaction_id,
         SUM(CASE WHEN settlement_status = 'SETTLED' THEN settlement_amount ELSE 0 END) AS settled_raw
  FROM gold.fact_settlement
  GROUP BY transaction_id          -- now exactly ONE row per transaction
)
-- 2) THEN join to transactions (one-to-one, no duplication)
```

**Faulty V2 logic** (`v2-defects/sql/05_silver_to_gold.sql`):

```sql
SELECT CAST(t.transaction_ts AS DATE), t.merchant_id, SUM(t.amount) AS settled_amount
FROM gold.fact_transaction t
JOIN gold.fact_settlement s ON s.transaction_id = t.transaction_id   -- join BEFORE aggregation
WHERE t.status = 'SUCCESS' AND s.settlement_status = 'SETTLED'
GROUP BY 1, 2
```

**Two things are wrong here:**

1. **Join before aggregation (the grain bug).**
   - `fact_transaction` has one row per payment.
   - `fact_settlement` has one row per settlement record, and one payment can have **several**.
   - Joining them first repeats the transaction row once per settlement.
2. **It sums `t.amount` (the payment amount), not `s.settlement_amount`.**
   - So each settled record counts the **full payment amount**.

**A worked example with T1001 (₹10,000, settled as ₹8,000 + ₹2,000):**

| Step | Correct V1 | Faulty V2 |
|---|---|---|
| Rows after the step | aggregate first: 1 row, settled = 8,000 + 2,000 = **10,000** | join first: 2 rows, both carrying the transaction amount 10,000 |
| Sum | 10,000 | 10,000 + 10,000 = **20,000** |
| Rate | 10,000 ÷ 10,000 = **100 %** | 20,000 ÷ 10,000 = **200 %** |

Also, a payment that was only **partly settled** (for example ₹6,000 of ₹10,000 settled) counts as the full ₹10,000 in V2. So partly-settled money looks fully settled, and the "partly settled" part of the gap disappears.

**Theory: grain.**
- **Grain** is what one row of a table means.
- When you join a table at one grain (payment) to a table at a finer grain (settlement), the coarser rows get **duplicated**.
- The fix is always the same: **aggregate the fine table to the coarse grain first, then join**.
- This is the same trap we solved on slide 4, and the same one our negative test checks: `test_multiple_settlements_do_not_inflate_the_settlement_rate`.

## Step 5: The missing guard, which is defect D

**Correct V1** (`day1/common/kpi.py` and `day1/api/models.py`):

```python
return round(max(0.0, min(settled / success * 100, 100.0)), 2)   # clamp to 0..100
Percent = Annotated[float, Field(ge=0, le=100)]                    # API refuses values outside 0..100
```

**Faulty V2:**

```python
return round(settled_amount / success_amount * 100, 2)   # no clamp
Percent = float                                          # any number accepted
```

- These are **defensive checks**, a last line of defence.
- In V1, even if the SQL had a bug, the **Pydantic model** would refuse to send a rate above 100. The API would have returned an **error** instead of a **wrong number**.
- **A loud failure is safer than a silent wrong answer.** Removing the guard let the impossible 103.98 % reach the dashboard with a normal 200 OK.

**Why D matters on its own:** defect A caused the wrong number, and defect D **let it reach users**. Two defects combined into one incident, which is typical of real outages.

## Step 6: Rule out defect B (`06_defect_B_check.txt`)

```
Daily transaction_amount identical for all 30 days: True  (dates not shifted -> defect B not present)
```

- **Defect B** would be a date or timezone bug, for example UTC vs IST moving payments to the previous day.
- **How we checked:** we compared the transaction amount **per day** for all 30 days between V1 and V2. Every day matched, so no dates were shifted.
- **Why mention it:** good investigation means **testing each hypothesis and ruling it out with evidence**, not only finding the first bug. It also shows the brief listed possible defects and we checked them all.

## The root cause, found at 22:06:40

> V2 2.0.1 calculated the settled amount by joining transactions to settlements before aggregating (A). It read an unapproved database (C). The 0–100 % guard had been removed (D), so the inflated rate reached users. Defect B was checked and is not present.

## Evidence for slide 11

| File | What it proves |
|---|---|
| `02_smoke_test_FAIL.txt` | Business checks failed while technical checks passed |
| `03_reconciliation_FAIL.txt` | The KPI table disagrees with the facts, on the settled amount only |
| `04_v1_vs_v2_summary.txt` | Same input, different settled output |
| `05_version_and_config.txt` | Version 2.0.1 on the wrong database (C) |
| `06_defect_B_check.txt` | Dates are fine (B ruled out) |
| `07_code_diff_gold_sql.txt` | The join-before-aggregation code (A) |
| `08_green_logs.txt` | No errors in the logs, which is why technical monitoring missed it |

---

# Slide 12: Decision and recovery

## The timeline (`00_timeline_log.txt`, real times on 26 Sep 2026)

| Time | Event | Elapsed |
|---|---|---|
| 21:41:52 | Good V2 2.0.0 cut over to green (baseline 93.72 %) | |
| 22:04:55 | Faulty 2.0.1 image built | |
| **22:05:24** | **Faulty 2.0.1 deployed to live green** | incident starts |
| **22:06:25** | **Smoke test detects 103.98 % vs 93.72 % baseline** | +1 min 1 s (time to detect) |
| 22:06:35 | Investigation: blue V1 vs green V2 compared | |
| 22:06:40 | Root cause identified (A, C, D) | |
| **22:13:39** | **Decision: roll back to blue V1**, and `switch.ps1 blue` is run | |
| **22:13:42** | **V1 live again: 100 % of traffic to blue** | **3 seconds** to recover |
| 22:13:45 | Smoke test PASS | |
| 22:13:51 | Reconciliation PASS: 93.72 % = baseline, production restored | total impact about 8.5 min |

**Key metrics to quote:**
- **MTTD (Mean Time To Detect):** about **1 minute**, thanks to the business smoke test.
- **MTTR (Mean Time To Recover):** **3 seconds** from the decision to V1 being live, and **12 seconds** from the decision to fully verified.
- **Total user impact:** 22:05:24 → 22:13:42, about **8 minutes 18 seconds**.

## The decision: roll back or fix forward?

Two options:

| | **Roll back** (switch to V1) | **Fix forward** (patch V2 live) |
|---|---|---|
| Time | 3 seconds | Hours: fix the SQL, fix the config, restore the guard, rebuild, re-test, redeploy |
| Risk | Very low: V1 was proven that morning and still running | High: 3 defects at once, and changing code under pressure causes new bugs |
| Users meanwhile | Correct numbers immediately | Wrong money numbers stay live until the fix ships |
| Proof | V1 already passed tests, security, smoke and reconciliation | The new patch is untested |

**Our reasons (say these four):**
1. **Wrong money figures were live now.** In a bank, a wrong settlement number leads to wrong decisions: chasing merchants for overpayments, missing risky merchants.
2. **V1 was known-good and one switch away**, thanks to blue-green.
3. **There were multiple defects**, which means a live patch was risky.
4. **Rolling back is reversible and fast.** A fix can come later through the full pipeline.

**The rule:** *when a release breaks correctness and a known-good version is available, roll back first and fix later.*

## How the rollback works technically

The command:

```powershell
.\day2\deploy\switch.ps1 blue
```

What the script does:
1. It **rewrites** `deploy/nginx/default.conf` so Nginx points to blue:
   ```
   location / { proxy_pass http://blue:8000; add_header X-Live-Colour blue always; }
   ```
2. It runs `docker compose exec lb nginx -s reload`. Nginx checks the new config and **reloads gracefully**: requests already in progress finish, and new ones go to blue. **Nothing is restarted and no connections are dropped.**
3. It appends a line to the evidence file:
   ```
   2026-09-26 22:13:42  100% traffic -> blue
   ```

**Why only 3 seconds?**
- Nothing is built, pulled or started.
- Blue was **already running and warm**, so the only change is one line of Nginx config.
- This is the whole point of blue-green deployment.

**What happens to green?** It **keeps running, isolated**, with no users. We can still inspect its logs, database and API for the investigation, and nothing is destroyed.

## Proving the recovery (verification)

Recovery isn't "we switched". It is "we switched **and proved** the numbers are right".

**1. The smoke test after the rollback** (`10_smoke_after_rollback_PASS.txt`), at 22:13:45:

```
version=1.0.0   live colour=blue
PASS  settlement_rate between 0 and 100        93.72 %
PASS  settlement_rate = reconciled baseline    93.72 % vs expected 93.72 %
PASS  response time < 500 ms                   453 ms
PASS  valid JSON list of merchants             11 merchants
RESULT: PASS
```

**2. Reconciliation after the rollback** (`11_reconciliation_after_rollback_PASS.txt`), at 22:13:51:

```
PASS  successful amount: facts = KPI table     41342329.17 vs 41342329.17
PASS  settled amount:    facts = KPI table     38746903.53 vs 38746903.53
PASS  settlement rate:   facts = KPI table     93.72 % vs 93.72 %
PASS  no merchant settled > successful         none
RESULT: PASS
```

**3. The dashboard screenshot** (`after_rollback.PNG`) shows:
- a settlement rate of 93.72 %
- a gap of ₹25,95,426
- 5 risky merchants again

| KPI | During the incident | After the rollback |
|---|---|---|
| Version | 2.0.1 | 1.0.0 |
| Settlement rate | 103.98 % | **93.72 %** |
| Settlement gap | −₹16,46,536 | **₹25,95,426** |
| Risky merchants | 3 | **5** |
| Exceptions | 8 | **11** |
| Smoke test | FAIL | **PASS** |
| Reconciliation | FAIL | **PASS** |

## What comes next (if asked)
1. Keep green isolated and collect its evidence (already saved).
2. Fix all three defects:
   - **A:** aggregate settlements per transaction first, and sum `settlement_amount`.
   - **C:** point to the approved database.
   - **D:** restore the 0–100 clamp and the Pydantic `Percent` rule.
3. Push the fix through the **full pipeline**:
   - tests, including the split-settlement regression test, which would fail on defect A
   - security scans
   - build, then smoke test against the **93.72 % baseline**
   - reconciliation
   - manual approval
4. Deploy it to the idle environment, verify it, and cut over again with blue-green.

---

## Hard questions and answers

**Q: You found the cause at 22:06:40 but only rolled back at 22:13:39. Why wait 7 minutes?**
A: We used that time to gather evidence (the V1 vs V2 comparison, the config, the code diff, and the defect B check) so the decision and the postmortem were based on facts. Honestly, in real production we should **roll back first and investigate after**, because blue stays available for comparison either way. That would cut user impact to about 1 minute. It's an improvement we'd make to the runbook.

**Q: Why didn't the CI pipeline catch this before release?**
A: In the exercise the faulty image was deployed straight to green, bypassing the pipeline, to simulate a bad release reaching production. If it had gone through GitLab CI, two gates would have stopped it:
- the regression test `test_multiple_settlements_do_not_inflate_the_settlement_rate`
- the smoke test with `--expected-rate 93.72`

That's exactly why our prevention step says **no deployment outside the pipeline**.

**Q: The baseline is 93.72 %. What happens when new data arrives and the real rate changes?**
A: The baseline isn't hard-coded forever. It comes from **reconciliation**: the rate recalculated from the fact tables. The smoke test compares the API against that independent calculation. On new data you run reconciliation first, then use its number as the expected rate.

**Q: Why didn't health checks catch it?**
A: Health checks test availability (is the process up, is the database reachable), not correctness. The service was up and answering. You need **business-level checks** that know what the right answer looks like.

**Q: Isn't the smoke test failing on response time (734 ms) a problem?**
A: That was a cold start: the first requests after a container starts are slow. It's unrelated to the incident, and after warm-up V1 answered in 453 ms. In the real cutover process we warm up the new environment before switching traffic.

**Q: What if blue had also been bad, or not running?**
A: Then we'd roll back by redeploying the last known-good image from the registry. Every image is tagged with its commit id and the approved one is tagged `:production`. It takes minutes instead of seconds, which is why keeping the previous version running is worth the cost.

**Q: Who is to blame?**
A: No one. It's a blameless postmortem. The *process* allowed a numbers change to reach production without a business check. We fix the process with the regression test, the reconciliation gate, the smoke test, a KPI alert and SQL review.

---

## A 60-second version of slides 10–12 (if you're short on time)

> "At 22:05 a faulty release, 2.0.1, went live on green. The dashboard showed a 103.98 % settlement rate, which is impossible, a negative gap, and risky merchants disappearing. Yet /health said OK and the logs were clean.
>
> Our business smoke test caught it in one minute. Reconciliation showed the settled amount disagreed with the facts, and comparing V1 and V2 showed the same input with a different output. The code diff showed three defects:
> - settlements joined before summing, so split settlements counted twice
> - the wrong database
> - the 0–100 guard removed
>
> We decided to roll back because wrong money numbers were live and V1 was proven and still running. One command switched Nginx to blue in 3 seconds, and the smoke test and reconciliation confirmed 93.72 % again. The lesson: a healthy service can still be wrong, so we check the business numbers, not just uptime."
