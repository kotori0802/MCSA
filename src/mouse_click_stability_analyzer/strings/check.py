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
    KEY_ALIASES,
    MALFORMED_TERM_RE,
    PLACEHOLDER_RE,
    REPORT_RESOURCE_FILE,
    StringResourceError,
    TERM_REF_RE,
    TERMINOLOGY_RESOURCE_FILE,
    expand_term_references,
    is_metadata_key,
    is_term_key,
    load_resource_file,
    named_placeholders,
    resolve_strings_root,
    term_ref_keys,
)

_SRC_ROOT = Path(__file__).resolve().parents[1]
_KNOWN_LANGS = {"en", "zh-TW"}
_HELP_REQUIRED_PREFIX = "term."


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


def _term_tables(payload: dict[str, Any]) -> dict[str, dict[str, str]]:
    tables: dict[str, dict[str, str]] = {"en": {}, "zh-TW": {}}
    for key, raw in payload.items():
        if is_metadata_key(key) or not isinstance(raw, dict):
            continue
        if str(raw.get("en") or "").strip():
            tables["en"][key] = str(raw["en"])
        if str(raw.get("zh-TW") or "").strip():
            tables["zh-TW"][key] = str(raw["zh-TW"])
    return tables


def validate_entry(
    file_name: str,
    key: str,
    raw: Any,
    *,
    report: bool,
    terminology: bool,
    terms: dict[str, dict[str, str]],
) -> list[Issue]:
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
    if terminology and not is_term_key(key):
        issues.append(Issue("error", f"{file_name}:{key} must use a term.* key"))
    if is_term_key(key) and not terminology:
        issues.append(Issue("error", f"term.* key {key!r} must live only in {TERMINOLOGY_RESOURCE_FILE}"))
    en = raw.get("en")
    zh = raw.get("zh-TW")
    if terminology:
        if not str(en or "").strip():
            issues.append(Issue("error", f"{file_name}:{key} missing required English value"))
        if not str(zh or "").strip():
            issues.append(Issue("error", f"{file_name}:{key} missing required zh-TW value"))
        if not str(raw.get("note") or "").strip():
            issues.append(Issue("error", f"{file_name}:{key} requires a note"))
        if key.startswith(_HELP_REQUIRED_PREFIX) and not str(raw.get("help") or "").strip():
            issues.append(Issue("error", f"{file_name}:{key} requires help"))
        for lang, text in (("en", en), ("zh-TW", zh)):
            if isinstance(text, str) and (TERM_REF_RE.search(text) or MALFORMED_TERM_RE.search(text)):
                issues.append(Issue("error", f"{file_name}:{key} may not reference other terms"))
    elif report:
        if not str(en or "").strip():
            issues.append(Issue("error", f"{file_name}:{key} missing required English value"))
    else:
        if not str(en or "").strip():
            issues.append(Issue("error", f"{file_name}:{key} missing required English value"))
        if not str(zh or "").strip():
            issues.append(Issue("error", f"{file_name}:{key} missing required zh-TW value"))
    lang_terms = {"en": terms.get("en") or {}, "zh-TW": terms.get("zh-TW") or {}}
    expanded: dict[str, str] = {}
    for lang, text in (("en", en), ("zh-TW", zh)):
        if not isinstance(text, str):
            continue
        if text != text.strip():
            issues.append(Issue("warning", f"{file_name}:{key} {lang} has leading/trailing whitespace"))
        if "&&" in text:
            issues.append(Issue("error", f"{file_name}:{key} stores accidental &&; use a single &"))
        for match in BAD_BRACE_RE.finditer(text):
            token = match.group(0)
            if TERM_REF_RE.fullmatch(token):
                continue
            if MALFORMED_TERM_RE.fullmatch(token):
                issues.append(Issue("error", f"{file_name}:{key} malformed term reference {token}"))
                continue
            if not PLACEHOLDER_RE.fullmatch(token):
                issues.append(Issue("error", f"{file_name}:{key} malformed placeholder {token}"))
        if not terminology:
            try:
                expanded[lang] = expand_term_references(
                    text, lang_terms[lang] if lang == "en" else lang_terms["zh-TW"], owner=f"{file_name}:{key}"
                )
            except StringResourceError as exc:
                issues.append(Issue("error", str(exc)))
                expanded[lang] = text
        else:
            expanded[lang] = text
        if not terminology and lang in expanded:
            for tkey in term_ref_keys(text):
                table = lang_terms["en"] if lang == "en" else lang_terms["zh-TW"]
                if tkey not in table:
                    issues.append(Issue("error", f"{file_name}:{key} missing term {tkey!r}"))
    declared = raw.get("placeholders")
    found_en = named_placeholders(expanded.get("en") or "")
    found_zh = named_placeholders(expanded.get("zh-TW") or "")
    if declared is not None:
        if not isinstance(declared, list) or any(not isinstance(p, str) for p in declared):
            issues.append(Issue("error", f"{file_name}:{key} placeholders must be a list of names"))
            return issues
        want = list(declared)
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


def _canonical_redefinition_errors(
    payloads: dict[str, dict[str, Any]],
    terms: dict[str, dict[str, str]],
) -> list[Issue]:
    issues: list[Issue] = []
    exact_en = {text: key for key, text in terms.get("en", {}).items()}
    exact_zh = {text: key for key, text in terms.get("zh-TW", {}).items()}
    for name, payload in payloads.items():
        if name == TERMINOLOGY_RESOURCE_FILE:
            continue
        for key, raw in payload.items():
            if is_metadata_key(key) or not isinstance(raw, dict):
                continue
            for lang, catalog in (("en", exact_en), ("zh-TW", exact_zh)):
                text = raw.get(lang)
                if not isinstance(text, str):
                    continue
                stripped = text.strip()
                term_key = catalog.get(stripped)
                if not term_key:
                    continue
                if stripped == f"{{@{term_key}}}":
                    continue
                issues.append(
                    Issue(
                        "error",
                        f"{name}:{key} redefines canonical {term_key} in {lang}; use {{@{term_key}}}",
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

    terms = _term_tables(payloads.get(TERMINOLOGY_RESOURCE_FILE) or {})
    for name, payload in payloads.items():
        report = name == REPORT_RESOURCE_FILE
        terminology = name == TERMINOLOGY_RESOURCE_FILE
        for key, raw in payload.items():
            if not is_metadata_key(key) and key in owners:
                issues.append(Issue("error", f"Duplicate key {key!r} in {name} and {owners[key]}"))
            elif not is_metadata_key(key):
                owners[key] = name
            issues.extend(
                validate_entry(
                    name,
                    key,
                    raw,
                    report=report,
                    terminology=terminology,
                    terms=terms,
                )
            )
    issues.extend(_canonical_redefinition_errors(payloads, terms))

    for alias, target in KEY_ALIASES.items():
        if alias in owners and owners[alias] != TERMINOLOGY_RESOURCE_FILE:
            issues.append(Issue("error", f"Alias {alias!r} collides with active key in {owners[alias]}"))
        if target not in owners:
            issues.append(Issue("error", f"Alias {alias!r} target {target!r} is missing"))

    values: dict[str, list[str]] = {}
    for name, payload in payloads.items():
        for key, raw in payload.items():
            if is_metadata_key(key) or not isinstance(raw, dict) or is_term_key(key):
                continue
            en = str(raw.get("en") or "")
            if TERM_REF_RE.search(en):
                continue
            if en:
                values.setdefault(en, []).append(f"{name}:{key}")
    for text, locs in values.items():
        if len(locs) > 1:
            issues.append(
                Issue(
                    "warning",
                    f"Identical English text in {', '.join(locs)} (not an error unless a registered canonical term is redefined)",
                )
            )

    referenced_terms: set[str] = set()
    for name, payload in payloads.items():
        if name == TERMINOLOGY_RESOURCE_FILE:
            continue
        for raw in payload.values():
            if not isinstance(raw, dict):
                continue
            for field in ("en", "zh-TW"):
                referenced_terms.update(term_ref_keys(str(raw.get(field) or "")))

    scan_root = src_root or _SRC_ROOT
    known = set(owners) | set(KEY_ALIASES) | set(terms.get("en") or {})
    referenced = _scan_python_keys(scan_root, known)
    referenced.update(KEY_ALIASES)
    referenced.update(KEY_ALIASES.values())
    referenced.update(referenced_terms)
    active = {k for k in owners if k not in KEY_ALIASES}
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
