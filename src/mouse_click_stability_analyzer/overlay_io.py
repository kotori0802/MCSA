"""Safe loading of overlay / compare JSON detail files."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Limits chosen for worst-case local QA runs:
# - 40 Hz fixture × 3600 s ≈ 144k clicks
# - detail JSON ~200–400 bytes/event → ~30–55 MiB
MAX_OVERLAY_FILE_BYTES = 32 * 1024 * 1024  # 32 MiB on disk
MAX_OVERLAY_EVENT_COUNT = 150_000  # hard cap after parse


class OverlayLoadError(ValueError):
    """Raised when an overlay file cannot be loaded safely."""


def overlay_limits_human() -> str:
    mb = MAX_OVERLAY_FILE_BYTES // (1024 * 1024)
    return f"{mb} MiB file / {MAX_OVERLAY_EVENT_COUNT:,} events"


def load_overlay_payload(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise OverlayLoadError(f"File not found: {p}")
    size = p.stat().st_size
    if size > MAX_OVERLAY_FILE_BYTES:
        raise OverlayLoadError(
            f"Overlay file too large ({size:,} bytes; limit {MAX_OVERLAY_FILE_BYTES:,}). "
            f"Use a shorter run or trim events. ({overlay_limits_human()})"
        )
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise OverlayLoadError(f"Invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise OverlayLoadError("Overlay JSON root must be an object.")
    events = extract_overlay_events(payload)
    if not events:
        raise OverlayLoadError("No click events in overlay file (need *_evidence.json or *_detail.json).")
    if len(events) > MAX_OVERLAY_EVENT_COUNT:
        raise OverlayLoadError(
            f"Too many events ({len(events):,}; limit {MAX_OVERLAY_EVENT_COUNT:,}). "
            f"({overlay_limits_human()})"
        )
    return payload


def extract_overlay_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    events = (
        payload.get("events")
        or payload.get("all_click_events")
        or (payload.get("legacy_payload") or {}).get("events")
        or []
    )
    if not isinstance(events, list):
        return []
    return [e for e in events if isinstance(e, dict)]
