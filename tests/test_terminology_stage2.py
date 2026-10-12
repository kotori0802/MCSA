"""Stage 2: canonical terminology references, aliases, and containment."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mouse_click_stability_analyzer.completed_result import (
    RUN_STATUS_COMPLETE,
    RUN_STATUS_INVALID,
    RUN_STATUS_NO_DATA,
    run_status_for_count,
)
from mouse_click_stability_analyzer.fixture_matching import (
    STATUS_AMBIGUOUS,
    STATUS_MATCHED,
    STATUS_OUTSIDE_CAPTURE_WINDOW,
    STATUS_UNMATCHED,
    match_fixture_press_observations,
)
from mouse_click_stability_analyzer.i18n import STRINGS, t
from mouse_click_stability_analyzer.strings.check import validate_resources
from mouse_click_stability_analyzer.strings.loader import (
    ALL_RESOURCE_FILES,
    KEY_ALIASES,
    TERMS,
    reload_string_tables,
    report_text,
    resolve_strings_root,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _prod_root() -> Path:
    return Path(str(resolve_strings_root()))


def _copy_prod(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    src = _prod_root()
    for name in ALL_RESOURCE_FILES:
        shutil.copy2(src / name, dest / name)


def _dump(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _issue_text(dest: Path) -> str:
    return "\n".join(str(i) for i in validate_resources(dest))


class TerminologyPropagationTests(unittest.TestCase):
    def test_one_source_propagation(self):
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw)
            _copy_prod(dest)
            payload = json.loads((dest / "terminology.json").read_text(encoding="utf-8"))
            payload["term.schedule_association_window"]["en"] = "Assoc Window Canonical"
            payload["term.schedule_association_window"]["zh-TW"] = "關聯範圍典範"
            _dump(dest / "terminology.json", payload)
            reload_string_tables(dest)
            try:
                self.assertEqual(t("en", "assoc_window"), "Assoc Window Canonical")
                self.assertEqual(t("en", "preview_timing_tolerance"), "Assoc Window Canonical")
                self.assertEqual(t("en", "tolerance"), "Assoc Window Canonical")
                self.assertEqual(
                    t("en", "fixture_timing_tolerance_ms"),
                    "Assoc Window Canonical (± ms)",
                )
                self.assertEqual(
                    report_text("report_label_schedule_association_window"),
                    "Assoc Window Canonical",
                )
                self.assertIn("Assoc Window Canonical ±{tol} ms", t("en", "he_config"))
            finally:
                reload_string_tables()

    def test_language_propagation(self):
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw)
            _copy_prod(dest)
            payload = json.loads((dest / "terminology.json").read_text(encoding="utf-8"))
            payload["term.host_observation"]["en"] = "Host Record EN"
            payload["term.host_observation"]["zh-TW"] = "主機紀錄 ZH"
            _dump(dest / "terminology.json", payload)
            reload_string_tables(dest)
            try:
                self.assertEqual(t("en", "legend_host_observation"), "Host Record EN")
                self.assertEqual(t("zh", "legend_host_observation"), "主機紀錄 ZH")
                self.assertEqual(report_text("report_legend_host_observation"), "Host Record EN")
            finally:
                reload_string_tables()

    def test_compound_term_reference_before_placeholders(self):
        text = t(
            "en",
            "he_config",
            hz="40",
            duration="10.000",
            tol="2.000",
            ref="25.000",
        )
        self.assertEqual(
            text,
            "Reference Rate 40 Hz · Capture Duration 10.000 s · "
            "Schedule Association Window ±2.000 ms · Configured reference interval 25.000 ms",
        )
        self.assertNotIn("{@", text)
        self.assertNotIn("{hz}", text)


class TerminologyValidatorTests(unittest.TestCase):
    def test_missing_term_fails(self):
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw)
            _copy_prod(dest)
            payload = json.loads((dest / "setup.json").read_text(encoding="utf-8"))
            payload["assoc_window"]["en"] = "{@term.does_not_exist}"
            _dump(dest / "setup.json", payload)
            text = _issue_text(dest)
            self.assertIn("missing term", text)
            self.assertTrue(any(i.level == "error" for i in validate_resources(dest)))

    def test_term_to_term_reference_fails(self):
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw)
            _copy_prod(dest)
            payload = json.loads((dest / "terminology.json").read_text(encoding="utf-8"))
            payload["term.hold"]["en"] = "{@term.interval}"
            _dump(dest / "terminology.json", payload)
            text = _issue_text(dest)
            self.assertIn("may not reference other terms", text)

    def test_canonical_redefinition_fails(self):
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw)
            _copy_prod(dest)
            payload = json.loads((dest / "setup.json").read_text(encoding="utf-8"))
            payload["assoc_window"]["en"] = "Schedule Association Window"
            payload["assoc_window"]["zh-TW"] = "排程關聯範圍"
            _dump(dest / "setup.json", payload)
            text = _issue_text(dest)
            self.assertIn("redefines canonical", text)

    def test_identical_unrelated_text_does_not_fail(self):
        issues = validate_resources()
        errors = [i.message for i in issues if i.level == "error"]
        self.assertEqual(errors, [])
        self.assertTrue(
            any("Identical English text" in i.message and "compare" in i.message for i in issues)
        )


class TerminologySemanticsTests(unittest.TestCase):
    def test_run_status_tokens_remain_machine_values(self):
        self.assertEqual(RUN_STATUS_COMPLETE, "COMPLETE")
        self.assertEqual(RUN_STATUS_NO_DATA, "NO_DATA")
        self.assertEqual(RUN_STATUS_INVALID, "INVALID")
        self.assertEqual(run_status_for_count(3, []), "COMPLETE")
        self.assertEqual(run_status_for_count(0, []), "NO_DATA")
        self.assertEqual(t("en", "run_status_complete"), "COMPLETE")
        self.assertEqual(t("zh", "run_status_complete"), "完成")

    def test_association_wording_does_not_change_matcher_output(self):
        before = match_fixture_press_observations(1, 10, 5, [0.0, 250.0])
        statuses = {row["status"] for row in before["observations"]}
        self.assertTrue(statuses <= {STATUS_MATCHED, STATUS_UNMATCHED, STATUS_AMBIGUOUS, STATUS_OUTSIDE_CAPTURE_WINDOW})
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw)
            _copy_prod(dest)
            payload = json.loads((dest / "terminology.json").read_text(encoding="utf-8"))
            payload["term.host_observations_unmatched"]["en"] = "Not associated"
            _dump(dest / "terminology.json", payload)
            reload_string_tables(dest)
            try:
                after = match_fixture_press_observations(1, 10, 5, [0.0, 250.0])
                self.assertEqual(after, before)
                self.assertEqual(t("en", "unmatched"), "Not associated")
            finally:
                reload_string_tables()

    def test_measurement_only_results_do_not_regain_legacy_legend_categories(self):
        self.assertEqual(STRINGS["en"]["legend_configured_reference"], "Reference interval")
        self.assertEqual(STRINGS["en"]["legend_host_observation"], "Host observation")
        self.assertEqual(STRINGS["en"]["legend_target"], "Target beat")
        self.assertNotEqual(STRINGS["en"]["legend_configured_reference"], STRINGS["en"]["legend_target"])
        self.assertEqual(STRINGS["en"]["legend_extra"], "Short interval")
        self.assertEqual(STRINGS["en"]["legend_chatter"], "Very short interval")
        self.assertEqual(STRINGS["en"]["legend_miss"], "Long interval")

    def test_alias_map_is_key_mapping_only(self):
        self.assertEqual(KEY_ALIASES, {"tolerance": "assoc_window"})
        for alias, target in KEY_ALIASES.items():
            self.assertTrue(alias.isidentifier())
            self.assertTrue(target.isidentifier())
            self.assertNotIn(" ", alias)
            self.assertNotIn(" ", target)
            self.assertEqual(t("en", alias), t("en", target))

    def test_page_specific_nav_stays_independent(self):
        self.assertEqual(t("en", "nav_results"), "Results")
        self.assertNotIn("nav_results", TERMS["en"])


if __name__ == "__main__":
    unittest.main()
