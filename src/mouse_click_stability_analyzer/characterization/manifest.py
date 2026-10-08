"""Engineer-editable characterization lab manifest (CSV)."""
from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any, Iterable

from .issues import LEVEL_ERROR, issue

MANIFEST_FIELDS = (
    "run_id",
    "package_path",
    "campaign_id",
    "purpose",
    "actuation_source",
    "characterization_eligible",
    "exclusion_reason",
    "fixture_vendor",
    "fixture_model",
    "fixture_unit_id",
    "fixture_firmware",
    "control_dut_id",
    "host_label",
    "usb_port_label",
    "expected_rate_hz",
    "expected_duration_sec",
    "repeat_index",
    "auto_stop_on",
    "notes",
    "vendor_timing_accuracy_ms",
    "vendor_spec_reference",
)

ACTUATION_PHYSICAL = "physical_fixture"
ACTUATION_HUMAN = "human"
ACTUATION_SOFTWARE = "software"
ACTUATION_UNKNOWN = "unknown"
ACTUATION_SOURCES = (ACTUATION_PHYSICAL, ACTUATION_HUMAN, ACTUATION_SOFTWARE, ACTUATION_UNKNOWN)

_YES = {"yes", "true", "1", "y"}
_NO = {"no", "false", "0", "n"}


class ManifestError(ValueError):
    """Manifest cannot be parsed."""


def _cell(row: dict[str, str], key: str) -> str:
    raw = row.get(key)
    if raw is None:
        return ""
    return str(raw).strip()


def _parse_bool(text: str) -> bool | None:
    token = text.strip().lower()
    if token in _YES:
        return True
    if token in _NO:
        return False
    return None


def _parse_float(text: str) -> float | None:
    if not text.strip():
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if not math.isfinite(number):
        return None
    return number


def _normalize_header(name: str) -> str:
    return str(name or "").strip().lstrip("\ufeff").lower()


def load_manifest(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (rows, issues). Rows keep original field text plus typed values."""
    if not path.is_file():
        raise ManifestError(f"manifest not found: {path}")
    issues: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        if not sample.strip():
            raise ManifestError("manifest is empty")
        reader = csv.DictReader(_skip_comments(handle))
        if reader.fieldnames is None:
            raise ManifestError("manifest has no header row")
        header_map = {_normalize_header(name): name for name in reader.fieldnames if name}
        missing = [name for name in ("run_id", "package_path", "actuation_source", "characterization_eligible") if name not in header_map]
        if missing:
            raise ManifestError("manifest missing required columns: " + ", ".join(missing))
        for line_no, raw in enumerate(reader, start=2):
            if raw is None:
                continue
            mapped = {_normalize_header(k): (v if v is not None else "") for k, v in raw.items() if k}
            if not any(str(v).strip() for v in mapped.values()):
                continue
            parsed, row_issues = parse_manifest_row(mapped, source_line=line_no, manifest_dir=path.parent)
            rows.append(parsed)
            issues.extend(row_issues)
    if not rows:
        raise ManifestError("manifest has no data rows")
    return rows, issues


def _skip_comments(handle: Iterable[str]):
    for line in handle:
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        yield line


def parse_manifest_row(
    mapped: dict[str, str],
    *,
    source_line: int,
    manifest_dir: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    run_id = _cell(mapped, "run_id")
    package_text = _cell(mapped, "package_path")
    actuation = _cell(mapped, "actuation_source").lower()
    eligible_text = _cell(mapped, "characterization_eligible")
    eligible = _parse_bool(eligible_text)
    auto_stop = _parse_bool(_cell(mapped, "auto_stop_on"))
    expected_rate = _parse_float(_cell(mapped, "expected_rate_hz"))
    expected_duration = _parse_float(_cell(mapped, "expected_duration_sec"))
    vendor_acc = _parse_float(_cell(mapped, "vendor_timing_accuracy_ms"))
    repeat_raw = _cell(mapped, "repeat_index")
    repeat_index = None
    if repeat_raw:
        try:
            repeat_index = int(float(repeat_raw))
        except ValueError:
            issues.append(issue(
                LEVEL_ERROR, "manifest_repeat_index",
                f"repeat_index is not an integer (line {source_line})",
                run_id=run_id,
            ))

    if not run_id:
        issues.append(issue(LEVEL_ERROR, "manifest_run_id", f"run_id is required (line {source_line})"))
    if not package_text:
        issues.append(issue(
            LEVEL_ERROR, "manifest_package_path",
            f"package_path is required (line {source_line})",
            run_id=run_id,
        ))
    if actuation not in ACTUATION_SOURCES:
        issues.append(issue(
            LEVEL_ERROR, "manifest_actuation_source",
            "actuation_source must be physical_fixture, human, software, or unknown "
            f"(line {source_line})",
            run_id=run_id,
        ))
        actuation = actuation or ACTUATION_UNKNOWN
    if eligible is None:
        issues.append(issue(
            LEVEL_ERROR, "manifest_eligible",
            f"characterization_eligible must be yes or no (line {source_line})",
            run_id=run_id,
        ))
        eligible = False
    if _cell(mapped, "expected_rate_hz") and expected_rate is None:
        issues.append(issue(
            LEVEL_ERROR, "manifest_expected_rate",
            f"expected_rate_hz is not a finite number (line {source_line})",
            run_id=run_id,
        ))
    if _cell(mapped, "expected_duration_sec") and expected_duration is None:
        issues.append(issue(
            LEVEL_ERROR, "manifest_expected_duration",
            f"expected_duration_sec is not a finite number (line {source_line})",
            run_id=run_id,
        ))
    if expected_duration is not None and abs(expected_duration - round(expected_duration)) > 1e-9:
        issues.append(issue(
            LEVEL_ERROR, "manifest_duration_not_whole_second",
            f"expected_duration_sec must be a whole-second lab duration (line {source_line})",
            run_id=run_id,
        ))
    if _cell(mapped, "auto_stop_on") and auto_stop is None:
        issues.append(issue(
            LEVEL_ERROR, "manifest_auto_stop",
            f"auto_stop_on must be yes or no (line {source_line})",
            run_id=run_id,
        ))
    if _cell(mapped, "vendor_timing_accuracy_ms") and vendor_acc is None:
        issues.append(issue(
            LEVEL_ERROR, "manifest_vendor_accuracy",
            f"vendor_timing_accuracy_ms is not a finite number (line {source_line})",
            run_id=run_id,
        ))

    package_path = Path(package_text) if package_text else None
    if package_path is not None and not package_path.is_absolute():
        package_path = (manifest_dir / package_path).resolve()

    row = {
        "source_line": source_line,
        "run_id": run_id,
        "package_path": str(package_path) if package_path else "",
        "package_path_raw": package_text,
        "campaign_id": _cell(mapped, "campaign_id"),
        "purpose": _cell(mapped, "purpose"),
        "actuation_source": actuation,
        "characterization_eligible": bool(eligible),
        "exclusion_reason": _cell(mapped, "exclusion_reason"),
        "fixture_vendor": _cell(mapped, "fixture_vendor"),
        "fixture_model": _cell(mapped, "fixture_model"),
        "fixture_unit_id": _cell(mapped, "fixture_unit_id"),
        "fixture_firmware": _cell(mapped, "fixture_firmware"),
        "control_dut_id": _cell(mapped, "control_dut_id"),
        "host_label": _cell(mapped, "host_label"),
        "usb_port_label": _cell(mapped, "usb_port_label"),
        "expected_rate_hz": expected_rate,
        "expected_duration_sec": expected_duration,
        "repeat_index": repeat_index,
        "auto_stop_on": auto_stop,
        "notes": _cell(mapped, "notes"),
        "vendor_timing_accuracy_ms": vendor_acc,
        "vendor_spec_reference": _cell(mapped, "vendor_spec_reference"),
    }
    return row, issues
