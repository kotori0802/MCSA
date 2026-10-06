"""Stage 0: display copy must not control machine values or Qt mnemonic storage.

Stage 1 constraints (not implemented here):
- Future JSON resources must be read with encoding utf-8-sig if BOM tolerance is promised.
- The first mechanical resource export must keep current i18n key names (no file-prefix rename yet).
- Identical visible text across files is a warning by default; a hard error only after a concept
  is registered as canonical terminology and redefined outside terminology.json.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from PySide6.QtWidgets import QComboBox

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mouse_click_stability_analyzer.i18n import STRINGS
from mouse_click_stability_analyzer.qt_shell import app as qt_app
from mouse_click_stability_analyzer.qt_shell.app import (
    DEFAULT_FOCUS_BUTTON,
    FOCUS_BUTTON_TOKENS,
    focus_button_token,
    populate_focus_button_combo,
    qt_button_label,
    select_focus_button,
)


def _make_qapp():
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:  # pragma: no cover
        return None
    return QApplication.instance() or QApplication([])


class FocusButtonComboTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._qapp = _make_qapp()
        if cls._qapp is None:
            raise unittest.SkipTest("PySide6 QApplication unavailable")

    def test_item_data_survives_changed_display_text(self):
        combo = QComboBox()
        populate_focus_button_combo(combo)
        self.assertEqual(tuple(combo.itemData(i) for i in range(combo.count())), FOCUS_BUTTON_TOKENS)
        combo.setItemText(0, "Left Button")
        combo.setCurrentIndex(0)
        self.assertEqual(combo.currentText(), "Left Button")
        self.assertEqual(focus_button_token(combo), "Left")
        select_focus_button(combo, "X1")
        combo.setItemText(combo.currentIndex(), "Side")
        self.assertEqual(focus_button_token(combo), "X1")
        select_focus_button(combo, DEFAULT_FOCUS_BUTTON)
        self.assertEqual(focus_button_token(combo), "Left")


class FocusButtonWindowTests(unittest.TestCase):
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
        self.win._cursor_over_capture_exclusion_ui = lambda: False

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()

    def _relabel(self, token: str, display: str) -> None:
        idx = self.win.button_combo.findData(token)
        self.assertGreaterEqual(idx, 0)
        self.win.button_combo.setItemText(idx, display)

    def test_settings_reads_item_data_not_display_text(self):
        self._relabel("Left", "Left Button")
        self.win.button_combo.setCurrentIndex(self.win.button_combo.findData("Left"))
        self.assertEqual(self.win.button_combo.currentText(), "Left Button")
        settings = self.win.settings()
        self.assertEqual(settings["focus_button"], "Left")
        self.assertEqual(settings["button"], "Left")

    def test_language_switch_does_not_change_machine_value(self):
        select_focus_button(self.win.button_combo, "Right")
        self._relabel("Right", "右鍵")
        self.assertEqual(self.win.settings()["focus_button"], "Right")
        zh_index = self.win.lang_combo.findData("zh")
        self.assertGreaterEqual(zh_index, 0)
        self.win.lang_combo.setCurrentIndex(zh_index)
        self.assertEqual(self.win.lang, "zh")
        self.assertEqual(self.win.settings()["focus_button"], "Right")
        self.assertEqual(self.win.button_combo.currentData(), "Right")
        en_index = self.win.lang_combo.findData("en")
        self.win.lang_combo.setCurrentIndex(en_index)
        self.assertEqual(self.win.settings()["focus_button"], "Right")

    def test_restore_setup_by_canonical_value_ignores_display(self):
        self._relabel("X2", "Thumb")
        self._relabel("Left", "Left Button")
        select_focus_button(self.win.button_combo, "Left")
        self.win._apply_settings_to_setup_widgets({"focus_button": "X2", "manual_mode": True}, "DUT")
        self.assertEqual(focus_button_token(self.win.button_combo), "X2")
        self.assertEqual(self.win.settings()["focus_button"], "X2")
        self.assertEqual(self.win.button_combo.currentText(), "Thumb")

    def test_wrong_button_logic_uses_canonical_token(self):
        self.win.radio_manual.setChecked(True)
        self._relabel("Left", "Left Button")
        select_focus_button(self.win.button_combo, "Left")
        self.assertTrue(self.win.lock_profile())
        self.assertTrue(self.win.arm_capture())
        self.assertEqual(self.win._locked_button, "Left")
        self.assertEqual(self.win.profile_locked_settings["focus_button"], "Left")
        t0 = float(self.win._arm_boundary_perf) + 0.001
        self.win._cursor_in_test_area = lambda: True
        self.win._begin_session_from_first_click("Right", t0, t0 + 0.01, {})
        self.assertFalse(self.win.running)
        self.assertIn("Wrong button", self.win.alert_label.text())
        self.assertIn("Left", self.win.alert_label.text())
        self.assertNotIn("Left Button", self.win.alert_label.text())
        self.win._begin_session_from_first_click("Left", t0, t0 + 0.01, {})
        self.assertTrue(self.win.running)
        self.win.stop_run()
        if self.win._post_run_input_guard_active:
            self.win._release_post_run_input_guard()


class QtMnemonicHelperTests(unittest.TestCase):
    def test_source_keeps_plain_ampersand_helper_escapes_for_qt(self):
        source = STRINGS["en"]["edit_setup_new_run"]
        self.assertEqual(source, "Edit Setup & New Run")
        self.assertNotIn("&&", source)
        self.assertEqual(qt_button_label(source), "Edit Setup && New Run")
        self.assertEqual(STRINGS["en"]["edit_setup_new_run"], "Edit Setup & New Run")

    def test_helper_is_idempotent_for_copy_without_ampersand(self):
        self.assertEqual(qt_button_label("Start Capture"), "Start Capture")


class QtMnemonicWindowTests(unittest.TestCase):
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

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()

    def test_buttons_render_through_helper_from_plain_source(self):
        source = self.win._tr("edit_setup_new_run")
        self.assertEqual(source, "Edit Setup & New Run")
        rendered = qt_button_label(source)
        self.assertEqual(self.win.btn_edit_setup_new_run.text(), rendered)
        self.assertEqual(self.win.btn_capture_edit_setup.text(), rendered)
        self.assertEqual(self.win.btn_lock_profile.text(), qt_button_label(self.win._tr("lock_profile_continue")))
        self.assertEqual(
            self.win.reset_window_geometry_button.text(),
            qt_button_label(self.win._tr("reset_window_geometry")),
        )


if __name__ == "__main__":
    unittest.main()
