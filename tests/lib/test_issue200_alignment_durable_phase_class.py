"""#200: `align_script_timing` is durable kernel work and must be classed that way.

The alignment phase starts a real durable job through the run kernel
(`lib/persian_alignment_job.py`), and `_PHASE_CHECKPOINT` already treats it as a
durable phase, but `_EXTERNAL_DURABLE_PHASES` omitted it. Its phase-telemetry entry
was therefore classed `editorial`, and `phase_time_accounting` wrote its duration into
the `active_editorial_seconds` alias of the frozen summary -- contradicting the
`provider_network_wait` span for the same phase in the same payload.

These tests pin the classification at the attempt seam, the accounting consequence,
and a structural guard: every phase that launches a durable kernel job is classed
external-durable, so the next such job cannot drift the same way.
"""

from __future__ import annotations

import ast
from datetime import timedelta
from pathlib import Path

import pytest

import lib.persian_asset_job as asset_job
import lib.persian_run_kernel as kernel
import lib.persian_video_workflow as workflow
from lib.persian_video_workflow import PHASES, load_workflow_state, record_phase_attempt
from tests.lib.test_persian_video_workflow import BASE, _bootstrap

ROOT = Path(__file__).resolve().parents[2]


def _state_at_alignment(tmp_path: Path) -> dict:
    state, _ = _bootstrap(tmp_path)
    state["completed_phases"] = list(PHASES[: PHASES.index("align_script_timing")])
    state["next_phase"] = "align_script_timing"
    state["attempts"] = {}
    workflow._write_state(tmp_path / "run", state)
    return state


def _literal_job_phases(module_path: Path) -> set[str]:
    """Phase literals passed to `start_phase_job` / `run_phase_job` in a module."""
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    phases: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name not in {"start_phase_job", "run_phase_job"}:
            continue
        for keyword in node.keywords:
            if keyword.arg == "phase" and isinstance(keyword.value, ast.Constant):
                phases.add(str(keyword.value.value))
    return phases


def test_alignment_attempt_is_classed_external_durable(tmp_path: Path) -> None:
    _state_at_alignment(tmp_path)
    state = record_phase_attempt("run", "align_script_timing", pipeline_dir=tmp_path, now=BASE)
    entry = state["phase_telemetry"]["align_script_timing"][-1]
    assert entry["execution_class"] == "external_durable"


def test_alignment_duration_lands_in_external_durable_alias(tmp_path: Path) -> None:
    _state_at_alignment(tmp_path)
    state = record_phase_attempt("run", "align_script_timing", pipeline_dir=tmp_path, now=BASE)
    entry = state["phase_telemetry"]["align_script_timing"][-1]
    entry["finished_at"] = (BASE + timedelta(seconds=40)).isoformat()
    entry["duration_seconds"] = 40.0
    entry["outcome"] = "succeeded"
    workflow._write_state(tmp_path / "run", state)

    accounting = workflow.phase_time_accounting(
        load_workflow_state("run", pipeline_dir=tmp_path), now=BASE + timedelta(seconds=60)
    )
    assert accounting["external_durable_seconds"] == pytest.approx(40.0)
    assert accounting["active_editorial_seconds"] == pytest.approx(0.0)


def test_alignment_job_literal_still_names_the_phase() -> None:
    # Guards the guard below: if the alignment job stops passing a literal phase,
    # the structural test would silently check nothing for it.
    assert _literal_job_phases(ROOT / "lib" / "persian_alignment_job.py") == {"align_script_timing"}


def test_every_durable_job_phase_is_classed_external_durable() -> None:
    job_phases = (
        _literal_job_phases(ROOT / "lib" / "persian_alignment_job.py")
        | {asset_job._PHASE}
        | set(kernel.MEDIA_EXECUTION_PHASES)
    )
    misclassed = sorted(
        phase for phase in job_phases
        if workflow._execution_class_for_phase(phase) != "external_durable"
    )
    assert misclassed == []


def test_editorial_phases_stay_editorial() -> None:
    # The fix must not relabel agent-authored phases as durable work.
    for phase in ("prepare_inputs", "plan_scenes_moments", "review_subject_regions",
                  "no_copy_preflight", "opening_review", "final_review"):
        assert workflow._execution_class_for_phase(phase) == "editorial", phase
