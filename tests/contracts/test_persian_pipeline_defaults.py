"""The Persian pipeline decides engine and music by default instead of asking every run.

Mehran Shabani, 2026-09-27: each run stopped a few minutes in to ask "Remotion or
HyperFrames?" and "Pixabay music or something else?". Both have one real answer for this
pipeline. Remotion is the only runtime with the Persian text layer, and Pixabay music is the
licensed, key-free default. So the skills must state these defaults and say not to ask,
while keeping the audit trail (both runtimes logged) and honouring a user-named track.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PERSIAN = ROOT / "skills" / "pipelines" / "persian-footage"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_idea_director_locks_remotion_without_asking() -> None:
    body = _read(PERSIAN / "idea-director.md")
    assert "Remotion is the Persian pipeline's default engine. Do not ask" in body
    assert "مشکلی نیست؟" not in body, "the runtime line must be a statement, not a question"
    assert "render_runtime_selection" in body and "options_considered" in body
    assert "pipeline_default" in body


def test_idea_director_defaults_music_to_pixabay_unless_user_named_one() -> None:
    body = _read(PERSIAN / "idea-director.md")
    assert "## Music (default: Pixabay, do not ask)" in body
    assert "pixabay_music" in body
    assert "names a specific track, gives a link or a file path" in body


def test_asset_stage_selects_pixabay_music_without_asking() -> None:
    for path in (PERSIAN / "asset-director.md", PERSIAN / "references" / "asset-acquisition.md"):
        body = _read(path)
        assert "without asking" in body or "do not ask" in body, path


def test_agent_guide_names_the_pipeline_locked_exception() -> None:
    guide = _read(ROOT / "AGENT_GUIDE.md")
    assert "Exception (pipeline-locked runtime)" in guide
    assert "persian-footage" in guide
