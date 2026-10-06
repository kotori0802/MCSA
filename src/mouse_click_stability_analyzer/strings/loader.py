"""Load engineer-editable copy JSON into runtime string tables."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

QT_RESOURCE_FILES: tuple[str, ...] = (
    "common.json",
    "setup.json",
    "capture.json",
    "results.json",
    "preferences.json",
)
REPORT_RESOURCE_FILE = "report.json"
TERMINOLOGY_RESOURCE_FILE = "terminology.json"
ALL_RESOURCE_FILES: tuple[str, ...] = QT_RESOURCE_FILES + (REPORT_RESOURCE_FILE, TERMINOLOGY_RESOURCE_FILE)

RESOURCE_LANG_TO_INTERNAL = {"en": "en", "zh-TW": "zh"}
INTERNAL_TO_RESOURCE_LANG = {"en": "en", "zh": "zh-TW"}
ALLOWED_ENTRY_FIELDS = frozenset({"en", "zh-TW", "placeholders", "note"})
PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
BAD_BRACE_RE = re.compile(r"\{[^{}]*\}")

_ENV_ROOT = "MCSA_STRINGS_DIR"
_ENV_STRICT = "MCSA_STRINGS_STRICT"


class DuplicateJsonKeyError(ValueError):
    def __init__(self, path: str, key: str) -> None:
        self.path = path
        self.key = key
        super().__init__(f"Duplicate JSON key {key!r} in {path}")


class StringResourceError(ValueError):
    pass


def strings_strict() -> bool:
    return os.environ.get(_ENV_STRICT, "").strip() == "1"


def _object_pairs_hook(path: str):
    def hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                raise DuplicateJsonKeyError(path, key)
            out[key] = value
        return out

    return hook


def _package_strings_root():
    from importlib.resources import files

    return files("mouse_click_stability_analyzer.resources").joinpath("strings")


def resolve_strings_root(override: str | Path | None = None):
    if override is not None:
        return Path(override)
    env = os.environ.get(_ENV_ROOT, "").strip()
    if env:
        return Path(env)
    return _package_strings_root()


def _read_text(root, name: str) -> str:
    target = root / name if isinstance(root, Path) else root.joinpath(name)
    if isinstance(target, Path):
        return target.read_text(encoding="utf-8-sig")
    return target.read_text(encoding="utf-8-sig")


def parse_resource_json(text: str, *, path: str) -> dict[str, Any]:
    try:
        payload = json.loads(text, object_pairs_hook=_object_pairs_hook(path))
    except DuplicateJsonKeyError:
        raise
    except json.JSONDecodeError as exc:
        raise StringResourceError(f"Malformed JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise StringResourceError(f"{path} must contain a JSON object")
    return payload


def load_resource_file(root, name: str) -> dict[str, Any]:
    return parse_resource_json(_read_text(root, name), path=str(name))


def is_metadata_key(key: str) -> bool:
    return key.startswith("_")


def named_placeholders(text: str) -> list[str]:
    return PLACEHOLDER_RE.findall(text or "")


def _format_template(text: str, kwargs: Mapping[str, Any], *, key: str, strict: bool) -> str:
    if not kwargs:
        return text
    try:
        return text.format(**kwargs)
    except Exception:
        if strict:
            raise StringResourceError(f"Broken runtime template for {key!r}") from None
        return text


def build_tables(root=None) -> tuple[dict[str, dict[str, str]], dict[str, str], dict[str, str]]:
    """Return (qt STRINGS, report English table, key->file map)."""
    resolved = resolve_strings_root(root)
    qt: dict[str, dict[str, str]] = {"en": {}, "zh": {}}
    report: dict[str, str] = {}
    owners: dict[str, str] = {}

    def take(name: str, payload: dict[str, Any], *, qt_required: bool, report_file: bool) -> None:
        for key, raw in payload.items():
            if is_metadata_key(key):
                continue
            if key in owners:
                raise StringResourceError(f"Duplicate key {key!r} in {name} and {owners[key]}")
            owners[key] = name
            if not isinstance(raw, dict):
                raise StringResourceError(f"{name}:{key} must be an object")
            unknown = set(raw) - ALLOWED_ENTRY_FIELDS
            if unknown:
                raise StringResourceError(f"{name}:{key} has unknown field(s): {', '.join(sorted(unknown))}")
            en = raw.get("en")
            zh_tw = raw.get("zh-TW")
            if report_file:
                if not str(en or "").strip():
                    raise StringResourceError(f"{name}:{key} requires a nonblank English value")
                report[key] = str(en)
                continue
            if qt_required:
                if not str(en or "").strip() or not str(zh_tw or "").strip():
                    raise StringResourceError(f"{name}:{key} requires nonblank en and zh-TW")
                qt["en"][key] = str(en)
                qt["zh"][key] = str(zh_tw)

    for name in QT_RESOURCE_FILES:
        take(name, load_resource_file(resolved, name), qt_required=True, report_file=False)
    take(
        REPORT_RESOURCE_FILE,
        load_resource_file(resolved, REPORT_RESOURCE_FILE),
        qt_required=False,
        report_file=True,
    )
    take(
        TERMINOLOGY_RESOURCE_FILE,
        load_resource_file(resolved, TERMINOLOGY_RESOURCE_FILE),
        qt_required=False,
        report_file=False,
    )
    return qt, report, owners


_QT_TABLES, _REPORT_TABLE, _KEY_OWNERS = build_tables()
STRINGS: dict[str, dict[str, str]] = _QT_TABLES
REPORT_STRINGS: dict[str, str] = _REPORT_TABLE
KEY_OWNERS: dict[str, str] = _KEY_OWNERS


def reload_string_tables(root: str | Path | None = None) -> None:
    """Rebuild in-memory tables in place so importers keep the same dict objects."""
    qt, report, owners = build_tables(root)
    STRINGS["en"].clear()
    STRINGS["en"].update(qt["en"])
    STRINGS["zh"].clear()
    STRINGS["zh"].update(qt["zh"])
    REPORT_STRINGS.clear()
    REPORT_STRINGS.update(report)
    KEY_OWNERS.clear()
    KEY_OWNERS.update(owners)


def lookup_qt(lang: str, key: str, **kwargs: Any) -> str:
    strict = strings_strict()
    table = STRINGS.get(lang) or STRINGS["en"]
    text = table.get(key) or STRINGS["en"].get(key)
    if text is None:
        if strict:
            raise StringResourceError(f"Missing string key {key!r}")
        return key
    return _format_template(text, kwargs, key=key, strict=strict)


def report_text(key: str, **kwargs: Any) -> str:
    strict = strings_strict()
    text = REPORT_STRINGS.get(key)
    if text is None:
        if strict:
            raise StringResourceError(f"Missing report string key {key!r}")
        return key
    return _format_template(text, kwargs, key=key, strict=strict)


def iter_resource_names() -> Iterable[str]:
    return ALL_RESOURCE_FILES
