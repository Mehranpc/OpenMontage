"""#262: the hook's first-proof ceiling is applied at plan completion.

On the first-date run, the automatic hook's first concrete proof («مطالعه: ۵۴۳ نفر»)
is spoken at 15s. The edit precheck refused it about 90 minutes in, after all footage
was bought. The plan now names the proof phrase; its time comes from the committed
word timings, and the same ceiling applies before acquisition.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import persian_video_workflow as workflow
from lib.persian_editorial_hook import build_initial_hook_selection

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "rehearsal" / "first-date"


def _state(tmp_path: Path, *, user_hook: str | None = None) -> dict:
    project = tmp_path / "run"
    (project / "artifacts").mkdir(parents=True)
    (project / "artifacts" / "script-word-timings.json").write_bytes(
        (FIXTURE / "recorded" / "word-timings.json").read_bytes()
    )
    script = json.loads((FIXTURE / "decisions" / "checkpoint-script.json").read_text(encoding="utf-8"))
    monkeypatch_target = {"artifacts": script["artifacts"], "status": "completed", "stage": "script"}
    _CHECKPOINTS[str(tmp_path)] = monkeypatch_target
    return {
        "project_id": "run", "projects_root": str(tmp_path),
        "read_allowlist": {"project_root": str(project)},
        "hook_selection": build_initial_hook_selection(user_hook),
    }


_CHECKPOINTS: dict[str, dict] = {}


@pytest.fixture(autouse=True)
def _script_checkpoint(monkeypatch):
    monkeypatch.setattr(
        workflow, "read_checkpoint",
        lambda root, _pid, stage: _CHECKPOINTS.get(str(root)) if stage == "script" else None,
    )


PROOF = {"kind": "evidence", "anchorText": "۵۴۳ نفر", "evidence": "the study scale"}


def test_a_late_proof_for_an_automatic_hook_stops_the_plan(tmp_path: Path) -> None:
    with pytest.raises(workflow.PersianVideoWorkflowError, match=r"\[HOOK_PROOF_LATE\].*1[45]\.\d\ds"):
        workflow._plan_hook_first_proof(_state(tmp_path), {"hook_first_proof": PROOF})


def test_the_refusal_names_the_three_choices(tmp_path: Path) -> None:
    with pytest.raises(workflow.PersianVideoWorkflowError) as caught:
        workflow._plan_hook_first_proof(_state(tmp_path), {"hook_first_proof": PROOF})
    message = str(caught.value)
    assert "hook-override" in message and "automatic hook" in message and "short-form" in message


def test_a_user_owned_hook_records_the_late_proof_and_passes(tmp_path: Path) -> None:
    state = _state(tmp_path, user_hook="پیام بدی یا صبر کنی؟ بعد از یه قرار خوب")
    record = workflow._plan_hook_first_proof(state, {"hook_first_proof": PROOF})
    assert record["authoritative"] is True
    assert record["atSeconds"] > record["blockSeconds"]


def test_a_prompt_proof_passes(tmp_path: Path) -> None:
    words = json.loads((FIXTURE / "recorded" / "word-timings.json").read_text(encoding="utf-8"))
    rows = words.get("words") if isinstance(words, dict) else words
    early = " ".join(str(row.get("word") or row.get("text")) for row in rows[3:6])
    record = workflow._plan_hook_first_proof(
        _state(tmp_path), {"hook_first_proof": {"kind": "example", "anchorText": early}}
    )
    assert record["atSeconds"] <= record["blockSeconds"]


def test_setup_language_is_not_concrete_proof(tmp_path: Path) -> None:
    with pytest.raises(workflow.PersianVideoWorkflowError, match="kind must be one of"):
        workflow._plan_hook_first_proof(
            _state(tmp_path), {"hook_first_proof": {"kind": "authority", "anchorText": "۵۴۳ نفر"}}
        )


def test_a_proof_not_in_the_narration_is_refused(tmp_path: Path) -> None:
    with pytest.raises(workflow.PersianVideoWorkflowError, match="not in the narration"):
        workflow._plan_hook_first_proof(
            _state(tmp_path), {"hook_first_proof": {"kind": "evidence", "anchorText": "کتابخانهٔ ملی ایران"}}
        )


def test_plans_without_a_named_proof_are_unchanged(tmp_path: Path) -> None:
    assert workflow._plan_hook_first_proof(_state(tmp_path), {}) is None


def test_the_user_can_own_the_hook_at_the_plan_gate(tmp_path: Path) -> None:
    """The plan-time stop is answerable in the same run (the #257 path, earlier)."""
    from datetime import datetime, timezone

    source = tmp_path.parent / f"{tmp_path.name}-262.wav"
    source.write_bytes(b"audio")
    workflow.bootstrap_persian_video(
        title="262", approved_script="پیام بدی یا صبر کنی؟ بعد از یه قرار خوب", narration_path=str(source),
        project_id="plan", pipeline_dir=tmp_path, backlot_opener=lambda _pid: 0,
        now=datetime(2026, 9, 27, tzinfo=timezone.utc),
    )
    state = workflow.load_workflow_state("plan", pipeline_dir=tmp_path)
    state["next_phase"] = "plan_scenes_moments"
    workflow._write_state(workflow._project_root(state), state)

    after = workflow.record_user_hook_override(
        "plan", selected_text="پیام بدی یا صبر کنی؟ بعد از یه قرار خوب",
        reason="User owns the hook at the plan-time proof gate.", pipeline_dir=tmp_path,
    )
    assert after["hook_selection"]["mode"] == "user_supplied"
    assert after["hook_selection"]["source"] == "user_plan_decision"
