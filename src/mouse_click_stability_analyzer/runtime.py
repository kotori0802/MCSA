"""Frozen vs source path, helper-mode, and bundled-resource helpers.

Packaging-only concerns live here so product modules do not grow scattered
``sys.frozen`` checks. This module must stay importable without Qt.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .schema import TOOL_VERSION

HELPER_FLAG = "--mcsa-raw-input-helper"
HELPER_ENV = "MCSA_HELPER_MODE"
STARTUP_LOG_NAME = "mcsa_startup.log"

REQUIRED_STRING_FILES: tuple[str, ...] = (
    "common.json",
    "setup.json",
    "capture.json",
    "results.json",
    "preferences.json",
    "report.json",
    "terminology.json",
)

REQUIRED_QT_ASSETS: tuple[str, ...] = (
    "check_white.svg",
    "chevron_down_light.svg",
    "chevron_down_dark.svg",
    "chart_fit.svg",
    "chart_zoom_in.svg",
    "chart_zoom_out.svg",
    "chart_reset.svg",
)


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False)) or hasattr(sys, "_MEIPASS")


def application_dir() -> Path:
    """Writable application folder: EXE directory when frozen, project root otherwise."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def default_report_root() -> Path:
    return application_dir() / "reports"


def is_helper_mode(argv: list[str] | None = None) -> bool:
    args = list(sys.argv[1:] if argv is None else argv)
    return HELPER_FLAG in args or os.environ.get(HELPER_ENV) == "1"


def helper_command() -> list[str]:
    """Command used to start the Raw Input helper process."""
    if is_frozen():
        return [str(Path(sys.executable).resolve()), HELPER_FLAG]
    bridge = Path(__file__).resolve().parent / "adapters" / "raw_input_bridge.py"
    return [sys.executable, str(bridge)]


def helper_env(base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    env[HELPER_ENV] = "1"
    return env


def write_startup_log(text: str) -> Path | None:
    if not is_frozen():
        return None
    try:
        path = application_dir() / STARTUP_LOG_NAME
        path.write_text(text, encoding="utf-8")
        return path
    except OSError:
        return None


def qt_asset_dir() -> Path:
    return Path(__file__).resolve().parent / "qt_shell" / "assets"


def missing_runtime_resources() -> list[str]:
    """Return missing bundled resource names. Empty means the package is intact."""
    missing: list[str] = []
    try:
        from .strings.loader import _read_text, resolve_strings_root

        root = resolve_strings_root()
        for name in REQUIRED_STRING_FILES:
            try:
                text = _read_text(root, name)
            except Exception:
                missing.append(f"strings/{name}")
                continue
            if not str(text).strip():
                missing.append(f"strings/{name}")
    except Exception:
        missing.extend(f"strings/{name}" for name in REQUIRED_STRING_FILES)

    assets = qt_asset_dir()
    for name in REQUIRED_QT_ASSETS:
        if not (assets / name).is_file():
            missing.append(f"qt_shell/assets/{name}")
    return missing


def windows_file_version() -> str:
    """Windows VERSIONINFO FileVersion string (four-part)."""
    return f"{TOOL_VERSION}.0"
