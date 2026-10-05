"""Phase 4D-2g-1: EN/zh-TW locales, Hz→ms reference normalization, typography tokens."""
from __future__ import annotations

import math
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

from PySide6.QtWidgets import QLabel

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mouse_click_stability_analyzer.cadence import cadence_ms
from mouse_click_stability_analyzer.i18n import (
    LANG_LABELS,
    STRINGS,
    SUPPORTED_LANGS,
    normalize_lang,
    t,
)
from mouse_click_stability_analyzer.measurements import (
    reference_interval_ms,
    reference_interval_ms_or_none,
)
from mouse_click_stability_analyzer.qt_shell import app as qt_app
from mouse_click_stability_analyzer.qt_shell import styles
from mouse_click_stability_analyzer.qt_shell.app import (
    format_reference_interval_ms,
    format_reference_rate_hz,
    post_run_quiet_ms,
    setup_reference_interval_ms,
)

_REMOVED_LANGS = ("fr", "it", "de", "es", "ja", "ko")

_REQUIRED_UI_KEYS = (
    "arm_capture",
    "disarm_capture",
    "run_status",
    "run_status_complete",
    "run_status_no_data",
    "run_status_invalid",
    "chart_stability_map",
    "chart_stability_map_subtitle",
    "chart_stability_map_subtitle_fixture",
    "chart_interval_trend",
    "viz_stability_map",
    "viz_interval_trend",
    "viz_fit_data",
    "viz_zoom_in",
    "viz_zoom_out",
    "viz_reset_view",
    "legend_configured_reference",
    "assoc_reference_interval",
    "assoc_window",
    "assoc_relative",
    "assoc_overlap",
    "assoc_yes",
    "assoc_no",
    "assoc_overlap_note",
    "assoc_derived_note",
    "test_area_hint_ready_manual",
    "test_area_hint_ready_fixture",
    "test_area_hint_armed_manual",
    "test_area_hint_armed_fixture",
    "status_ready_manual",
    "status_ready_fixture",
    "new_run",
    "nav_results",
    "edit_setup_new_run",
    "reference_rate_hz",
    "reference_interval_derived",
    "mode_fixture",
    "display_language",
    "screening",
    "screening_measurement_only",
    "screening_measurement_only_note",
    "legend_on_cadence",
    "legend_extra",
    "legend_chatter",
    "legend_miss",
    "legend_rebound",
)

_CONVERSIONS = (
    (0.5, 2000.0),
    (1, 1000.0),
    (2, 500.0),
    (6, 1000.0 / 6.0),
    (10, 100.0),
    (20, 50.0),
    (40, 25.0),
)


def _make_qapp():
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:  # pragma: no cover
        return None
    return QApplication.instance() or QApplication([])


class SupportedLanguageTests(unittest.TestCase):
    def test_supported_locales_are_exactly_english_and_traditional_chinese(self):
        self.assertEqual(SUPPORTED_LANGS, ("en", "zh"))
        self.assertEqual(set(STRINGS), {"en", "zh"})
        self.assertEqual(LANG_LABELS, {"en": "English", "zh": "繁體中文"})

    def test_removed_locales_are_not_selectable(self):
        for code in _REMOVED_LANGS:
            with self.subTest(code=code):
                self.assertNotIn(code, SUPPORTED_LANGS)
                self.assertNotIn(code, LANG_LABELS)

    def test_legacy_and_unknown_locales_normalize_to_english(self):
        for value in (*_REMOVED_LANGS, "DE", "ja_JP", "pt", "", "   ", None, 7, "zh-CN"):
            with self.subTest(value=value):
                self.assertEqual(normalize_lang(value), "en")

    def test_traditional_chinese_aliases_normalize_to_zh(self):
        for value in ("zh", "ZH", "zh-TW", "zh_TW", "zh-Hant", " zh-hant-tw "):
            with self.subTest(value=value):
                self.assertEqual(normalize_lang(value), "zh")

    def test_translate_with_legacy_locale_falls_back_to_english_text(self):
        for code in _REMOVED_LANGS:
            with self.subTest(code=code):
                self.assertEqual(t(code, "arm_capture"), STRINGS["en"]["arm_capture"])
                self.assertNotEqual(t(code, "arm_capture"), "arm_capture")

    def test_required_keys_exist_and_are_nonblank_in_both_languages(self):
        for lang in SUPPORTED_LANGS:
            for key in _REQUIRED_UI_KEYS:
                with self.subTest(lang=lang, key=key):
                    self.assertTrue(str(STRINGS[lang].get(key) or "").strip())

    def test_both_tables_share_keys_and_placeholders(self):
        en, zh = STRINGS["en"], STRINGS["zh"]
        self.assertEqual(set(en), set(zh))
        for key in en:
            with self.subTest(key=key):
                self.assertEqual(
                    set(re.findall(r"\{(\w+)\}", en[key])),
                    set(re.findall(r"\{(\w+)\}", zh[key])),
                )

    def test_zh_table_is_traditional_for_core_capture_terms(self):
        zh = STRINGS["zh"]
        self.assertEqual(zh["arm_capture"], "開始擷取")
        self.assertEqual(zh["disarm_capture"], "取消開始")
        self.assertEqual(zh["chart_stability_map"], "點擊穩定度圖")
        self.assertEqual(zh["assoc_window"], "排程關聯範圍")
        self.assertNotIn("视窗", "".join(zh.values()))


class ReferenceConversionTests(unittest.TestCase):
    def test_canonical_rate_to_interval(self):
        for hz, expected in _CONVERSIONS:
            with self.subTest(hz=hz):
                self.assertEqual(reference_interval_ms(hz), expected)
                self.assertEqual(reference_interval_ms_or_none(hz), expected)

    def test_six_hz_keeps_full_precision(self):
        value = reference_interval_ms(6)
        self.assertEqual(value, 1000.0 / 6.0)
        self.assertNotEqual(value, 166.67)
        self.assertEqual(format_reference_interval_ms(value), "166.67")

    def test_invalid_rates_never_produce_inf_or_nan(self):
        for raw in (None, 0, -1, math.inf, -math.inf, math.nan, "6", True):
            with self.subTest(raw=raw):
                self.assertIsNone(reference_interval_ms_or_none(raw))
        for raw in ("", "  ", "abc", "0", "-3", "inf", "nan", None):
            with self.subTest(setup_raw=raw):
                self.assertIsNone(setup_reference_interval_ms(raw))
                self.assertEqual(format_reference_interval_ms(setup_reference_interval_ms(raw)), "—")

    def test_setup_parse_matches_canonical_helper(self):
        for hz, expected in _CONVERSIONS:
            with self.subTest(hz=hz):
                self.assertEqual(setup_reference_interval_ms(str(hz)), expected)

    def test_runtime_cadence_reuses_canonical_conversion(self):
        for hz, expected in _CONVERSIONS:
            with self.subTest(hz=hz):
                settings = {"fixture_reference_hz": float(hz), "fixture_hz": float(hz)}
                self.assertEqual(cadence_ms(settings), expected)
        self.assertIsNone(cadence_ms({"fixture_reference_hz": 0.0}))
        self.assertIsNone(cadence_ms({}))

    def test_post_run_quiet_period_unchanged_for_six_hz(self):
        settings = {"manual_mode": False, "profile_name": "Fixture_Custom", "fixture_reference_hz": 6.0}
        expected = max(int(qt_app.POST_RUN_INPUT_QUIET_MS), int(round(qt_app.POST_RUN_QUIET_INTERVALS * (1000.0 / 6.0))))
        self.assertEqual(post_run_quiet_ms(settings), expected)

    def test_rate_formatting_is_presentation_only(self):
        self.assertEqual(format_reference_rate_hz(6.0), "6")
        self.assertEqual(format_reference_rate_hz(0.5), "0.5")
        self.assertEqual(format_reference_rate_hz(0.0), "—")
        self.assertEqual(format_reference_interval_ms(100.0), "100.00")
        self.assertEqual(format_reference_interval_ms(math.nan), "—")


class TypographyTokenTests(unittest.TestCase):
    def test_every_theme_and_density_resolves_all_tokens(self):
        for theme in ("light", "dark"):
            for density in styles.DENSITIES:
                with self.subTest(theme=theme, density=density):
                    sheet = styles.get_style(theme, density)
                    self.assertNotIn("@FS_", sheet)
                    self.assertNotIn("@PAD_", sheet)
                    self.assertNotIn("@FONT_", sheet)
                    self.assertIn("Microsoft JhengHei UI", sheet)
                    self.assertNotIn(".ttf", sheet)
                    self.assertNotIn(".otf", sheet)

    def test_compact_tier_never_grows_text_and_keeps_body_readable(self):
        normal = styles.TYPE_SCALE[styles.DENSITY_NORMAL]
        compact = styles.TYPE_SCALE[styles.DENSITY_COMPACT]
        self.assertEqual(set(normal), set(compact))
        for role in normal:
            with self.subTest(role=role):
                self.assertLessEqual(compact[role], normal[role])
        self.assertGreaterEqual(compact["body"], 12)
        hierarchy = ("page_title", "section_title", "metric", "body", "label", "caption")
        for density in styles.DENSITIES:
            sizes = [styles.type_px(role, density) for role in hierarchy]
            self.assertEqual(sizes, sorted(sizes, reverse=True), density)

    def test_density_tiers_follow_window_presets(self):
        self.assertEqual(styles.density_for_size(1280, 720), styles.DENSITY_COMPACT)
        self.assertEqual(styles.density_for_size(1366, 768), styles.DENSITY_COMPACT)
        self.assertEqual(styles.density_for_size(1024, 640), styles.DENSITY_COMPACT)
        self.assertEqual(styles.density_for_size(1440, 810), styles.DENSITY_NORMAL)
        self.assertEqual(styles.density_for_size(1600, 900), styles.DENSITY_NORMAL)
        self.assertEqual(styles.density_for_size(1920, 1080), styles.DENSITY_NORMAL)
        self.assertEqual(set(styles.DENSITIES), {"normal", "compact"})


class QtLanguageAndSetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._qapp = _make_qapp()
        if cls._qapp is None:
            raise unittest.SkipTest("PySide6 QApplication unavailable")
        cls._tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _window(self, lang: str = "en"):
        win = qt_app.MainWindow(report_root=Path(self._tmp.name), lang=lang)
        win._listen_start_timer.stop()
        win.ui_timer.stop()
        win.ensure_raw_input = lambda: None
        self.addCleanup(self._close, win)
        return win

    def _close(self, win):
        win.close()
        win.deleteLater()
        self._qapp.processEvents()

    def test_language_selector_offers_only_english_and_traditional_chinese(self):
        win = self._window()
        combo = win.lang_combo
        self.assertEqual([combo.itemData(i) for i in range(combo.count())], ["en", "zh"])
        self.assertEqual([combo.itemText(i) for i in range(combo.count())], ["English", "繁體中文"])

    def test_legacy_stored_locale_starts_in_english_without_blank_keys(self):
        for code in (*_REMOVED_LANGS, "xx", ""):
            with self.subTest(code=code):
                win = self._window(code)
                self.assertEqual(win.lang, "en")
                self.assertEqual(win.lang_combo.currentData(), "en")
                self.assertEqual(win.btn_arm.text(), STRINGS["en"]["arm_capture"])
                self.assertEqual(win.hz_label.text(), STRINGS["en"]["reference_rate_hz"])

    def test_selecting_traditional_chinese_updates_capture_and_setup(self):
        win = self._window()
        win.lang_combo.setCurrentIndex(win.lang_combo.findData("zh"))
        self.assertEqual(win.lang, "zh")
        self.assertEqual(win.btn_arm.text(), STRINGS["zh"]["arm_capture"])
        self.assertEqual(win.btn_view_stability.text(), STRINGS["zh"]["viz_stability_map"])
        self.assertEqual(win.btn_chart_fit.text(), STRINGS["zh"]["viz_fit_data"])
        self.assertEqual(win.btn_chart_reset.text(), STRINGS["zh"]["viz_reset_view"])
        self.assertEqual(win.scatter.title, STRINGS["zh"]["chart_stability_map"])
        win.lang_combo.setCurrentIndex(win.lang_combo.findData("en"))
        self.assertEqual(win.btn_arm.text(), STRINGS["en"]["arm_capture"])

    def test_run_status_display_localizes_without_changing_token(self):
        win = self._window("zh")
        self.assertEqual(win._run_status_display("COMPLETE"), "完成")
        self.assertEqual(win._run_status_display("NO_DATA"), "無資料")
        self.assertEqual(win._run_status_display("INVALID"), "無效")
        self.assertEqual(win._run_status_display("--"), "--")
        en = self._window("en")
        for token in ("COMPLETE", "NO_DATA", "INVALID"):
            self.assertEqual(en._run_status_display(token), token)

    def _fixture(self, win, hz: str):
        win.radio_fixture.setChecked(True)
        win.hz_combo.setCurrentText(hz)
        win.timing_tol_edit.setText("2")
        win.auto_stop_off.setChecked(True)

    def test_setup_shows_derived_interval_for_rate(self):
        win = self._window()
        self._fixture(win, "6")
        self.assertEqual(win.hz_interval_label.text(), "= 166.67 ms interval")
        win.hz_combo.setCurrentText("10")
        self.assertEqual(win.hz_interval_label.text(), "= 100.00 ms interval")
        win.hz_combo.setCurrentText("0.5")
        self.assertEqual(win.hz_interval_label.text(), "= 2000.00 ms interval")

    def test_derived_interval_is_read_only_label(self):
        win = self._window()
        self._fixture(win, "6")
        label = win.hz_interval_label
        self.assertIsInstance(label, QLabel)
        self.assertEqual(label.textInteractionFlags(), qt_app.Qt.TextInteractionFlag.NoTextInteraction)
        self.assertEqual(label.focusPolicy(), qt_app.Qt.FocusPolicy.NoFocus)

    def test_derived_interval_invalid_rate_is_safe(self):
        win = self._window()
        self._fixture(win, "6")
        for raw in ("", "abc", "0", "-2", "inf", "nan"):
            with self.subTest(raw=raw):
                win.hz_combo.setCurrentText(raw)
                text = win.hz_interval_label.text()
                self.assertIn("—", text)
                self.assertNotIn("inf", text.lower())
                self.assertNotIn("nan", text.lower())

    def test_manual_hides_fixture_reference_interval(self):
        win = self._window()
        win.show()
        self._qapp.processEvents()
        self._fixture(win, "6")
        win._show_workflow_page("setup")
        self._qapp.processEvents()
        self.assertTrue(win.hz_interval_label.isVisibleTo(win))
        win.radio_manual.setChecked(True)
        self._qapp.processEvents()
        self.assertFalse(win.hz_interval_label.isVisibleTo(win))
        self.assertFalse(win.hz_combo.isVisibleTo(win))
        self.assertEqual(win.mode_label.text(), win._tr("mode_manual"))

    def test_derived_interval_follows_language(self):
        win = self._window()
        self._fixture(win, "6")
        win.lang_combo.setCurrentIndex(win.lang_combo.findData("zh"))
        self.assertEqual(win.hz_interval_label.text(), "= 間隔 166.67 ms")

    def test_profile_lock_stores_only_canonical_rate(self):
        win = self._window()
        self._fixture(win, "6")
        self.assertTrue(win.lock_profile())
        locked = win.profile_locked_settings
        self.assertEqual(locked["fixture_reference_hz"], 6.0)
        self.assertEqual(locked["fixture_hz"], 6.0)
        self.assertNotIn("reference_interval_ms", locked)
        self.assertNotIn("fixture_interval_ms", locked)
        self.assertNotIn(166.67, list(locked.values()))
        self.assertEqual(cadence_ms(locked), 1000.0 / 6.0)

    def test_six_hz_capture_uses_full_precision_reference(self):
        win = self._window()
        self._fixture(win, "6")
        self.assertTrue(win.lock_profile())
        win._refresh_metrics()
        self.assertEqual(win.scatter.target_beat_ms, 1000.0 / 6.0)
        self.assertEqual(win.interval_chart.target_beat_ms, 1000.0 / 6.0)
        self.assertIn("166.67 ms", win.scatter.subtitle)
        self.assertIn("6 Hz", win.scatter.subtitle)
        self.assertLess(win.scatter.subtitle.index("166.67 ms"), win.scatter.subtitle.index("6 Hz"))
        self.assertIn("166.67 ms", win.mode_label.text())
        self.assertLess(win.mode_label.text().index("ms"), win.mode_label.text().index("Hz"))

    def test_capture_axes_stay_in_milliseconds(self):
        win = self._window()
        labels = win._chart_labels()
        self.assertEqual(labels["axis_interval_ms"], "Interval (ms)")
        self.assertEqual(labels["axis_hold_ms"], "Hold (ms)")
        zh = self._window("zh")._chart_labels()
        self.assertIn("ms", zh["axis_interval_ms"])
        self.assertIn("ms", zh["axis_hold_ms"])

    def test_manual_capture_has_no_reference(self):
        win = self._window()
        win.radio_manual.setChecked(True)
        self.assertTrue(win.lock_profile())
        win._refresh_metrics()
        self.assertIsNone(win.scatter.target_beat_ms)
        self.assertIsNone(win.interval_chart.target_beat_ms)
        self.assertNotIn("Hz", win.scatter.subtitle)


if __name__ == "__main__":
    unittest.main()
