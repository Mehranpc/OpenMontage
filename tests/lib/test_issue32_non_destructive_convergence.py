from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from lib.persian_edit_workspace import PersianEditWorkspaceError, stage_edit_draft
from tests.lib.test_persian_preflight_contract import _payload


def _two_moment_edit() -> dict:
    payload = _payload()
    payload["persian"]["moments"].append({
        "id": "moment-callout-memory",
        "kind": "statement",
        "startSeconds": 6.0,
        "endSeconds": 9.5,
        "segments": [
            {"role": "lead", "text": "بهبود بیشتر دیده شد در"},
            {"role": "hero", "text": "حافظه"},
        ],
    })
    return payload


def test_preflight_revisions_cannot_silently_delete_editorial_moments(tmp_path: Path) -> None:
    first = _two_moment_edit()
    stage_edit_draft(tmp_path, "edit-v1", first)

    reduced = deepcopy(first)
    reduced["persian"]["moments"] = [reduced["persian"]["moments"][0]]

    with pytest.raises(PersianEditWorkspaceError, match="silent editorial moment removal"):
        stage_edit_draft(tmp_path, "edit-v2", reduced)


def test_explicit_user_authorization_can_remove_named_editorial_moment(tmp_path: Path) -> None:
    first = _two_moment_edit()
    stage_edit_draft(tmp_path, "edit-v1", first)

    revised = deepcopy(first)
    revised["persian"]["moments"] = [revised["persian"]["moments"][0]]
    revised.setdefault("metadata", {})["editorialMomentRemovalAuthorization"] = {
        "authorized": True,
        "source": "explicit_user_response",
        "decisionId": "user-remove-memory-callout",
        "reason": "User explicitly asked to remove this callout.",
        "removedMomentIds": ["moment-callout-memory"],
    }

    staged = stage_edit_draft(tmp_path, "edit-v2", revised)
    assert staged["editorialMomentIds"] == ["moment-1"]
    assert staged["removedEditorialMomentIds"] == ["moment-callout-memory"]
    assert staged["removalAuthorized"] is True
