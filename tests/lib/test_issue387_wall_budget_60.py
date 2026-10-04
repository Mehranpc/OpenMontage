"""#387: the Persian footage run gets a 60-minute wall budget (was 45).

2026-10-04 acceptance-3 used ~41 of 45 minutes before the final render, with the
v3 hook rewrite loop (render + review per rewrite) still to come. Mehran raised the
cap to 60 minutes. The budget and the end-to-end SLO must agree.
"""
from __future__ import annotations

from lib import persian_video_workflow as workflow


def test_persian_footage_wall_budget_is_sixty_minutes():
    assert workflow.get_workflow_budgets().max_wall_time_minutes == 60


def test_end_to_end_slo_matches_the_wall_budget():
    assert workflow.END_TO_END_SLO_SECONDS == 60 * 60
    assert workflow.END_TO_END_SLO_SECONDS == workflow.get_workflow_budgets().max_wall_time_minutes * 60
