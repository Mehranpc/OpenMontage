"""The opening hook shot's semantic evidence is checked with the cheap edit checks.

Live run on f418063 (2026-09-28): the draft's opening shot lacked semanticRole /
semanticDirection / openingSemanticMatch / selectionReason / showsSubject. Only the
browser pass (compose) refused it, after an EDIT_ARTIFACT candidate was spent, and the
repair then needed a third candidate the class allows only two of.
"""
from __future__ import annotations

from lib.persian_edit_contract import collect_persian_edit_diagnostics
from lib.persian_preflight import aggregate_preflight_edit_decisions

_COMPLETE = {
    "semanticRole": "tension_hook", "semanticDirection": "waiting_for_reply",
    "openingSemanticMatch": True, "selectionReason": "A phone face-down on a bare table.",
    "showsSubject": True, "humanPresence": False,
}


def _persian(**shot_fields) -> dict:
    return {
        "design": {"version": 2, "profile": "film-type", "seed": "s"},
        "shots": [{"id": "shot-1", "visualEventId": "ev-1", "narrativeRole": "hook",
                   "startSeconds": 0.0, "endSeconds": 2.5, **shot_fields}],
    }


def _codes(persian: dict) -> list[str]:
    return [d.code for d in collect_persian_edit_diagnostics({"persian": persian})]


def test_a_bare_opening_hook_shot_is_refused_on_the_draft() -> None:
    codes = _codes(_persian())
    assert codes.count("shot.opening_semantic_missing") >= 5


def test_a_complete_opening_hook_shot_passes() -> None:
    assert "shot.opening_semantic_missing" not in _codes(_persian(**_COMPLETE))


def test_the_cheap_precheck_names_it_before_any_candidate() -> None:
    edit = {"version": "1.0", "render_runtime": "remotion", "cuts": [], "persian": _persian()}
    report = aggregate_preflight_edit_decisions(edit, cheap_only=True)
    assert report["ok"] is False
    assert "shot.opening_semantic_missing" in {i["code"] for i in report["blockingIssues"]}


def test_legacy_profiles_are_unaffected() -> None:
    persian = _persian()
    persian["design"] = {"version": 2, "profile": "legacy", "seed": "s"}
    assert "shot.opening_semantic_missing" not in _codes(persian)
