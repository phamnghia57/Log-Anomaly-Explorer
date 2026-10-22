# Query & Incident API (Nghia) - image deploy.
#
# Build tu THU MUC GOC repo vi query-api/src/main.py import thang
# `ingestion.src.storage` (log cua Minh) va `clustering.src.storage`
# (cum cua Nam):
#   docker build -f query-api/Dockerfile -t prj2-query-api .

FROM python:3.11-slim

WORKDIR /app

COPY query-api/requirements.txt query-api/requirements.txt
RUN pip install --no-cache-dir -r query-api/requirements.txt

COPY query-api query-api
COPY ingestion ingestion
COPY clustering clustering

ENV PYTHONPATH=/app
RUN useradd -m appuser && chown -R appuser /app
USER appuser

EXPOSE 8002
CMD ["uvicorn", "query-api.src.main:app", "--host", "0.0.0.0", "--port", "8002"]
