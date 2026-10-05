"""Command-line entry for Mouse Click Stability Analyzer."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


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
        help="GUI toolkit: auto (Qt if installed, else Tk), qt, or tk",
    )
    parser.add_argument("--report-root", default="", help="Directory for generated reports")
    parser.add_argument("--run-id", default="", help="Optional run id for self-test output")
    parser.add_argument("--target", default="", help="Device under test label (optional)")
    parser.add_argument("--operator", default="", help="Operator name (optional, not auto-filled)")
    parser.add_argument("--lang", default="en", help="UI language: en (English) or zh (Traditional Chinese); others fall back to en")
    parser.add_argument("--theme", default="light", choices=["light", "dark"], help="UI theme (Qt shell)")
    args = parser.parse_args(argv)

    report_root = Path(args.report_root) if args.report_root else Path(__file__).resolve().parents[2] / "reports"

    if args.mode == "self-test":
        from .app import run_cadence_gates, run_synthetic

        paths = run_synthetic(report_root, args.run_id or "synthetic_10hz_flatline")
        gates = run_cadence_gates(report_root / "cadence_gates")
        print(json.dumps({"type": "self_test_complete", **paths, "cadence_gates": gates}, ensure_ascii=False, default=str))
        return 0

    kwargs = dict(
        run_id=args.run_id or "",
        report_root=report_root,
        target=args.target,
        operator=args.operator,
        lang=args.lang,
        theme=args.theme,
        standalone_mode=True,
    )

    use_qt = args.ui == "qt"
    if args.ui == "auto":
        try:
            import PySide6  # noqa: F401
            use_qt = True
        except Exception:
            use_qt = False

    if use_qt:
        try:
            from .qt_shell import run_qt_ui
            return int(run_qt_ui(**kwargs) or 0)
        except Exception as exc:
            if args.ui == "qt":
                print(f"[ERROR] Qt UI failed: {exc}", file=sys.stderr)
                print("Install with: python -m pip install PySide6", file=sys.stderr)
                return 1
            print(f"[WARN] Qt UI unavailable ({exc}); falling back to Tk.", file=sys.stderr)

    from .app import run_visible_ui
    return run_visible_ui(**kwargs)


if __name__ == "__main__":
    raise SystemExit(main())
