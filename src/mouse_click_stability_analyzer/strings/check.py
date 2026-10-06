"""Validate engineer-editable copy resources."""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from .loader import (
    ALL_RESOURCE_FILES,
    ALLOWED_ENTRY_FIELDS,
    BAD_BRACE_RE,
    DuplicateJsonKeyError,
    PLACEHOLDER_RE,
    REPORT_RESOURCE_FILE,
    StringResourceError,
    is_metadata_key,
    load_resource_file,
    named_placeholders,
    resolve_strings_root,
)

_SRC_ROOT = Path(__file__).resolve().parents[1]
_KNOWN_LANGS = {"en", "zh-TW"}


class Issue:
    def __init__(self, level: str, message: str) -> None:
        self.level = level
        self.message = message

    def __str__(self) -> str:
        return f"{self.level.upper()}: {self.message}"


def _scan_python_keys(src_root: Path, known: set[str]) -> set[str]:
    keys: set[str] = set()
    blob = []
    for path in src_root.rglob("*.py"):
        if "resources" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        blob.append(text)
        keys.update(m for m in re.findall(r"""['"]([A-Za-z][A-Za-z0-9_]*)['"]""", text) if m in known)
    joined = "\n".join(blob)
    if "window_mode_" in joined:
        keys.update(k for k in known if k.startswith("window_mode_"))
    if "run_status_" in joined:
        keys.update(k for k in known if k.startswith("run_status_"))
    return keys


def validate_entry(file_name: str, key: str, raw: Any, *, report: bool) -> list[Issue]:
    issues: list[Issue] = []
    if is_metadata_key(key):
        if not isinstance(raw, dict):
            issues.append(Issue("error", f"{file_name}:{key} metadata must be an object"))
        return issues
    if not isinstance(raw, dict):
        issues.append(Issue("error", f"{file_name}:{key} must be an object"))
        return issues
    unknown = set(raw) - ALLOWED_ENTRY_FIELDS
    if unknown:
        issues.append(Issue("error", f"{file_name}:{key} unknown field(s): {', '.join(sorted(unknown))}"))
    for field in raw:
        if field not in ALLOWED_ENTRY_FIELDS and field not in _KNOWN_LANGS:
            if "zh" in field.lower() and field != "zh-TW":
                issues.append(Issue("error", f"{file_name}:{key} language typo {field!r}; use zh-TW"))
    en = raw.get("en")
    zh = raw.get("zh-TW")
    if report:
        if not str(en or "").strip():
            issues.append(Issue("error", f"{file_name}:{key} missing required English value"))
    else:
        if not str(en or "").strip():
            issues.append(Issue("error", f"{file_name}:{key} missing required English value"))
        if not str(zh or "").strip():
            issues.append(Issue("error", f"{file_name}:{key} missing required zh-TW value"))
    for lang, text in (("en", en), ("zh-TW", zh)):
        if isinstance(text, str) and text != text.strip():
            issues.append(Issue("warning", f"{file_name}:{key} {lang} has leading/trailing whitespace"))
        if isinstance(text, str) and "&&" in text:
            issues.append(Issue("error", f"{file_name}:{key} stores accidental &&; use a single &"))
        if isinstance(text, str):
            for match in BAD_BRACE_RE.finditer(text):
                token = match.group(0)
                inner = token[1:-1]
                if not PLACEHOLDER_RE.fullmatch(token):
                    issues.append(Issue("error", f"{file_name}:{key} malformed placeholder {token}"))
    declared = raw.get("placeholders")
    found_en = named_placeholders(str(en or ""))
    found_zh = named_placeholders(str(zh or ""))
    if declared is not None:
        if not isinstance(declared, list) or any(not isinstance(p, str) for p in declared):
            issues.append(Issue("error", f"{file_name}:{key} placeholders must be a list of names"))
            return issues
        want = list(declared)
        if found_en != want and sorted(found_en) != sorted(want):
            if set(found_en) != set(want) or found_en != want:
                if set(found_en) != set(want):
                    issues.append(
                        Issue(
                            "error",
                            f"{file_name}:{key} English placeholders {found_en} do not match declaration {want}",
                        )
                    )
        if zh is not None and set(found_zh) != set(want):
            issues.append(
                Issue(
                    "error",
                    f"{file_name}:{key} zh-TW placeholders {found_zh} do not match declaration {want}",
                )
            )
        if zh is not None and set(found_en) != set(found_zh):
            issues.append(
                Issue(
                    "error",
                    f"{file_name}:{key} placeholder set differs between en {found_en} and zh-TW {found_zh}",
                )
            )
    else:
        if found_en or found_zh:
            issues.append(
                Issue(
                    "error",
                    f"{file_name}:{key} uses placeholders {found_en or found_zh} but has no placeholders declaration",
                )
            )
    return issues


def validate_resources(root=None, *, src_root: Path | None = None) -> list[Issue]:
    issues: list[Issue] = []
    resolved = resolve_strings_root(root)
    payloads: dict[str, dict[str, Any]] = {}
    owners: dict[str, str] = {}
    for name in ALL_RESOURCE_FILES:
        try:
            payload = load_resource_file(resolved, name)
        except DuplicateJsonKeyError as exc:
            issues.append(Issue("error", f"{exc.path}: duplicate key {exc.key!r}"))
            continue
        except FileNotFoundError:
            issues.append(Issue("error", f"Missing resource file {name}"))
            continue
        except (StringResourceError, OSError) as exc:
            issues.append(Issue("error", str(exc)))
            continue
        payloads[name] = payload
        report = name == REPORT_RESOURCE_FILE
        for key, raw in payload.items():
            if not is_metadata_key(key) and key in owners:
                issues.append(Issue("error", f"Duplicate key {key!r} in {name} and {owners[key]}"))
            elif not is_metadata_key(key):
                owners[key] = name
            issues.extend(validate_entry(name, key, raw, report=report))

    values: dict[str, list[str]] = {}
    for name, payload in payloads.items():
        for key, raw in payload.items():
            if is_metadata_key(key) or not isinstance(raw, dict):
                continue
            en = str(raw.get("en") or "")
            if en:
                values.setdefault(en, []).append(f"{name}:{key}")
    for text, locs in values.items():
        if len(locs) > 1:
            issues.append(
                Issue(
                    "warning",
                    f"Identical English text in {', '.join(locs)} (not an error until Stage 2 terminology.json)",
                )
            )

    scan_root = src_root or _SRC_ROOT
    referenced = _scan_python_keys(scan_root, set(owners))
    active = {k for k in owners}
    for key in sorted(active - referenced):
        issues.append(Issue("warning", f"Unreferenced key {key!r} in {owners[key]}"))
    return issues


def format_issues(issues: list[Issue]) -> str:
    return "\n".join(str(item) for item in issues)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mouse_click_stability_analyzer.strings")
    parser.add_argument("command", nargs="?", default="check", choices=["check"])
    parser.add_argument("--root", default=None, help="Override strings directory (tests only)")
    args = parser.parse_args(argv)
    issues = validate_resources(args.root)
    text = format_issues(issues)
    if text:
        print(text)
    errors = [i for i in issues if i.level == "error"]
    if errors:
        print(f"\n{len(errors)} error(s)")
        return 1
    warnings = [i for i in issues if i.level == "warning"]
    print(f"OK ({len(warnings)} warning(s))" if warnings else "OK")
    return 0
