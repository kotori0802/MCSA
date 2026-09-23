"""MCSA public report and settings schema (v1)."""
from __future__ import annotations

from typing import Any

TOOL_ID = "mouse_click_stability_analyzer"
TOOL_NAME = "Mouse Click Stability Analyzer"
TOOL_VERSION = "1.0.0"
SUMMARY_SCHEMA = "MCSA_REPORT_V1"
DETAIL_SCHEMA = "MCSA_DETAIL_V1"
SETTINGS_SCHEMA = "MCSA_SETTINGS_V1"

CAPTURE_WINDOWS_RAW_INPUT = "Windows Raw Input"
DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = ("en", "zh")

ARMING_SEC = 0.40


def default_report_dir(app_root) -> "Path":
    from pathlib import Path
    return Path(app_root) / "reports"


def artifact_names(run_id: str) -> dict[str, str]:
    rid = str(run_id or "run")
    return {
        "summary_json": f"mcsa_{rid}_summary.json",
        "detail_json": f"mcsa_{rid}_detail.json",
        "all_click_log_csv": f"mcsa_{rid}_events.csv",
        "engineering_xlsx": f"mcsa_{rid}_report.xlsx",
        "engineering_html": f"mcsa_{rid}_report.html",
        "txt": f"mcsa_{rid}_analysis.txt",
    }


def build_host_environment(settings: dict[str, Any]) -> dict[str, Any]:
    import platform
    import sys

    device = settings.get("device_under_test") or {}
    return {
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "capture_backend": settings.get("capture_mode") or CAPTURE_WINDOWS_RAW_INPUT,
        "language": settings.get("language") or DEFAULT_LANGUAGE,
        "profile_name": settings.get("profile_name"),
        "fixture_hz": settings.get("fixture_hz"),
        "duration_sec": settings.get("duration_sec"),
        "focus_button": settings.get("focus_button"),
        "device_under_test": {
            "name": device.get("name") or "",
            "vid": device.get("vid") or "",
            "pid": device.get("pid") or "",
            "bcd_device": device.get("bcd_device") or "",
            "instance_id": device.get("instance_id") or "",
        } if device else None,
    }


def normalize_public_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    s = dict(settings or {})
    s.setdefault("language", DEFAULT_LANGUAGE)
    s.setdefault("operator", "")
    s.setdefault("device_label", "")
    s.setdefault("device_under_test", None)
    s.setdefault("capture_mode", CAPTURE_WINDOWS_RAW_INPUT)
    return s
