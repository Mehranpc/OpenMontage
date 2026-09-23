"""Reproducible P0 baseline collector for the Persian footage pipeline.

The harness records observations; it does not claim an improvement or enforce the
future performance target. Real runs remain external and their completed JSON
observations are summarized deterministically into JSON and Markdown.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

BRIEFS_DIR = Path(__file__).with_name("persian_baseline_briefs")
PHASES = ("idea", "script", "scene_plan", "acquire_assets", "edit", "compose")


@dataclass(frozen=True)
class BaselineRow:
    brief_id: str
    revision: str
    cache_state: str
    wall_seconds: float
    phase_seconds: dict[str, float]
    interphase_seconds: float
    prompt_text_bytes: int
    temporary_script_count: int
    render_count: int
    critical_blockers: int
    quality_disposition: str


def _timestamp(value: str) -> datetime:
    if not value:
        raise ValueError("completed observations require non-empty timestamps")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include an explicit UTC offset")
    return parsed


def _duration(span: dict[str, Any]) -> float:
    seconds = (_timestamp(span["ended_at"]) - _timestamp(span["started_at"])).total_seconds()
    if seconds < 0:
        raise ValueError("span ended before it started")
    return round(seconds, 3)


def load_briefs(directory: Path = BRIEFS_DIR) -> list[dict[str, Any]]:
    briefs = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*.json"))]
    ids = [brief.get("id") for brief in briefs]
    if len(briefs) != 3 or len(set(ids)) != 3:
        raise ValueError("P0 requires exactly three uniquely identified Persian briefs")
    if "first-date-first-text" not in ids:
        raise ValueError("P0 briefs must include first-date-first-text")
    for brief in briefs:
        if brief.get("schema_version") != 1:
            raise ValueError(f"{brief.get('id')}: unsupported brief schema")
        if brief.get("language") != "fa" or not str(brief.get("request_fa") or "").strip():
            raise ValueError(f"{brief.get('id')}: expected a non-empty Persian request")
        if brief.get("cache_state") != "cold":
            raise ValueError(f"{brief.get('id')}: P0 baseline briefs must be cold-cache")
        if brief.get("render_runtime") != "remotion" or brief.get("active_profile") != "film-type-2.16":
            raise ValueError(f"{brief.get('id')}: baseline runtime/profile drift")
    return briefs


def observation_template(brief: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "pending",
        "brief_id": brief["id"],
        "revision": "",
        "cache_state": "cold",
        "run_started_at": "",
        "awaiting_human_at": "",
        "phase_spans": [
            {"phase": phase, "started_at": "", "ended_at": ""} for phase in PHASES
        ],
        "interphase_spans": [],
        "prompt_text_bytes": 0,
        "temporary_scripts": [],
        "renders": [],
        "runtime_metadata": {
            "os": "", "hardware": "", "python": "", "node": "", "remotion": ""
        },
        "quality_snapshot": {"critical_blockers": 0, "quality_disposition": ""},
        "notes": [],
    }


def summarize_observation(observation: dict[str, Any], brief_ids: set[str]) -> BaselineRow:
    if observation.get("schema_version") != 1 or observation.get("status") != "completed":
        raise ValueError("only completed schema-v1 observations can enter the baseline")
    brief_id = str(observation.get("brief_id") or "")
    if brief_id not in brief_ids:
        raise ValueError(f"unknown baseline brief: {brief_id}")
    if observation.get("cache_state") != "cold":
        raise ValueError(f"{brief_id}: observation is not cold-cache")
    revision = str(observation.get("revision") or "")
    if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision.lower()):
        raise ValueError(f"{brief_id}: revision must be a full Git SHA")

    spans = observation.get("phase_spans") or []
    phase_names = [span.get("phase") for span in spans]
    if phase_names != list(PHASES):
        raise ValueError(f"{brief_id}: phase spans must follow the canonical order")
    phase_seconds = {str(span["phase"]): _duration(span) for span in spans}
    interphase_seconds = round(sum(_duration(span) for span in observation.get("interphase_spans") or []), 3)
    wall_seconds = round(
        (_timestamp(observation["awaiting_human_at"]) - _timestamp(observation["run_started_at"])).total_seconds(),
        3,
    )
    if wall_seconds < 0:
        raise ValueError(f"{brief_id}: awaiting_human precedes run start")

    prompt_bytes = observation.get("prompt_text_bytes")
    if not isinstance(prompt_bytes, int) or prompt_bytes < 0:
        raise ValueError(f"{brief_id}: prompt_text_bytes must be a non-negative integer")
    temporary_scripts = observation.get("temporary_scripts") or []
    renders = observation.get("renders") or []
    if not isinstance(temporary_scripts, list) or not isinstance(renders, list):
        raise ValueError(f"{brief_id}: temporary_scripts and renders must be lists")
    runtime = observation.get("runtime_metadata") or {}
    if any(not str(runtime.get(key) or "").strip() for key in ("os", "hardware", "python", "node", "remotion")):
        raise ValueError(f"{brief_id}: runtime metadata is incomplete")
    quality = observation.get("quality_snapshot") or {}
    blockers = quality.get("critical_blockers")
    if not isinstance(blockers, int) or blockers < 0:
        raise ValueError(f"{brief_id}: critical_blockers must be a non-negative integer")

    return BaselineRow(
        brief_id=brief_id,
        revision=revision,
        cache_state="cold",
        wall_seconds=wall_seconds,
        phase_seconds=phase_seconds,
        interphase_seconds=interphase_seconds,
        prompt_text_bytes=prompt_bytes,
        temporary_script_count=len(set(map(str, temporary_scripts))),
        render_count=len(renders),
        critical_blockers=blockers,
        quality_disposition=str(quality.get("quality_disposition") or ""),
    )


def build_report(briefs: list[dict[str, Any]], observations: Iterable[dict[str, Any]]) -> dict[str, Any]:
    brief_ids = {brief["id"] for brief in briefs}
    rows = sorted(
        (summarize_observation(observation, brief_ids) for observation in observations),
        key=lambda row: row.brief_id,
    )
    if {row.brief_id for row in rows} != brief_ids or len(rows) != 3:
        raise ValueError("baseline report requires one completed observation for every fixed brief")
    revisions = {row.revision for row in rows}
    if len(revisions) != 1:
        raise ValueError("all baseline observations must use the same exact Git revision")
    return {
        "schema_version": 1,
        "baseline_only": True,
        "improvement_claimed": False,
        "revision": next(iter(revisions)),
        "brief_count": 3,
        "rows": [asdict(row) for row in rows],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Persian pipeline P0 baseline",
        "",
        "> Measurement only. This table makes no performance-improvement claim.",
        "",
        f"Revision: `{report['revision']}`  ",
        "Cache state: `cold`",
        "",
        "| Brief | Wall s | Interphase s | Prompt bytes | Temp scripts | Renders | Critical blockers | Disposition |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in report["rows"]:
        lines.append(
            f"| {row['brief_id']} | {row['wall_seconds']:.3f} | {row['interphase_seconds']:.3f} | "
            f"{row['prompt_text_bytes']} | {row['temporary_script_count']} | {row['render_count']} | "
            f"{row['critical_blockers']} | {row['quality_disposition']} |"
        )
    lines.extend(["", "## Phase seconds", ""])
    lines.append("| Brief | " + " | ".join(PHASES) + " |")
    lines.append("|---|" + "---:|" * len(PHASES))
    for row in report["rows"]:
        values = " | ".join(f"{row['phase_seconds'][phase]:.3f}" for phase in PHASES)
        lines.append(f"| {row['brief_id']} | {values} |")
    return "\n".join(lines) + "\n"


def _load_observations(directory: Path) -> list[dict[str, Any]]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*.json"))]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect the three-brief Persian P0 baseline")
    parser.add_argument("--briefs-dir", type=Path, default=BRIEFS_DIR)
    parser.add_argument("--validate-briefs", action="store_true")
    parser.add_argument("--emit-templates", type=Path)
    parser.add_argument("--observations-dir", type=Path)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args(argv)

    briefs = load_briefs(args.briefs_dir)
    if args.emit_templates:
        args.emit_templates.mkdir(parents=True, exist_ok=True)
        for brief in briefs:
            target = args.emit_templates / f"{brief['id']}.json"
            target.write_text(json.dumps(observation_template(brief), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.validate_briefs and not args.observations_dir:
        print(json.dumps({"valid": True, "brief_ids": sorted(brief["id"] for brief in briefs)}))
        return 0
    if not args.observations_dir:
        parser.error("--observations-dir is required unless only --validate-briefs is used")

    report = build_report(briefs, _load_observations(args.observations_dir))
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    markdown = render_markdown(report)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(markdown, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
