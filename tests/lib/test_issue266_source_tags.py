"""#266: provider tag strings are stored as phrases, not characters."""
from __future__ import annotations

from lib.persian_asset_workspace import _source_tags


def test_a_pexels_tag_string_stays_one_phrase():
    assert _source_tags("a woman using laptop while sitting") == ["a woman using laptop while sitting"]


def test_comma_separated_tags_split():
    assert _source_tags("phone, hand ,  desk") == ["phone", "hand", "desk"]


def test_lists_pass_through_stripped():
    assert _source_tags([" phone ", "", "hand"]) == ["phone", "hand"]


def test_a_record_stored_as_characters_heals():
    assert _source_tags(list("using a smartphone")) == ["using a smartphone"]


def test_missing_is_empty():
    assert _source_tags(None) == []
