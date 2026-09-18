from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.persian_design import resolve_design
from lib.persian_moments import audit_moments, build_moments
from schemas.artifacts import validate_artifact


def _long_statement():
    return {
        "id": "body-1",
        "kind": "statement",
        "startSeconds": 1.0,
        "endSeconds": 6.0,
        "segments": [{"role": "hero", "text": "این عبارت عمداً از سقف قدیمی سی نویسه بلندتر است"}],
        "presentation": {"recipeId": "editorial-callout-balanced"},
    }


def test_adaptive_pixel_typography_replaces_character_cap_with_render_fit() -> None:
    moment = build_moments([_long_statement()])[0]
    legacy = audit_moments([moment], duration_seconds=12.0)
    assert any("visible chars" in item for item in legacy.problems)
    adaptive = audit_moments([moment], duration_seconds=12.0, adaptive_pixel_typography=True)
    assert not any("visible chars" in item for item in adaptive.problems)


def test_recipe_id_is_curated_not_freeform_css(tmp_path: Path) -> None:
    moment = _long_statement()
    assert moment["presentation"]["recipeId"] == "editorial-callout-balanced"
    bad = dict(moment)
    bad["presentation"] = {"recipeId": "agent-css", "fontSize": 173}
    # schema fragment validation is exercised through a minimal edit fixture elsewhere;
    # the presentation parser must reject arbitrary recipe/style keys itself.
    with pytest.raises(ValueError, match="recipe"):
        build_moments([bad])


def test_unpinned_film_type_resolves_to_215_default() -> None:
    design = resolve_design({"version": 2, "profile": "film-type", "seed": "issue28"})
    assert design is not None
    assert design["profileVersion"] in {"2.15.0", "2.16.0"}
    assert design["resolved"]["layoutVersion"] == 16
    assert design["resolved"]["watermark"]["planningMode"] == "fixed-anchors-text-only"
