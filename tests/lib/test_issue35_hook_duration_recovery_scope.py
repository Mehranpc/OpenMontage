from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from lib import persian_edit_workspace as workspace


def _edit(*, hook_end: float) -> dict:
    return {
        "metadata": {
            "target_platform": "instagram-reels",
            "hookQuality": {"version": "2.0"},
        },
        "persian": {
            "format": "vertical",
            "durationSeconds": 12.0,
            "shots": [
                {
                    "id": "shot-1",
                    "startSeconds": 0.0,
                    "endSeconds": 12.0,
                    "narrativeRole": "hook",
                    "changeType": "establish",
                    "visualEventId": "event-1",
                    "humanPresence": True,
                    "openingSemanticMatch": True,
                    "semanticRole": "belief_reversal_hook",
                    "semanticDirection": "stereotype_to_counterevidence",
                    "selectionReason": "Player and controller visibly establish the gaming subject.",
                    "source": "/tmp/source.mp4",
                    "avoidRegions": [],
                }
            ],
            "moments": [
                {
                    "id": "hook-1",
                    "kind": "hook",
                    "startSeconds": 0.0,
                    "endSeconds": hook_end,
                    "segments": [
                        {"role": "hero", "text": "بازی‌های ویدیویی"}
                    ],
                }
            ],
            "typographicBeats": [],
            "captions": [],
            "audio": {},
            "watermark": {
                "persianText": "طریقت تسلیم",
                "latinText": "Pathway_of_Surrender",
            },
        },
    }


def test_hook_duration_layout_recovery_is_timeline_scope_but_invalidates_hook_dependency(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    base_edit = _edit(hook_end=5.75)
    child_edit = deepcopy(base_edit)
    child_edit["persian"]["moments"][0]["endSeconds"] = 4.95

    assert workspace._dependency_digests(base_edit)["hook"] != workspace._dependency_digests(child_edit)["hook"]
    assert workspace._changed_scopes(base_edit, child_edit) == ["timeline"]

    workspace.stage_edit_draft(project, "base", base_edit, max_candidates=4)
    child = workspace.stage_edit_draft(
        project,
        "layout-1",
        child_edit,
        parent_attempt_id="base",
        diagnostic_issue={"code": "FILM_TYPE_PREPASS", "recoveryClass": "FILM_TYPE_LAYOUT"},
        strategy="adjust_editorial_hold_within_policy",
        changed_fields=["typography.duration"],
        max_candidates=4,
    )
    assert child["changedScopes"] == ["timeline"]
