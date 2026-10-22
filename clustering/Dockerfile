# Clustering worker (Nam) - image deploy.
#
# Khong phai HTTP service: chay vong lap nen (xem src/worker.py).
# Build tu THU MUC GOC repo vi clustering/src/storage.py import thang
# `ingestion.src.storage` (dung chung ket noi/cau hinh OpenSearch voi Minh):
#   docker build -f clustering/Dockerfile -t prj2-clustering .

FROM python:3.11-slim

WORKDIR /app

# requirements-ml.txt da bao gom requirements.txt (-r) va them scikit-learn
# cho lop TF-IDF augment. Cai luon de ML_AUGMENT_ENABLED (mac dinh true) chay
# duoc that; neu khong co scikit-learn, worker van chay nhung tu lui ve
# rule-based (xem clustering/src/ml_augment.py).
COPY clustering/requirements.txt clustering/requirements.txt
COPY clustering/requirements-ml.txt clustering/requirements-ml.txt
RUN pip install --no-cache-dir -r clustering/requirements-ml.txt

COPY clustering clustering
COPY ingestion ingestion

ENV PYTHONPATH=/app
# clustering/data/ chua file state cua ML augment - worker phai ghi duoc.
RUN useradd -m appuser && mkdir -p /app/clustering/data && chown -R appuser /app
USER appuser

CMD ["python", "-m", "clustering.src.worker"]
