"""Test-only helper for historical/advanced Schedule Association.

Normal Setup no longer stamps W. Tests that still need association evidence
apply it to the frozen snapshot after lock, never through a hidden Setup default.
"""
from __future__ import annotations

from mouse_click_stability_analyzer.qt_shell.app import stamp_qt_fixture_timing_tolerance


def apply_explicit_association(win, tolerance_ms: float) -> None:
    snap = win.profile_locked_settings
    if snap is not None and not snap.get("manual_mode"):
        win.profile_locked_settings = stamp_qt_fixture_timing_tolerance(
            snap, manual=False, tolerance_ms=float(tolerance_ms),
        )
    locked = win.locked
    if locked is not None and not locked.get("manual_mode"):
        win.locked = stamp_qt_fixture_timing_tolerance(
            locked, manual=False, tolerance_ms=float(tolerance_ms),
        )
