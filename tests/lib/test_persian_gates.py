"""Behaviour of the Persian pipeline's Python gates.

Two modules are covered: `lib.persian_cues` (reading-speed and clause-boundary cue
construction) and `lib.persian_assets` (the video-only footage gate).

The emphasis throughout is on the **rejections**. A gate that accepts good input is
easy to write and easy to verify by hand; a gate that reliably rejects bad input under
the conditions where the bad input is tempting is the part that earns its tests. So
each rejection case below names the situation in which an agent would plausibly produce
it.
"""

from __future__ import annotations

import pytest

from lib.persian_assets import (
    ImageFootageRejected,
    assert_orientation,
    assert_video_only,
    audit_asset_manifest,
)
from lib.persian_cues import (
    MAX_CUE_SECONDS,
    MAX_CUE_VISIBLE_CHARS,
    MIN_CUE_SECONDS,
    audit_cues,
    build_cues,
)
from lib.persian_text import visible_length


def _words(text: str, seconds_per_char: float = 0.06, start: float = 0.0) -> list[dict]:
    """Synthesize plausible word timings from a Persian sentence.

    Duration scales with visible length, so the resulting stream has the same
    density characteristics as real narration — which is what the cue builder's
    limits actually respond to.
    """
    words: list[dict] = []
    cursor = start
    for word in text.split():
        duration = max(0.12, visible_length(word) * seconds_per_char)
        words.append({"word": word, "start": round(cursor, 3), "end": round(cursor + duration, 3)})
        cursor += duration + 0.03
    return words


class TestCueConstruction:
    def test_cues_are_built_and_ordered(self) -> None:
        cues = build_cues(_words("سلام دوستان. امروز درباره‌ی تمرکز حرف می‌زنیم."))
        assert cues
        for earlier, later in zip(cues, cues[1:]):
            assert later.start_seconds >= earlier.end_seconds

    def test_overspeed_narration_is_reported_not_silently_repacked(self) -> None:
        """Density is a property of the narration, so grouping cannot fix it.

        Adding a word to a cue adds both its characters and its duration, so every cue
        converges on the narration's own rate. When that rate exceeds the ceiling, the
        honest outcome is a reported violation — not one-word cues, which would be
        over-speed *and* below the minimum duration.
        """
        text = " ".join(["می‌رود"] * 60)
        cues = build_cues(_words(text, seconds_per_char=0.02))

        # Cues are still packed to a sensible extent rather than fragmented.
        assert all(len(cue.words) > 1 for cue in cues)
        # And the violation is surfaced rather than hidden.
        problems = audit_cues(cues)
        assert any("chars/sec" in problem for problem in problems)

    def test_reading_speed_is_satisfied_at_a_normal_delivery_rate(self) -> None:
        """At a realistic narration pace, cues come out within the ceiling."""
        text = (
            "توجه، کمیاب‌ترین چیزی است که داریم. "
            "هر روز آن را خرج می‌کنیم و حساب‌ش را نگه نمی‌داریم."
        )
        cues = build_cues(_words(text, seconds_per_char=0.075))
        assert audit_cues(cues) == [], [c.text for c in cues]

    def test_no_cue_exceeds_the_character_ceiling(self) -> None:
        cues = build_cues(_words(" ".join(["کلمه"] * 80)))
        for cue in cues:
            assert visible_length(cue.text) <= MAX_CUE_VISIBLE_CHARS

    def test_no_cue_exceeds_the_duration_ceiling(self) -> None:
        cues = build_cues(_words(" ".join(["واژه"] * 40), seconds_per_char=0.3))
        for cue in cues:
            assert cue.duration <= MAX_CUE_SECONDS + 0.01

    def test_cues_prefer_to_end_on_clause_boundaries(self) -> None:
        """A cue ending mid-clause reads as an error even when the timing is right."""
        text = (
            "اول این جمله تمام می‌شود. "
            "دوم جمله‌ی دیگری شروع می‌شود. "
            "سوم و آخرین جمله اینجاست."
        )
        cues = build_cues(_words(text))
        terminators = (".", "؟", "!", "،", "؛", ":", "…")
        ending_on_boundary = sum(1 for cue in cues if cue.text.rstrip().endswith(terminators))
        assert ending_on_boundary >= len(cues) - 1, (
            f"only {ending_on_boundary}/{len(cues)} cues end on a clause boundary: "
            f"{[c.text for c in cues]}"
        )

    def test_short_cues_are_merged_away(self) -> None:
        """A sub-second cue is a flash, not text."""
        cues = build_cues(_words("بله. خیر. شاید. حتماً. البته."))
        # Every cue except possibly a forced final one clears the minimum.
        below = [c for c in cues if c.duration < MIN_CUE_SECONDS]
        assert not below, [(c.id, c.duration, c.text) for c in below]

    def test_zwnj_is_preserved_through_cue_construction(self) -> None:
        """The orthography must survive the grouping.

        Splitting and rejoining on whitespace is where ZWNJ gets lost, and losing it
        turns «می‌روم» into two words on screen.
        """
        cues = build_cues(_words("او می‌رود و نمی‌داند"))
        joined = " ".join(cue.text for cue in cues)
        assert "\u200c" in joined
        assert "می\u200cرود" in joined

    def test_digits_are_converted_to_persian(self) -> None:
        cues = build_cues(_words("سال 2024 بود"))
        joined = " ".join(cue.text for cue in cues)
        assert "۲۰۲۴" in joined
        assert "2024" not in joined

    def test_digit_conversion_can_be_disabled(self) -> None:
        cues = build_cues(_words("سال 2024 بود"), persian_digits=False)
        assert "2024" in " ".join(cue.text for cue in cues)

    def test_arabic_letters_are_folded(self) -> None:
        cues = build_cues(_words("كي مي‌رود"))
        joined = " ".join(cue.text for cue in cues)
        assert "ك" not in joined and "ي" not in joined
        assert "کی" in joined

    def test_word_timings_are_carried_into_props(self) -> None:
        """Karaoke needs per-word timings on the cue, in renderer key names."""
        cues = build_cues(_words("یک دو سه چهار"))
        props = cues[0].to_props()
        assert props["words"]
        for word in props["words"]:
            assert set(word) == {"text", "startSeconds", "endSeconds"}
            assert word["endSeconds"] >= word["startSeconds"]

    def test_empty_input_yields_no_cues(self) -> None:
        assert build_cues([]) == []

    def test_whitespace_only_words_are_dropped(self) -> None:
        cues = build_cues(
            [
                {"word": "  ", "start": 0.0, "end": 0.2},
                {"word": "سلام", "start": 0.2, "end": 0.8},
            ]
        )
        assert len(cues) == 1
        assert cues[0].text == "سلام"

    def test_missing_timing_raises_rather_than_dropping(self) -> None:
        """Silently dropping a word would shift every later cue out of sync."""
        with pytest.raises(ValueError, match="missing start/end"):
            build_cues([{"word": "سلام"}])

    def test_missing_text_raises(self) -> None:
        with pytest.raises(ValueError, match="neither 'word' nor 'text'"):
            build_cues([{"start": 0.0, "end": 1.0}])

    def test_both_key_spellings_are_accepted(self) -> None:
        """Callers should not have to know which transcriber produced the stream."""
        from_word = build_cues([{"word": "سلام", "start": 0.0, "end": 1.2}])
        from_text = build_cues([{"text": "سلام", "start": 0.0, "end": 1.2}])
        assert from_word[0].text == from_text[0].text


class TestCueAudit:
    def test_clean_cues_audit_clean(self) -> None:
        assert audit_cues(build_cues(_words("این یک جمله‌ی معمولی است."))) == []

    def test_audit_catches_an_overspeed_cue(self) -> None:
        """Hand-built cues bypass the builder's limits; the audit is the backstop."""
        from lib.persian_cues import PersianCue

        cue = PersianCue(
            id="cue-1",
            text="این جمله بسیار طولانی است و در زمان بسیار کوتاهی نمایش داده می‌شود",
            start_seconds=0.0,
            end_seconds=1.2,
        )
        problems = audit_cues([cue])
        assert any("chars/sec" in problem for problem in problems)

    def test_audit_catches_overlapping_cues(self) -> None:
        """Two overlapping cues render two glass panels on the same frame."""
        from lib.persian_cues import PersianCue

        problems = audit_cues(
            [
                PersianCue(id="a", text="یک", start_seconds=0.0, end_seconds=3.0),
                PersianCue(id="b", text="دو", start_seconds=2.0, end_seconds=5.0),
            ]
        )
        assert any("overlaps" in problem for problem in problems)

    def test_audit_catches_a_flash_cue(self) -> None:
        from lib.persian_cues import PersianCue

        problems = audit_cues(
            [PersianCue(id="a", text="سلام", start_seconds=0.0, end_seconds=0.3)]
        )
        assert any("flash" in problem for problem in problems)


class TestVideoOnlyGate:
    """«استفاده از فوتیج عکس ممنوع» — enforced, not merely stated."""

    def test_a_video_manifest_passes(self) -> None:
        assert_video_only({"assets": [{"beat_id": "b1", "kind": "video", "path": "a.mp4"}]})

    def test_declared_image_kind_is_rejected(self) -> None:
        with pytest.raises(ImageFootageRejected):
            assert_video_only({"assets": [{"beat_id": "b1", "kind": "image", "path": "a.mp4"}]})

    @pytest.mark.parametrize("extension", [".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"])
    def test_image_extension_is_rejected_even_when_kind_says_video(
        self, extension: str
    ) -> None:
        """The realistic case: a photo copied in with the kind field left alone."""
        with pytest.raises(ImageFootageRejected):
            assert_video_only(
                {"assets": [{"beat_id": "b1", "kind": "video", "path": f"a{extension}"}]}
            )

    @pytest.mark.parametrize(
        "tool", ["pexels_image", "pixabay_image", "flux_image", "nano_banana"]
    )
    def test_image_producing_tool_is_rejected(self, tool: str) -> None:
        """Provenance is checked too, so laundering the path is not enough."""
        with pytest.raises(ImageFootageRejected):
            assert_video_only(
                {"assets": [{"beat_id": "b1", "kind": "video", "path": "a.mp4", "tool": tool}]}
            )

    def test_alternate_path_fields_are_also_checked(self) -> None:
        """A manifest using `public_path` instead of `path` must not slip through."""
        with pytest.raises(ImageFootageRejected):
            assert_video_only(
                {"assets": [{"beat_id": "b1", "kind": "video", "public_path": "clips/a.png"}]}
            )

    def test_metadata_nesting_is_supported(self) -> None:
        """Artifacts sometimes carry the body under `metadata`."""
        with pytest.raises(ImageFootageRejected):
            assert_video_only(
                {"metadata": {"assets": [{"beat_id": "b1", "kind": "image", "path": "a.mp4"}]}}
            )

    def test_every_violation_is_reported_at_once(self) -> None:
        """Reporting one at a time would burn the stage's revision budget."""
        with pytest.raises(ImageFootageRejected) as excinfo:
            assert_video_only(
                {
                    "assets": [
                        {"beat_id": "b1", "kind": "image", "path": "a.mp4"},
                        {"beat_id": "b2", "kind": "video", "path": "b.jpg"},
                        {"beat_id": "b3", "kind": "video", "path": "c.mp4", "tool": "pexels_image"},
                    ]
                }
            )
        message = str(excinfo.value)
        assert "b1" in message and "b2" in message and "b3" in message

    def test_rejection_message_names_the_remedy(self) -> None:
        """The gate must say what to do instead, or it invites a workaround."""
        with pytest.raises(ImageFootageRejected) as excinfo:
            assert_video_only({"assets": [{"beat_id": "b1", "kind": "image", "path": "a.jpg"}]})
        message = str(excinfo.value)
        assert "typographic" in message
        assert "Do not" in message

    def test_unknown_extension_is_flagged_rather_than_assumed(self) -> None:
        with pytest.raises(ImageFootageRejected, match="neither"):
            assert_video_only({"assets": [{"beat_id": "b1", "kind": "video", "path": "a.xyz"}]})

    def test_empty_manifest_passes(self) -> None:
        """Nothing to reject. The 'no asset per beat' fault is the audit's job."""
        assert_video_only({"assets": []})


class TestAssetAudit:
    def _asset(self, **overrides) -> dict:
        base = {
            "beat_id": "b1",
            "kind": "video",
            "path": "a.mp4",
            "public_path": "clips/a.mp4",
            "duration_seconds": 12.0,
            "source_in_seconds": 0.0,
            "width": 1080,
            "height": 1920,
            "provider": "pexels",
            "original_url": "https://example.test/1",
            "license": "Pexels License",
            "attribution": "Video by Someone on Pexels",
        }
        base.update(overrides)
        return base

    def test_a_complete_manifest_audits_clean(self) -> None:
        manifest = {"assets": [self._asset()]}
        scene_plan = {"beats": [{"id": "b1", "duration_seconds": 5.0, "typographic": False}]}
        assert audit_asset_manifest(manifest, scene_plan) == []

    @pytest.mark.parametrize(
        "field", ["provider", "original_url", "license", "attribution"]
    )
    def test_missing_provenance_is_reported(self, field: str) -> None:
        """Both stock licences require attribution."""
        problems = audit_asset_manifest({"assets": [self._asset(**{field: None})]})
        assert any(field in problem for problem in problems)

    def test_missing_public_path_is_reported(self) -> None:
        """A clip outside public/ renders as a black beat with no error."""
        problems = audit_asset_manifest({"assets": [self._asset(public_path=None)]})
        assert any("public_path" in problem for problem in problems)

    def test_a_clip_reused_across_beats_is_reported(self) -> None:
        manifest = {
            "assets": [
                self._asset(beat_id="b1"),
                self._asset(beat_id="b2"),
            ]
        }
        problems = audit_asset_manifest(manifest)
        assert any("reuses" in problem for problem in problems)

    def test_a_clip_shorter_than_its_beat_is_reported(self) -> None:
        """The tail would render black."""
        manifest = {"assets": [self._asset(duration_seconds=3.0)]}
        scene_plan = {"beats": [{"id": "b1", "duration_seconds": 5.0}]}
        problems = audit_asset_manifest(manifest, scene_plan)
        assert any("renders black" in problem for problem in problems)

    def test_in_point_is_counted_against_usable_duration(self) -> None:
        """A late in-point can make a nominally long clip too short."""
        manifest = {"assets": [self._asset(duration_seconds=10.0, source_in_seconds=8.0)]}
        scene_plan = {"beats": [{"id": "b1", "duration_seconds": 5.0}]}
        problems = audit_asset_manifest(manifest, scene_plan)
        assert any("renders black" in problem for problem in problems)

    def test_a_beat_with_no_asset_is_reported(self) -> None:
        scene_plan = {"beats": [{"id": "b9", "duration_seconds": 5.0}]}
        problems = audit_asset_manifest({"assets": []}, scene_plan)
        assert any("b9" in problem and "no asset" in problem for problem in problems)

    def test_a_typographic_beat_with_footage_is_reported(self) -> None:
        """One of the two decisions is stale."""
        manifest = {"assets": [self._asset(beat_id="b1")]}
        scene_plan = {"beats": [{"id": "b1", "duration_seconds": 4.0, "typographic": True}]}
        problems = audit_asset_manifest(manifest, scene_plan)
        assert any("typographic" in problem for problem in problems)

    def test_a_typographic_beat_without_footage_is_clean(self) -> None:
        scene_plan = {"beats": [{"id": "b1", "duration_seconds": 4.0, "typographic": True}]}
        assert audit_asset_manifest({"assets": []}, scene_plan) == []

    def test_orientation_mismatch_is_reported_not_raised(self) -> None:
        """Sometimes a centred subject survives the crop — a judgement, not a rule."""
        manifest = {"assets": [self._asset(width=1920, height=1080)]}
        problems = assert_orientation(manifest, "vertical")
        assert any("landscape in a vertical" in problem for problem in problems)

    def test_matching_orientation_is_clean(self) -> None:
        assert assert_orientation({"assets": [self._asset()]}, "vertical") == []

    def test_unknown_dimensions_are_reported(self) -> None:
        manifest = {"assets": [self._asset(width=0, height=0)]}
        problems = assert_orientation(manifest, "vertical")
        assert any("dimensions unknown" in problem for problem in problems)
