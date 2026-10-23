# Ingestion Service (Minh) - image deploy.
#
# Build tu THU MUC GOC repo (khong phai tu trong ingestion/), vi
# ingestion/src/validator.py doc docs/architect/contracts/log-schema.json
# theo duong dan tuong doi tinh tu goc repo luc chay:
#   docker build -f ingestion/Dockerfile -t log-anomaly-ingestion .
# (docker-compose.yml o goc repo da cau hinh dung context nay)

FROM python:3.11-slim

WORKDIR /app

COPY ingestion/requirements.txt ingestion/requirements.txt
RUN pip install --no-cache-dir -r ingestion/requirements.txt

COPY ingestion ingestion
COPY docs docs

ENV PYTHONPATH=/app
RUN useradd -m appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "ingestion.src.main:app", "--host", "0.0.0.0", "--port", "8000"]
