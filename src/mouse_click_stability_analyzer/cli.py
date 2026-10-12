"""Command-line entry for Mouse Click Stability Analyzer."""
from __future__ import annotations

import argparse
import codecs
import json
import os
import sys
from pathlib import Path

from .runtime import (
    HELPER_FLAG,
    application_dir,
    default_report_root,
    is_frozen,
    is_helper_mode,
    missing_runtime_resources,
    write_startup_log,
)


def package_file() -> Path:
    return Path(__file__).resolve()


def folder_local_mismatch() -> str | None:
    """If run.bat set MCSA_ROOT, the imported package must live under that folder."""
    if is_frozen():
        return None
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


_STREAM_ERRORS = (OSError, ValueError, AttributeError)


def _configure_stdio() -> None:
    """Best-effort UTF-8 for console-output modes only (not GUI, not helper)."""
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except _STREAM_ERRORS:
            continue


def _stream_encoding(stream) -> str:
    name = getattr(stream, "encoding", None) or "ascii"
    try:
        return codecs.lookup(name).name
    except LookupError:
        return "ascii"


def _write_and_flush(stream, data) -> None:
    stream.write(data)
    flush = getattr(stream, "flush", None)
    if callable(flush):
        flush()


def emit_diagnostic(text: str, *, stream=None) -> None:
    """Write diagnostic text; degrade unencodable characters instead of raising.

    A missing (``None``), closed, or write-less stream drops the line silently,
    because windowed builds have no console.
    """
    target = sys.stdout if stream is None else stream
    if target is None:
        return
    line = text if text.endswith("\n") else f"{text}\n"
    try:
        _write_and_flush(target, line)
        return
    except UnicodeEncodeError:
        pass
    except _STREAM_ERRORS:
        return
    encoding = _stream_encoding(target)
    safe = line.encode(encoding, errors="replace")
    buffer = getattr(target, "buffer", None)
    if buffer is not None:
        try:
            _write_and_flush(buffer, safe)
            return
        except _STREAM_ERRORS:
            pass
    try:
        _write_and_flush(target, safe.decode(encoding, errors="replace"))
    except (UnicodeError, *_STREAM_ERRORS):
        return


def print_source_diagnostic() -> None:
    pkg = package_file()
    emit_diagnostic(f"MCSA_SOURCE={pkg}")
    emit_diagnostic(f"MCSA_PACKAGE_ROOT={pkg.parent}")
    emit_diagnostic(f"MCSA_PROJECT_ROOT={application_dir()}")
    emit_diagnostic(f"MCSA_FROZEN={int(is_frozen())}")
    emit_diagnostic(f"MCSA_PYTHON={sys.version.split()[0]}")
    emit_diagnostic(f"MCSA_EXECUTABLE={sys.executable}")
    emit_diagnostic(f"MCSA_REPORT_ROOT={default_report_root()}")


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
    emit_diagnostic(f"[ERROR] {message}", stream=sys.stderr)
    for line in extra:
        emit_diagnostic(f"        {line}", stream=sys.stderr)
    return 1


def _run_raw_input_helper() -> int:
    from .adapters.raw_input_bridge import main as bridge_main

    try:
        return int(bridge_main() or 0)
    except Exception as exc:
        from .adapters.raw_input_bridge import emit_error

        emit_error(exc)
        return 1


def _show_gui_startup_error(message: str, *extra: str) -> int:
    lines = [message, *extra]
    log_path = write_startup_log("\n".join(lines))
    if log_path is not None:
        extra = (*extra, f"Details were also written to: {log_path}")
        lines = [message, *extra]
    if is_frozen():
        _native_error_dialog("Mouse Click Stability Analyzer", "\n".join(lines))
    return _fail(message, *extra)


def _native_error_dialog(title: str, text: str) -> None:
    """Win32 MessageBoxW: the windowed EXE has no console, and Qt may be the failure."""
    if sys.platform != "win32":
        return
    import ctypes

    mb_ok_iconerror_foreground = 0x0 | 0x10 | 0x10000
    try:
        ctypes.windll.user32.MessageBoxW(None, text, title, mb_ok_iconerror_foreground)
    except (OSError, AttributeError):
        return


def main(argv: list[str] | None = None) -> int:
    argv_list = list(sys.argv[1:] if argv is None else argv)
    if is_helper_mode(argv_list):
        return _run_raw_input_helper()

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
    parser.add_argument(
        HELPER_FLAG,
        action="store_true",
        dest="raw_input_helper",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv_list)

    mismatch = folder_local_mismatch()
    if mismatch:
        return _fail("Wrong or missing MCSA source folder.", mismatch, "Launch with this folder's run.bat after a full copy/unzip.")

    if args.print_source or args.mode == "self-test":
        _configure_stdio()

    if args.print_source:
        print_source_diagnostic()
        return 0

    if args.ui == "tk" and is_frozen():
        return _show_gui_startup_error(
            "Legacy Tk UI is not included in the packaged Windows release.",
            "Use the normal Qt UI: start MCSA.exe without --ui tk.",
        )

    report_root = Path(args.report_root) if args.report_root else default_report_root()
    try:
        ensure_writable_report_root(report_root)
    except OSError as exc:
        return _show_gui_startup_error(
            f"Report folder is not writable: {report_root}",
            f"{type(exc).__name__}: {exc}",
            "Extract MCSA to a writable folder such as C:\\MCSA\\ or C:\\Tools\\MCSA\\ and retry.",
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
        return _show_gui_startup_error(
            "Qt UI could not start because PySide6 is not available.",
            f"{type(exc).__name__}: {exc}",
            "From a source checkout run install.bat. The packaged EXE must include PySide6.",
        )

    _print_openpyxl_warning()

    missing = missing_runtime_resources()
    if missing:
        return _show_gui_startup_error(
            "Required MCSA resources are missing from this installation.",
            "Missing: " + ", ".join(missing),
            "Re-extract MCSA-1.0.0-win64.zip or reinstall from the project folder.",
        )

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
        return _show_gui_startup_error(
            "Qt UI could not start.",
            f"{type(exc).__name__}: {exc}",
            "See mcsa_startup.log next to MCSA.exe, or run_diagnose.bat from a source checkout.",
        )


if __name__ == "__main__":
    raise SystemExit(main())
