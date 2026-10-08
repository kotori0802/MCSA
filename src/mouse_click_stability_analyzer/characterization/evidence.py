"""Read MCSA_EVIDENCE_V1 packages. Stage 2D comparison fields are ignored."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from ..schema import EVIDENCE_SCHEMA

IGNORED_COMPARISON_KEYS = (
    "interval_comparison_enabled",
    "interval_comparison_basis",
    "interval_comparison_value",
    "interval_comparison",
)

_TRUE = {"true", "1", "yes"}


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def resolve_evidence_path(package_path: Path) -> Path | None:
    """Locate *_evidence.json. Does not fall back to summary.json / detail.json."""
    path = package_path
    if path.is_file():
        name = path.name.lower()
        if name.endswith("_evidence.json") or name == "evidence.json":
            return path
        return None
    if not path.is_dir():
        return None
    matches = sorted(path.glob("*_evidence.json")) + sorted(path.glob("evidence.json"))
    if not matches:
        nested = sorted(path.glob("mcsa_*/mcsa_*_evidence.json"))
        matches = nested
    unique = []
    seen: set[Path] = set()
    for item in matches:
        resolved = item.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(item)
    if len(unique) == 1:
        return unique[0]
    if len(unique) > 1:
        # Prefer a file whose parent is the given directory.
        direct = [item for item in unique if item.parent.resolve() == path.resolve()]
        if len(direct) == 1:
            return direct[0]
    return unique[0] if len(unique) == 1 else None


def load_evidence_json(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("evidence.json root must be an object")
    return payload


def schema_ok(payload: dict[str, Any]) -> bool:
    schema = str(payload.get("schema") or payload.get("schema_version") or "")
    return schema == EVIDENCE_SCHEMA


def settings_of(payload: dict[str, Any]) -> dict[str, Any]:
    settings = payload.get("settings")
    return dict(settings) if isinstance(settings, dict) else {}


def comparison_fields_present(payload: dict[str, Any]) -> bool:
    settings = settings_of(payload)
    if any(key in settings for key in IGNORED_COMPARISON_KEYS[:3]):
        return True
    return isinstance(payload.get("interval_comparison"), dict)


def accepted_focus_presses(payload: dict[str, Any]) -> list[dict[str, Any]]:
    settings = settings_of(payload)
    focus = str(settings.get("focus_button") or "").strip()
    events = payload.get("events")
    if not isinstance(events, list):
        return []
    out: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        accepted = event.get("accepted")
        if accepted is True or (isinstance(accepted, str) and accepted.strip().lower() in _TRUE):
            button = str(event.get("button") or "").strip()
            if focus and button.lower() != focus.lower():
                continue
            press = _finite(event.get("press_elapsed_ms"))
            if press is None:
                continue
            row = dict(event)
            row["press_elapsed_ms"] = press
            out.append(row)
    out.sort(key=lambda row: (float(row["press_elapsed_ms"]), str(row.get("click_index") or row.get("index") or "")))
    return out


def host_context(payload: dict[str, Any]) -> dict[str, Any]:
    info = payload.get("host_information")
    if not isinstance(info, dict):
        env = payload.get("host_test_environment")
        info = env if isinstance(env, dict) else {}
    controllers = info.get("usb_host_controllers")
    if isinstance(controllers, list):
        controller_text = "; ".join(str(item) for item in controllers if item)
    else:
        controller_text = str(controllers or "")
    return {
        "host_manufacturer": info.get("host_manufacturer") or info.get("manufacturer"),
        "host_model": info.get("host_model") or info.get("model"),
        "os_name": info.get("os_name"),
        "os_version": info.get("os_version"),
        "cpu_model": info.get("cpu_model"),
        "bios_vendor": info.get("bios_vendor"),
        "bios_version": info.get("bios_version"),
        "usb_host_controllers": controller_text,
        "dut_usb_controller_attributed": bool(info.get("dut_usb_controller_attributed")),
        "capture_backend": info.get("capture_backend"),
        "tool_version": payload.get("tool_version") or info.get("tool_version"),
        "python_version": info.get("python_version") or info.get("python_runtime"),
        "pyside6_version": info.get("pyside6_version"),
        "qt_version": info.get("qt_version"),
    }
