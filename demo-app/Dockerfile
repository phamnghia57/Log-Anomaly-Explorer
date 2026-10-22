# Demo App (Manh) - image deploy.
#
# Build tu THU MUC GOC repo cho nhat quan voi 3 Dockerfile con lai:
#   docker build -f demo-app/Dockerfile -t prj2-demo-app .

FROM python:3.11-slim

WORKDIR /app

COPY demo-app/requirements.txt demo-app/requirements.txt
RUN pip install --no-cache-dir -r demo-app/requirements.txt

COPY demo-app demo-app

ENV PYTHONPATH=/app
RUN useradd -m appuser && chown -R appuser /app
USER appuser

EXPOSE 8001
CMD ["uvicorn", "demo-app.src.main:app", "--host", "0.0.0.0", "--port", "8001"]
