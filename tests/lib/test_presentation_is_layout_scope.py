"""Every moment presentation field is a typography/layout change, not an unclassified one.

f418063 Mac acceptance run (2026-09-28): an explicit `presentation.placement:
upper-right` for a moment whose auto-placement failed was not stageable, because only
`presentation.recipeId` counted as layout. The rest of `presentation` landed in the
`unclassified` scope, which no recovery class may change, so FILM_TYPE_LAYOUT could not
make the repair its own surface exists for.
"""
from __future__ import annotations

import copy

import pytest

from lib import persian_edit_workspace as workspace


def _edit() -> dict:
    return {"persian": {"moments": [{
        "id": "moment-3", "kind": "body", "startSeconds": 10.0, "endSeconds": 13.0,
        "segments": [{"role": "hero", "text": "۵۴۳ نفر"}],
        "presentation": {"placement": "auto", "treatment": "editorial", "recipeId": "editorial-hero-balanced"},
    }], "shots": [], "typographicBeats": []}}


@pytest.mark.parametrize("field,value", [
    ("placement", "upper-right"), ("treatment", "inline-statement"),
    ("recipeId", "editorial-hero-compact"), ("contrastStrength", "strong"),
])
def test_a_presentation_change_is_a_typography_change(field: str, value: str) -> None:
    changed = copy.deepcopy(_edit())
    changed["persian"]["moments"][0]["presentation"][field] = value
    assert workspace._changed_scopes(_edit(), changed) == ["typography"]
