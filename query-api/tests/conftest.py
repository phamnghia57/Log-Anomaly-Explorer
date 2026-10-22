import os
import sys
from pathlib import Path

# Backend nhe, khong can OpenSearch that. Phai set TRUOC khi import main vi
# store = build_store() chay ngay luc import module.
os.environ.setdefault("STORAGE_BACKEND", "memory")

# Them GOC REPO (khong phai thu muc query-api) vao sys.path: query-api import
# thang `ingestion.src.storage`, va test import `query-api.src.main` bang ten
# day du de khong dung ten package "src" voi cac module khac khi chay chung.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
