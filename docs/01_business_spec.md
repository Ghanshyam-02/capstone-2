# 1. Business Specification

## Problem statement
Yesterday ₹48 Cr was transacted but only ₹45.8 Cr settled. Operations works from nightly Excel
reports and cannot tell whether the ₹2.2 Cr gap is caused by failed payments, pending settlements,
processing delays, merchant risk controls or data-quality problems.

## Objective
One trusted, near-real-time view of payment → settlement performance that **explains** the gap,
flags slow/abnormal merchants, and exposes it through an API and a web dashboard.

## Users
| User | Needs |
|---|---|
| Head of Payments | Headline KPIs, trend, "why is there a gap?" |
| Payments Operations analyst | Merchant exceptions, unsettled transactions to chase |
| Risk team | Merchants with abnormal settlement behaviour + their risk level |
| Data engineering / support | Data-quality log, pipeline run log |

## KPIs
| # | KPI | Formula |
|---|---|---|
| 1 | Transaction Volume | Σ amount of **SUCCESS** transactions |
| 2 | Settlement Rate | Σ settled amount ÷ Σ successful amount × 100 |
| 3 | Settlement Gap | Σ successful amount − Σ settled amount |
| 4 | Settlement SLA | % of successful transactions **fully settled within 30 min** of the transaction |
| 5 | Merchant Risk | # merchants with Settlement Rate < 95 % **AND** SLA < 90 % |

## Scope
**In:** the 4 source files, Bronze/Silver/Gold on Snowflake, incremental loads, data-quality handling,
REST API, HTML dashboard, automated tests, CI/CD design.
**Out:** real-time streaming (we run micro-batches), refunds/chargebacks, FX conversion, user management UI.

## Assumptions
1. All valid transactions are in **INR** (India acquiring). Anything else is an invalid currency.
2. "Settled" means `settlement_status = SETTLED`. PENDING / FAILED records settle nothing.
3. Settled amount per transaction is **capped** at the transaction amount (rates never exceed 100 %).
4. SLA is measured per successful transaction: time from `transaction_ts` to its **last** SETTLED record.
5. An event is **late** if `ingestion_ts − event_ts > 5 minutes` (configurable).
6. Timestamps are local business time (IST), no time-zone conversion.
7. A merchant's risk level for a transaction is the one valid **on the transaction date**.

## Business rules — how each data problem is treated
| Problem | Class | Handling |
|---|---|---|
| Unreadable id / timestamp / amount | **Reject** | Logged in `AUDIT.DQ_LOG`, never loaded |
| Duplicate event id | **Reject** | First copy kept, duplicate logged |
| Missing / unknown merchant id | **Quarantine** | Held in DQ log for Ops to fix |
| Invalid currency | **Quarantine** | Held in DQ log |
| Negative settlement amount | **Quarantine** | Could be a refund/reversal → human review |
| Settlement without matching transaction | **Quarantine** | Orphan, held in DQ log |
| Event arriving after SLA (late) | **Warning** | Loaded, flagged `IS_LATE`, logged |
| Successful transaction not (fully) settled | **Business exception** | Loaded, classified UNSETTLED / PENDING / PARTIALLY_SETTLED, shown in `GOLD.V_SETTLEMENT_EXCEPTIONS` |

## Acceptance criteria
1. Dashboard shows the KPI cards, the daily chart, the top-10 gap chart and the merchant table, **from the API only**.
2. `GET /api/v1/settlement-summary` and `GET /api/v1/merchant-exceptions` return the documented JSON.
3. A split settlement (8,000 + 2,000) counts the transaction **once**.
4. Every rejected / quarantined / warning record is visible in `AUDIT.DQ_LOG` with a reason.
5. Re-running the pipeline with no new files changes nothing; adding a new file processes only the new rows.
6. Successful amount = settled amount + gap (reconciles exactly).
7. All unit, API-contract and data-model tests pass.
