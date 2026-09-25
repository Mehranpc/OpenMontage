"""#152: the hook/caption handoff must be a caption-scope change.

`CAPTION_CONTINUITY`'s whole purpose is to repair the hook/caption handoff
(`captions.semantic_handoff`). But `metadata.hookCaptionHandoff` was classified
into the `unclassified` scope, which that class is not allowed to change — so the
one repair it exists to make was unreachable through its own surface.

That gap is what motivated the L3 run's agent to declare an unrelated recovery
class to get a correct repair past the mutation surface. The fix is to classify
the handoff where it belongs, so the legal surface is reachable and misdeclaring
is unnecessary.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lib import persian_edit_workspace as workspace
from lib.persian_recovery_policy import recovery_policy_for_issue


def _edit(*, handoff: dict | None) -> dict:
    return {
        "metadata": {"hookCaptionHandoff": handoff} if handoff is not None else {},
        "persian": {
            "durationSeconds": 6.0,
            "shots": [
                {
                    "id": "shot-1",
                    "startSeconds": 0.0,
                    "endSeconds": 6.0,
                    "narrativeRole": "hook",
                }
            ],
            "moments": [
                {
                    "id": "moment-01",
                    "kind": "hook",
                    "startSeconds": 0.0,
                    "endSeconds": 5.0,
                    "segments": [{"role": "hero", "text": "بازی‌های ویدیویی"}],
                }
            ],
            "typographicBeats": [],
            "captions": [],
            "audio": {},
            "watermark": {},
        },
    }


def test_caption_continuity_owns_the_hook_caption_handoff() -> None:
    plan = recovery_policy_for_issue({"code": "CAPTION_HANDOFF_INVALID"})

    assert plan["recoveryClass"] == "CAPTION_CONTINUITY"
    assert "captions.semantic_handoff" in plan["mutationSurface"]
    strategy = "set_semantic_replacement_resume_to_next_complete_unit"
    assert strategy in plan["strategies"]


def test_handoff_repair_lands_in_the_captions_scope(tmp_path: Path) -> None:
    """The repair permitted by CAPTION_CONTINUITY must register as a caption change."""
    project = tmp_path / "project"
    workspace.stage_edit_draft(project, "base", _edit(handoff=None), max_candidates=4)

    staged = workspace.stage_edit_draft(
        project,
        "handoff",
        _edit(handoff={"mode": "semantic_replacement", "resumeAtSeconds": 5.0}),
        parent_attempt_id="base",
        diagnostic_issue={"code": "CAPTION_HANDOFF_INVALID"},
        strategy="set_semantic_replacement_resume_to_next_complete_unit",
        changed_fields=["captions.semantic_handoff"],
        max_candidates=4,
    )

    assert staged["changedScopes"] == ["captions"]


def test_declaring_an_unrelated_field_for_a_named_diagnostic_is_refused(
    tmp_path: Path,
) -> None:
    """A candidate may not relabel itself to repair something else.

    The wildcard surface means "the contract field this diagnostic names". When the
    diagnostic names one, a candidate reporting an unrelated field is misdeclaring
    the repair it is making — the shape the L3 run used to get a caption-handoff
    change past a surface that had no business allowing it (#152).
    """
    project = tmp_path / "project"
    workspace.stage_edit_draft(project, "base", _edit(handoff=None), max_candidates=4)

    with pytest.raises(
        workspace.PersianEditWorkspaceError,
        match="do not name the field the diagnostic reports",
    ):
        workspace.stage_edit_draft(
            project,
            "misdeclared",
            _edit(handoff={"mode": "semantic_replacement", "resumeAtSeconds": 5.0}),
            parent_attempt_id="base",
            diagnostic_issue={
                "code": "SCHEMA.ENUM",
                "details": {"field": "persian.shots[].narrativeRole"},
            },
            strategy="repair_reported_contract_field_only",
            changed_fields=["captions.semantic_handoff"],
            max_candidates=4,
        )


def test_a_field_naming_diagnostic_accepts_its_own_field(tmp_path: Path) -> None:
    """The hardening must not refuse the repair the diagnostic actually reports."""
    project = tmp_path / "project"
    workspace.stage_edit_draft(project, "base", _edit(handoff=None), max_candidates=4)

    staged = workspace.stage_edit_draft(
        project,
        "in-scope",
        _edit(handoff={"mode": "semantic_replacement", "resumeAtSeconds": 5.0}),
        parent_attempt_id="base",
        diagnostic_issue={
            "code": "CAPTION_HANDOFF_INVALID",
            "details": {"field": "captions.semantic_handoff"},
        },
        strategy="set_semantic_replacement_resume_to_next_complete_unit",
        changed_fields=["captions.semantic_handoff"],
        max_candidates=4,
    )

    assert staged["changedScopes"] == ["captions"]
