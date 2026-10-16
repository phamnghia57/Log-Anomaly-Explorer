"""
Validate structured log dua theo docs/architect/contracts/log-schema.json.

Day la phan code da chay duoc (khong chi la TODO) vi day la diem dam bao
hop dong du lieu giua demo-app (Manh) va ingestion (Minh).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from jsonschema import Draft7Validator

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "docs" / "architect" / "contracts" / "log-schema.json"
_schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
_validator = Draft7Validator(_schema)


def _timestamp_error(value: object) -> str | None:
    """jsonschema khong tu kiem tra `format: date-time` -> kiem tra them de OpenSearch
    khong tu choi (mapper_parsing_exception) mot timestamp hong."""
    if not isinstance(value, str):
        return None  # loi kieu da duoc schema bao
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "timestamp: khong phai ISO 8601 date-time hop le"
    if parsed.tzinfo is None:
        return "timestamp: thieu mui gio (can UTC, vd. 2026-10-01T09:30:00Z)"
    return None


def validate_log(payload: dict) -> list[str]:
    """Tra ve danh sach loi (rong = hop le)."""
    errors = sorted(_validator.iter_errors(payload), key=lambda e: [str(p) for p in e.path])
    out = [f"{'.'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors]
    if "timestamp" in payload:
        ts_err = _timestamp_error(payload["timestamp"])
        if ts_err:
            out.append(ts_err)
    return out
