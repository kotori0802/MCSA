"""Setup configuration combos must not change value on mouse wheel; the page scrolls instead."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mouse_click_stability_analyzer.qt_shell import app as qt_app


def _make_qapp():
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:  # pragma: no cover - environment without Qt
        return None
    return QApplication.instance() or QApplication([])


def _wheel_event(widget, delta_y: int):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent

    local = QPointF(widget.rect().center())
    return QWheelEvent(
        local,
        QPointF(widget.mapToGlobal(local.toPoint())),
        QPoint(0, 0),
        QPoint(0, delta_y),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )


def _wheel(widget, delta_y: int) -> bool:
    """Deliver a wheel event to ``widget`` only. Returns whether it was accepted."""
    from PySide6.QtWidgets import QApplication

    event = _wheel_event(widget, delta_y)
    QApplication.sendEvent(widget, event)
    QApplication.processEvents()
    return event.isAccepted()


def _wheel_with_propagation(widget, delta_y: int):
    """Mirror QApplication::notify for spontaneous wheel input: walk up parents until accepted.

    Synthetic ``sendEvent`` wheel events are not propagated by Qt 6, so tests replay the
    propagation explicitly. Returns the widget that accepted the event, or None.
    """
    from PySide6.QtWidgets import QApplication

    target = widget
    while target is not None:
        event = _wheel_event(target, delta_y)
        QApplication.sendEvent(target, event)
        if event.isAccepted():
            QApplication.processEvents()
            return target
        if target.isWindow():
            break
        target = target.parentWidget()
    QApplication.processEvents()
    return None


class SetupWheelSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._qapp = _make_qapp()
        if cls._qapp is None:
            raise unittest.SkipTest("PySide6 QApplication unavailable")
        cls._tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self.win = qt_app.MainWindow(report_root=Path(self._tmp.name))
        self.win._listen_start_timer.stop()
        self.win.ui_timer.stop()
        self.win.ensure_raw_input = lambda: None
        self.win.radio_fixture.setChecked(True)
        self.win.interval_cmp_on.setChecked(True)
        self.win.auto_stop_on.setChecked(True)

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()

    def _setup_combos(self):
        return {
            "button": self.win.button_combo,
            "reference_rate": self.win.hz_combo,
            "range_unit": self.win.interval_cmp_unit,
            "duration": self.win.auto_stop_sec_combo,
        }

    def test_every_setup_combo_is_wheel_safe(self):
        for name, combo in self._setup_combos().items():
            with self.subTest(control=name):
                self.assertIsInstance(combo, qt_app.WheelSafeComboBox)

    def test_plain_combo_would_change_on_wheel(self):
        from PySide6.QtWidgets import QComboBox

        plain = QComboBox()
        plain.addItems(["a", "b", "c"])
        plain.setCurrentIndex(1)
        _wheel(plain, -120)
        self.assertNotEqual(plain.currentIndex(), 1)

    def test_wheel_does_not_change_values(self):
        self.win.hz_combo.setCurrentText("3")
        self.win.interval_cmp_unit.setCurrentIndex(1)
        self.win.auto_stop_sec_combo.setCurrentText("00:00:30")
        self.win.button_combo.setCurrentIndex(0)
        before = {name: (c.currentIndex(), c.currentText()) for name, c in self._setup_combos().items()}
        for name, combo in self._setup_combos().items():
            targets = [combo] + ([combo.lineEdit()] if combo.isEditable() else [])
            for target in targets:
                for delta in (120, -120, 120 * 3, -120 * 3):
                    with self.subTest(control=name, target=type(target).__name__, delta=delta):
                        _wheel(target, delta)
                        self.assertEqual((combo.currentIndex(), combo.currentText()), before[name])
        self.assertEqual(self.win.settings()["fixture_reference_hz"], 3.0)

    def test_wheel_over_focused_combo_does_not_change_value(self):
        self.win.show()
        self._qapp.processEvents()
        for name, combo in self._setup_combos().items():
            with self.subTest(control=name):
                combo.setFocus()
                self._qapp.processEvents()
                before = (combo.currentIndex(), combo.currentText())
                _wheel(combo, -120)
                _wheel(combo, 120)
                _wheel(combo, -240)
                self.assertEqual((combo.currentIndex(), combo.currentText()), before)

    def test_combo_leaves_wheel_unaccepted_for_parent(self):
        for name, combo in self._setup_combos().items():
            targets = [combo] + ([combo.lineEdit()] if combo.isEditable() else [])
            for target in targets:
                with self.subTest(control=name, target=type(target).__name__):
                    self.assertFalse(_wheel(target, -120))

    def test_wheel_over_combo_scrolls_setup_page(self):
        self.win.resize(900, 420)
        self.win.show()
        self.win._show_workflow_page("setup")
        self._qapp.processEvents()
        bar = self.win.setup_scroll.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0, "Setup page must overflow for this check")
        for name, combo in self._setup_combos().items():
            targets = [combo] + ([combo.lineEdit()] if combo.isEditable() else [])
            for target in targets:
                with self.subTest(control=name, target=type(target).__name__):
                    combo.setFocus()
                    bar.setValue(0)
                    before_value = (combo.currentIndex(), combo.currentText())
                    accepted_by = _wheel_with_propagation(target, -120)
                    self.assertIsNotNone(accepted_by)
                    self.assertNotIsInstance(accepted_by, qt_app.WheelSafeComboBox)
                    self.assertGreater(bar.value(), 0)
                    self.assertEqual((combo.currentIndex(), combo.currentText()), before_value)

    def test_keyboard_selection_still_works(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        self.win.show()
        self._qapp.processEvents()
        unit = self.win.interval_cmp_unit
        unit.setCurrentIndex(0)
        unit.setFocus()
        QTest.keyClick(unit, Qt.Key.Key_Down)
        self.assertEqual(unit.currentIndex(), 1)
        hz = self.win.hz_combo
        hz.setCurrentIndex(0)
        hz.setFocus()
        QTest.keyClick(hz.lineEdit(), Qt.Key.Key_Down)
        self.assertEqual(hz.currentIndex(), 1)

    def test_popup_click_selection_still_works(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        self.win.show()
        self._qapp.processEvents()
        combo = self.win.interval_cmp_unit
        combo.setCurrentIndex(0)
        combo.showPopup()
        self._qapp.processEvents()
        view = combo.view()
        rect = view.visualRect(combo.model().index(1, 0))
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, rect.center())
        self._qapp.processEvents()
        self.assertEqual(combo.currentIndex(), 1)

    def test_typed_reference_rate_still_works(self):
        from PySide6.QtTest import QTest

        hz = self.win.hz_combo
        hz.lineEdit().clear()
        QTest.keyClicks(hz.lineEdit(), "3")
        self.assertEqual(hz.currentText(), "3")
        self.assertEqual(self.win.settings()["fixture_reference_hz"], 3.0)


if __name__ == "__main__":
    unittest.main()
