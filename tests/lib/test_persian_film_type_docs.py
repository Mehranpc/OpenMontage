from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.persian_film_type_docs import (
    FilmTypeDocumentationError,
    active_film_type_version,
    film_type_contract_paths,
    film_type_patch_path,
)

ROOT = Path(__file__).resolve().parents[2]


def test_active_profile_resolves_matching_patch_document() -> None:
    version = active_film_type_version(repo_root=ROOT)
    path = film_type_patch_path(repo_root=ROOT)
    assert version == "2.16.0"
    assert path.name == "persian-film-type-2.16-patch.md"
    assert path.is_file()


def test_pinned_213_resolves_its_own_patch() -> None:
    path = film_type_patch_path("2.13.0", repo_root=ROOT)
    assert path.name == "persian-film-type-2.13-patch.md"
    assert path.is_file()


def test_registered_current_contract_paths_exist() -> None:
    paths = film_type_contract_paths(repo_root=ROOT)
    assert {path.name for path in paths} == {
        "film-type.md",
        "persian-film-type-2.16-patch.md",
        "film-type-visual-regression.md",
    }
    assert all(path.is_file() for path in paths)


def test_missing_version_patch_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "styles" / "persian-footage").mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "styles" / "persian-footage" / "film-type.json").write_text(
        json.dumps({"profile": "film-type", "profileVersion": "9.9.0"}), encoding="utf-8"
    )
    with pytest.raises(FilmTypeDocumentationError, match="no matching patch document"):
        film_type_patch_path(repo_root=tmp_path)


def test_edit_director_uses_canonical_music_track_shape() -> None:
    text = (ROOT / "skills" / "pipelines" / "persian-footage" / "edit-director.md").read_text(encoding="utf-8")
    assert '"musicTrack": {' in text
    assert '"audio": {\n    "narration"' in text
    assert '"audio": {\n    "narration": "assets/audio/voiceover.mp3",\n    "music":' not in text
    assert "persian.acknowledgeUnknownMusicRisk" in text
