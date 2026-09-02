"""Prop construction for the Persian composition.

These tests exist because of one bug, and they are shaped by it.

`persian_compose` hands props to Remotion via `--props`, and Remotion **shallow-merges
those over the composition's `defaultProps`**. An omitted key is therefore not "unset";
it is inherited. The tool originally wrote `typographicBeats` only when the edit
decisions contained beats — an ordinary and reasonable-looking conditional — and the
composition defaulted to a demo fixture that had two beats spanning 0-18s. Every real
render inherited them, the typographic plate painted its opaque background over the
footage, and the render reported success. Eight cues were verified as correctly
rendered text before anyone noticed the footage underneath was not there.

So the property under test is not "the props are correct". It is **every optional key
that can paint is present**, whether or not it has content. A conditional that omits
such a key is the bug, and it is invisible in the props themselves: they are valid, they
are minimal, and they are wrong.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tools.video.persian_compose import PersianCompose

#: Keys that paint something and therefore must never be inheritable. A key here that
#: the tool omits gets whatever the composition's `defaultProps` says.
PAINTING_KEYS = ("shots", "cues", "typographicBeats", "hookText")


@pytest.fixture
def clip(tmp_path: Path) -> Path:
    """A file that exists, since `_stage` refuses to stage a missing one."""
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"\x00" * 64)
    return path


@pytest.fixture
def staging(tmp_path: Path) -> Path:
    return tmp_path / "staging"


def _persian(clip: Path, **overrides: object) -> dict:
    """Minimal valid edit decisions: one attributed shot, one cue."""
    base: dict = {
        "format": "vertical",
        "durationSeconds": 5.0,
        "shots": [
            {
                "id": "s1",
                "source": str(clip),
                "startSeconds": 0.0,
                "endSeconds": 5.0,
                "sourceInSeconds": 0.0,
                "camera": "none",
                "attribution": "Video by Someone on Pexels",
            }
        ],
        "cues": [
            {"id": "cue-1", "startSeconds": 0.5, "endSeconds": 3.0, "text": "سلام دنیا"}
        ],
    }
    base.update(overrides)
    return base


def _build(persian: dict, staging: Path) -> tuple[dict, list[str]]:
    return PersianCompose()._build_props(persian, staging, "run-test")


class TestNoKeyIsInheritable:
    @pytest.mark.parametrize("key", PAINTING_KEYS)
    def test_every_painting_key_is_stated_even_when_unused(
        self, key: str, clip: Path, staging: Path
    ) -> None:
        """The core guard.

        Nothing in these edit decisions mentions typographic beats or a hook, and both
        must still appear in the props — as empty — so neither can be inherited from
        `defaultProps`.
        """
        props, _ = _build(_persian(clip), staging)
        assert key in props, (
            f"'{key}' is absent from the props, so Remotion will take it from the "
            "composition's defaultProps. An inherited painting key covers the render "
            "without failing it."
        )

    def test_absent_typographic_beats_become_an_empty_list(
        self, clip: Path, staging: Path
    ) -> None:
        """Not `None`, not missing: an empty list.

        This is the exact key whose omission hid the footage.
        """
        props, _ = _build(_persian(clip), staging)
        assert props["typographicBeats"] == []

    def test_absent_hook_becomes_an_empty_string_with_zero_duration(
        self, clip: Path, staging: Path
    ) -> None:
        """A hook is full-width text over the footage — the same failure shape."""
        props, _ = _build(_persian(clip), staging)
        assert props["hookText"] == ""
        assert props["hookDurationSeconds"] == 0.0

    def test_present_typographic_beats_are_passed_through(
        self, clip: Path, staging: Path
    ) -> None:
        """The guard must not defeat the feature it guards."""
        beats = [{"id": "b1", "startSeconds": 0.0, "endSeconds": 2.0}]
        props, _ = _build(_persian(clip, typographicBeats=beats), staging)
        assert props["typographicBeats"] == beats

    def test_present_hook_is_passed_through_with_its_duration(
        self, clip: Path, staging: Path
    ) -> None:
        props, _ = _build(
            _persian(clip, hookText="این یک قلاب است", hookDurationSeconds=3.5), staging
        )
        assert props["hookText"] == "این یک قلاب است"
        assert props["hookDurationSeconds"] == 3.5


class TestShotStaging:
    def test_a_staged_source_is_a_public_relative_path(
        self, clip: Path, staging: Path
    ) -> None:
        """Remotion resolves it with `staticFile()`, which needs a relative path.

        An absolute path would work in the studio and fail in a render, because the
        render serves `public/` over HTTP rather than reading the filesystem.
        """
        props, _ = _build(_persian(clip), staging)
        source = props["shots"][0]["source"]
        assert not source.startswith("/")
        assert source.startswith("persian/run-test/")
        assert (staging / Path(source).name).exists()

    def test_two_clips_with_the_same_basename_do_not_collide(
        self, tmp_path: Path, staging: Path
    ) -> None:
        """Staging is flat, so `a/clip.mp4` and `b/clip.mp4` would overwrite.

        The second clip would silently render as the first — a wrong video that plays
        perfectly.
        """
        sources = []
        for folder in ("a", "b"):
            directory = tmp_path / folder
            directory.mkdir()
            path = directory / "clip.mp4"
            path.write_bytes(folder.encode() * 32)
            sources.append(path)

        persian = _persian(sources[0])
        persian["shots"].append(
            {
                **persian["shots"][0],
                "id": "s2",
                "source": str(sources[1]),
                "startSeconds": 5.0,
                "endSeconds": 10.0,
            }
        )

        props, _ = _build(persian, staging)
        staged = [shot["source"] for shot in props["shots"]]
        assert staged[0] != staged[1]
        assert len(list(staging.iterdir())) == 2

    def test_a_missing_clip_is_refused(self, tmp_path: Path, staging: Path) -> None:
        """A missing clip renders as a black beat — valid output, wrong video."""
        with pytest.raises(FileNotFoundError, match="Media file not found"):
            _build(_persian(tmp_path / "absent.mp4"), staging)

    def test_a_shot_without_attribution_is_refused(
        self, clip: Path, staging: Path
    ) -> None:
        """Both stock licences require it; the render is the last place to catch it."""
        persian = _persian(clip)
        persian["shots"][0]["attribution"] = "  "
        with pytest.raises(ValueError, match="no attribution"):
            _build(persian, staging)

    def test_attributions_are_returned_in_shot_order(
        self, clip: Path, staging: Path
    ) -> None:
        """They go into the publish description, where order should match the cut."""
        persian = _persian(clip)
        persian["shots"].append(
            {
                **persian["shots"][0],
                "id": "s2",
                "attribution": "Video by Another on Pexels",
                "startSeconds": 5.0,
                "endSeconds": 10.0,
            }
        )
        _, attributions = _build(persian, staging)
        assert attributions == [
            "Video by Someone on Pexels",
            "Video by Another on Pexels",
        ]

    def test_a_shot_without_a_source_is_refused(
        self, clip: Path, staging: Path
    ) -> None:
        persian = _persian(clip)
        del persian["shots"][0]["source"]
        with pytest.raises(ValueError, match="no source path"):
            _build(persian, staging)


class TestAudioProps:
    def test_audio_is_absent_when_no_audio_is_supplied(
        self, clip: Path, staging: Path
    ) -> None:
        """Audio is the one optional key that may be omitted.

        It paints nothing, and the composition's own defaults for the music levels are
        the intended values — inheriting them is correct rather than dangerous.
        """
        props, _ = _build(_persian(clip), staging)
        assert "audio" not in props

    def test_narration_is_staged_like_footage(
        self, clip: Path, staging: Path, tmp_path: Path
    ) -> None:
        narration = tmp_path / "vo.wav"
        narration.write_bytes(b"\x00" * 32)
        props, _ = _build(
            _persian(clip, audio={"narration": str(narration)}), staging
        )
        assert props["audio"]["narration"].startswith("persian/run-test/")

    def test_music_levels_pass_through_as_floats(
        self, clip: Path, staging: Path
    ) -> None:
        props, _ = _build(
            _persian(
                clip,
                audio={
                    "musicBaseVolume": 0.6,
                    "musicDuckVolume": 0.36,
                    "musicFlatVolume": 0.5,
                },
            ),
            staging,
        )
        assert props["audio"]["musicBaseVolume"] == pytest.approx(0.6)
        assert props["audio"]["musicDuckVolume"] == pytest.approx(0.36)
        assert props["audio"]["musicFlatVolume"] == pytest.approx(0.5)


class TestFormatAndDuration:
    def test_format_defaults_to_vertical(self, clip: Path, staging: Path) -> None:
        persian = _persian(clip)
        del persian["format"]
        props, _ = _build(persian, staging)
        assert props["format"] == "vertical"

    def test_landscape_is_preserved(self, clip: Path, staging: Path) -> None:
        props, _ = _build(_persian(clip, format="landscape"), staging)
        assert props["format"] == "landscape"

    def test_duration_is_a_float(self, clip: Path, staging: Path) -> None:
        """`calculateMetadata` multiplies it by fps; an int string would break there."""
        props, _ = _build(_persian(clip, durationSeconds=60), staging)
        assert isinstance(props["durationSeconds"], float)
        assert props["durationSeconds"] == 60.0
