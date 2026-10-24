import sys
from pathlib import Path

# clustering/src/storage.py import thang `ingestion.src.storage` (cung kho du
# lieu voi Minh, khong goi HTTP) - can them goc repo vao sys.path de Python
# tim duoc package `ingestion`.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
