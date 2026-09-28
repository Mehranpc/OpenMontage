"""#206: a moment-carrying event must spend one query on the space its type needs.

#183 wrote the rule into `scene-director.md`, but `audit_scene_plan` -- the gate the
manifest says to run rather than self-assess -- never checked it, so a plan whose
moment-carrying events searched on action alone audited clean. Those queries return
footage whose subject fills the declared band, and the plan's moments collapse after
acquisition (8 -> 6 -> 5 -> 3 across runs, recorded on #107).

These tests pin the gate, its scope, and that it stays in step with the prose contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lib.persian_scenes import FRAMING_QUERY_TERMS, audit_scene_plan
import tests.lib.test_persian_gates as gates

ROOT = Path(__file__).resolve().parents[2]
# Reuse the scene-audit fixture builders without re-collecting that test class here.
_EVENT = gates.TestSceneAudit()._event
_PLAN = gates.TestSceneAudit()._plan


def _audit(**event_overrides) -> list[str]:
    beat = {
        "id": "beat-1",
        "duration_seconds": 2.5,
        "typographic": False,
        "visual_events": [_EVENT(1, **event_overrides)],
    }
    return audit_scene_plan(_PLAN([beat]))["problems"]


def _framing_problems(problems: list[str]) -> list[str]:
    return [p for p in problems if "asks for the clear space" in p]


def test_action_only_queries_on_a_moment_event_are_refused() -> None:
    problems = _audit(
        carries_moment=True,
        negative_space="upper_band",
        queries=["man looking at phone at table", "hands typing text message"],
    )
    framing = _framing_problems(problems)
    assert len(framing) == 1, problems
    assert "beat-1/beat-1-event-1" in framing[0]
    assert "'upper_band'" in framing[0]


def test_one_framing_query_is_enough() -> None:
    problems = _audit(
        carries_moment=True,
        negative_space="upper_band",
        queries=["man looking at phone at table", "phone lying on table wide shot plain wall above"],
    )
    assert problems == []


def test_framing_match_is_case_insensitive() -> None:
    problems = _audit(
        carries_moment=True,
        negative_space="upper_band",
        queries=["man looking at phone", "Phone On EMPTY Desk"],
    )
    assert _framing_problems(problems) == []


def test_events_without_a_moment_are_not_constrained() -> None:
    problems = _audit(queries=["man looking at phone at table", "hands typing text message"])
    assert problems == []


def test_an_undeclared_region_reports_the_region_problem_not_a_framing_one() -> None:
    # Framing is judged against a declared band; with none declared, the existing
    # `negative_space` problem is the one actionable fix, and one problem is reported.
    problems = _audit(carries_moment=True, queries=["man looking at phone", "hands typing"])
    assert _framing_problems(problems) == []
    assert any("declares no" in p for p in problems), problems


@pytest.mark.parametrize(
    "query",
    ["lonely woman on phone", "man opening wallet at cafe", "skyscraper office worker",
     "plainly dressed man", "background actor texting"],
)
def test_a_framing_term_inside_another_word_does_not_count(query: str) -> None:
    # Substring matching let `lonely`, `wallet` and `skyscraper` pass as framing.
    problems = _audit(
        carries_moment=True,
        negative_space="upper_band",
        queries=["man looking at phone", query],
    )
    assert len(_framing_problems(problems)) == 1, query


@pytest.mark.parametrize("term", FRAMING_QUERY_TERMS)
def test_every_framing_term_satisfies_the_gate(term: str) -> None:
    problems = _audit(
        carries_moment=True,
        negative_space="full_frame",
        queries=["man looking at phone", f"phone {term} shot"],
    )
    assert _framing_problems(problems) == [], term


def test_the_director_prose_names_the_gate() -> None:
    # The rule lived only in prose once; keep prose and gate pointing at each other.
    director = (ROOT / "skills/pipelines/persian-footage/scene-director.md").read_text(encoding="utf-8")
    assert "FRAMING_QUERY_TERMS" in director


# A close framing fills the frame with the subject, so it cannot be the framing query
# (f418063 acceptance run, 2026-09-28: both hook queries asked for a phone close-up).
import pytest as _pytest

from lib.persian_scenes import _asks_for_framing


@_pytest.mark.parametrize("query", [
    "close up hand holding phone plain wall",
    "close-up phone on empty table",
    "phone screen macro blank",
    "woman texting closeup wall",
    "extreme close phone message plain",
])
def test_a_close_framing_is_not_a_framing_query(query: str) -> None:
    assert _asks_for_framing(query) is False


def test_a_wide_framing_still_counts() -> None:
    assert _asks_for_framing("lone phone on plain table wide shot") is True
