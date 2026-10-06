"""Command-line entry for Mouse Click Stability Analyzer."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def package_file() -> Path:
    return Path(__file__).resolve()


def default_report_root() -> Path:
    # cli.py -> package -> src -> project folder / reports
    return package_file().parents[2] / "reports"


def folder_local_mismatch() -> str | None:
    """If run.bat set MCSA_ROOT, the imported package must live under that folder."""
    marker = os.environ.get("MCSA_ROOT", "").strip()
    if not marker:
        return None
    root = Path(marker).resolve()
    pkg = package_file()
    try:
        pkg.relative_to(root)
    except ValueError:
        return (
            f"Imported MCSA source is not from this folder.\n"
            f"        Expected under: {root}\n"
            f"        Imported from:  {pkg}"
        )
    return None


def ensure_writable_report_root(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ".mcsa_write_probe"
    try:
        probe.write_text("ok", encoding="utf-8")
    finally:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass


def print_source_diagnostic() -> None:
    pkg = package_file()
    print(f"MCSA_SOURCE={pkg}")
    print(f"MCSA_PACKAGE_ROOT={pkg.parent}")
    print(f"MCSA_PROJECT_ROOT={pkg.parents[2]}")
    print(f"MCSA_PYTHON={sys.version.split()[0]}")
    print(f"MCSA_EXECUTABLE={sys.executable}")
    print(f"MCSA_REPORT_ROOT={default_report_root()}")


def _print_openpyxl_warning() -> None:
    try:
        import openpyxl  # noqa: F401
    except Exception:
        print(
            "[WARN] openpyxl is not installed. HTML/JSON/CSV reports still work; "
            "XLSX export is unavailable. Re-run install.bat to restore Excel output.",
            file=sys.stderr,
        )


def _fail(message: str, *extra: str) -> int:
    print(f"[ERROR] {message}", file=sys.stderr)
    for line in extra:
        print(f"        {line}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mcsa",
        description="Mouse Click Stability Analyzer — capture, measure, and report mouse click behavior.",
    )
    parser.add_argument(
        "--mode",
        default="gui",
        choices=["gui", "self-test"],
        help="Launch GUI (default) or run synthetic cadence self-test",
    )
    parser.add_argument(
        "--ui",
        default="auto",
        choices=["auto", "qt", "tk"],
        help="GUI toolkit: auto/qt launch the Qt UI (required for normal use). "
        "--ui tk is an explicit legacy Tk entry point only.",
    )
    parser.add_argument("--report-root", default="", help="Directory for generated reports")
    parser.add_argument("--run-id", default="", help="Optional run id for self-test output")
    parser.add_argument("--target", default="", help="Device under test label (optional)")
    parser.add_argument("--operator", default="", help="Operator name (optional, not auto-filled)")
    parser.add_argument("--lang", default="en", help="UI language: en (English) or zh (Traditional Chinese); others fall back to en")
    parser.add_argument("--theme", default="light", choices=["light", "dark"], help="UI theme (Qt shell)")
    parser.add_argument(
        "--print-source",
        action="store_true",
        help="Print the imported package path and Python executable, then exit",
    )
    args = parser.parse_args(argv)

    mismatch = folder_local_mismatch()
    if mismatch:
        return _fail("Wrong or missing MCSA source folder.", mismatch, "Launch with this folder's run.bat after a full copy/unzip.")

    if args.print_source:
        print_source_diagnostic()
        return 0

    report_root = Path(args.report_root) if args.report_root else default_report_root()
    try:
        ensure_writable_report_root(report_root)
    except OSError as exc:
        return _fail(
            f"Report folder is not writable: {report_root}",
            f"{type(exc).__name__}: {exc}",
            "Move MCSA to a writable folder such as C:\\MCSA\\ or C:\\Tools\\MCSA\\ and retry.",
        )

    if args.mode == "self-test":
        from .app import run_cadence_gates, run_synthetic

        _print_openpyxl_warning()
        paths = run_synthetic(report_root, args.run_id or "synthetic_10hz_flatline")
        gates = run_cadence_gates(report_root / "cadence_gates")
        print(json.dumps({"type": "self_test_complete", **paths, "cadence_gates": gates}, ensure_ascii=False, default=str))
        return 0

    if args.ui == "tk":
        from .app import run_visible_ui

        return run_visible_ui(
            run_id=args.run_id or "",
            report_root=report_root,
            target=args.target,
            operator=args.operator,
            standalone_mode=True,
        )

    try:
        import PySide6  # noqa: F401
    except Exception as exc:
        return _fail(
            "Qt UI could not start because PySide6 is not available.",
            f"{type(exc).__name__}: {exc}",
            "From this folder run install.bat (creates a local .venv with Python 3.12).",
            "Do not use the legacy Tk UI for production; it is only available via --ui tk.",
        )

    _print_openpyxl_warning()

    try:
        from .qt_shell import run_qt_ui

        return int(
            run_qt_ui(
                run_id=args.run_id or "",
                report_root=report_root,
                target=args.target,
                operator=args.operator,
                lang=args.lang,
                theme=args.theme,
                standalone_mode=True,
            )
            or 0
        )
    except Exception as exc:
        return _fail(
            "Qt UI could not start.",
            f"{type(exc).__name__}: {exc}",
            "Run run_diagnose.bat from this folder for details.",
        )


if __name__ == "__main__":
    raise SystemExit(main())
