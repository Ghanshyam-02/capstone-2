# Day 2 – Viva / Leadership Presentation Script

A spoken script for the **8–10 minute** leadership presentation (Task 6), following the 8 slides the
brief requires, then the 360° peer review and the viva questions with answers.

> ⚠️ **Fill in the `[ … ]` placeholders with YOUR real evidence** (times, pipeline ids, screenshots) after we
> implement Day 2. The brief says the numbers must come from your own run, not be assumed.
> Numbers already known from our data: V1 baseline September settlement rate **93.72 %**, gap **₹25.95 lakh**,
> SLA **77.09 %**, 3,383 successful transactions, 5 risky merchants.

---

## Slide 1 – Business problem (1 min)

> "Bank of New York's payments operations could not explain why successful payments and settled amounts
> didn't match. ₹48 crore succeeded but ₹45.8 crore settled. They had four separate systems and only nightly Excel.
>
> Our Settlement Intelligence Platform answers that question every day: how big the gap is, **why** it
> exists (never settled, pending, partly settled or delayed), **which merchants** cause it, and **how much
> is bad data**. On our September data, the settlement rate is 93.72 % against a 95 % target, a gap of
> ₹25.95 lakh, and only 77 % of payments are settled within the 30-minute SLA.
>
> Today's question isn't *does it work*. It's *can the bank trust it in production*."

## Slide 2 – Architecture (1 min)

> "Data flows Source → Bronze → Silver → Gold → API → Dashboard. Bronze keeps the raw files, Silver
> validates and logs every bad row, Gold is a star schema with a daily KPI table, FastAPI serves it
> read-only, and the dashboard only talks to the API.
>
> **Deployment architecture:** the application is one Docker image with the validated database built
> inside. It's built by **GitLab CI**, the primary path, and independently by **Jenkins**, the secondary path.
> Production runs **blue-green**: two containers behind an **Nginx** load balancer. Blue is Version 1, green is
> Version 2, and Nginx decides which one users reach."

## Slide 3 – Production readiness (1.5 min)

> "Here's the proof, one tick per production requirement:
> - **Tests ✓:** [22] tests across unit, data model, pipeline, API, business rules and security, 100 % passing,
>   including the mandatory negative test for multiple settlements. *(evidence 01)*
> - **Security ✓:** Bandit SAST, Gitleaks secret scan, pip-audit SCA and Trivy container scan.
>   [0] critical findings. [List any high/medium findings and the remediation.] *(evidence 02)*
> - **Docker ✓:** image `settlement-api:[v2 tag]`, non-root, with a health check. *(evidence 05)*
> - **GitLab CI ✓:** validate, test, security, build, package, deploy_dev, smoke_test, then deploy_prod behind a
>   **manual approval**, using artifacts, cache, rules, needs, protected variables and environments.
>   Pipeline [#id]. *(evidence 03)*
> - **Jenkins ✓:** a Jenkinsfile that independently checks out, installs, tests, scans, builds and
>   publishes the same artifact. Build [#id]. *(evidence 04)*
> - **Blue-green ✓:** pre-cutover checks on green (health, database, pipeline, tests, smoke test, KPI
>   reconciliation), then 100 % traffic to green. *(evidence 06–09)*
>
> The API responds in [xx] ms, well under the 500 ms target. No secrets are in the code."

## Slide 4 – Production incident (1.5 min)

> "At [10:08] we cut over to green, Version 2. At [10:15] the dashboard showed a settlement rate of
> **103.98 %**. Before, it was **93.72 %**. Operations also reported 21 merchants whose settled amount was higher
> than their successful amount. That's impossible under our business rules.
>
> **How it was detected:** not by the health check. `/health` still returned HTTP 200. It was detected by the
> **business smoke test and KPI reconciliation**: the API's rate was above 100 %, and it no longer matched the
> rate calculated directly in SQL.
>
> **Impact:** three KPIs were wrong: settlement rate, settlement gap and the merchant-exceptions list.
> Operations would have concluded that everything was settled and stopped chasing ₹[25.95] lakh of real
> unsettled money. In a bank, wrong financial figures are a severe incident.
>
> **Evidence:** API responses from V1 and V2 side by side, application logs, the deployed version from
> `/health`, the KPI SQL output, and the pipeline artifacts. *(incident folder)*
>
> **Diagnosis:** we compared V1 (blue, still running) with V2 (green). The transaction amount was identical,
> but the settled amount was 42.99 M instead of 38.75 M. The faulty release 2.0.1 contained:
> - **A (grain):** the Gold query joins transactions to settlements before aggregating, so a transaction
>   with two settlement rows is counted twice.
> - **C (configuration):** `/health` showed it reading `settlement_db_v2` instead of the approved database.
> - **D (API):** the 0–100 guard was removed, so the impossible rate reached the dashboard with HTTP 200.
> - We also checked **B** (date filter on `ingestion_ts`) by comparing the daily trend of V1 and V2: not present."

## Slide 5 – Decision (1 min)

> "The question was: roll back, or keep troubleshooting V2 in production?
>
> We **rolled back**, for three reasons:
> 1. **Business risk:** production was showing wrong money figures right now.
> 2. **Recovery time:** blue, Version 1, was still running and proven correct. Switching back takes seconds.
>    Fixing forward meant diagnosing, coding, testing and redeploying under pressure.
> 3. **Uncertainty:** with more than one defect, we couldn't be sure a quick patch fixed everything.
>
> So: restore correct numbers first, then fix V2 calmly through the normal pipeline."

## Slide 6 – Recovery (1 min)

> "V2, incident, detection, rollback, V1, validation. Our actual timeline:
>
> | Time | Step |
> |---|---|
> | [10:00] | V2 deployed to green |
> | [10:08] | Blue-green cutover |
> | [10:15] | KPI anomaly detected (rate 103.98 %) |
> | [10:22] | Investigation started |
> | [10:35] | Root cause identified |
> | [10:40] | Rollback initiated: traffic removed from green |
> | [10:45] | V1 restored: 100 % on blue |
> | [10:50] | Smoke tests passed |
> | [10:55] | Business KPIs reconciled: rate back to **93.72 %** |
>
> Before rollback: 103.98 %. After rollback: 93.72 %, which matches the SQL reconciliation exactly.
> Production was restored in [N] minutes from detection."

## Slide 7 – Prevention (1 min)

> "Root cause, using 5 Whys:
> 1. The rate was over 100 % because the settled amount was inflated.
> 2. The settled amount was inflated because multiple settlement rows were joined to each transaction.
> 3. That happened because V2 changed the Gold aggregation logic.
> 4. It wasn't caught because the deployment smoke test only checked `/health`.
> 5. That was the case because no gate compared business KPIs with the baseline.
>
> Permanent controls, added to the pipeline:
> 1. **Regression test:** one transaction with multiple settlements must stay at 100 %, as a required gate.
> 2. **Reconciliation gate:** settled amount ≤ successful amount, and API KPIs = SQL KPIs.
> 3. **Business smoke test** in blue-green: checks KPI values, not only `/health`.
> 4. **KPI anomaly alert:** fires if the rate moves more than [x] points or goes above 100 %.
> 5. **Mandatory SQL / data-model review** for any change to Gold metrics.
>
> Owner: [name]. Due date: [date]."

## Slide 8 – Business outcome (1 min)

> "What the bank gains:
> - **Settlement visibility:** daily KPIs instead of nightly Excel, and the gap explained by reason.
> - **Operational investigation:** exception lists by merchant, day and type (unsettled, pending, delayed).
> - **Data trust:** bad data is quarantined with a reason and never hidden, and the numbers are reconciled.
> - **Deployment safety:** tests, security gates and approvals before anything reaches production.
> - **Recovery capability:** a bad release was detected by business checks and rolled back in minutes,
>   with evidence.
>
> Today we didn't just ship software, we proved we can run it safely. Thank you."

---

## 360° peer review (Task 7)

Score the other team 1–5 per area:

| Area | Score | Comment |
|---|---|---|
| Technical implementation | | |
| Data modelling | | |
| Testing | | |
| Security | | |
| CI/CD | | |
| Incident response | | |
| Communication | | |
| Business understanding | | |
| Team collaboration | | |

Answer:
1. What was technically strong?
2. What was the biggest engineering risk?
3. Was the production decision supported by evidence?
4. Was the rollback strategy adequate?
5. What one improvement would you recommend?

*Be specific: "the smoke test only checked /health" is more useful than "testing was weak".*

---

## Likely viva questions – with answers

### Production readiness & testing
1. **What does production-ready mean?** It means proven, with evidence, to be tested, secure, deployable, observable and recoverable. Running on a laptop doesn't count.
2. **What is a quality gate?** An automatic pipeline check that stops the release if it fails, e.g. any failing test or any critical vulnerability.
3. **What is the mandatory negative test?** One transaction with settlements of 8,000 + 2,000 on 10,000 must give a 100 % rate, not 200 %. It proves the one-to-many trap can't come back.

### Security gate
4. **SAST vs SCA vs container scan?** SAST checks our own code (Bandit). SCA checks third-party libraries for known CVEs (pip-audit). A container scan checks the whole image, including OS packages (Trivy).
5. **What do you do with a vulnerable dependency?** Record the library, the CVE and its severity, and decide whether it blocks production (critical / high = yes). Then fix it, usually by upgrading to the patched version, and re-run the scan.
6. **How do you guarantee no secrets are in the repo?** Gitleaks scans the code and the Git history in CI. Secrets live only in masked, protected CI variables and `.env` (git-ignored).

### GitLab CI & Jenkins
7. **Artifacts vs cache?** Artifacts are outputs we keep and pass on (test reports, images, evidence). A cache just speeds up the next run (pip downloads) and can be thrown away.
8. **What do `rules` and `needs` do?** `rules` decide *whether* a job runs (branch, changed files). `needs` let a job start as soon as specific jobs finish, instead of waiting for the whole stage.
9. **How is production approval controlled?** `deploy_prod` has `when: manual` and runs only on the protected main branch with protected variables, so an authorised person must click it.
10. **Why keep Jenkins next to GitLab CI?** For legacy workloads, as an independent backup build path if GitLab is unavailable, for its plugin integrations, and because a big migration all at once is risky. Both produce the same artifact.

### Blue-green
11. **How does blue-green work?** Two identical environments. The new version is deployed to the idle one and checked, then the load balancer switches all traffic. Rollback means switching back.
12. **Blue-green vs canary vs rolling?** Blue-green gives an instant rollback but needs double the resources. Canary sends a small % first, which is safer for gradual exposure. Rolling replaces instances one by one, with a slower rollback.
13. **What are the pre-cutover checks?** App health, API health, database connectivity, pipeline health, test suite, smoke test and KPI reconciliation, all on green before any traffic moves.

### Incident
14. **Why didn't the health check catch the incident?** `/health` only proves the app is alive. The defect produced wrong numbers with HTTP 200, so only a business-level check (KPI values, reconciliation) catches it.
15. **Which KPIs were affected, and what type of problem was it?** The settlement rate, the gap and merchant exceptions. Defects A and B are query / data-model problems, C is a configuration problem, and D is an application calculation problem.
16. **Why roll back instead of fixing?** Wrong financial figures were live, V1 was proven and one switch away, and there were several defects of uncertain scope. Rollback is the fastest, lowest-risk way to restore correct numbers.
17. **How did you prove the recovery?** Smoke tests passed on blue, and the API's settlement rate (93.72 %) matched the SQL reconciliation exactly. Evidence files were saved with timestamps.
18. **What is a 5 Whys?** You keep asking "why" until you reach a process cause. Ours ended at "no gate compared business KPIs", not just "a wrong join".
19. **Name three preventive controls.** A multiple-settlement regression test as a gate, a reconciliation gate (settled ≤ successful, API = SQL), and business-KPI smoke tests plus anomaly alerts. SQL review for Gold changes is a fourth.
20. **What would you do differently next time?** Run the business smoke test on green *before* the cutover, so the incident would have been caught before any user saw it.
