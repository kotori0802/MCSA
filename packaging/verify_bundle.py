"""Check the one-directory release folder after PyInstaller."""
from __future__ import annotations

import sys
from pathlib import Path

REQUIRED_DOCS = ("LICENSE", "QUICK_START.txt", "THIRD_PARTY_NOTICES.txt")
REQUIRED_LICENSE_FILES = (
    "licenses/python_LICENSE.txt",
    "licenses/openpyxl_LICENCE.rst",
    "licenses/et_xmlfile_LICENCE.rst",
    "licenses/et_xmlfile_LICENCE.python",
    "licenses/pyinstaller_COPYING.txt",
    "licenses/pyside6_LicenseRef-Qt-Commercial.txt",
    "licenses/qt_LGPL-3.0-only.txt",
    "licenses/qt_GPL-3.0-only.txt",
    "licenses/qt_GPL-2.0-only.txt",
)
REQUIRED_STRINGS = (
    "terminology.json",
    "common.json",
    "setup.json",
    "capture.json",
    "results.json",
    "preferences.json",
    "report.json",
)
FORBIDDEN_NAME_PARTS = ("__pycache__", ".pytest_cache", "characterization_out")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: verify_bundle.py <release-folder>", file=sys.stderr)
        return 2
    root = Path(args[0]).resolve()
    errors: list[str] = []
    exe = root / "MCSA.exe"
    if not exe.is_file():
        errors.append(f"missing {exe}")
    qwindows = list(root.rglob("qwindows.dll"))
    if not qwindows:
        errors.append("missing platforms/qwindows.dll")
    for name in REQUIRED_STRINGS:
        matches = list(root.rglob(name))
        if not matches:
            errors.append(f"missing resource {name}")
    for name in ("chart_fit.svg", "check_white.svg"):
        if not list(root.rglob(name)):
            errors.append(f"missing asset {name}")
    for name in REQUIRED_DOCS:
        if not (root / name).is_file():
            errors.append(f"missing {name}")
    for name in REQUIRED_LICENSE_FILES:
        if not (root / name).is_file():
            errors.append(f"missing {name}")
    if (root / "tests").exists():
        errors.append("release folder must not contain tests/")
    if (root / ".git").exists():
        errors.append("release folder must not contain .git/")
    for path in root.rglob("*"):
        text = str(path)
        if any(part in text for part in FORBIDDEN_NAME_PARTS):
            errors.append(f"unexpected path {path.relative_to(root)}")
            break
    if errors:
        print("BUNDLE CHECK FAILED", file=sys.stderr)
        for item in errors:
            print(f"  {item}", file=sys.stderr)
        return 1
    print(f"BUNDLE CHECK OK: {root}")
    print(f"  exe={exe} ({exe.stat().st_size} bytes)")
    print(f"  qwindows={qwindows[0].relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
