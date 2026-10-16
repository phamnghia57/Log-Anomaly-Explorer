import os
import sys
from pathlib import Path

os.environ.setdefault("STORAGE_BACKEND", "memory")
os.environ.setdefault("RETENTION_INTERVAL_SECONDS", "0")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
