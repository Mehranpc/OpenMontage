"""Prop construction for the Persian composition.

These tests exist because of one bug, and they are shaped by it.

`persian_compose` hands props to Remotion via `--props`, and Remotion **shallow-merges
those over the composition's `defaultProps`**. An omitted key is therefore not "unset";
it is inherited. The tool originally wrote `typographicBeats` only when the edit
decisions contained beats — an ordinary and reasonable-looking conditional — and the
composition defaulted to a demo fixture that had two beats spanning 0-18s. Every real
render inherited them, the typographic plate painted its opaque background over the
footage, and the render reported success. Eight text blocks were verified as correctly
rendered before anyone noticed the footage underneath was not there.

So the first property under test is not "the props are correct". It is **every optional
key that can paint is present**, whether or not it has content. A conditional that omits
such a key is the bug, and it is invisible in the props themselves: they are valid, they
are minimal, and they are wrong.

The second property is that retired keys are refused. `cues` and `hookText` both used to
paint; both are gone. Accepting either silently would let an edit stage that was never
updated produce a render whose text layer is simply absent — the props would look fine
and the video would have no type in it.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tools.video.persian_compose import PersianCompose

#: Keys that paint something and therefore must never be inheritable. A key here that
#: the tool omits gets whatever the composition's `defaultProps` says.
PAINTING_KEYS = ("shots", "moments", "typographicBeats")

#: Keys from the retired caption/hook design. Present in edit decisions means the edit
#: stage was not updated, which must fail loudly rather than render without text.
RETIRED_KEYS = ("cues", "hookText")


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
    """Minimal valid edit decisions: one attributed shot, one moment.

    Duration is 12s rather than the moment's own 3s because `audit_moments` measures
    text coverage against the runtime, and a 3-second video that is 3 seconds of text is
    100% covered — a legitimate failure that would make every test here fail for a
    reason none of them is about.
    """
    base: dict = {
        # Explicit Legacy opt-out: these tests pin design-independent gates
        # (staging, audio, plate windows), so they run the historical path
        # deliberately. New productions must carry a film-type design instead.
        "design": {"version": 2, "profile": "legacy"},
        "format": "vertical",
        "durationSeconds": 12.0,
        "shots": [
            {
                "id": "s1",
                "source": str(clip),
                "startSeconds": 0.0,
                "endSeconds": 12.0,
                "sourceInSeconds": 0.0,
                "camera": "none",
                "attribution": "Video by Someone on Pexels",
            }
        ],
        "moments": [
            {
                "id": "moment-1",
                "kind": "statement",
                "startSeconds": 0.4,
                "endSeconds": 4.4,
                "segments": [
                    {"role": "lead", "text": "پیام این ویدیو:"},
                    {"role": "hero", "text": "سلام دنیا"},
                ],
            }
        ],
    }
    base.update(overrides)
    return base


def _build(persian: dict, staging: Path) -> tuple[dict, list[str]]:
    return PersianCompose()._build_props(persian, staging, "run-test")


def test_shots_state_hard_cut_grammar_by_default(clip: Path, staging: Path) -> None:
    props, _ = _build(_persian(clip), staging)
    assert props["shots"][0]["transitionIn"] == "cut"


def test_explicit_hard_cut_survives_compose_boundary(clip: Path, staging: Path) -> None:
    persian = _persian(clip)
    persian["shots"][0]["transitionIn"] = "cut"
    props, _ = _build(persian, staging)
    assert props["shots"][0]["transitionIn"] == "cut"


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

    def test_shot_semantic_and_visual_event_ids_survive_props_build(
        self, clip: Path, staging: Path
    ) -> None:
        persian = _persian(clip)
        persian["shots"][0]["semanticBeatId"] = "beat-1"
        persian["shots"][0]["visualEventId"] = "beat-1-event-2"
        props, _ = _build(persian, staging)
        assert props["shots"][0]["semanticBeatId"] == "beat-1"
        assert props["shots"][0]["visualEventId"] == "beat-1-event-2"

    def test_absent_typographic_beats_become_an_empty_list(
        self, clip: Path, staging: Path
    ) -> None:
        """Not `None`, not missing: an empty list.

        This is the exact key whose omission hid the footage.
        """
        props, _ = _build(_persian(clip), staging)
        assert props["typographicBeats"] == []

    def test_present_typographic_beats_are_derived_from_overlapping_moments(
        self, clip: Path, staging: Path
    ) -> None:
        """The guard must not defeat the feature it guards.

        The plate window follows the type, not the authored numbers: the
        authored window (0-2s) only partly covers the moment (0.4-4.4s), so
        the props carry the moment's span and no empty plate outruns the text.
        """
        beats = [{"id": "b1", "startSeconds": 0.0, "endSeconds": 2.0}]
        props, _ = _build(_persian(clip, typographicBeats=beats), staging)
        assert props["typographicBeats"] == [
            {"id": "b1", "startSeconds": 0.4, "endSeconds": 4.4}
        ]

    def test_no_retired_key_reaches_the_props(
        self, clip: Path, staging: Path
    ) -> None:
        """The retired keys must not be forwarded even under another name."""
        props, _ = _build(_persian(clip), staging)
        for key in RETIRED_KEYS:
            assert key not in props


class TestRetiredKeysAreRefused:
    """A retired key means the caller is a stage that was never updated.

    Refused rather than ignored, because ignoring it produces exactly the outcome the
    caller was trying to avoid: `cues` present and dropped is a video whose entire text
    layer silently vanished, and the render succeeds.
    """

    def test_cues_are_refused(self, clip: Path, staging: Path) -> None:
        cues = [{"id": "cue-1", "startSeconds": 0.0, "endSeconds": 2.0, "text": "سلام"}]
        with pytest.raises(ValueError, match="cues"):
            _build(_persian(clip, cues=cues), staging)

    def test_the_cue_refusal_names_the_replacement(
        self, clip: Path, staging: Path
    ) -> None:
        """An error that does not say what to do instead gets worked around."""
        cues = [{"id": "cue-1", "startSeconds": 0.0, "endSeconds": 2.0, "text": "سلام"}]
        with pytest.raises(ValueError, match=r"\.srt"):
            _build(_persian(clip, cues=cues), staging)

    def test_hook_text_is_refused(self, clip: Path, staging: Path) -> None:
        with pytest.raises(ValueError, match="hookText"):
            _build(_persian(clip, hookText="این یک قلاب است"), staging)

    def test_an_empty_retired_key_is_tolerated(
        self, clip: Path, staging: Path
    ) -> None:
        """`cues: []` from a stage that emits the key unconditionally is harmless.

        Refusing it would fail a caller that is doing nothing wrong: an empty list paints
        nothing, so there is no fault to report.
        """
        props, _ = _build(_persian(clip, cues=[], hookText=""), staging)
        assert props["moments"]


class TestMomentAudit:
    """Pacing is enforced here, before any clip is staged.

    The composition asserts the same rules, but it does so when the browser mounts the
    tree — minutes into a render. Same fault, two orders of magnitude difference in what
    it costs to find.
    """

    def test_an_empty_moment_list_is_refused(
        self, clip: Path, staging: Path
    ) -> None:
        with pytest.raises(ValueError, match="moments is empty"):
            _build(_persian(clip, moments=[]), staging)

    def test_moments_packed_below_the_gap_floor_are_refused(
        self, clip: Path, staging: Path
    ) -> None:
        """Two moments 0.2s apart are a caption track, whatever they are called."""
        moments = [
            {
                "kind": "statement",
                "startSeconds": 1.0,
                "endSeconds": 3.0,
                "segments": [
                    {"role": "hero", "text": "جملهٔ اول"},
                ],
            },
            {
                "kind": "statement",
                "startSeconds": 3.2,
                "endSeconds": 5.2,
                "segments": [
                    {"role": "hero", "text": "جملهٔ دوم"},
                ],
            },
        ]
        with pytest.raises(ValueError, match="empty frame"):
            _build(_persian(clip, moments=moments), staging)

    def test_wall_to_wall_text_is_refused(self, clip: Path, staging: Path) -> None:
        """Coverage is the rule a well-behaved caption track cannot satisfy."""
        moments = [
            {
                "kind": "statement",
                "startSeconds": index * 4.0,
                "endSeconds": index * 4.0 + 3.0,
                "segments": [{"role": "hero", "text": f"جملهٔ شمارهٔ {index}"}],
            }
            for index in range(3)
        ]
        with pytest.raises(ValueError, match="caption track"):
            _build(_persian(clip, moments=moments), staging)

    def test_a_figure_without_support_is_refused(
        self, clip: Path, staging: Path
    ) -> None:
        """A bare numeral reads as decoration rather than information.

        The slot model called this "a figure without a label"; the segment model
        says it more honestly — the phrase around the hero is missing, so nothing
        on screen says what the number counts. That is the frame rejected as
        «معلوم نیست در مورد چیه».
        """
        moments = [
            {
                "kind": "figure",
                "startSeconds": 1.0,
                "endSeconds": 4.0,
                "segments": [{"role": "hero", "text": "۲۲۶۴"}],
            }
        ]
        with pytest.raises(ValueError, match="lead or tail"):
            _build(_persian(clip, moments=moments), staging)

    def test_a_well_formed_moment_survives_with_persian_digits(
        self, clip: Path, staging: Path
    ) -> None:
        """The audit must not defeat the feature it guards."""
        moments = [
            {
                "kind": "figure",
                "startSeconds": 0.4,
                "endSeconds": 5.0,
                "segments": [
                    {"role": "lead", "text": "مطالعهٔ اولو روی"},
                    {"role": "hero", "text": "2264 نفر"},
                ],
            }
        ]
        props, _ = _build(_persian(clip, moments=moments), staging)
        assert props["moments"][0]["segments"][1]["text"] == "۲۲۶۴ نفر"

    def test_moments_are_sorted_by_start_time(
        self, clip: Path, staging: Path
    ) -> None:
        """Every pacing rule is about adjacency, which needs timeline order."""
        moments = [
            {
                "kind": "statement",
                "startSeconds": 6.0,
                "endSeconds": 9.0,
                "segments": [{"role": "hero", "text": "دومی"}],
            },
            {
                "kind": "statement",
                "startSeconds": 0.4,
                "endSeconds": 3.0,
                "segments": [{"role": "hero", "text": "اولی"}],
            },
        ]
        persian = _persian(clip, moments=moments)
        persian["durationSeconds"] = 20.0
        persian["shots"][0]["endSeconds"] = 20.0
        props, _ = _build(persian, staging)
        assert [m["segments"][0]["text"] for m in props["moments"]] == ["اولی", "دومی"]


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
        """Narration is staged — and in narrated mode the music gate now engages.

        A narration with no bed used to sail through compose and ship as silence
        under the voice's pauses; the gate now refuses it unless the silence is
        recorded as deliberate. The recorded-reason path is the one exercised
        here, so the staging behaviour under test stays the staging behaviour.
        """
        narration = tmp_path / "vo.wav"
        narration.write_bytes(b"\x00" * 32)
        props, _ = _build(
            _persian(
                clip,
                audio={"narration": str(narration)},
                omitMusicReason="test fixture: narration staging only",
            ),
            staging,
        )
        assert props["audio"]["narration"].startswith("persian/run-test/")

    def test_narration_without_a_bed_is_refused(
        self, clip: Path, staging: Path, tmp_path: Path
    ) -> None:
        """The shipped defect, now refused: silence under the voice was the default.

        Delivering with no bed and then asking «می‌خوای موزیک هم اضافه کنم؟» was
        called a catastrophe by the user, verbatim. The gate makes the silence
        impossible unless someone writes down why.
        """
        narration = tmp_path / "vo.wav"
        narration.write_bytes(b"\x00" * 32)
        with pytest.raises(ValueError, match="music bed"):
            _build(_persian(clip, audio={"narration": str(narration)}), staging)

    def test_a_music_record_is_staged_and_default_levels_added(
        self, clip: Path, staging: Path, tmp_path: Path
    ) -> None:
        """The record path carries provenance and gets its default fade.

        The fade is stated here rather than inherited from the renderer, because a
        default that lives in two places drifts apart in exactly one of them.
        """
        narration = tmp_path / "vo.wav"
        bed = tmp_path / "bed.mp3"
        narration.write_bytes(b"\x00" * 32)
        bed.write_bytes(b"\x00" * 32)
        persian = _persian(
            clip,
            audio={"narration": str(narration)},
            musicTrack={
                "path": str(bed),
                "source": "pixabay_music",
                "license": {
                    "name": "Pixabay Content License",
                    "url": "https://pixabay.com/music/",
                    "downloadedAt": "2026-09-02",
                },
                "contentIdRisk": {
                    "level": "low",
                    "reason": "Pixabay Content License permits monetized social use.",
                },
            },
        )
        props, _ = _build(persian, staging)
        assert props["audio"]["music"].startswith("persian/run-test/")
        assert props["audio"]["musicFadeSeconds"] == 1.5

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
