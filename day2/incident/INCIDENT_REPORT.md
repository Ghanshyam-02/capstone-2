# Incident report – settlement rate above 100 % after the V2 release

> Fill every `[ … ]` with YOUR times and outputs (GUIDE.md step 7). The brief says the numbers must come
> from your own run. The values already written are what this dataset produces.

## 1. Incident timeline
| Time | Event | Evidence |
|---|---|---|
| [hh:mm] | V2 (2.0.0) deployed to GREEN, pre-cutover checks passed | `evidence/08`, `09` |
| [hh:mm] | Blue-green cutover: 100 % traffic → GREEN | `evidence/07_blue_green_status.txt` |
| [hh:mm] | Faulty V2 release (2.0.1) replaces GREEN | `incident/evidence/01_*` |
| [hh:mm] | KPI anomaly detected: settlement rate **103.98 %** on the dashboard | `incident/evidence/02_*` |
| [hh:mm] | Investigation started (V1 vs V2 compared) | `incident/evidence/03_*` |
| [hh:mm] | Root cause identified | this report, section 4 |
| [hh:mm] | Rollback initiated: `switch.ps1 blue` | `evidence/07_blue_green_status.txt` |
| [hh:mm] | V1 restored (100 % traffic → BLUE) | `/health` shows version 1.0.0 |
| [hh:mm] | Smoke tests passed | `incident/evidence/05_*` |
| [hh:mm] | Business KPI reconciled: settlement rate **93.72 %** | `incident/evidence/06_*` |

## 2. Incident report
| Field | Value |
|---|---|
| **Incident ID** | INC-[yyyymmdd]-001 |
| **Date** | [date] |
| **Application** | Settlement Intelligence Platform (settlement-api) |
| **Production version** | 2.0.1 on GREEN (faulty) → rolled back to 1.0.0 on BLUE |
| **What happened?** | After the blue-green cutover, the dashboard showed a settlement rate of **103.98 %** (baseline **93.72 %**). 21 merchants showed a settled amount greater than their successful transaction amount. The API still returned **HTTP 200**. |
| **Business impact** | Settlement Rate, Settlement Gap and Merchant Exceptions were wrong. The gap looked **negative** (more settled than paid), so Operations would have stopped chasing ₹25.95 lakh of really unsettled money, and the exception list dropped from 11 to 8 merchants. Wrong financial figures in production = high severity. |
| **Detection method** | Business smoke test (`smoke_test.py`: rate must be 0–100 and equal the reconciled baseline) and KPI reconciliation (`common.reconcile`). **`/health` did NOT detect it** (still 200). |
| **Technical root cause** | Defect A: the V2 Gold query joins `fact_transaction` to `fact_settlement` **before** aggregating, so a transaction with two settlement rows is counted twice (settled amount 42,988,864.94 instead of 38,746,903.53). Defect D: V2 removed the 0–100 guard from the KPI calculation and the API contract, so the impossible value reached users. Defect C: V2 reads `settlement_db_v2.duckdb` instead of the approved database. |
| **Problem type** | query / data-model (A), application (D), configuration (C). Not an infrastructure failure. |
| **Evidence** | `incident/evidence/`: `/health` of V1 vs V2 (version + database file), smoke test FAIL, reconciliation FAIL, V1 vs V2 API responses, dashboard screenshot |
| **Decision** | **Rollback** (see section 3) |
| **Rollback performed** | `day2\deploy\switch.ps1 blue` – traffic removed from GREEN, 100 % to BLUE (V1) in about 1 second |
| **Validation after rollback** | smoke test PASS, reconciliation PASS, settlement rate 93.72 % = baseline |
| **Preventive action** | section 5 |
| **Owner** | [your name] |
| **Due date** | [date] |

## 3. Decision – rollback or fix forward?
| Question | Answer |
|---|---|
| Is production showing wrong money numbers now? | Yes: 103.98 % and a negative gap |
| Is a known-good version available? | Yes: BLUE (V1) is still running and was validated this morning |
| How fast is rollback? | about 1 second (one Nginx switch) |
| How fast is a fix forward? | unknown: diagnose, change SQL + code, test, rebuild, redeploy, under pressure |
| Is the cause fully understood at decision time? | Several defects, scope uncertain |
| **Decision** | **Roll back to V1 now**, then fix V2 through the normal pipeline with new tests |

## 4. Root cause analysis – 5 Whys
1. **Why was the settlement rate above 100 %?** The settled amount in the KPI table was inflated (42.99 M vs 38.75 M).
2. **Why was it inflated?** V2 joined transactions to settlements before aggregating, so transactions with 2 settlement rows were counted twice.
3. **Why did V2 change it?** The Gold aggregation was "simplified" and the 0–100 guard was removed in the same release.
4. **Why was it not detected before users saw it?** The faulty release was checked only for `/health`, which returns 200 even when the numbers are wrong.
5. **Why only `/health`?** No mandatory gate compared business KPIs with the reconciled baseline before or after a release.

**Root cause:** a Gold-layer aggregation change reached production without a business-KPI gate.

## 5. Preventive controls (at least 3)
| # | Control | Status / where |
|---|---|---|
| 1 | Regression test: one transaction → multiple settlements must stay at 100 % | ✅ `day1/tests/test_business_rules.py::test_multiple_settlements_do_not_inflate_the_settlement_rate`, runs in GitLab CI + Jenkins |
| 2 | Reconciliation gate: settled ≤ successful, KPI table = facts | ✅ `python -m common.reconcile` (exit 1 on failure), mandatory before every cutover |
| 3 | Business smoke test in blue-green (KPI values, not only `/health`) | ✅ `day2/scripts/smoke_test.py --expected-rate`, in the GitLab `smoke_test` stage |
| 4 | KPI anomaly monitoring: alert if the rate moves > 2 points or leaves 0–100 | [proposed – run smoke_test.py every 5 minutes] |
| 5 | Mandatory SQL / data-model review for changes to Gold metrics | [proposed – merge request approval rule] |

## 6. Other defect types checked
| Defect (brief) | Checked how | Result in this incident |
|---|---|---|
| B – filter on `ingestion_ts` instead of `transaction_ts` | compare `/api/v1/daily-trend` of V1 (8001) and V2 (8002) day by day | not present (daily totals of successful amount identical) |
