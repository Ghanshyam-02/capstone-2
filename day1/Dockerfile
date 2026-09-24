# Image for the API + dashboard.
#   docker build -t settlement-api:1.0 .
#   docker run -p 8000:8000 -e API_KEY=<your key> settlement-api:1.0
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# 1. dependencies first -> Docker caches this layer until requirements.txt changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. the code + the source CSV files (no tests, no .env - see .dockerignore)
COPY common/ common/
COPY pipeline/ pipeline/
COPY sql/ sql/
COPY data/raw/ data/raw/
COPY api/ api/
COPY frontend/ frontend/

# 3. build the database INSIDE the image, so every container of this version
#    serves exactly the same, already-validated data
RUN python -m pipeline.run_pipeline

# 4. never run as root
RUN useradd --create-home appuser && chown -R appuser /app/data
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status == 200 else 1)"

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
