"""Step 3c: Preferences > Window & Layout (MCSA application window only)."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QPoint, QRect, QSettings, QSize

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mouse_click_stability_analyzer.i18n import STRINGS, SUPPORTED_LANGS
from mouse_click_stability_analyzer.qt_shell import app as qt_app
from mouse_click_stability_analyzer.qt_shell.app import (
    WINDOW_MODES,
    auto_window_size,
    centered_top_left,
    fit_requested_window_size,
    geometry_is_reachable,
    window_size_for_mode,
)

_WINDOW_KEYS = (
    "pref_window_section",
    "startup_window",
    "window_mode_auto",
    "window_mode_compact",
    "window_mode_standard",
    "window_mode_large",
    "window_mode_laptop",
    "window_mode_large_plus",
    "window_mode_full_hd",
    "window_mode_custom",
    "window_mode_maximized",
    "window_fit_note",
    "custom_window_size",
    "custom_width",
    "custom_height",
    "apply_custom_size",
    "custom_size_pending",
    "remember_window_size",
    "remember_window_size_note",
    "reset_window_geometry",
)
_PRESETS = {
    "compact": QSize(1280, 720),
    "laptop": QSize(1366, 768),
    "standard": QSize(1440, 810),
    "large": QSize(1600, 900),
    "large_plus": QSize(1728, 972),
    "full_hd": QSize(1920, 1080),
}
# 1920 x 1080 at 100% with a bottom taskbar, placed right of a primary monitor.
_REFERENCE_WORK_AREA = QRect(1920, 0, 1920, 1040)
_MIN = QSize(1024, 640)


def _make_qapp():
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:  # pragma: no cover
        return None
    return QApplication.instance() or QApplication([])


def _under(widget, ancestor) -> bool:
    node = widget
    while node is not None:
        if node is ancestor:
            return True
        node = node.parentWidget()
    return False


class WindowSizingPolicyTests(unittest.TestCase):
    def test_auto_reference_work_area_lands_near_1600_by_900(self):
        size = auto_window_size(_REFERENCE_WORK_AREA.size(), _MIN)
        self.assertEqual(size, QSize(1600, 900))

    def test_auto_fits_inside_available_area(self):
        for avail in (QSize(1920, 1040), QSize(1366, 728), QSize(1280, 680), QSize(2560, 1400)):
            with self.subTest(avail=avail):
                size = auto_window_size(avail, _MIN)
                self.assertLessEqual(size.width(), avail.width())
                self.assertLessEqual(size.height(), avail.height())

    def test_auto_never_exceeds_comfortable_maximum(self):
        size = auto_window_size(QSize(3840, 2100), _MIN)
        self.assertLessEqual(size.width(), 1600)
        self.assertLessEqual(size.height(), 900)

    def test_auto_on_smaller_work_area_is_smaller(self):
        big = auto_window_size(QSize(1920, 1040), _MIN)
        small = auto_window_size(QSize(1366, 728), _MIN)
        self.assertLess(small.width(), big.width())
        self.assertLess(small.height(), big.height())
        self.assertGreaterEqual(small.width(), _MIN.width())
        self.assertGreaterEqual(small.height(), _MIN.height())

    def test_presets_map_to_documented_sizes_when_permitted(self):
        avail = QSize(1920, 1040)
        self.assertEqual(window_size_for_mode("compact", avail, _MIN), QSize(1280, 720))
        self.assertEqual(window_size_for_mode("standard", avail, _MIN), QSize(1440, 810))
        self.assertEqual(window_size_for_mode("large", avail, _MIN), QSize(1600, 900))

    def test_oversized_preset_is_clamped_to_work_area(self):
        avail = QSize(1366, 728)
        for mode in ("standard", "large"):
            with self.subTest(mode=mode):
                size = window_size_for_mode(mode, avail, _MIN)
                self.assertLessEqual(size.width(), avail.width())
                self.assertLessEqual(size.height(), avail.height())
        tiny = QSize(900, 560)
        size = window_size_for_mode("compact", tiny, _MIN)
        self.assertEqual(size, tiny)

    def test_every_preset_maps_exactly_when_work_area_permits(self):
        roomy = QSize(2560, 1400)
        for mode, size in _PRESETS.items():
            with self.subTest(mode=mode):
                self.assertEqual(window_size_for_mode(mode, roomy, _MIN), size)

    def test_new_presets_on_reference_work_area(self):
        avail = _REFERENCE_WORK_AREA.size()
        self.assertEqual(window_size_for_mode("laptop", avail, _MIN), QSize(1366, 768))
        self.assertEqual(window_size_for_mode("large_plus", avail, _MIN), QSize(1728, 972))
        full_hd = window_size_for_mode("full_hd", avail, _MIN)
        self.assertLessEqual(full_hd.width(), avail.width())
        self.assertLessEqual(full_hd.height(), avail.height())
        self.assertEqual(full_hd.height(), avail.height())
        self.assertAlmostEqual(full_hd.width() / full_hd.height(), 16 / 9, delta=0.01)

    def test_every_preset_stays_inside_available_area(self):
        for avail in (QSize(1920, 1001), QSize(1366, 728), QSize(1280, 680), QSize(1100, 650), QSize(900, 560)):
            for mode in WINDOW_MODES:
                with self.subTest(avail=avail, mode=mode):
                    size = window_size_for_mode(mode, avail, _MIN, QSize(3000, 1800))
                    self.assertLessEqual(size.width(), avail.width())
                    self.assertLessEqual(size.height(), avail.height())

    def test_oversized_request_keeps_aspect_before_clamping(self):
        fitted = fit_requested_window_size(1920, 1080, QSize(1904, 1001), _MIN)
        self.assertEqual(fitted.height(), 1001)
        self.assertAlmostEqual(fitted.width() / fitted.height(), 16 / 9, delta=0.01)
        self.assertEqual(fit_requested_window_size(1500, 820, QSize(1904, 1001), _MIN), QSize(1500, 820))

    def test_custom_size_policy(self):
        avail = _REFERENCE_WORK_AREA.size()
        self.assertEqual(window_size_for_mode("custom", avail, _MIN, QSize(1500, 820)), QSize(1500, 820))
        big = window_size_for_mode("custom", avail, _MIN, QSize(3000, 1800))
        self.assertLessEqual(big.width(), avail.width())
        self.assertLessEqual(big.height(), avail.height())
        self.assertEqual(window_size_for_mode("custom", avail, _MIN, None), auto_window_size(avail, _MIN))

    def test_centering_uses_work_area_origin_not_zero(self):
        top_left = centered_top_left(QSize(1600, 900), _REFERENCE_WORK_AREA)
        self.assertEqual(top_left, QPoint(1920 + 160, 70))
        oversized = centered_top_left(QSize(2400, 1400), _REFERENCE_WORK_AREA)
        self.assertEqual(oversized, _REFERENCE_WORK_AREA.topLeft())

    def test_reachability_rejects_disconnected_monitor_geometry(self):
        areas = [QRect(0, 0, 1920, 1040)]
        self.assertTrue(geometry_is_reachable(QRect(100, 100, 1280, 720), areas))
        self.assertFalse(geometry_is_reachable(QRect(4000, 100, 1280, 720), areas))
        self.assertFalse(geometry_is_reachable(QRect(1800, 100, 1280, 720), areas))
        self.assertFalse(geometry_is_reachable(QRect(100, -700, 1280, 720), areas))
        self.assertFalse(geometry_is_reachable(QRect(), areas))


class WindowPreferencesUiTests(unittest.TestCase):
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
        self._windows = []
        self.win = self._make_window()

    def tearDown(self):
        from PySide6.QtCore import QCoreApplication, QEvent

        for win in self._windows:
            win.close()
            win.deleteLater()
        self._qapp.processEvents()
        # processEvents() skips DeferredDelete; leaked windows make every later restyle slower.
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def _make_window(self, settings: QSettings | None = None):
        win = qt_app.MainWindow(report_root=Path(self._tmp.name), window_settings=settings)
        win._listen_start_timer.stop()
        win.ui_timer.stop()
        win.ensure_raw_input = lambda: None
        win._available_geometry = lambda: QRect(_REFERENCE_WORK_AREA)
        win._work_areas = lambda: [QRect(_REFERENCE_WORK_AREA)]
        self._windows.append(win)
        return win

    def _settings(self) -> QSettings:
        path = Path(tempfile.mkdtemp(dir=self._tmp.name)) / "mcsa.ini"
        return QSettings(str(path), QSettings.Format.IniFormat)

    def _settle(self):
        for _ in range(4):
            self._qapp.processEvents()

    def _select_mode(self, mode: str):
        self.win.startup_window_combo.setCurrentIndex(WINDOW_MODES.index(mode))
        self._settle()

    def _assert_centered_inside_work_area(self, win):
        frame = win.frameGeometry()
        self.assertTrue(_REFERENCE_WORK_AREA.contains(frame), frame)
        self.assertLessEqual(abs(frame.center().x() - _REFERENCE_WORK_AREA.center().x()), 2)
        self.assertLessEqual(abs(frame.center().y() - _REFERENCE_WORK_AREA.center().y()), 2)

    # 1
    def test_default_startup_mode_is_auto(self):
        self.assertEqual(self.win.window_mode, "auto")
        self.assertEqual(self.win.startup_window_combo.currentData(), "auto")
        self.assertEqual(self.win.startup_window_combo.currentText(), self.win._tr("window_mode_auto"))

    # 19
    def test_remember_last_window_size_is_off_by_default(self):
        self.assertFalse(self.win.remember_window_geometry)
        self.assertFalse(self.win.remember_window_size_checkbox.isChecked())

    def test_combo_items_are_stable_internal_modes(self):
        combo = self.win.startup_window_combo
        self.assertEqual([combo.itemData(i) for i in range(combo.count())], list(WINDOW_MODES))
        self.assertEqual(
            list(WINDOW_MODES),
            ["auto", "compact", "laptop", "standard", "large", "large_plus", "full_hd", "custom", "maximized"],
        )
        expected = {
            "compact": "1280 × 720 — Compact",
            "laptop": "1366 × 768 — Laptop",
            "standard": "1440 × 810 — Standard",
            "large": "1600 × 900 — Large",
            "large_plus": "1728 × 972 — Large+",
            "full_hd": "1920 × 1080 — Full HD",
            "custom": "Custom…",
            "maximized": "Maximized",
            "auto": "Auto (Recommended)",
        }
        for mode, text in expected.items():
            self.assertEqual(combo.itemText(WINDOW_MODES.index(mode)), text)
        texts = " ".join(combo.itemText(i) for i in range(combo.count()))
        self.assertNotIn("2560", texts)
        self.assertNotIn("3840", texts)

    # 2, 3
    def test_startup_auto_fits_and_centers_in_work_area(self):
        self.win.show_startup_window()
        self._settle()
        self.assertFalse(self.win.isMaximized())
        self.assertLessEqual(self.win.width(), 1600)
        self.assertLessEqual(self.win.height(), 900)
        self.assertGreater(self.win.width(), 1400)
        self._assert_centered_inside_work_area(self.win)

    # 5, 6, 7
    def test_selecting_presets_applies_immediately(self):
        self.win.show()
        for mode, (width, height) in (("compact", (1280, 720)), ("standard", (1440, 810)), ("large", (1600, 900))):
            with self.subTest(mode=mode):
                self._select_mode(mode)
                self.assertEqual(self.win.window_mode, mode)
                self.assertEqual(self.win.size(), QSize(width, height))
                self._assert_centered_inside_work_area(self.win)

    # 8
    def test_preset_larger_than_work_area_is_clamped_on_window(self):
        small = QRect(0, 0, 1366, 728)
        self.win._available_geometry = lambda: QRect(small)
        self.win.show()
        self._select_mode("large")
        self.assertTrue(small.contains(self.win.frameGeometry()), self.win.frameGeometry())

    # 9
    def test_maximized_uses_qt_maximize(self):
        self.win.show()
        with mock.patch.object(self.win, "showMaximized", wraps=self.win.showMaximized) as maximize, \
                mock.patch.object(self.win, "resize", wraps=self.win.resize) as resize:
            self._select_mode("maximized")
        maximize.assert_called_once_with()
        resize.assert_not_called()
        self.assertTrue(self.win.isMaximized())

    def test_leaving_maximized_restores_normal_preset(self):
        self.win.show()
        self._select_mode("maximized")
        self._select_mode("compact")
        self.assertFalse(self.win.isMaximized())
        self.assertEqual(self.win.size(), QSize(1280, 720))

    # 10
    def test_reset_applies_auto_and_recenters(self):
        self.win.show()
        self._select_mode("compact")
        self.win.move(_REFERENCE_WORK_AREA.x() + 5, 5)
        self._settle()
        self.win.reset_window_geometry_button.click()
        self._settle()
        self.assertEqual(self.win.size(), auto_window_size(_REFERENCE_WORK_AREA.size(), self.win.minimumSize()))
        self._assert_centered_inside_work_area(self.win)
        self.assertEqual(self.win.window_mode, "auto")
        self.assertEqual(self.win.startup_window_combo.currentData(), "auto")

    # A
    def test_reset_after_large_syncs_mode_combo_and_persistence(self):
        settings = self._settings()
        win = self._make_window(settings)
        win.show()
        win.startup_window_combo.setCurrentIndex(WINDOW_MODES.index("large"))
        self._settle()
        self.assertEqual(settings.value("window/startup_mode"), "large")
        with mock.patch.object(win, "apply_window_mode", wraps=win.apply_window_mode) as apply:
            win.reset_window_geometry_button.click()
            self._settle()
        apply.assert_called_once_with("auto")
        self.assertEqual(win.startup_window_combo.currentData(), "auto")
        self.assertEqual(win.startup_window_combo.currentText(), win._tr("window_mode_auto"))
        self.assertEqual(win.window_mode, "auto")
        self.assertEqual(settings.value("window/startup_mode"), "auto")
        self.assertEqual(win.size(), auto_window_size(_REFERENCE_WORK_AREA.size(), win.minimumSize()))
        relaunched = self._make_window(settings)
        self.assertEqual(relaunched.window_mode, "auto")
        self.assertEqual(relaunched.startup_window_combo.currentData(), "auto")

    # B
    def test_selecting_previous_preset_after_reset_reapplies_it(self):
        # Work area where Auto (90%) is visibly smaller than Large but Large still fits.
        work = QRect(0, 0, 1760, 1000)
        self.win._available_geometry = lambda: QRect(work)
        self.win.show()
        self._select_mode("large")
        self.assertEqual(self.win.size(), QSize(1600, 900))
        self.win.reset_window_geometry_button.click()
        self._settle()
        self.assertLess(self.win.width(), 1600)
        self.assertTrue(work.contains(self.win.frameGeometry()))
        self._select_mode("large")
        self.assertEqual(self.win.window_mode, "large")
        self.assertEqual(self.win.size(), QSize(1600, 900))
        self.assertTrue(work.contains(self.win.frameGeometry()))

    def test_reset_from_maximized_returns_to_normal_auto(self):
        self.win.show()
        self._select_mode("maximized")
        self.assertTrue(self.win.isMaximized())
        self.win.reset_window_geometry_button.click()
        self._settle()
        self.assertFalse(self.win.isMaximized())
        self.assertEqual(self.win.window_mode, "auto")
        self.assertEqual(self.win.startup_window_combo.currentData(), "auto")

    # C
    def test_reset_discards_remembered_geometry_only(self):
        settings = self._settings()
        settings.setValue("window/geometry", QRect(2000, 50, 1300, 760))
        settings.setValue("window/maximized", True)
        settings.setValue("window/remember_geometry", True)
        settings.setValue("window/startup_mode", "standard")
        win = self._make_window(settings)
        win.show()
        win.reset_window_geometry()
        self.assertFalse(settings.contains("window/geometry"))
        self.assertFalse(settings.contains("window/maximized"))
        self.assertEqual(settings.value("window/startup_mode"), "auto")
        self.assertTrue(win.remember_window_geometry)
        self.assertTrue(win.remember_window_size_checkbox.isChecked())

    # 11, 12
    def test_resizing_and_reset_preserve_setup_profile_and_run_state(self):
        win = self.win
        win.show()
        win.listening = True
        win._cursor_in_test_area = lambda: True
        win._cursor_over_capture_exclusion_ui = lambda: False
        win.device_edit.setText("DUT-42")
        win.radio_fixture.setChecked(True)
        win.hz_combo.setCurrentText("40")
        win.timing_tol_edit.setText("2")
        self.assertTrue(win.lock_profile())
        self.assertTrue(win.arm_capture())
        armed_state = (win.capture_armed, win.running, win.profile_locked_settings)
        self.assertTrue(win.capture_armed)
        for mode in ("compact", "large", "maximized", "auto"):
            self._select_mode(mode)
        win.reset_window_geometry()
        self._settle()
        self.assertEqual((win.capture_armed, win.running, win.profile_locked_settings), armed_state)

        t0 = float(win._arm_boundary_perf) + 0.001
        win._begin_session_from_first_click("Left", t0, t0 + 0.01, {})
        self.assertTrue(win.running)
        state = (win.running, win.capture_armed, win.completed, win.locked, win.profile_locked_settings, len(win.events))
        widgets = (win.page_setup, win.page_capture, win.page_preferences, win.setup_card_grid)
        top_levels = len(self._qapp.topLevelWidgets())
        for mode in ("standard", "maximized", "compact"):
            self._select_mode(mode)
        win.reset_window_geometry_button.click()
        self._settle()
        self.assertEqual(
            (win.running, win.capture_armed, win.completed, win.locked, win.profile_locked_settings, len(win.events)),
            state,
        )
        self.assertEqual(win.device_edit.text(), "DUT-42")
        self.assertEqual(win.timing_tol_edit.text(), "2")
        self.assertEqual((win.page_setup, win.page_capture, win.page_preferences, win.setup_card_grid), widgets)
        self.assertEqual(len(self._qapp.topLevelWidgets()), top_levels)

    # 13
    def test_theme_still_switches(self):
        self.win.theme_combo.setCurrentIndex(1)
        self.assertEqual(self.win.theme, "dark")
        self.win.theme_combo.setCurrentIndex(0)
        self.assertEqual(self.win.theme, "light")

    # 14
    def test_language_retranslates_window_controls(self):
        self.win.lang_combo.setCurrentIndex(SUPPORTED_LANGS.index("de"))
        self.assertEqual(self.win.lang, "de")
        de = STRINGS["de"]
        self.assertEqual(self.win.lbl_pref_window.text(), de["pref_window_section"].upper())
        self.assertEqual(self.win.startup_window_combo.currentText(), de["window_mode_auto"])
        self.assertEqual(self.win.remember_window_size_checkbox.text(), de["remember_window_size"])
        self.assertEqual(self.win.remember_window_size_note.text(), de["remember_window_size_note"])
        self.assertEqual(self.win.reset_window_geometry_button.text(), de["reset_window_geometry"])
        self.assertEqual(self.win.startup_window_combo.currentData(), "auto")

    # 15, 16
    def test_window_controls_owned_by_preferences_without_duplicates(self):
        from PySide6.QtWidgets import QComboBox

        for widget in (
            self.win.pref_window_card,
            self.win.startup_window_combo,
            self.win.remember_window_size_checkbox,
            self.win.reset_window_geometry_button,
            self.win.theme_combo,
            self.win.lang_combo,
        ):
            self.assertTrue(_under(widget, self.win.page_preferences), widget)
            self.assertFalse(_under(widget, self.win.page_setup), widget)
        combos = self.win.findChildren(QComboBox)
        theme_like = [c for c in combos if [c.itemData(i) for i in range(c.count())] == ["light", "dark"]]
        lang_like = [c for c in combos if [c.itemData(i) for i in range(c.count())] == list(SUPPORTED_LANGS)]
        self.assertEqual(theme_like, [self.win.theme_combo])
        self.assertEqual(lang_like, [self.win.lang_combo])

    def test_window_controls_are_capture_exclusion_chrome(self):
        widgets = self.win._capture_exclusion_widgets()
        for widget in (
            self.win.startup_window_combo,
            self.win.remember_window_size_checkbox,
            self.win.reset_window_geometry_button,
        ):
            self.assertIn(widget, widgets)

    # 17
    def test_setup_grid_reflows_from_resulting_viewport(self):
        self.win.show()
        self.win._show_workflow_page("setup")
        self._select_mode("large")
        self.assertEqual(self.win.setup_card_grid.columns(), 3)
        self._select_mode("compact")
        viewport = self.win.setup_scroll.viewport().width()
        self.assertEqual(self.win.setup_card_grid.columns(), qt_app.ResponsiveCardGrid.columns_for_width(viewport - 4))
        self.assertEqual(self.win.setup_card_grid.columns(), 2)
        self.win.setMinimumSize(1, 1)
        self.win._available_geometry = lambda: QRect(0, 0, 860, 700)
        self._select_mode("auto")
        self.assertEqual(self.win.setup_card_grid.columns(), 1)

    # 18
    def test_window_i18n_keys_exist_in_all_languages(self):
        for lang in SUPPORTED_LANGS:
            for key in _WINDOW_KEYS:
                with self.subTest(lang=lang, key=key):
                    value = STRINGS[lang].get(key)
                    self.assertTrue(value)
                    self.assertNotEqual(value, key)

    def test_preferences_persist_to_supplied_settings_only(self):
        settings = self._settings()
        win = self._make_window(settings)
        win.show()
        win.startup_window_combo.setCurrentIndex(WINDOW_MODES.index("standard"))
        win.remember_window_size_checkbox.setChecked(True)
        self.assertEqual(settings.value("window/startup_mode"), "standard")
        self.assertTrue(win._window_pref_bool("window/remember_geometry", False))
        again = self._make_window(settings)
        self.assertEqual(again.window_mode, "standard")
        self.assertTrue(again.remember_window_size_checkbox.isChecked())

    # 20
    def test_saved_geometry_restores_when_enabled(self):
        settings = self._settings()
        first = self._make_window(settings)
        first.remember_window_size_checkbox.setChecked(True)
        first.show()
        target = QRect(2100, 80, 1300, 760)
        first.setGeometry(target)
        self._settle()
        saved = first.geometry()
        first.close()
        self.assertEqual(settings.value("window/geometry"), saved)

        second = self._make_window(settings)
        second.show_startup_window()
        self._settle()
        self.assertEqual(second.geometry(), saved)
        self.assertFalse(second.isMaximized())

    def test_saved_geometry_ignored_when_remember_off(self):
        settings = self._settings()
        settings.setValue("window/geometry", QRect(2100, 80, 1300, 760))
        win = self._make_window(settings)
        win.show_startup_window()
        self._settle()
        self.assertEqual(win.size(), auto_window_size(_REFERENCE_WORK_AREA.size(), win.minimumSize()))

    def test_turning_remember_off_forgets_geometry(self):
        settings = self._settings()
        win = self._make_window(settings)
        win.remember_window_size_checkbox.setChecked(True)
        settings.setValue("window/geometry", QRect(2100, 80, 1300, 760))
        win.remember_window_size_checkbox.setChecked(False)
        self.assertFalse(settings.contains("window/geometry"))

    # 21
    def test_offscreen_saved_geometry_falls_back_to_auto(self):
        settings = self._settings()
        settings.setValue("window/remember_geometry", True)
        settings.setValue("window/geometry", QRect(9000, 3000, 1300, 760))
        settings.setValue("window/maximized", False)
        win = self._make_window(settings)
        win.show_startup_window()
        self._settle()
        self.assertEqual(win.size(), auto_window_size(_REFERENCE_WORK_AREA.size(), win.minimumSize()))
        self._assert_centered_inside_work_area(win)

    def test_remember_control_is_a_real_checkbox_with_accurate_copy(self):
        from PySide6.QtWidgets import QCheckBox

        box = self.win.remember_window_size_checkbox
        self.assertIsInstance(box, QCheckBox)
        self.assertIn("position", box.text().lower())
        self.assertTrue(self.win.remember_window_size_note.text())
        from mouse_click_stability_analyzer.qt_shell.styles import get_style

        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                sheet = get_style(theme)
                self.assertIn("QCheckBox::indicator", sheet)
                self.assertIn("18px", sheet)
                self.assertIn("QComboBox::down-arrow", sheet)
                self.assertIn("QComboBox::drop-down", sheet)
                self.assertIn("QPushButton#Secondary:hover", sheet)

    def test_reset_is_secondary_push_button(self):
        from PySide6.QtWidgets import QPushButton

        btn = self.win.reset_window_geometry_button
        self.assertIsInstance(btn, QPushButton)
        self.assertEqual(btn.objectName(), "Secondary")
        self.assertGreaterEqual(btn.minimumHeight(), 38)
        self.assertEqual(btn.text(), "Reset Window Size && Position")
        self.win.lang_combo.setCurrentIndex(SUPPORTED_LANGS.index("en"))
        self.assertEqual(btn.text(), "Reset Window Size && Position")

    # D, E, G
    def test_theme_switch_keeps_same_real_controls(self):
        from PySide6.QtWidgets import QCheckBox, QComboBox

        controls = (
            self.win.theme_combo,
            self.win.lang_combo,
            self.win.startup_window_combo,
            self.win.remember_window_size_checkbox,
            self.win.reset_window_geometry_button,
        )
        for combo in controls[:3]:
            self.assertIsInstance(combo, QComboBox)
        self.assertIsInstance(controls[3], QCheckBox)
        for theme_index, theme in ((1, "dark"), (0, "light")):
            with self.subTest(theme=theme):
                self.win.theme_combo.setCurrentIndex(theme_index)
                self.assertEqual(self.win.theme, theme)
                current = (
                    self.win.theme_combo,
                    self.win.lang_combo,
                    self.win.startup_window_combo,
                    self.win.remember_window_size_checkbox,
                    self.win.reset_window_geometry_button,
                )
                for before, after in zip(controls, current):
                    self.assertIs(before, after)
                    self.assertTrue(after.isEnabled())
                self.assertEqual(self.win.startup_window_combo.currentData(), "auto")

    def test_remember_checkbox_still_toggles_state(self):
        box = self.win.remember_window_size_checkbox
        self.win.show()
        self._settle()
        box.click()
        self.assertTrue(box.isChecked())
        self.assertTrue(self.win.remember_window_geometry)
        box.click()
        self.assertFalse(box.isChecked())
        self.assertFalse(self.win.remember_window_geometry)

    def test_combo_popup_and_keyboard_selection_unchanged(self):
        combo = self.win.startup_window_combo
        self.assertEqual(combo.count(), len(WINDOW_MODES))
        self.assertFalse(combo.isEditable())
        self.win.show()
        self._settle()
        with mock.patch.object(self.win, "apply_window_mode") as apply:
            combo.setFocus()
            from PySide6.QtCore import Qt
            from PySide6.QtTest import QTest

            QTest.keyClick(combo, Qt.Key.Key_Down)
            self._settle()
        self.assertEqual(combo.currentData(), "compact")
        self.assertEqual(self.win.window_mode, "compact")
        apply.assert_called_once_with()

    def test_indicator_assets_exist_and_load(self):
        from PySide6.QtGui import QPixmap
        from mouse_click_stability_analyzer.qt_shell.styles import STYLE_ASSETS, get_style, style_asset_path

        for theme, assets in STYLE_ASSETS.items():
            sheet = get_style(theme)
            self.assertNotIn("data:image", sheet)
            self.assertNotIn("@CHECK_ICON@", sheet)
            self.assertNotIn("@CHEVRON_ICON@", sheet)
            for name in assets.values():
                with self.subTest(theme=theme, asset=name):
                    path = style_asset_path(name)
                    self.assertTrue(path.is_file(), path)
                    self.assertIn(path.as_posix(), sheet)
                    pixmap = QPixmap(str(path))
                    self.assertFalse(pixmap.isNull(), path)
                    self.assertGreater(pixmap.width(), 0)

    def _show_preferences(self):
        self.win.show()
        self.win._show_workflow_page("preferences")
        self._settle()

    @staticmethod
    def _pixels(image, rect):
        return [
            image.pixelColor(x, y)
            for y in range(max(rect.top(), 0), min(rect.bottom() + 1, image.height()))
            for x in range(max(rect.left(), 0), min(rect.right() + 1, image.width()))
        ]

    def test_checked_checkbox_renders_tick_in_both_themes(self):
        from PySide6.QtWidgets import QStyle, QStyleOptionButton

        box = self.win.remember_window_size_checkbox
        self._show_preferences()
        for theme_index, theme in ((0, "light"), (1, "dark")):
            self.win.theme_combo.setCurrentIndex(theme_index)
            for checked in (False, True):
                with self.subTest(theme=theme, checked=checked):
                    box.setChecked(checked)
                    self._settle()
                    opt = QStyleOptionButton()
                    box.initStyleOption(opt)
                    indicator = box.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, opt, box)
                    pixels = self._pixels(box.grab().toImage(), indicator.adjusted(3, 3, -3, -3))
                    accent = sum(1 for c in pixels if c.blue() > 180 and c.red() < 80)
                    white = sum(1 for c in pixels if min(c.red(), c.green(), c.blue()) > 235)
                    if checked:
                        self.assertGreater(accent, 10, "checked fill missing")
                        self.assertGreater(white, 6, "check mark not drawn")
                    else:
                        self.assertEqual(accent, 0)

    def test_combo_renders_visible_chevron_in_both_themes(self):
        from PySide6.QtCore import QRect as _QRect

        self._show_preferences()
        for theme_index, theme in ((0, "light"), (1, "dark")):
            self.win.theme_combo.setCurrentIndex(theme_index)
            self._settle()
            for combo in (self.win.startup_window_combo, self.win.theme_combo, self.win.lang_combo):
                with self.subTest(theme=theme, combo=combo.objectName() or combo.currentText()):
                    image = combo.grab().toImage()
                    w, h = image.width(), image.height()
                    region = _QRect(w - 26, 4, 20, h - 8)
                    pixels = self._pixels(image, region)
                    bg = image.pixelColor(w - 28, h // 2)
                    contrast = sum(
                        1
                        for c in pixels
                        if abs(c.red() - bg.red()) + abs(c.green() - bg.green()) + abs(c.blue() - bg.blue()) > 150
                    )
                    self.assertGreater(contrast, 8, "dropdown chevron not drawn")

    # --- Step 3e: preset expansion ---------------------------------------------------------------

    def _assert_inside_reachable(self, win, work: QRect = _REFERENCE_WORK_AREA):
        frame = win.frameGeometry()
        self.assertTrue(work.contains(frame), frame)
        self.assertTrue(geometry_is_reachable(frame, [work]), frame)

    def test_legacy_preset_ids_still_restore(self):
        for mode in ("compact", "standard", "large"):
            with self.subTest(mode=mode):
                settings = self._settings()
                settings.setValue("window/startup_mode", mode)
                win = self._make_window(settings)
                self.assertEqual(win.window_mode, mode)
                self.assertEqual(win.startup_window_combo.currentData(), mode)
                win.show_startup_window()
                self._settle()
                self.assertEqual(win.size(), _PRESETS[mode])
                self.assertEqual(settings.value("window/startup_mode"), mode)

    def test_unknown_stored_mode_falls_back_to_auto(self):
        settings = self._settings()
        settings.setValue("window/startup_mode", "qhd")
        win = self._make_window(settings)
        self.assertEqual(win.window_mode, "auto")
        self.assertEqual(win.startup_window_combo.currentData(), "auto")

    def test_every_preset_applies_immediately_inside_work_area(self):
        self.win.show()
        for mode, size in _PRESETS.items():
            with self.subTest(mode=mode):
                self._select_mode(mode)
                self.assertEqual(self.win.window_mode, mode)
                if mode != "full_hd":
                    self.assertEqual(self.win.size(), size)
                self._assert_inside_reachable(self.win)

    def test_full_hd_request_is_fitted_on_full_hd_desktop(self):
        self.win.show()
        self._select_mode("full_hd")
        self.assertFalse(self.win.isMaximized())
        self._assert_inside_reachable(self.win)
        self.assertGreaterEqual(self.win.frameGeometry().top(), _REFERENCE_WORK_AREA.top())
        self.assertLessEqual(self.win.frameGeometry().bottom(), _REFERENCE_WORK_AREA.bottom())
        self.assertAlmostEqual(self.win.width() / self.win.height(), 16 / 9, delta=0.02)

    def test_full_hd_request_on_small_work_area_stays_reachable(self):
        small = QRect(0, 0, 1366, 728)
        self.win._available_geometry = lambda: QRect(small)
        self.win.show()
        for mode in ("laptop", "large_plus", "full_hd"):
            with self.subTest(mode=mode):
                self._select_mode(mode)
                self._assert_inside_reachable(self.win, small)

    def test_language_switch_keeps_numeric_preset_text(self):
        self.win.lang_combo.setCurrentIndex(SUPPORTED_LANGS.index("zh"))
        combo = self.win.startup_window_combo
        self.assertEqual(combo.itemText(WINDOW_MODES.index("laptop")), f"1366 × 768 — {STRINGS['zh']['window_mode_laptop']}")
        self.assertEqual(combo.itemText(WINDOW_MODES.index("custom")), STRINGS["zh"]["window_mode_custom"])
        self.assertEqual(self.win.apply_custom_size_button.text(), STRINGS["zh"]["apply_custom_size"])
        self.assertEqual(self.win.lbl_custom_width.text(), STRINGS["zh"]["custom_width"])
        self.assertEqual(self.win.window_fit_note.text(), STRINGS["zh"]["window_fit_note"])

    # --- Step 3e: custom window size -------------------------------------------------------------

    def _custom_widgets(self, win=None):
        win = win or self.win
        return (win.custom_width_spin, win.custom_height_spin, win.apply_custom_size_button)

    def _show_prefs(self, win=None):
        win = win or self.win
        win.show()
        win._show_workflow_page("preferences")
        self._settle()

    def test_custom_controls_hidden_by_default(self):
        self._show_prefs()
        self.assertFalse(self.win.custom_window_panel.isVisibleTo(self.win))
        for widget in self._custom_widgets():
            self.assertFalse(widget.isVisibleTo(self.win))

    def test_custom_controls_are_bounded_spinboxes_and_button(self):
        from PySide6.QtWidgets import QPushButton, QSpinBox

        self.assertIsInstance(self.win.custom_width_spin, QSpinBox)
        self.assertIsInstance(self.win.custom_height_spin, QSpinBox)
        self.assertIsInstance(self.win.apply_custom_size_button, QPushButton)
        self.assertEqual(self.win.custom_width_spin.minimum(), self.win.minimumWidth())
        self.assertEqual(self.win.custom_height_spin.minimum(), self.win.minimumHeight())
        self.assertEqual(self.win.custom_width_spin.maximum(), 7680)
        self.assertEqual(self.win.custom_height_spin.maximum(), 4320)
        self.assertFalse(self.win.custom_width_spin.isReadOnly())

    def test_selecting_custom_reveals_fields_without_applying(self):
        settings = self._settings()
        win = self._make_window(settings)
        self._show_prefs(win)
        win.startup_window_combo.setCurrentIndex(WINDOW_MODES.index("large"))
        self._settle()
        with mock.patch.object(win, "apply_window_mode", wraps=win.apply_window_mode) as apply:
            win.startup_window_combo.setCurrentIndex(WINDOW_MODES.index("custom"))
            self._settle()
        apply.assert_not_called()
        for widget in self._custom_widgets(win):
            self.assertTrue(widget.isVisibleTo(win), widget)
        self.assertEqual(win.window_mode, "large")
        self.assertEqual(settings.value("window/startup_mode"), "large")
        self.assertFalse(settings.contains("window/custom_width"))
        self.assertEqual(win.size(), QSize(1600, 900))
        self.assertTrue(win.custom_size_status.isVisibleTo(win))
        self.assertEqual(win.custom_size_status.text(), win._tr("custom_size_pending"))

    def test_first_custom_selection_seeds_from_current_window(self):
        self._show_prefs()
        self._select_mode("large")
        self._select_mode("custom")
        self.assertEqual((self.win.custom_width_spin.value(), self.win.custom_height_spin.value()), (1600, 900))

    def test_first_custom_selection_while_maximized_uses_normal_geometry(self):
        self._show_prefs()
        self._select_mode("standard")
        self._select_mode("maximized")
        self.assertTrue(self.win.isMaximized())
        self._select_mode("custom")
        seed = QSize(self.win.custom_width_spin.value(), self.win.custom_height_spin.value())
        normal = self.win.normalGeometry()
        expected = normal.size() if normal.isValid() and not normal.isEmpty() else auto_window_size(
            _REFERENCE_WORK_AREA.size(), self.win.minimumSize()
        )
        self.assertEqual(seed, expected)
        self.assertLessEqual(seed.width(), _REFERENCE_WORK_AREA.width())

    def test_apply_valid_custom_persists_and_resizes_once(self):
        settings = self._settings()
        win = self._make_window(settings)
        self._show_prefs(win)
        win.startup_window_combo.setCurrentIndex(WINDOW_MODES.index("custom"))
        win.custom_width_spin.setValue(1500)
        win.custom_height_spin.setValue(820)
        with mock.patch.object(win, "apply_window_mode", wraps=win.apply_window_mode) as apply:
            win.apply_custom_size_button.click()
            self._settle()
        apply.assert_called_once_with("custom")
        self.assertEqual(int(settings.value("window/custom_width")), 1500)
        self.assertEqual(int(settings.value("window/custom_height")), 820)
        self.assertEqual(settings.value("window/startup_mode"), "custom")
        self.assertEqual(win.window_mode, "custom")
        self.assertEqual(win.startup_window_combo.currentData(), "custom")
        self.assertEqual(win.size(), QSize(1500, 820))
        self._assert_inside_reachable(win)
        self.assertFalse(win.custom_size_status.isVisibleTo(win))

    def test_editing_after_apply_marks_pending_until_applied(self):
        self._show_prefs()
        self.assertTrue(self.win.apply_custom_window_size(1500, 820))
        self.win.custom_width_spin.setValue(1550)
        self.assertTrue(self.win.custom_size_status.isVisibleTo(self.win))
        self.assertEqual(self.win.size(), QSize(1500, 820))
        self.win.apply_custom_size_button.click()
        self._settle()
        self.assertEqual(self.win.size(), QSize(1550, 820))
        self.assertFalse(self.win.custom_size_status.isVisibleTo(self.win))

    def test_custom_below_minimum_is_bounded_or_rejected(self):
        settings = self._settings()
        win = self._make_window(settings)
        win.custom_width_spin.setValue(500)
        win.custom_height_spin.setValue(300)
        self.assertEqual(win.custom_width_spin.value(), win.minimumWidth())
        self.assertEqual(win.custom_height_spin.value(), win.minimumHeight())
        for bad in ((500, 300), (1500, 100), (9000, 900), (1500.5, 820), ("1500", 820), (True, 820)):
            with self.subTest(bad=bad):
                self.assertFalse(win.apply_custom_window_size(*bad))
        self.assertEqual(win.window_mode, "auto")
        self.assertIsNone(win.custom_window_size)
        self.assertFalse(settings.contains("window/custom_width"))
        self.assertFalse(settings.contains("window/startup_mode"))

    def test_custom_larger_than_work_area_is_fitted_and_reachable(self):
        settings = self._settings()
        win = self._make_window(settings)
        self._show_prefs(win)
        self.assertTrue(win.apply_custom_window_size(3000, 1800))
        self._settle()
        self.assertEqual(win.window_mode, "custom")
        self.assertEqual(int(settings.value("window/custom_width")), 3000)
        self._assert_inside_reachable(win)
        self.assertFalse(win.isMaximized())

    def test_custom_relaunch_with_remember_off_applies_stored_request(self):
        settings = self._settings()
        first = self._make_window(settings)
        self._show_prefs(first)
        self.assertTrue(first.apply_custom_window_size(1500, 820))
        first.close()
        second = self._make_window(settings)
        self.assertFalse(second.remember_window_geometry)
        self.assertEqual(second.window_mode, "custom")
        self.assertEqual(second.startup_window_combo.currentData(), "custom")
        self.assertEqual((second.custom_width_spin.value(), second.custom_height_spin.value()), (1500, 820))
        second.show_startup_window()
        self._settle()
        self.assertEqual(second.size(), QSize(1500, 820))
        self._assert_inside_reachable(second)
        second._show_workflow_page("preferences")
        self._settle()
        self.assertTrue(second.custom_window_panel.isVisibleTo(second))
        self.assertFalse(second.custom_size_status.isVisibleTo(second))

    def test_custom_mode_without_valid_size_never_restores_as_custom(self):
        for width, height in ((None, None), (500, 300), ("abc", 900)):
            with self.subTest(width=width, height=height):
                settings = self._settings()
                settings.setValue("window/startup_mode", "custom")
                if width is not None:
                    settings.setValue("window/custom_width", width)
                    settings.setValue("window/custom_height", height)
                win = self._make_window(settings)
                self.assertEqual(win.window_mode, "auto")
                self.assertEqual(win.startup_window_combo.currentData(), "auto")
                self.assertIsNone(win.custom_window_size)

    def test_custom_with_remember_on_keeps_remembered_geometry_authoritative(self):
        settings = self._settings()
        settings.setValue("window/startup_mode", "custom")
        settings.setValue("window/custom_width", 1500)
        settings.setValue("window/custom_height", 820)
        settings.setValue("window/remember_geometry", True)
        remembered = QRect(2000, 60, 1300, 760)
        settings.setValue("window/geometry", remembered)
        win = self._make_window(settings)
        win.show_startup_window()
        self._settle()
        self.assertEqual(win.geometry(), remembered)

    def test_reset_returns_to_auto_but_keeps_custom_dimensions(self):
        settings = self._settings()
        win = self._make_window(settings)
        self._show_prefs(win)
        self.assertTrue(win.apply_custom_window_size(1500, 820))
        win.reset_window_geometry_button.click()
        self._settle()
        self.assertEqual(win.window_mode, "auto")
        self.assertEqual(win.startup_window_combo.currentData(), "auto")
        self.assertEqual(settings.value("window/startup_mode"), "auto")
        self.assertFalse(win.custom_window_panel.isVisibleTo(win))
        self.assertEqual(int(settings.value("window/custom_width")), 1500)
        self.assertEqual(int(settings.value("window/custom_height")), 820)
        self.assertEqual(win.size(), auto_window_size(_REFERENCE_WORK_AREA.size(), win.minimumSize()))
        win.startup_window_combo.setCurrentIndex(WINDOW_MODES.index("custom"))
        self._settle()
        self.assertEqual((win.custom_width_spin.value(), win.custom_height_spin.value()), (1500, 820))
        self.assertEqual(win.window_mode, "auto")
        self.assertTrue(win.custom_size_status.isVisibleTo(win))

    def test_selecting_preset_after_custom_hides_panel(self):
        self._show_prefs()
        self.assertTrue(self.win.apply_custom_window_size(1500, 820))
        self._select_mode("standard")
        self.assertFalse(self.win.custom_window_panel.isVisibleTo(self.win))
        self.assertEqual(self.win.size(), QSize(1440, 810))
        self.assertEqual(self.win.custom_window_size, QSize(1500, 820))

    def test_custom_apply_does_not_recreate_window_or_controls(self):
        self._show_prefs()
        before = (
            self.win.page_setup, self.win.page_capture, self.win.page_preferences,
            self.win.startup_window_combo, self.win.custom_width_spin, self.win.apply_custom_size_button,
        )
        top_levels = len(self._qapp.topLevelWidgets())
        self.assertTrue(self.win.apply_custom_window_size(1500, 820))
        self.assertTrue(self.win.apply_custom_window_size(1300, 760))
        self._settle()
        after = (
            self.win.page_setup, self.win.page_capture, self.win.page_preferences,
            self.win.startup_window_combo, self.win.custom_width_spin, self.win.apply_custom_size_button,
        )
        for a, b in zip(before, after):
            self.assertIs(a, b)
        self.assertEqual(len(self._qapp.topLevelWidgets()), top_levels)

    def test_custom_apply_in_ready_and_running_keeps_lifecycle(self):
        win = self.win
        self._show_prefs()
        win.listening = True
        win.radio_fixture.setChecked(True)
        win.hz_combo.setCurrentText("40")
        win.timing_tol_edit.setText("2")
        self.assertTrue(win.lock_profile())

        def snapshot():
            return (
                win._lifecycle_state(), win.profile_locked_settings, win.profile_locked_target,
                win.capture_armed, win.running, win.completed, win.locked, win.start_time,
                win.first_press_time, win.end_time, list(win.events), list(win.raw_events),
                win.host_evidence_snapshot,
            )

        ready = snapshot()
        self.assertTrue(win.apply_custom_window_size(1500, 820))
        self.assertEqual(snapshot(), ready)
        self.assertTrue(win.arm_capture())
        t0 = float(win._arm_boundary_perf) + 0.001
        win._begin_session_from_first_click("Left", t0, t0 + 0.01, {})
        self.assertTrue(win.running)
        running = snapshot()
        self.assertTrue(win.apply_custom_window_size(1300, 760))
        self._settle()
        self.assertEqual(snapshot(), running)

    def test_custom_panel_background_matches_card_in_both_themes(self):
        self._show_prefs()
        self._select_mode("custom")
        card, panel = self.win.pref_window_card, self.win.custom_window_panel
        for theme_index, theme in ((0, "light"), (1, "dark")):
            with self.subTest(theme=theme):
                self.win.theme_combo.setCurrentIndex(theme_index)
                self._settle()
                image = card.grab().toImage()
                card_bg = image.pixelColor(card.width() // 2, 10)
                inside = panel.mapTo(card, QPoint(panel.width() - 6, 3))
                panel_bg = image.pixelColor(inside.x(), inside.y())
                diff = (
                    abs(card_bg.red() - panel_bg.red())
                    + abs(card_bg.green() - panel_bg.green())
                    + abs(card_bg.blue() - panel_bg.blue())
                )
                self.assertLessEqual(diff, 6, (card_bg.name(), panel_bg.name()))

    def test_custom_controls_are_capture_exclusion_chrome(self):
        widgets = self.win._capture_exclusion_widgets()
        for widget in self._custom_widgets():
            self.assertIn(widget, widgets)


if __name__ == "__main__":
    unittest.main()
