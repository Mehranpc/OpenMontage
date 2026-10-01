"""#360 public-boundary rehearsal: early refusal → truthful status → repair → phase completion.

Driven only through the front-door CLI. It fails if the shared requirement check is
removed from admission (the bad pick would be selected) or from readiness (status
would advise building the manifest for the legacy invalid selection), even while the
manifest audit still refuses at the end.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import persian_asset_workspace as workspace
from lib import persian_video_workflow as workflow
from tests.lib.test_issue224_plan_reconcile import _run_at_acquire
from tests.lib.test_issue331_acquisition_next_step import _spend_both_passes
from tests.lib.test_issue360_truthful_readiness import _candidate, _legacy_select


def _cli(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict]:
    try:
        code = workflow.main(list(argv))
    except SystemExit as exc:
        code = int(exc.code or 0)
    out = capsys.readouterr().out
    payload = json.loads(out[out.index("{"):]) if "{" in out else {}
    return code, payload


def test_bad_admission_to_completed_acquire_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    project = _run_at_acquire(tmp_path)
    _spend_both_passes(tmp_path)
    monkeypatch.setattr(workflow, "PROJECTS_DIR", tmp_path)
    # The fixture clock is historical; budgets are covered by their own scenarios.
    monkeypatch.setattr(workflow, "_enforce_cli_front_door_budget", lambda args: None)
    assert _cli(capsys, "attempt", "run", "--phase", "acquire_assets")[0] == 0

    good_a = _candidate(tmp_path, "event-1", "good-a")
    no_subject = _candidate(tmp_path, "event-2", "no-subject", shows_subject=False)
    good_c = _candidate(tmp_path, "event-2", "good-c")
    legacy_bad = _candidate(tmp_path, "event-0", "legacy-bad", shows_subject=False)
    alternate = _candidate(tmp_path, "event-0", "alternate")
    passes = workspace.asset_workspace_status(project)["discoveryPassCount"]

    # 1. Admission refuses the known-bad pick before any write.
    code, refused = _cli(capsys, "asset-candidate-select", "run", "event-2", no_subject)
    # Every known blocker at once: the footage fails, and the reviewed alternate needs a reason.
    assert code == 2 and sorted(d["code"] for d in refused["diagnostics"]) == [
        "ALTERNATE_REASONS_MISSING", "SUBJECT_CONTINUITY_LOST",
    ]
    assert workspace.asset_workspace_status(project)["selectedCount"] == 0

    # 2. A partial valid set is admitted; a pre-#360 selection is recorded as it was then.
    rejections = project / ".workspace" / "rejections.json"
    rejections.parent.mkdir(parents=True, exist_ok=True)
    rejections.write_text(json.dumps({no_subject: "the phone never appears"}), encoding="utf-8")
    assert _cli(capsys, "asset-candidate-select", "run", "event-1", good_a)[0] == 0
    assert _cli(capsys, "asset-candidate-select", "run", "event-2", good_c,
                "--rejections-json", str(rejections))[0] == 0
    _legacy_select(project, "event-0", legacy_bad)

    # 3. Status is truthful and read-only: three recorded, two valid, no "build" advice.
    code, status = _cli(capsys, "status", "run", "--json")
    acquisition = status["acquisition"]
    assert (acquisition["recordedSelectionCount"], acquisition["validSelectionCount"]) == (3, 2)
    assert acquisition["invalidEvents"] == ["event-0"]
    assert "Do not build the manifest yet" in acquisition["nextStep"]
    assert acquisition["preparation"]["decisionRequired"] is None  # routine recovery
    assert _cli(capsys, "assets", "build-manifest", "run")[0] == 2  # audit still strict

    # 4. Repair with the reviewed alternate, bound to the prepared readiness.
    sha = acquisition["readiness"]["inputsSha256"]
    rejections.write_text(json.dumps({legacy_bad: "the phone never appears"}), encoding="utf-8")
    code, _ = _cli(capsys, "asset-candidate-select", "run", "event-0", alternate,
                   "--replace-existing", "--rejections-json", str(rejections), "--expect-readiness", sha)
    assert code == 0

    # 5. Manifest, checkpoint and phase completion through the front door.
    code, status = _cli(capsys, "status", "run", "--json")
    assert status["acquisition"]["readiness"]["disposition"] == "ready_for_manifest"
    assert _cli(capsys, "assets", "build-manifest", "run")[0] == 0
    assert _cli(capsys, "assets", "write-checkpoint", "run")[0] == 0
    assert _cli(capsys, "complete", "run", "--phase", "acquire_assets")[0] == 0
    state = workflow.load_workflow_state("run", pipeline_dir=tmp_path)
    assert state["next_phase"] == "review_subject_regions"
    assert state["evidence"]["acquire_assets"]["assetWorkspaceBinding"]["selectedCount"] == 3
    assert workspace.asset_workspace_status(project)["discoveryPassCount"] == passes
    assert state["send_backs"] == 0
