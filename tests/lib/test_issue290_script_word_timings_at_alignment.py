"""#290: the alignment commit produces the approved-script word timings.

#262 times the hook's first proof on committed word timings at plan, but no front
door wrote them: the first-date agent wrote `artifacts/script-word-timings.json`
by hand, and the rehearsal copied that file. Real recorded ASR + script here.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import persian_alignment_job as alignment_job
from lib import persian_video_workflow as workflow

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "rehearsal" / "first-date"


def test_recorded_asr_maps_onto_the_approved_script(tmp_path: Path) -> None:
    script = tmp_path / "approved_script.txt"
    script.write_text((FIXTURE / "approved_script.txt").read_text(encoding="utf-8"), encoding="utf-8")
    words = json.loads((FIXTURE / "recorded" / "transcript.json").read_text(encoding="utf-8"))["word_timestamps"]
    result = tmp_path / "alignment-result.json"
    result.write_text("{}", encoding="utf-8")
    evidence = alignment_job._write_script_word_timings(tmp_path, result, script, "0" * 64, words)
    assert evidence["script_word_timings_ref"] == "artifacts/script-word-timings.json"
    written = json.loads((tmp_path / evidence["script_word_timings_ref"]).read_text(encoding="utf-8"))
    recorded = json.loads((FIXTURE / "recorded" / "word-timings.json").read_text(encoding="utf-8"))
    # Same lexemes on the same clock the recorded agent produced by hand.
    assert [w["word"] for w in written["words"]] == [w["word"] for w in recorded["words"]]
    assert written["words"][0]["start"] == pytest.approx(recorded["words"][0]["start"])


def test_unmappable_script_records_why_instead_of_failing_alignment(tmp_path: Path) -> None:
    script = tmp_path / "approved_script.txt"
    script.write_text("کاملاً متن دیگری که هیچ ربطی ندارد", encoding="utf-8")
    words = [{"word": "سلام", "start": 0.0, "end": 0.4}]
    evidence = alignment_job._write_script_word_timings(tmp_path, tmp_path / "r.json", script, "0" * 64, words)
    assert "script_word_timings_ref" not in evidence
    assert evidence["script_word_timings_error"]


def test_plan_reads_the_alignment_committed_timings(tmp_path: Path) -> None:
    project = tmp_path / "p"
    (project / "artifacts").mkdir(parents=True)
    path = project / "artifacts" / "script-word-timings.json"
    path.write_text(json.dumps({"words": [{"word": "سلام", "start": 0.0, "end": 0.4}]}), encoding="utf-8")
    state = {"read_allowlist": {"project_root": str(project)}, "evidence": {"align_script_timing": {
        "script_word_timings_ref": "artifacts/script-word-timings.json",
        "script_word_timings_sha256": workflow._hash_file(path)}}}
    assert workflow._committed_word_timings(state)[0]["word"] == "سلام"
    path.write_text(json.dumps({"words": []}), encoding="utf-8")
    with pytest.raises(workflow.PersianVideoWorkflowError, match="changed after alignment"):
        workflow._committed_word_timings(state)
