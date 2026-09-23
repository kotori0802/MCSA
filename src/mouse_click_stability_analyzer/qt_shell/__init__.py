"""PySide6 portfolio shell for Mouse Click Stability Analyzer."""
from __future__ import annotations

def run_qt_ui(**kwargs) -> int:
    from .app import run_qt_ui as _run
    return _run(**kwargs)
