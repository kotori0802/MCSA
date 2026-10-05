"""Step 3: Setup + Preferences presentation migration (structure, not pixels)."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from PySide6.QtWidgets import QComboBox, QFrame, QLineEdit, QPushButton, QRadioButton, QScrollArea

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mouse_click_stability_analyzer.i18n import STRINGS, SUPPORTED_LANGS
from mouse_click_stability_analyzer.qt_shell import app as qt_app
from mouse_click_stability_analyzer.qt_shell.app import ResponsiveCardGrid, locked_profile_preview_rows

_NEW_KEYS = (
    "setup_profile_section",
    "setup_locked_profile_section",
    "preview_mode",
    "preview_reference_rate",
    "preview_timing_tolerance",
    "preview_auto_stop_off",
    "pref_appearance_section",
    "display_language",
    "preferences_more_note",
    "screening",
    "screening_measurement_only",
    "screening_measurement_only_note",
)


def _make_qapp():
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:  # pragma: no cover
        return None
    return QApplication.instance() or QApplication([])


def _under(widget, ancestor) -> bool:
    current = widget
    while current is not None:
        if current is ancestor:
            return True
        current = current.parentWidget()
    return False


class SetupPreferencesUiTests(unittest.TestCase):
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

    def _setup_controls(self):
        return [
            self.win.device_edit,
            self.win.button_combo,
            self.win.radio_manual,
            self.win.radio_fixture,
            self.win.hz_combo,
            self.win.timing_tol_edit,
            self.win.auto_stop_off,
            self.win.auto_stop_on,
            self.win.auto_stop_sec_combo,
        ]

    def _fixture(self, *, device="DUT-1", hz="5", tol="2", auto_sec="20"):
        self.win.device_edit.setText(device)
        self.win.radio_fixture.setChecked(True)
        self.win.hz_combo.setCurrentText(hz)
        self.win.timing_tol_edit.setText(tol)
        if auto_sec is None:
            self.win.auto_stop_off.setChecked(True)
        else:
            self.win.auto_stop_on.setChecked(True)
            self.win.auto_stop_sec_combo.setCurrentText(auto_sec)

    def _preview_pairs(self):
        return [
            (key.text(), val.text())
            for cell, key, val in self.win._preview_cells
            if not cell.isHidden()
        ]

    # 1, 2
    def test_exactly_one_instance_of_every_setup_control_on_setup_page(self):
        by_type = {
            QLineEdit: self.win.findChildren(QLineEdit),
            QComboBox: self.win.findChildren(QComboBox),
            QRadioButton: self.win.findChildren(QRadioButton),
            QPushButton: self.win.findChildren(QPushButton),
        }
        for widget in self._setup_controls():
            with self.subTest(widget=widget.objectName() or type(widget).__name__):
                pool = next(v for k, v in by_type.items() if isinstance(widget, k))
                self.assertEqual(pool.count(widget), 1)
                self.assertTrue(_under(widget, self.win.page_setup))
                self.assertTrue(_under(widget, self.win.setup_scroll))
        button_likes = [
            w for w in by_type[QComboBox]
            if [w.itemText(i) for i in range(w.count())] == ["Left", "Right", "Middle", "X1", "X2"]
        ]
        self.assertEqual(button_likes, [self.win.button_combo])
        self.assertEqual(self.win._limit_edits, {})
        screening_edits = [
            w for w in self.win.setup_screening_card.findChildren(QLineEdit)
        ]
        self.assertEqual(screening_edits, [])

    def test_setup_cards_follow_contract_hierarchy(self):
        grid = self.win.setup_card_grid
        self.assertTrue(_under(grid, self.win.page_setup))
        self.assertTrue(_under(self.win.device_edit, self.win.setup_device_card))
        self.assertTrue(_under(self.win.button_combo, self.win.setup_device_card))
        for widget in (self.win.radio_manual, self.win.hz_combo, self.win.timing_tol_edit,
                       self.win.auto_stop_on, self.win.auto_stop_sec_combo):
            self.assertTrue(_under(widget, self.win.setup_config_card), widget)
        self.assertTrue(_under(self.win.lbl_screening, self.win.setup_screening_card))
        self.assertTrue(_under(self.win.lbl_screening_status, self.win.setup_screening_card))
        self.assertIs(self.win.setup_limits_card, self.win.setup_screening_card)
        self.assertTrue(_under(self.win.lbl_profile_status, self.win.setup_profile_card))
        self.assertTrue(_under(self.win.btn_lock_profile, self.win.setup_profile_card))
        self.assertTrue(_under(self.win.locked_profile_card, self.win.page_setup))

    # 3
    def test_settings_reads_moved_controls(self):
        self._fixture(hz="40", tol="1.5", auto_sec="30")
        self.win.button_combo.setCurrentText("Right")
        s = self.win.settings()
        self.assertFalse(s["manual_mode"])
        self.assertEqual(s["focus_button"], "Right")
        self.assertEqual(s["fixture_reference_hz"], 40.0)
        self.assertEqual(s[qt_app.FIXTURE_TIMING_TOLERANCE_KEY], 1.5)
        self.assertEqual(s["duration_sec"], 30.0)
        self.assertEqual(s["chatter_threshold_ms"], qt_app.qt_custom_limit_defaults()["chatter_threshold_ms"])

    # 4
    def test_lock_profile_behavior_unchanged(self):
        self._fixture()
        self.assertTrue(self.win.lock_profile())
        self.assertEqual(self.win._lifecycle_state(), "ready")
        self.assertFalse(self.win.capture_armed)
        self.assertFalse(self.win.running)
        self.assertIs(self.win.page_stack.currentWidget(), self.win.page_capture)
        self.assertFalse(self.win.btn_lock_profile.isEnabled())
        self.assertEqual(self.win.lbl_profile_status.property("state"), "locked")

    def test_validation_error_presentation_stays_on_setup(self):
        self._fixture(tol="")
        self.assertFalse(self.win.lock_profile())
        self.assertIs(self.win.page_stack.currentWidget(), self.win.page_setup)
        self.assertIsNone(self.win.profile_locked_settings)
        self.assertEqual(self.win.lbl_profile_status.property("state"), "error")
        self.assertEqual(self.win.lbl_profile_status.text(), self.win._tr("fixture_timing_tolerance_invalid"))
        self.assertTrue(self.win.btn_lock_profile.isEnabled())
        self.assertTrue(self.win.locked_profile_card.isHidden())

    def test_screening_card_is_measurement_only(self):
        self.win._show_workflow_page("setup")
        self.assertEqual(self.win.lbl_screening.text(), self.win._tr("screening").upper())
        self.assertEqual(self.win.lbl_screening_status.text(), self.win._tr("screening_measurement_only"))
        self.assertEqual(self.win.lbl_screening_note.text(), self.win._tr("screening_measurement_only_note"))
        for phrase in ("Chatter", "Double-click", "Actuation short", "Low hold", "Interval CV", "PASS"):
            self.assertNotIn(phrase, self.win.lbl_screening_status.text())
            self.assertNotIn(phrase, self.win.lbl_screening_note.text())

    def test_draft_presentation_is_neutral(self):
        self.assertEqual(self.win.lbl_profile_status.property("state"), "draft")
        self.assertEqual(self.win.lbl_profile_status.text(), self.win._tr("profile_status_draft"))
        self.assertTrue(self.win.btn_lock_profile.isEnabled())
        self.assertTrue(self.win.locked_profile_card.isHidden())

    # 5
    def test_locked_preview_comes_from_frozen_snapshot(self):
        self._fixture(device="DUT-7", hz="5", tol="2", auto_sec="20")
        self.assertTrue(self.win.lock_profile())
        self.assertFalse(self.win.locked_profile_card.isHidden())
        expected = locked_profile_preview_rows(
            self.win.profile_locked_settings, self.win.profile_locked_target, self.win._tr
        )
        self.assertEqual(self._preview_pairs(), [(k.upper(), v) for k, v in expected])
        values = dict(expected)
        self.assertEqual(values[self.win._tr("device")], "DUT-7")
        self.assertEqual(values[self.win._tr("button")], "Left")
        self.assertEqual(values[self.win._tr("preview_mode")], self.win._tr("fixture"))
        self.assertEqual(values[self.win._tr("preview_reference_rate")], "5 Hz")
        self.assertEqual(values[self.win._tr("preview_timing_tolerance")], "±2.00 ms")
        self.assertEqual(values[self.win._tr("auto_stop")], "20 s")

    def test_manual_preview_shows_no_fixture_values(self):
        self.win.radio_manual.setChecked(True)
        self.win.hz_combo.setCurrentText("40")
        self.win.timing_tol_edit.setText("3")
        self.assertTrue(self.win.lock_profile())
        labels = [k for k, _v in self._preview_pairs()]
        self.assertEqual(len(labels), 3)
        for key in ("preview_reference_rate", "preview_timing_tolerance", "auto_stop"):
            self.assertNotIn(self.win._tr(key).upper(), labels)

    def test_fixture_auto_stop_off_preview(self):
        self._fixture(auto_sec=None)
        self.assertTrue(self.win.lock_profile())
        values = dict(self._preview_pairs())
        self.assertEqual(values[self.win._tr("auto_stop").upper()], self.win._tr("preview_auto_stop_off"))

    def test_preview_rows_helper_is_snapshot_only(self):
        self.assertEqual(locked_profile_preview_rows(None, "x", self.win._tr), [])
        rows = locked_profile_preview_rows(
            {"manual_mode": True, "focus_button": "X1"}, "", self.win._tr
        )
        self.assertEqual(rows[0][1], "—")
        self.assertEqual(rows[1][1], "X1")
        self.assertEqual(len(rows), 3)

    # 6
    def test_widget_mutation_cannot_change_preview_until_relock(self):
        self._fixture(device="DUT-A", hz="5", tol="2", auto_sec="20")
        self.assertTrue(self.win.lock_profile())
        before = self._preview_pairs()
        self.win.device_edit.setText("DUT-B")
        self.win.hz_combo.setCurrentText("40")
        self.win.timing_tol_edit.setText("9")
        self.win._update_controls()
        self.win._retranslate_ui()
        self.assertEqual(self._preview_pairs(), before)
        self.assertTrue(self.win.edit_profile())
        self._fixture(device="DUT-B", hz="40", tol="9", auto_sec="20")
        self.assertTrue(self.win.lock_profile())
        values = dict(self._preview_pairs())
        self.assertEqual(values[self.win._tr("device").upper()], "DUT-B")
        self.assertEqual(values[self.win._tr("preview_reference_rate").upper()], "40 Hz")
        self.assertEqual(values[self.win._tr("preview_timing_tolerance").upper()], "±9.00 ms")

    # 7
    def test_edit_profile_removes_preview_and_returns_draft(self):
        self._fixture()
        self.assertTrue(self.win.lock_profile())
        self.assertFalse(self.win.locked_profile_card.isHidden())
        self.assertTrue(self.win.edit_profile())
        self.assertTrue(self.win.locked_profile_card.isHidden())
        self.assertEqual(self.win._current_page, "setup")
        self.assertEqual(self.win.lbl_profile_status.property("state"), "draft")
        self.assertEqual(self.win.lbl_profile_status.text(), self.win._tr("profile_status_draft"))
        self.assertTrue(self.win.btn_lock_profile.isEnabled())

    # 8, 9, 15
    def test_theme_and_language_live_only_in_preferences(self):
        for combo in (self.win.theme_combo, self.win.lang_combo):
            with self.subTest(combo=combo):
                self.assertTrue(_under(combo, self.win.page_preferences))
                self.assertFalse(_under(combo, self.win.page_setup))
                self.assertFalse(_under(combo, self.win.page_capture))
                self.assertFalse(_under(combo, self.win.nav_rail))
        self.assertTrue(_under(self.win.theme_combo, self.win.pref_appearance_card))
        self.assertTrue(_under(self.win.lang_combo, self.win.pref_language_card))
        combos = self.win.findChildren(QComboBox)
        themes = [c for c in combos if [c.itemData(i) for i in range(c.count())] == ["light", "dark"]]
        langs = [c for c in combos if [c.itemData(i) for i in range(c.count())] == list(SUPPORTED_LANGS)]
        self.assertEqual(themes, [self.win.theme_combo])
        self.assertEqual(langs, [self.win.lang_combo])

    def test_global_header_has_only_title_and_subtitle(self):
        header_parent = self.win.page_title.parentWidget()
        header_combos = [
            c for c in header_parent.findChildren(QComboBox)
            if not _under(c, self.win.page_stack)
        ]
        self.assertEqual(header_combos, [])
        self.assertTrue(_under(self.win.lbl_theme, self.win.page_preferences))
        self.assertTrue(_under(self.win.lbl_lang, self.win.page_preferences))

    # 10
    def test_theme_switch_retains_setup_and_profile_state(self):
        self._fixture(device="DUT-T", hz="40", tol="2")
        self.assertTrue(self.win.lock_profile())
        snap = self.win.profile_locked_settings
        preview = self._preview_pairs()
        device = self.win.device_edit
        self.win.nav_preferences.click()
        self.win.theme_combo.setCurrentIndex(1)
        self.assertEqual(self.win.theme, "dark")
        self.assertIs(self.win.device_edit, device)
        self.assertIs(self.win.profile_locked_settings, snap)
        self.assertEqual(self.win._lifecycle_state(), "ready")
        self.assertEqual(self.win.hz_combo.currentText(), "40")
        self.assertEqual(self._preview_pairs(), preview)
        self.assertEqual(self.win._current_page, "preferences")

    # 11
    def test_language_switch_retains_setup_and_profile_state(self):
        self._fixture(device="DUT-L", hz="40", tol="2")
        self.assertTrue(self.win.lock_profile())
        self.assertTrue(self.win.arm_capture())
        snap = self.win.profile_locked_settings
        self.win.nav_preferences.click()
        self.win.lang_combo.setCurrentIndex(self.win.lang_combo.findData("zh"))
        self.assertEqual(self.win.lang, "zh")
        self.assertIs(self.win.profile_locked_settings, snap)
        self.assertEqual(self.win._lifecycle_state(), "armed")
        self.assertTrue(self.win.capture_armed)
        self.assertEqual(self.win.hz_combo.currentText(), "40")
        self.assertEqual(self.win.lbl_theme.text(), STRINGS["zh"]["theme"])
        self.assertEqual(self.win.lbl_lang.text(), STRINGS["zh"]["display_language"])
        values = dict(self._preview_pairs())
        self.assertEqual(values[STRINGS["zh"]["preview_mode"].upper()], STRINGS["zh"]["fixture"])

    # 12
    def test_navigation_does_not_change_lifecycle(self):
        self._fixture()
        for btn in (self.win.nav_preferences, self.win.nav_capture, self.win.nav_results, self.win.nav_setup):
            btn.click()
            self.assertEqual(self.win._lifecycle_state(), "draft")
        self.assertTrue(self.win.lock_profile())
        for btn in (self.win.nav_preferences, self.win.nav_setup, self.win.nav_results, self.win.nav_capture):
            btn.click()
            self.assertEqual(self.win._lifecycle_state(), "ready")
            self.assertFalse(self.win.capture_armed)
            self.assertFalse(self.win.running)

    # 13
    def test_setup_scroll_area_contract(self):
        scroll = self.win.setup_scroll
        self.assertIsInstance(scroll, QScrollArea)
        self.assertTrue(scroll.widgetResizable())
        self.assertEqual(scroll.horizontalScrollBarPolicy(), qt_app.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.assertEqual(scroll.verticalScrollBarPolicy(), qt_app.Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def test_responsive_grid_reflows_by_width(self):
        self.assertEqual(ResponsiveCardGrid.columns_for_width(1320), 3)
        self.assertEqual(ResponsiveCardGrid.columns_for_width(1080), 3)
        self.assertEqual(ResponsiveCardGrid.columns_for_width(1000), 2)
        self.assertEqual(ResponsiveCardGrid.columns_for_width(700), 2)
        self.assertEqual(ResponsiveCardGrid.columns_for_width(600), 1)
        self.assertLess(3 * ResponsiveCardGrid.CARD_MIN_WIDTH + 32, ResponsiveCardGrid.THREE_COLUMN_MIN_WIDTH)
        self.assertLess(2 * ResponsiveCardGrid.CARD_MIN_WIDTH + 16, ResponsiveCardGrid.TWO_COLUMN_MIN_WIDTH)
        cards = [QFrame(), QFrame(), QFrame()]
        grid = ResponsiveCardGrid(cards)
        try:
            for width, columns in ((1300, 3), (900, 2), (500, 1), (1200, 3)):
                with self.subTest(width=width):
                    grid.resize(width, 400)
                    grid.show()
                    self._qapp.processEvents()
                    self.assertEqual(grid.columns(), columns)
            for card in cards:
                self.assertIs(card.parentWidget(), grid)
        finally:
            grid.close()
            grid.deleteLater()

    def _setup_at(self, width: int, height: int = 860) -> int:
        """Resize the real MainWindow on Setup and return the settled Setup viewport width."""
        if width < self.win.minimumWidth():
            self.win.setMinimumSize(1, 1)
        self.win.show()
        self.win._show_workflow_page("setup")
        self.win.resize(width, height)
        for _ in range(4):
            self._qapp.processEvents()
        if self.win.width() != width:
            self.skipTest(f"window could not reach {width} px logical width on this screen")
        return self.win.setup_scroll.viewport().width()

    def _assert_grid_geometry(self, columns: int) -> None:
        grid = self.win.setup_card_grid
        device, config, limits = self.win.setup_device_card, self.win.setup_config_card, self.win.setup_limits_card
        self.assertEqual(grid.columns(), columns)
        if columns == 3:
            self.assertEqual(device.y(), config.y())
            self.assertEqual(config.y(), limits.y())
            self.assertLess(device.x(), config.x())
            self.assertLess(config.x(), limits.x())
        elif columns == 2:
            self.assertEqual(device.y(), config.y())
            self.assertLess(device.x(), config.x())
            self.assertGreater(limits.y(), device.y())
            self.assertGreater(limits.width(), device.width() + config.width())
        else:
            self.assertEqual(device.x(), config.x())
            self.assertEqual(config.x(), limits.x())
            self.assertLess(device.y(), config.y())
            self.assertLess(config.y(), limits.y())
        for card in (self.win.setup_profile_card, self.win.locked_profile_card):
            if card.isVisibleTo(self.win):
                self.assertEqual(card.width(), grid.width())

    def _assert_setup_owns_viewport(self, viewport: int) -> None:
        content = self.win.setup_content
        cap = qt_app.MainWindow.MAX_SETUP_CONTENT_WIDTH
        self.assertEqual(content.width(), min(viewport, cap))
        self.assertLessEqual(self.win.setup_card_grid.width(), content.width())
        self.assertGreaterEqual(self.win.setup_card_grid.width(), content.width() - 16)

    def test_real_window_wide_setup_is_three_columns(self):
        viewport = self._setup_at(1600)
        self._assert_setup_owns_viewport(viewport)
        self._assert_grid_geometry(3)
        self.assertGreater(self.win.setup_content.width(), 3 * ResponsiveCardGrid.CARD_MIN_WIDTH)
        self.assertGreaterEqual(self.win.setup_card_grid.width(), ResponsiveCardGrid.THREE_COLUMN_MIN_WIDTH)

    def test_real_window_medium_setup_is_two_columns(self):
        viewport = self._setup_at(1280)
        self._assert_setup_owns_viewport(viewport)
        self._assert_grid_geometry(2)

    def test_real_window_compact_setup_is_one_column(self):
        viewport = self._setup_at(820)
        self.assertLess(viewport, ResponsiveCardGrid.TWO_COLUMN_MIN_WIDTH)
        self._assert_setup_owns_viewport(viewport)
        self._assert_grid_geometry(1)

    def test_real_window_live_resize_compact_to_wide_reflows_up(self):
        self._setup_at(820)
        self._assert_grid_geometry(1)
        self._setup_at(1280)
        self._assert_grid_geometry(2)
        viewport = self._setup_at(1600)
        self._assert_setup_owns_viewport(viewport)
        self._assert_grid_geometry(3)

    def test_real_window_live_resize_wide_to_compact_reflows_down(self):
        self._setup_at(1600)
        self._assert_grid_geometry(3)
        self._setup_at(1280)
        self._assert_grid_geometry(2)
        viewport = self._setup_at(820)
        self._assert_setup_owns_viewport(viewport)
        self._assert_grid_geometry(1)

    def test_real_window_setup_fields_stay_comfortably_bounded(self):
        for width in (820, 1280, 1600):
            with self.subTest(width=width):
                self._setup_at(width)
                for field in (self.win.device_edit, self.win.hz_combo, self.win.timing_tol_edit, self.win.auto_stop_sec_combo):
                    self.assertGreaterEqual(field.width(), 160)
                    self.assertLessEqual(field.width(), 700)
                for btn in (self.win.auto_stop_off, self.win.auto_stop_on):
                    self.assertGreaterEqual(btn.width(), 80)
                self.assertTrue(self.win.timing_tol_label.wordWrap())

    # 14
    def test_preferences_is_no_longer_placeholder_only(self):
        self.assertFalse(hasattr(self.win, "preferences_placeholder"))
        self.assertTrue(_under(self.win.pref_appearance_card, self.win.page_preferences))
        self.assertTrue(_under(self.win.pref_language_card, self.win.page_preferences))
        self.assertEqual(self.win.lbl_pref_appearance.text(), self.win._tr("pref_appearance_section").upper())
        self.assertEqual(self.win.lbl_lang.text(), self.win._tr("display_language"))
        self.assertEqual(self.win.preferences_note.text(), self.win._tr("preferences_more_note"))

    # 16
    def test_new_i18n_keys_exist_for_all_languages(self):
        for lang in SUPPORTED_LANGS:
            for key in _NEW_KEYS:
                with self.subTest(lang=lang, key=key):
                    text = str(STRINGS[lang].get(key) or "").strip()
                    self.assertTrue(text)
                    self.assertNotIn("{", text)
            self.assertNotIn("page_preferences_placeholder", STRINGS[lang])

    def test_setup_check_heading_replaces_profile_validation(self):
        self.assertEqual(STRINGS["en"]["setup_profile_section"], "Setup Check")
        self.assertEqual(STRINGS["zh"]["setup_profile_section"], "設定檢查")
        self.assertEqual(self.win.lbl_profile_section.text(), "SETUP CHECK")
        self.win.lang_combo.setCurrentIndex(self.win.lang_combo.findData("zh"))
        self.assertEqual(self.win.lbl_profile_section.text(), "設定檢查")

    def test_no_visible_mnemonic_markers_in_buttons_tabs_or_actions(self):
        from PySide6.QtGui import QAction
        from PySide6.QtWidgets import QAbstractButton, QTabWidget

        for lang in ("en", "zh"):
            self.win.lang_combo.setCurrentIndex(self.win.lang_combo.findData(lang))
            texts = [b.text() for b in self.win.findChildren(QAbstractButton)]
            texts += [a.text() for a in self.win.findChildren(QAction)]
            for tabs in self.win.findChildren(QTabWidget):
                texts += [tabs.tabText(i) for i in range(tabs.count())]
            for text in texts:
                with self.subTest(lang=lang, text=text):
                    self.assertNotIn("&", text.replace("&&", ""))
        self.win.lang_combo.setCurrentIndex(self.win.lang_combo.findData("en"))
        rendered = {
            self.win.btn_lock_profile: "Lock Profile & Continue",
            self.win.btn_edit_setup_new_run: "Edit Setup & New Run",
            self.win.btn_capture_edit_setup: "Edit Setup & New Run",
        }
        for button, visible in rendered.items():
            with self.subTest(button=visible):
                self.assertEqual(button.text().replace("&&", "&"), visible)

    # 17
    def test_capture_lifecycle_widgets_exist_once_on_capture(self):
        buttons = self.win.findChildren(QPushButton)
        for widget in (self.win.btn_arm, self.win.btn_stop, self.win.btn_edit_profile):
            with self.subTest(widget=widget.text()):
                self.assertEqual(buttons.count(widget), 1)
                self.assertTrue(_under(widget, self.win.page_capture))
        for widget in (
            self.win.btn_new, self.win.btn_generate_excel, self.win.btn_generate_html,
            self.win.btn_overlay, self.win.btn_clear_overlay,
        ):
            with self.subTest(widget=widget.text()):
                self.assertEqual(buttons.count(widget), 1)
                self.assertTrue(_under(widget, self.win.page_results))
        self.assertTrue(_under(self.win.btn_export, self.win.page_results))
        for widget in (self.win.test_area, self.win.scatter, self.win.interval_chart, self.win.review_text):
            self.assertTrue(_under(widget, self.win.page_capture))
        self.assertEqual(buttons.count(self.win.btn_lock_profile), 1)

    # 18
    def test_results_remains_placeholder(self):
        self.win.nav_results.click()
        self.assertEqual(self.win.results_placeholder.text(), self.win._tr("results_empty"))
        self.assertTrue(self.win.results_empty_card.isVisibleTo(self.win))
        self.assertFalse(_under(self.win.review_text, self.win.page_results))

    def test_rail_identity_keeps_product_name(self):
        self.assertEqual(self.win.brand_label.text(), "MCSA")
        self.assertEqual(self.win.title_label.text(), self.win._tr("app_title"))
        self.assertTrue(_under(self.win.brand_label, self.win.nav_rail))
        self.assertTrue(_under(self.win.title_label, self.win.nav_rail))


if __name__ == "__main__":
    unittest.main()
