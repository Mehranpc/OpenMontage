"""#260 acceptance for #251 and #248, in one rehearsal pass to region review.

#251: the f13d914 run's user-directed revision zeroed the counters its acceptance
report then read as whole-run facts. The user sends region review back through the
real `send-back --user-directed-revision`; after region review runs again, the
run-wide totals must still carry both cycles.

#248: the fd2fb05 run spent its wall budget because edit-stage counted a soft region
(general body) against a declared band that region review had certified clear. The
recorded first-date regions are all hard, so the edit marks soft body occupancy in
ve-1's upper band, the way a reviewer marks a background figure, and stages it through
the real CLI.
"""
from __future__ import annotations

import json
from pathlib import Path

from lib.persian_video_workflow import _whole_run_totals
from scripts.persian_rehearsal import DEFAULT_FIXTURE, PROJECT_ID, Rehearsal, _apply_named_remedies


def test_revision_history_and_soft_band_occupancy(tmp_path: Path) -> None:
    rehearsal = Rehearsal(DEFAULT_FIXTURE, tmp_path, echo=False)
    result = rehearsal.rehearse(until="regions")
    assert result["ok"], result["failure"]

    # -- #251 ---------------------------------------------------------------------
    rehearsal.wf(
        "send-back review_subject_regions (user-directed)", "send-back", PROJECT_ID,
        "review_subject_regions", "--reason", "User asked to re-review the hook shot regions.",
        "--user-directed-revision",
    )
    rehearsal.regions()
    state = json.loads((rehearsal.project / "persian-video-workflow.json").read_text(encoding="utf-8"))
    assert state["next_phase"] == "no_copy_preflight"
    assert state["user_revision_cycles"] == 1
    assert state["send_backs"] == 0  # the fresh cycle's own counter
    archive = state["revision_cycle_archive"]
    assert [cycle["revision_cycle"] for cycle in archive] == [0]
    assert archive[0]["attempts"]["acquire_assets"] >= 1
    totals = _whole_run_totals(state)
    assert totals["revision_cycles"] == 1
    assert totals["user_directed_revisions"] == 1
    assert totals["phases"]["review_subject_regions"]["attempts"] == 2
    assert totals["phases"]["review_subject_regions"]["cycles"] == [0, 1]

    # -- #248 ---------------------------------------------------------------------
    draft = _apply_named_remedies(
        rehearsal.decision("edit-decisions-draft.json"), rehearsal.decision("region-annotations.json"),
    )
    shot = next(s for s in draft["persian"]["shots"] if s.get("visualEventId") == "ve-1")
    shot["avoidRegions"] = [
        *shot.get("avoidRegions", []),
        {"x": 0.55, "y": 0.02, "w": 0.35, "h": 0.2, "priority": "soft"},
    ]
    rehearsal.wf(
        "edit-stage base (soft region in the declared band)", "edit-stage", PROJECT_ID,
        "base", "--json", rehearsal.write("edit-decisions-soft.json", draft),
    )
    staged = json.loads(
        (rehearsal.project / ".drafts" / "edit" / "base" / "edit_decisions.json").read_text(encoding="utf-8")
    )
    staged_shot = next(s for s in staged["persian"]["shots"] if s.get("visualEventId") == "ve-1")
    assert any(region.get("priority") == "soft" for region in staged_shot["avoidRegions"])
