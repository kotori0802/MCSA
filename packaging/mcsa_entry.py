"""PyInstaller entry for MCSA.exe.

Helper mode is handled inside ``cli.main`` before Qt is imported, so this
file must not construct a GUI of its own.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mouse_click_stability_analyzer.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
