"""#210: operator override for the Persian stock-search candidate ceiling."""

from __future__ import annotations

import pytest

from lib import persian_video_workflow as workflow

ENV = "OPENMONTAGE_PERSIAN_MAX_CANDIDATES"


def _manifest_total() -> int:
    return workflow.get_workflow_budgets().max_candidates_total


def test_unset_env_keeps_the_manifest_policy(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    assert workflow.asset_search_policy()["max_candidates_total"] == _manifest_total()


def test_blank_env_keeps_the_manifest_policy(monkeypatch):
    monkeypatch.setenv(ENV, "   ")
    assert workflow.asset_search_policy()["max_candidates_total"] == _manifest_total()


def test_override_widens_only_the_candidate_ceiling(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    base = workflow.asset_search_policy()
    monkeypatch.setenv(ENV, str(_manifest_total() + 8))
    widened = workflow.asset_search_policy()
    assert widened["max_candidates_total"] == _manifest_total() + 8
    for key, value in base.items():
        if key != "max_candidates_total":
            assert widened[key] == value, key


def test_scoped_grant_stacks_on_the_overridden_ceiling(monkeypatch):
    monkeypatch.setenv(ENV, "24")
    total = workflow.asset_search_policy()["max_candidates_total"]
    assert workflow._candidate_ceiling({}, total) == 24


@pytest.mark.parametrize("raw", ["abc", "1.5", "0", "-3"])
def test_invalid_override_fails_loudly(monkeypatch, raw):
    monkeypatch.setenv(ENV, raw)
    with pytest.raises(workflow.PersianVideoWorkflowError, match=ENV):
        workflow.asset_search_policy()
