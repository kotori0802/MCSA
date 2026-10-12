"""Pre-build checks for MCSA 1.0.0: pinned toolchain and report safety.

Usage: python packaging/check_build_env.py <repository root>
Exit code 0 when the environment matches exactly and the previous release folder
holds no report packages; 1 otherwise. build_exe.bat runs this before it deletes
the previous dist folder.
"""
from __future__ import annotations

import importlib.metadata
import importlib.util
import sys
from pathlib import Path
from typing import Callable

REQUIRED_PYTHON = (3, 12)
REQUIRED_DISTRIBUTIONS = {
    "pyinstaller": "6.13.0",
    "PySide6": "6.11.0",
    "openpyxl": "3.1.5",
}
MCSA_DISTRIBUTION = "mouse-click-stability-analyzer"
MCSA_PACKAGE = "mouse_click_stability_analyzer"
MCSA_VERSION = "1.0.0"
DIST_FOLDER_NAME = "MCSA-1.0.0-win64"
REPORT_PACKAGE_PATTERN = "mcsa_*"

PROVISION_COMMANDS = (
    "py -3.12 -m venv .venv-build",
    r".venv-build\Scripts\python -m pip install -U pip",
    r".venv-build\Scripts\python -m pip install -r requirements-build.txt",
    r".venv-build\Scripts\python -m pip install -e .",
)


def distribution_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def package_origin(name: str) -> Path | None:
    spec = importlib.util.find_spec(name)
    if spec is None or not spec.origin:
        return None
    return Path(spec.origin).resolve()


def check_environment(
    root: Path,
    *,
    version_info: tuple[int, ...] = tuple(sys.version_info[:3]),
    is_64bit: bool = sys.maxsize > 2**32,
    get_version: Callable[[str], str | None] = distribution_version,
    get_origin: Callable[[str], Path | None] = package_origin,
) -> list[str]:
    errors: list[str] = []
    if tuple(version_info[:2]) != REQUIRED_PYTHON or not is_64bit:
        found = ".".join(str(part) for part in version_info)
        errors.append(f"Python 3.12 64-bit required; found {found} {'64' if is_64bit else '32'}-bit")

    for name, required in REQUIRED_DISTRIBUTIONS.items():
        found = get_version(name)
        if found != required:
            errors.append(f"{name}=={required} required; found {found or 'not installed'}")

    expected = (root / "src" / MCSA_PACKAGE / "__init__.py").resolve()
    origin = get_origin(MCSA_PACKAGE)
    if origin is None:
        errors.append(f"{MCSA_PACKAGE} is not importable; install this repository with pip install -e .")
    elif origin != expected:
        errors.append(f"{MCSA_PACKAGE} resolves to {origin}; expected this repository: {expected}")

    found = get_version(MCSA_DISTRIBUTION)
    if found != MCSA_VERSION:
        errors.append(f"{MCSA_DISTRIBUTION}=={MCSA_VERSION} required; found {found or 'not installed'}")
    return errors


def existing_report_packages(root: Path) -> list[Path]:
    """Report packages inside the previous portable release that a rebuild would delete."""
    reports = root / "dist" / DIST_FOLDER_NAME / "reports"
    if not reports.is_dir():
        return []
    return sorted(reports.glob(REPORT_PACKAGE_PATTERN))


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    root = Path(args[0] if args else Path(__file__).resolve().parents[1]).resolve()
    errors = check_environment(root)
    if errors:
        print("[ERROR] Build environment does not match the pinned MCSA 1.0.0 toolchain:")
        for error in errors:
            print(f"  - {error}")
        print("Provision or update .venv-build from the repository folder:")
        for command in PROVISION_COMMANDS:
            print(f"    {command}")
    packages = existing_report_packages(root)
    if packages:
        reports = root / "dist" / DIST_FOLDER_NAME / "reports"
        print(f"[ERROR] {len(packages)} report package(s) exist in the previous release folder:")
        for package in packages:
            print(f"  - {package.name}")
        print(f"A rebuild deletes {reports.parent}, including these reports.")
        print("Back up or move them out of the dist folder first, then run build_exe.bat again.")
        print("Nothing was deleted.")
    if errors or packages:
        return 1
    print(f"Python {'.'.join(str(p) for p in sys.version_info[:3])} 64-bit")
    for name, required in REQUIRED_DISTRIBUTIONS.items():
        print(f"{name} {required}")
    print(f"{MCSA_DISTRIBUTION} {MCSA_VERSION} from {root / 'src' / MCSA_PACKAGE}")
    print("BUILD ENVIRONMENT OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
