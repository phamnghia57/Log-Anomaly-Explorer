# Demo App (Manh) - image deploy.
#
# Build tu THU MUC GOC repo cho nhat quan voi 3 Dockerfile con lai:
#   docker build -f demo-app/Dockerfile -t log-anomaly-demo-app .

FROM python:3.11-slim

WORKDIR /app

COPY demo-app/requirements.txt demo-app/requirements.txt
# KHONG dung --pre o day: no se cho phep pip chon ban beta cho MOI goi trong
# file (tung lam httpx bi keo len 1.0.dev, doi API, lam demo-app crash lien
# tuc). Marker "b0" ngay trong requirements.txt (opentelemetry-instrumentation-
# fastapi>=0.39b0) da du de pip nhan beta CHI cho rieng goi do.
RUN pip install --no-cache-dir -r demo-app/requirements.txt

COPY demo-app demo-app

ENV PYTHONPATH=/app
RUN useradd -m appuser && chown -R appuser /app
USER appuser

EXPOSE 8001
CMD ["uvicorn", "demo-app.src.main:app", "--host", "0.0.0.0", "--port", "8001"]
