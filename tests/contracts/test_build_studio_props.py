"""The studio preview derives plate windows through the render's own rule.

scripts/build_studio_props.py mirrors PersianCompose._build_props for the
Remotion studio. It used to copy `typographicBeats` verbatim while the render
derives each plate window from the typography inside it, so studio and render
could disagree about where an opaque near-black plate sits. These tests pin
the script to the shared derivation: a wide authored window shrinks, and a
beat with no typography refuses.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.build_studio_props as studio_props


def _moment(moment_id: str, start: float, end: float, hero: str = "نور") -> dict:
    return {
        "id": moment_id,
        "kind": "statement",
        "startSeconds": start,
        "endSeconds": end,
        "segments": [
            {"role": "lead", "text": "پیام این ویدیو:"},
            {"role": "hero", "text": hero},
        ],
    }


def _persian(moments: list[dict], beats: list[dict]) -> dict:
    return {
        # Explicit Legacy opt-out (see test_persian_default_film_type.py):
        # the studio mirror pins the design-independent derivation rule.
        "design": {"version": 2, "profile": "legacy"},
        "format": "vertical",
        "durationSeconds": 20.0,
        "shots": [
            {
                "id": "s1",
                "source": "projects/coffee-hormones-fa/assets/clips/clip.mp4",
                "startSeconds": 0.0,
                "endSeconds": 20.0,
                "sourceInSeconds": 0.0,
                "camera": "none",
                "attribution": "Video by Someone on Pexels",
            }
        ],
        "moments": moments,
        "typographicBeats": beats,
    }


@pytest.fixture
def project_dir(tmp_path: Path, monkeypatch) -> Path:
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "composer").mkdir()
    monkeypatch.setattr(studio_props, "PROJECT", tmp_path)
    monkeypatch.setattr(studio_props, "COMPOSER", tmp_path / "composer")
    monkeypatch.setattr(studio_props, "STAGE", tmp_path / "stage")
    monkeypatch.setattr(studio_props, "stage_stable", lambda source, name: name)
    return tmp_path


def _run(project_dir: Path, persian: dict) -> dict:
    (project_dir / "artifacts" / "edit_decisions.json").write_text(
        json.dumps({"persian": persian}, ensure_ascii=False), encoding="utf-8"
    )
    studio_props.main()
    out = project_dir / "composer" / ".studio-props" / "coffee-hormones-fa.json"
    return json.loads(out.read_text(encoding="utf-8"))


def test_a_wide_authored_window_shrinks_to_the_type_span(
    project_dir: Path,
) -> None:
    moments = [_moment("moment-1", 0.4, 4.0), _moment("moment-2", 5.0, 8.0)]
    beats = [{"id": "beat-8", "startSeconds": 4.2, "endSeconds": 10.0}]
    props = _run(project_dir, _persian(moments, beats))
    assert props["typographicBeats"] == [
        {"id": "beat-8", "startSeconds": 5.0, "endSeconds": 8.0}
    ]


def test_a_beat_with_no_typography_refuses(project_dir: Path) -> None:
    moments = [_moment("moment-1", 0.4, 4.4)]
    beats = [{"id": "beat-9", "startSeconds": 10.0, "endSeconds": 14.0}]
    (project_dir / "artifacts" / "edit_decisions.json").write_text(
        json.dumps(
            {"persian": _persian(moments, beats)}, ensure_ascii=False
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="beat-9"):
        studio_props.main()


def test_no_beats_still_means_no_beats(project_dir: Path) -> None:
    props = _run(project_dir, _persian([_moment("moment-1", 0.4, 4.4)], []))
    assert props["typographicBeats"] == []
