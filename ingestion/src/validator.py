"""
Validate structured log dua theo docs/architect/contracts/log-schema.json.

Day la phan code da chay duoc (khong chi la TODO) vi day la diem dam bao
hop dong du lieu giua demo-app (Manh) va ingestion (Minh).
"""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft7Validator

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "docs" / "architect" / "contracts" / "log-schema.json"
_schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
_validator = Draft7Validator(_schema)


def validate_log(payload: dict) -> list[str]:
    """Tra ve danh sach loi (rong = hop le)."""
    errors = sorted(_validator.iter_errors(payload), key=lambda e: e.path)
    return [f"{'.'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors]
