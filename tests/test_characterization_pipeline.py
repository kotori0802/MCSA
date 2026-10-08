"""4E-B1 manifest, eligibility, analysis, CLI, and report tests."""
from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mouse_click_stability_analyzer.characterization import analysis as analysis_module
from mouse_click_stability_analyzer.characterization.analysis import (
    ROLE_ELIGIBLE,
    ROLE_PIPELINE,
    ROLE_UNUSABLE,
    analyze_campaign,
    auto_stop_from_evidence,
)
from mouse_click_stability_analyzer.characterization.cli import main as char_main
from mouse_click_stability_analyzer.characterization.manifest import load_manifest
from mouse_click_stability_analyzer.characterization.report import contains_banned_copy, write_outputs

_REPO = Path(__file__).resolve().parents[1]


def _event(index: int, press_ms: float, *, accepted: bool = True, button: str = "Left") -> dict:
    return {
        "click_index": index,
        "index": index,
        "button": button,
        "accepted": accepted,
        "press_elapsed_ms": press_ms,
        "hold_ms": 40.0,
        "capture_source": "Windows Raw Input",
    }


def _settings(*, hz=5.0, duration=1.0, window=10.0, manual=False, extra=None) -> dict:
    payload = {
        "manual_mode": manual,
        "focus_button": "Left",
        "duration_sec": duration,
        "fixture_reference_hz": hz,
        "fixture_timing_tolerance_ms": window,
        "capture_mode": "Windows Raw Input",
    }
    if extra:
        payload.update(extra)
    return payload


def _write_evidence(root: Path, run_id: str, events: list[dict], settings: dict, **extra) -> Path:
    pkg = root / f"mcsa_{run_id}"
    pkg.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "MCSA_EVIDENCE_V1",
        "schema_version": "MCSA_EVIDENCE_V1",
        "tool_version": "1.0.0",
        "run_id": run_id,
        "run_status": extra.pop("run_status", "COMPLETE"),
        "analysis_scope": "measurement_only",
        "settings": settings,
        "events": events,
        "host_information": extra.pop("host_information", {
            "host_manufacturer": "TestCo",
            "host_model": extra.pop("host_model", "PC-A"),
            "capture_backend": "Windows Raw Input",
            "dut_usb_controller_attributed": False,
        }),
    }
    payload.update(extra)
    path = pkg / f"mcsa_{run_id}_evidence.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return pkg


def _manifest_row(run_id: str, package: Path, **overrides) -> dict:
    row = {
        "run_id": run_id,
        "package_path": str(package),
        "campaign_id": "lab-1",
        "purpose": "controlled characterization",
        "actuation_source": "physical_fixture",
        "characterization_eligible": True,
        "exclusion_reason": "",
        "fixture_vendor": "Vendor",
        "fixture_model": "FX-1",
        "fixture_unit_id": "unit-1",
        "fixture_firmware": "1.0",
        "control_dut_id": "DUT-A",
        "host_label": "host-a",
        "usb_port_label": "rear-1",
        "expected_rate_hz": 5.0,
        "expected_duration_sec": 1.0,
        "repeat_index": 1,
        "auto_stop_on": True,
        "notes": "",
        "vendor_timing_accuracy_ms": 0.5,
        "vendor_spec_reference": "spec-1",
        "source_line": 2,
        "package_path_raw": str(package),
    }
    row.update(overrides)
    return row


def _write_manifest_csv(path: Path, rows: list[dict]) -> None:
    fields = [
        "run_id", "package_path", "campaign_id", "purpose", "actuation_source",
        "characterization_eligible", "exclusion_reason", "host_label",
        "expected_rate_hz", "expected_duration_sec", "repeat_index", "auto_stop_on",
        "fixture_unit_id", "control_dut_id",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            out = dict(row)
            if isinstance(out.get("characterization_eligible"), bool):
                out["characterization_eligible"] = "yes" if out["characterization_eligible"] else "no"
            if isinstance(out.get("auto_stop_on"), bool):
                out["auto_stop_on"] = "yes" if out["auto_stop_on"] else "no"
            writer.writerow(out)


def _presses(*times: float) -> list[dict]:
    return [_event(i + 1, t) for i, t in enumerate(times)]


def _simulate_explicit_evidence_auto_stop(test: unittest.TestCase, value: bool | None) -> None:
    """MCSA_EVIDENCE_V1 has no explicit Auto Stop field; simulate one for eligible-path tests."""
    patcher = mock.patch.object(analysis_module, "auto_stop_from_evidence", return_value=value)
    patcher.start()
    test.addCleanup(patcher.stop)


class ManifestEligibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _simulate_explicit_evidence_auto_stop(self, True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_physical_eligible_yes_enters_aggregate(self):
        pkg = _write_evidence(self.root, "ok", _presses(0, 207, 396), _settings())
        campaign = analyze_campaign([_manifest_row("ok", pkg)])
        self.assertEqual(campaign["eligible_run_count"], 1)
        self.assertEqual(campaign["analyzed"][0]["role"], ROLE_ELIGIBLE)

    def test_human_eligible_yes_is_excluded_from_aggregate(self):
        pkg = _write_evidence(self.root, "human", _presses(0, 207), _settings())
        row = _manifest_row("human", pkg, actuation_source="human", characterization_eligible=True)
        campaign = analyze_campaign([row])
        self.assertEqual(campaign["eligible_run_count"], 0)
        self.assertEqual(campaign["analyzed"][0]["role"], ROLE_PIPELINE)
        self.assertTrue(any(i["code"] == "actuation_not_physical_fixture" for i in campaign["issues"]))
        self.assertGreater(campaign["analyzed"][0]["summary"]["analyzed_residual_count"], 0)

    def test_software_eligible_yes_is_excluded(self):
        pkg = _write_evidence(self.root, "sw", _presses(0, 200), _settings())
        row = _manifest_row("sw", pkg, actuation_source="software", characterization_eligible=True)
        campaign = analyze_campaign([row])
        self.assertEqual(campaign["eligible_run_count"], 0)

    def test_eligible_no_is_pipeline_only(self):
        pkg = _write_evidence(self.root, "no", _presses(0, 200), _settings())
        row = _manifest_row("no", pkg, characterization_eligible=False, exclusion_reason="pilot")
        campaign = analyze_campaign([row])
        self.assertEqual(campaign["eligible_run_count"], 0)
        self.assertEqual(campaign["analyzed"][0]["role"], ROLE_PIPELINE)

    def test_manual_mode_excluded(self):
        pkg = _write_evidence(self.root, "man", _presses(0, 200), _settings(manual=True))
        campaign = analyze_campaign([_manifest_row("man", pkg)])
        self.assertTrue(any(i["code"] == "manual_mode" for i in campaign["issues"]))
        self.assertNotEqual(campaign["analyzed"][0]["role"], ROLE_ELIGIBLE)

    def test_no_data_not_eligible(self):
        pkg = _write_evidence(self.root, "nd", _presses(0, 200), _settings(), run_status="NO_DATA")
        campaign = analyze_campaign([_manifest_row("nd", pkg)])
        self.assertNotEqual(campaign["analyzed"][0]["role"], ROLE_ELIGIBLE)

    def test_invalid_not_eligible(self):
        pkg = _write_evidence(self.root, "inv", _presses(0, 200), _settings(), run_status="INVALID")
        campaign = analyze_campaign([_manifest_row("inv", pkg)])
        self.assertNotEqual(campaign["analyzed"][0]["role"], ROLE_ELIGIBLE)

    def test_rate_mismatch_is_error(self):
        pkg = _write_evidence(self.root, "rate", _presses(0, 200), _settings(hz=10.0))
        row = _manifest_row("rate", pkg, expected_rate_hz=5.0)
        campaign = analyze_campaign([row])
        self.assertTrue(any(i["code"] == "reference_rate_mismatch" and i["level"] == "ERROR" for i in campaign["issues"]))

    def test_duration_mismatch_is_error(self):
        pkg = _write_evidence(self.root, "dur", _presses(0, 200), _settings(duration=2.0))
        row = _manifest_row("dur", pkg, expected_duration_sec=1.0)
        campaign = analyze_campaign([row])
        self.assertTrue(any(i["code"] == "duration_mismatch" and i["level"] == "ERROR" for i in campaign["issues"]))

    def test_stage2d_present_is_ignored(self):
        extra = {
            "interval_comparison_enabled": True,
            "interval_comparison_basis": "percent",
            "interval_comparison_value": 20.0,
        }
        pkg = _write_evidence(self.root, "s2d", _presses(0, 207, 396), _settings(extra=extra))
        campaign = analyze_campaign([_manifest_row("s2d", pkg)])
        self.assertTrue(any(i["code"] == "stage2d_ignored" for i in campaign["issues"]))
        self.assertEqual(campaign["eligible_run_count"], 1)

    def test_example_manifest_parses(self):
        example = _REPO / "docs" / "examples" / "characterization_manifest.example.csv"
        rows, issues = load_manifest(example)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["characterization_eligible"])
        self.assertEqual(rows[0]["actuation_source"], "human")
        self.assertFalse(any(i["level"] == "ERROR" for i in issues))


class ResidualContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _simulate_explicit_evidence_auto_stop(self, True)

    def tearDown(self):
        self.tmp.cleanup()

    def _analyze(self, times, **settings_kwargs):
        pkg = _write_evidence(self.root, "r1", _presses(*times), _settings(**settings_kwargs))
        return analyze_campaign([_manifest_row("r1", pkg)])["analyzed"][0]

    def test_anchor_is_t0_and_excluded_from_residuals(self):
        item = self._analyze([10.0, 217.0])
        self.assertEqual(item["summary"]["source_t0_ms"], 10.0)
        self.assertEqual(item["observations"][0]["t_rel_ms"], 0.0)
        self.assertTrue(item["observations"][0]["is_anchor"])
        self.assertFalse(item["observations"][0]["in_residual_sample"])
        self.assertEqual(item["summary"]["analyzed_residual_count"], 1)
        self.assertAlmostEqual(item["residuals"][0]["t_rel_ms"], 207.0)

    def test_observation_at_and_after_duration_excluded(self):
        item = self._analyze([0.0, 200.0, 1000.0, 1200.0], duration=1.0)
        self.assertEqual(item["summary"]["observation_outside_configured_window_count"], 2)
        times = [row["t_rel_ms"] for row in item["residuals"]]
        self.assertNotIn(1000.0, times)
        self.assertNotIn(1200.0, times)

    def test_same_slot_multiplicity_without_duplicate_label(self):
        item = self._analyze([0.0, 201.0, 202.0])
        occ = item["summary"]["occupancy"]
        self.assertGreaterEqual(occ["slots_with_multiple_observations"], 1)
        blob = json.dumps(item["summary"]["occupancy"])
        self.assertNotIn("duplicate", blob)
        self.assertNotIn("bounce", blob)
        self.assertIn("slots_with_multiple_observations", blob)

    def test_empty_slots_not_called_miss(self):
        item = self._analyze([0.0, 200.0], duration=1.0)
        occ = item["summary"]["occupancy"]
        self.assertGreater(occ["empty_slot_count"], 0)
        self.assertNotIn("miss", json.dumps(occ))

    def test_changing_w_leaves_primary_residuals_identical(self):
        times = (0.0, 207.0, 396.0)
        a = self._analyze(times, window=5.0)
        b_pkg = _write_evidence(self.root, "r2", _presses(*times), _settings(window=40.0))
        b = analyze_campaign([_manifest_row("r2", b_pkg, expected_rate_hz=5.0)])["analyzed"][0]
        ra = [(r["t_rel_ms"], r["wrapped_residual_ms"], r["nearest_slot_index"]) for r in a["residuals"]]
        rb = [(r["t_rel_ms"], r["wrapped_residual_ms"], r["nearest_slot_index"]) for r in b["residuals"]]
        self.assertEqual(ra, rb)
        self.assertNotEqual(
            a["summary"]["configured_association_window_ms"],
            b["summary"]["configured_association_window_ms"],
        )

    def test_changing_stage2d_leaves_residuals_identical(self):
        times = (0.0, 207.0, 396.0)
        a = self._analyze(times)
        extra = {
            "interval_comparison_enabled": True,
            "interval_comparison_basis": "milliseconds",
            "interval_comparison_value": 80.0,
        }
        pkg = _write_evidence(
            self.root, "cmp", _presses(*times), _settings(extra=extra),
            interval_comparison={"enabled": True, "lower_bound_ms": 120, "upper_bound_ms": 280},
        )
        b = analyze_campaign([_manifest_row("cmp", pkg)])["analyzed"][0]
        ra = [r["wrapped_residual_ms"] for r in a["residuals"]]
        rb = [r["wrapped_residual_ms"] for r in b["residuals"]]
        self.assertEqual(ra, rb)


class CrossRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _simulate_explicit_evidence_auto_stop(self, True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_grouping_uses_run_metrics_not_pooled_clicks(self):
        # Tight residual, many events.
        tight = [i * 200.0 + (1.0 if i else 0.0) for i in range(40)]
        # Wide residual, few events.
        wide_b = [0.0, 250.0]
        wide_c = [0.0, 250.0]
        rows = []
        for run_id, times, host in (("a", tight, "host-a"), ("b", wide_b, "host-a"), ("c", wide_c, "host-b")):
            pkg = _write_evidence(
                self.root, run_id, _presses(*times), _settings(), host_model=host,
            )
            rows.append(_manifest_row(run_id, pkg, host_label=host, repeat_index=len(rows) + 1))
        campaign = analyze_campaign(rows)
        self.assertEqual(campaign["eligible_run_count"], 3)
        p95s = [
            item["summary"]["absolute_residual"]["p95"]
            for item in campaign["analyzed"]
            if item["role"] == ROLE_ELIGIBLE
        ]
        self.assertEqual(len(p95s), 3)
        host_a = next(g for g in campaign["groups"] if g["group_kind"] == "rate_host" and g["host_label"] == "host-a")
        self.assertEqual(host_a["aggregation_unit"], "run")
        self.assertFalse(host_a["iid_event_bootstrap"])
        self.assertFalse(host_a["pooled_click_distribution"])
        # Two host-a runs: tiny p95 and ~50 ms p95. Median of run p95s is not click-weighted toward the long run.
        self.assertEqual(host_a["run_count"], 2)
        self.assertGreater(host_a["run_p95_absolute_residual_ms"]["range"], 20)
        cross = next(g for g in campaign["groups"] if g["group_kind"] == "rate_cross_host")
        self.assertIn("host-a", cross["hosts"])
        self.assertIn("host-b", cross["hosts"])

    def test_different_w_reported_without_changing_residuals(self):
        times = (0.0, 207.0)
        pkg_a = _write_evidence(self.root, "wa", _presses(*times), _settings(window=5.0))
        pkg_b = _write_evidence(self.root, "wb", _presses(*times), _settings(window=25.0))
        campaign = analyze_campaign([
            _manifest_row("wa", pkg_a, repeat_index=1),
            _manifest_row("wb", pkg_b, repeat_index=2),
        ])
        self.assertTrue(any(i["code"] == "association_window_varied" for i in campaign["issues"]))
        ra = [r["wrapped_residual_ms"] for r in campaign["analyzed"][0]["residuals"]]
        rb = [r["wrapped_residual_ms"] for r in campaign["analyzed"][1]["residuals"]]
        self.assertEqual(ra, rb)
        camp = next(g for g in campaign["groups"] if g["group_kind"] == "campaign")
        self.assertTrue(camp["association_window_varied"])


class CliReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_pipeline_pilot_cli_and_banned_language(self):
        pkg = _write_evidence(self.root, "pilot", _presses(0.0, 207.0, 396.0), _settings())
        manifest = self.root / "manifest.csv"
        _write_manifest_csv(manifest, [_manifest_row(
            "pilot", pkg,
            purpose="artifact pipeline pilot",
            actuation_source="human",
            characterization_eligible=False,
            exclusion_reason="hand actuation",
        )])
        out = self.root / "characterization_out" / "pilot"
        code = char_main(["--mode", "analyze", "--manifest", str(manifest), "--output", str(out)])
        self.assertEqual(code, 0)
        html = (out / "characterization_report.html").read_text(encoding="utf-8")
        self.assertIn("NOT CHARACTERIZATION EVIDENCE", html)
        data = json.loads((out / "characterization_analysis.json").read_text(encoding="utf-8"))
        self.assertIsNone(data["window_policy_decision"])
        self.assertFalse(data["has_characterization_evidence"])
        self.assertTrue(data["independent_of_association_window"])
        self.assertTrue(data["independent_of_configured_interval_range"])
        source_evidence = pkg / "mcsa_pilot_evidence.json"
        original = source_evidence.read_text(encoding="utf-8")
        self.assertEqual(json.loads(original)["run_id"], "pilot")
        for path in out.iterdir():
            text = path.read_text(encoding="utf-8", errors="replace")
            found = contains_banned_copy(text)
            self.assertEqual(found, [], msg=f"{path.name}: {found}")
            for token in ("DUT pass", "DUT fail", "optimal W", "best tolerance"):
                self.assertNotIn(token, text)
        residuals = list(csv.DictReader((out / "characterization_residuals.csv").open(encoding="utf-8-sig")))
        self.assertTrue(residuals)
        self.assertTrue(all(row["is_anchor"] == "no" for row in residuals))

    def _strings(self, node):
        if isinstance(node, dict):
            for value in node.values():
                yield from self._strings(value)
        elif isinstance(node, list):
            for value in node:
                yield from self._strings(value)
        elif isinstance(node, str):
            yield node

    def test_persisted_provenance_is_portable_for_relative_manifest_ref(self):
        reports = self.root / "reports"
        _write_evidence(reports, "rel", _presses(0.0, 207.0, 396.0), _settings())
        lab = self.root / "lab"
        lab.mkdir()
        manifest = lab / "manifest.csv"
        manifest.write_text(
            "run_id,package_path,campaign_id,purpose,actuation_source,characterization_eligible,"
            "exclusion_reason,expected_rate_hz,expected_duration_sec,auto_stop_on\n"
            "rel,../reports/mcsa_rel,tier0,artifact pipeline pilot,human,no,hand actuation,5,1,yes\n",
            encoding="utf-8",
        )
        manifest_before = manifest.read_text(encoding="utf-8")
        out = self.root / "characterization_out" / "tier0"
        self.assertEqual(char_main(["--mode", "validate", "--manifest", str(manifest)]), 0)
        self.assertEqual(char_main(["--mode", "analyze", "--manifest", str(manifest), "--output", str(out)]), 0)
        self.assertEqual(manifest.read_text(encoding="utf-8"), manifest_before)

        data = json.loads((out / "characterization_analysis.json").read_text(encoding="utf-8"))
        roots = {str(self.root), str(self.root.resolve()), str(Path.cwd()), str(_REPO)}
        for text in self._strings(data):
            for root in roots:
                self.assertNotIn(root, text)
                self.assertNotIn(root.replace("\\", "/"), text)
        self.assertNotIn("source_evidence_paths", data)
        self.assertEqual(data["manifest_rows"][0]["package_ref"], "../reports/mcsa_rel")
        self.assertNotIn("package_path", data["manifest_rows"][0])
        self.assertEqual(data["source_evidence_refs"], [{
            "run_id": "rel",
            "package_ref": "../reports/mcsa_rel",
            "evidence_file": "mcsa_rel_evidence.json",
        }])
        run = data["per_run"][0]
        self.assertNotIn("evidence_path", run)
        self.assertEqual(run["package_ref"], "../reports/mcsa_rel")
        self.assertEqual(run["evidence_file"], "mcsa_rel_evidence.json")
        self.assertIs(run["auto_stop_on_manifest"], True)
        self.assertIsNone(run["auto_stop_on_evidence"])
        self.assertEqual(run["role"], ROLE_PIPELINE)
        codes = {(i["code"], i["level"]) for i in data["issues"]}
        self.assertIn(("manifest_not_eligible", "EXCLUDED"), codes)
        self.assertIn(("auto_stop_evidence_unavailable", "INFO"), codes)
        self.assertFalse(any(i["level"] == "ERROR" for i in data["issues"]))
        self.assertEqual(data["unusable_run_count"], 0)
        self.assertEqual(data["eligible_run_count"], 0)
        self.assertIsNone(data["window_policy_decision"])
        self.assertEqual(data["groups"], [])
        self.assertGreater(run["analyzed_residual_count"], 0)

    def test_auto_stop_provenance_absent_is_not_synthesized(self):
        settings = _settings()
        del settings["duration_sec"]
        pkg = _write_evidence(self.root, "nodur", _presses(0.0, 200.0), settings)
        row = _manifest_row("nodur", pkg, auto_stop_on=None, expected_duration_sec=None)
        summary = analyze_campaign([row])["analyzed"][0]["summary"]
        self.assertIsNone(summary["auto_stop_on_manifest"])
        self.assertIsNone(summary["auto_stop_on_evidence"])

    def test_duration_sec_does_not_imply_evidence_auto_stop(self):
        for duration in (60.0, 0.0, None):
            settings = _settings(duration=duration)
            if duration is None:
                del settings["duration_sec"]
            payload = {"schema": "MCSA_EVIDENCE_V1", "settings": settings}
            self.assertIsNone(auto_stop_from_evidence(payload), msg=f"duration_sec={duration}")
        pkg = _write_evidence(self.root, "d60", _presses(0.0, 200.0), _settings(duration=60.0))
        row = _manifest_row("d60", pkg, actuation_source="human", characterization_eligible=False,
                            expected_duration_sec=60.0)
        summary = analyze_campaign([row])["analyzed"][0]["summary"]
        self.assertIsNone(summary["auto_stop_on_evidence"])

    def test_eligible_physical_with_unverifiable_evidence_auto_stop_is_error(self):
        pkg = _write_evidence(self.root, "unv", _presses(0.0, 207.0, 396.0), _settings())
        campaign = analyze_campaign([_manifest_row("unv", pkg, auto_stop_on=True)])
        found = [i for i in campaign["issues"] if i["code"] == "auto_stop_unverifiable"]
        self.assertEqual([i["level"] for i in found], ["ERROR"])
        self.assertEqual(campaign["eligible_run_count"], 0)
        self.assertEqual(campaign["analyzed"][0]["role"], ROLE_UNUSABLE)
        summary = campaign["analyzed"][0]["summary"]
        self.assertIs(summary["auto_stop_on_manifest"], True)
        self.assertIsNone(summary["auto_stop_on_evidence"])

    def test_eligible_physical_manifest_auto_stop_off_is_error(self):
        pkg = _write_evidence(self.root, "off", _presses(0.0, 200.0), _settings())
        campaign = analyze_campaign([_manifest_row("off", pkg, auto_stop_on=False)])
        self.assertTrue(any(
            i["code"] == "auto_stop_off" and i["level"] == "ERROR" for i in campaign["issues"]
        ))
        self.assertEqual(campaign["eligible_run_count"], 0)

    def test_explicit_evidence_auto_stop_true_matches_manifest(self):
        _simulate_explicit_evidence_auto_stop(self, True)
        pkg = _write_evidence(self.root, "ok", _presses(0.0, 207.0, 396.0), _settings())
        campaign = analyze_campaign([_manifest_row("ok", pkg, auto_stop_on=True)])
        self.assertFalse(any(i["code"].startswith("auto_stop") for i in campaign["issues"]))
        self.assertEqual(campaign["eligible_run_count"], 1)
        self.assertIs(campaign["analyzed"][0]["summary"]["auto_stop_on_evidence"], True)

    def test_explicit_evidence_auto_stop_false_is_mismatch_for_eligible_physical(self):
        _simulate_explicit_evidence_auto_stop(self, False)
        pkg = _write_evidence(self.root, "asm", _presses(0.0, 200.0), _settings())
        campaign = analyze_campaign([_manifest_row("asm", pkg, auto_stop_on=True)])
        mismatch = [i for i in campaign["issues"] if i["code"] == "auto_stop_mismatch"]
        self.assertEqual([i["level"] for i in mismatch], ["ERROR"])
        self.assertEqual(campaign["eligible_run_count"], 0)
        summary = campaign["analyzed"][0]["summary"]
        self.assertIs(summary["auto_stop_on_manifest"], True)
        self.assertIs(summary["auto_stop_on_evidence"], False)

    def test_validate_reports_missing_evidence(self):
        manifest = self.root / "manifest.csv"
        _write_manifest_csv(manifest, [_manifest_row("missing", self.root / "no-such-package")])
        code = char_main(["--mode", "validate", "--manifest", str(manifest)])
        self.assertEqual(code, 1)

    def test_write_outputs_does_not_touch_report_package(self):
        pkg = _write_evidence(self.root, "keep", _presses(0.0, 200.0), _settings())
        marker = pkg / "mcsa_keep_report.html"
        marker.write_text("field-test-package", encoding="utf-8")
        campaign = analyze_campaign([_manifest_row("keep", pkg)])
        write_outputs(self.root / "out", campaign, [_manifest_row("keep", pkg)])
        self.assertEqual(marker.read_text(encoding="utf-8"), "field-test-package")
        self.assertFalse((pkg / "characterization_report.html").exists())


if __name__ == "__main__":
    unittest.main()
