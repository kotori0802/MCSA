"""Validation issue records. Not DUT WARN/FAIL."""
from __future__ import annotations

from typing import Any

LEVEL_ERROR = "ERROR"
LEVEL_EXCLUDED = "EXCLUDED"
LEVEL_INFO = "INFO"
VALID_LEVELS = (LEVEL_ERROR, LEVEL_EXCLUDED, LEVEL_INFO)


def issue(level: str, code: str, message: str, **extra: Any) -> dict[str, Any]:
    if level not in VALID_LEVELS:
        raise ValueError(f"unknown characterization issue level: {level}")
    payload: dict[str, Any] = {"level": level, "code": code, "message": message}
    payload.update(extra)
    return payload
