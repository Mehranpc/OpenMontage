import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests.eval.persian_baseline import PHASES, build_report, load_briefs, render_markdown


def _observation(brief_id: str, revision: str = "a" * 40) -> dict:
    start = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    cursor = start
    phase_spans = []
    for index, phase in enumerate(PHASES, start=1):
        end = cursor + timedelta(seconds=index * 10)
        phase_spans.append({"phase": phase, "started_at": cursor.isoformat(), "ended_at": end.isoformat()})
        cursor = end
    return {
        "schema_version": 1,
        "status": "completed",
        "brief_id": brief_id,
        "revision": revision,
        "cache_state": "cold",
        "run_started_at": start.isoformat(),
        "awaiting_human_at": cursor.isoformat(),
        "phase_spans": phase_spans,
        "interphase_spans": [{"from_phase": "idea", "to_phase": "script", "started_at": start.isoformat(), "ended_at": (start + timedelta(seconds=3)).isoformat()}],
        "prompt_text_bytes": 1234,
        "temporary_scripts": [".workspace/one.py", ".workspace/one.py"],
        "renders": [{"kind": "candidate", "output_path": "renders/final.mp4"}],
        "runtime_metadata": {"os": "macOS", "hardware": "Apple Silicon", "python": "3.13", "node": "24", "remotion": "4"},
        "quality_snapshot": {"critical_blockers": 0, "quality_disposition": "awaiting_human"},
    }


def test_fixed_persian_briefs_are_complete_and_cold_cache():
    briefs = load_briefs()
    assert sorted(brief["id"] for brief in briefs) == ["coffee-hormones", "first-date-first-text", "rewards-of-slowness"]
    assert all(brief["cache_state"] == "cold" for brief in briefs)


def test_baseline_report_is_reproducible_and_makes_no_improvement_claim():
    briefs = load_briefs()
    observations = [_observation(brief["id"]) for brief in reversed(briefs)]
    first = build_report(briefs, observations)
    second = build_report(briefs, list(reversed(observations)))
    assert first == second
    assert first["baseline_only"] is True
    assert first["improvement_claimed"] is False
    assert first["rows"][0]["temporary_script_count"] == 1
    assert first["rows"][0]["render_count"] == 1
    assert "Measurement only" in render_markdown(first)


def test_baseline_rejects_mixed_revisions_and_warm_cache():
    briefs = load_briefs()
    observations = [_observation(brief["id"]) for brief in briefs]
    observations[1]["revision"] = "b" * 40
    with pytest.raises(ValueError, match="same exact Git revision"):
        build_report(briefs, observations)
    observations[1]["revision"] = "a" * 40
    observations[1]["cache_state"] = "warm"
    with pytest.raises(ValueError, match="not cold-cache"):
        build_report(briefs, observations)
