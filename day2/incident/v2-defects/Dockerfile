# ⚠️ INCIDENT EXERCISE ONLY - a "bad release" of Version 2 with injected defects.
#
#   docker build -t settlement-api:v2-incident day2/incident/v2-defects
#
# It starts FROM the good V2 image and changes only 3 files + the configuration:
#   Defect A (grain)         sql/05_silver_to_gold.sql : settlements joined before aggregation
#   Defect C (configuration) SETTLEMENT_DB             : points to settlement_db_v2, not the approved database
#   Defect D (API)           common/kpi.py, models.py  : the 0..100 guard removed
FROM settlement-api:v2

USER root
COPY sql/05_silver_to_gold.sql sql/05_silver_to_gold.sql
COPY common/kpi.py common/kpi.py
COPY api/models.py api/models.py

ENV APP_VERSION=2.0.1 \
    SETTLEMENT_DB=data/warehouse/settlement_db_v2.duckdb

RUN python -m pipeline.run_pipeline && chown -R appuser /app/data
USER appuser
