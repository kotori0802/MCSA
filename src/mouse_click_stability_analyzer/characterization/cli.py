"""Characterization CLI. No admin rights. No network."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .analysis import analyze_campaign
from .manifest import ManifestError, load_manifest
from .report import write_outputs


def _print_issues(issues: list[dict], *, stream=None) -> None:
    stream = stream or sys.stdout
    if not issues:
        print("INFO\tno_issues\tmanifest parsed with no row issues", file=stream)
        return
    for item in issues:
        ident = item.get("run_id") or item.get("campaign_id") or ""
        print(f"{item['level']}\t{item['code']}\t{ident}\t{item['message']}", file=stream)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mouse_click_stability_analyzer.characterization",
        description=(
            "Offline Schedule Association Window characterization. "
            "Does not choose W and is not a DUT verdict."
        ),
    )
    parser.add_argument("--manifest", required=True, help="Lab manifest CSV")
    parser.add_argument(
        "--output",
        default="",
        help="Output directory for analyze (characterization_out/<campaign> recommended)",
    )
    parser.add_argument(
        "--mode",
        choices=("validate", "analyze"),
        default="analyze",
        help="validate prints issues only; analyze writes the characterization package",
    )
    args = parser.parse_args(argv)
    manifest_path = Path(args.manifest)
    try:
        rows, manifest_issues = load_manifest(manifest_path)
    except ManifestError as exc:
        print(f"ERROR\tmanifest\t{exc}", file=sys.stderr)
        return 1
    campaign = analyze_campaign(rows, manifest_issues=manifest_issues)
    _print_issues(campaign["issues"])
    if not campaign["has_characterization_evidence"]:
        print("INFO\tnot_characterization_evidence\tNOT CHARACTERIZATION EVIDENCE")
    print(f"INFO\teligible_runs\t{campaign['eligible_run_count']}")
    print(f"INFO\tpipeline_only_runs\t{campaign['pipeline_only_run_count']}")
    print(f"INFO\tunusable_runs\t{campaign['unusable_run_count']}")
    has_error = any(item["level"] == "ERROR" for item in campaign["issues"])
    if args.mode == "validate":
        return 1 if has_error else 0
    output = Path(args.output) if args.output else Path("characterization_out") / (
        campaign["campaign_ids"][0] if campaign["campaign_ids"] else "campaign"
    )
    paths = write_outputs(output, campaign, rows)
    print(f"INFO\toutput_dir\t{output}")
    for key, path in paths.items():
        print(f"INFO\tartifact_{key}\t{path}")
    return 1 if has_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
