"""#313: a dark-footage refusal is a scoped asset repair, and overlapping windows are not options.

f418063 Mac acceptance run (2026-09-28): the final render was refused for a near-black
stretch under shot-13. The refusal named only seconds, so no scoped path could take it,
and `shot_local_recovery_plan` counted two overlapping windows of the same dark source as
reviewed alternates, so an acquire_assets send-back was refused with
"existing reviewed asset option remains".
"""
from __future__ import annotations

from lib.persian_recovery_policy import recovery_class_for_code, shot_local_recovery_plan
from tests.lib.test_persian_p3_shot_local_sendback import _candidate

_EDIT = {"persian": {"shots": [{"id": "shot-13", "visualEventId": "ev-13"}]}}


def _workspace(*alternates: dict) -> dict:
    return {
        "selectedCandidateIds": {"ev-13": "sel"},
        "reusableCandidatesByVisualEvent": {"ev-13": [
            _candidate("sel", "dark-source", disposition="selected", window=(3.665, 9.815)),
            *alternates,
        ]},
    }


def _plan(code: str, workspace: dict) -> dict:
    return shot_local_recovery_plan({"code": code, "details": {"shotIds": ["shot-13"]}}, _EDIT, workspace)


def test_the_code_is_an_asset_selection_repair() -> None:
    assert recovery_class_for_code("ASSET_SELECTION_DARK_FOOTAGE") == "ASSET_SELECTION"


def test_an_overlapping_window_of_the_same_source_is_not_an_option() -> None:
    plan = _plan("ASSET_SELECTION_DARK_FOOTAGE",
                 _workspace(_candidate("overlap", "dark-source", window=(4.065, 10.215))))
    assert plan["decision"] == "scoped_asset_reacquisition"
    assert plan["sendBackAllowed"] is True
    assert plan["reacquireShotIds"] == ["shot-13"]


def test_a_disjoint_window_of_the_same_source_still_counts() -> None:
    plan = _plan("ASSET_SELECTION_DARK_FOOTAGE",
                 _workspace(_candidate("later", "dark-source", window=(10.215, 16.4))))
    assert plan["decision"] == "same_phase_repair"
    assert [row["candidateId"] for row in plan["existingOptions"]["shot-13"]] == ["later"]


def test_another_source_still_counts() -> None:
    plan = _plan("ASSET_SELECTION_DARK_FOOTAGE",
                 _workspace(_candidate("other", "bright-source", window=(3.665, 9.815))))
    assert plan["decision"] == "same_phase_repair"


def test_other_codes_keep_overlapping_windows_as_options() -> None:
    plan = _plan("ASSET_SELECTION_SEMANTIC_MISMATCH",
                 _workspace(_candidate("overlap", "dark-source", window=(4.065, 10.215))))
    assert plan["decision"] == "same_phase_repair"


def test_the_render_refusal_names_the_code_and_the_shots(tmp_path) -> None:
    import subprocess
    from unittest.mock import patch

    from lib.persian_render_qa import DarkRun
    from tools.video.persian_compose import PersianCompose

    composer = tmp_path / "runtime"
    (composer / "node_modules").mkdir(parents=True)
    output = tmp_path / "result.mp4"
    props = {"format": "vertical", "durationSeconds": 62.5, "moments": [], "typographicBeats": [],
             "shots": [{"id": "shot-12", "startSeconds": 0.0, "endSeconds": 56.33},
                       {"id": "shot-13", "startSeconds": 56.33, "endSeconds": 62.48}]}

    def build(persian, stage, run):
        stage.mkdir(parents=True)
        return props, []

    def render(*args, **kwargs):
        output.write_bytes(b"mocked")
        return subprocess.CompletedProcess([], 0, stdout="", stderr="")

    class QA:
        passed = False
        warn_runs: list = []
        dead_runs = [DarkRun(57.0, 59.0, 18.8)]

        def to_dict(self):
            return {"passed": False}

    with patch("tools.video.persian_compose._composer_dir", return_value=composer), \
            patch.object(PersianCompose, "_build_props", side_effect=build), \
            patch.object(PersianCompose, "run_command", side_effect=render), \
            patch("tools.video.persian_compose.audit_render_luminance", return_value=QA()):
        result = PersianCompose().execute({
            "edit_decisions": {"render_runtime": "remotion", "persian": {"format": "vertical"}},
            "output_path": str(output),
        })
    assert result.success is False, result.error
    assert result.data.get("code"), result.error
    assert result.data["code"] == "ASSET_SELECTION_DARK_FOOTAGE"
    assert result.data["shotIds"] == ["shot-13"]
    assert "--shot-id shot-13" in result.error
