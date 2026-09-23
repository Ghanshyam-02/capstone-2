# Image for the API + dashboard.
#   docker build -t settlement-api:1.0 .
#   docker run -p 8000:8000 --env-file .env -v "${PWD}/keys:/app/keys:ro" settlement-api:1.0
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# 1. dependencies first -> Docker caches this layer until requirements.txt changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. only the code the API needs (no data, no tests, no secrets - see .dockerignore)
COPY common/ common/
COPY api/ api/
COPY frontend/ frontend/

# 3. never run as root
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status == 200 else 1)"

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
