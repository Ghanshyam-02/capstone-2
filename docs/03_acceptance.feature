Feature: Merchant settlement intelligence
  Operations must be able to trust and explain payment vs settlement numbers.

  Scenario: Identify an unsettled successful transaction
    Given a successful payment exists
    And no successful settlement exists for the transaction
    When the settlement pipeline runs
    Then the transaction should be classified as UNSETTLED
    And it should appear in the settlement exception report

  Scenario: A split settlement is counted once
    Given transaction T1001 of 10,000 INR is SUCCESS
    And it has settlements S1 of 8,000 and S2 of 2,000, both SETTLED
    When the settlement pipeline runs
    Then the settled amount of T1001 should be 10,000
    And the transaction amount should be counted once in the daily totals

  Scenario: A negative settlement is quarantined
    Given a settlement record with settlement_amount -500
    When the settlement pipeline runs
    Then the record should not be loaded into Silver or Gold
    And it should be in AUDIT.DQ_LOG with severity QUARANTINE and reason NEGATIVE_SETTLEMENT_AMOUNT

  Scenario: Risk level is taken as of the transaction date
    Given merchant M100 is LOW from January to March and HIGH from April to June
    And a transaction for M100 on 15 February
    When the pipeline runs
    Then the transaction's risk level should be LOW

  Scenario: A late event is kept but flagged
    Given an event with event_ts 10:02:15 and ingestion_ts 10:08:41
    When the pipeline runs
    Then the event should be loaded with IS_LATE = TRUE
    And reports should use event_ts (business time), not ingestion_ts

  Scenario: A merchant with poor settlement appears in the exception API
    Given merchant M108 has settlement rate 76% and SLA 43% in the selected period
    When I call GET /api/v1/merchant-exceptions
    Then the response should contain M108 with its risk level

  Scenario: Only new data is processed on the next run
    Given the pipeline has already processed batch 1
    When batch 2 files arrive and the pipeline runs again
    Then batch 1 files should not be loaded again
    And only the dates affected by batch 2 should be recalculated

  Scenario: Investigate a delayed settlement
    Given a successful payment at 10:00
    And it was fully settled at 10:45
    When the settlement pipeline runs
    Then the transaction should miss the 30-minute SLA
    And it should appear in the settlement exception report as DELAYED with a delay of 45 minutes
