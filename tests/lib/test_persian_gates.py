"""Behaviour of the Persian pipeline's Python gates.

Six modules are covered: `lib.persian_srt` (reading-speed and clause-boundary cue
construction for the sidecar subtitle file), `lib.persian_moments` (the segment
model, the reading-time model, and the pacing rules for the typographic layer),
`lib.persian_sync` (binding moments to the narration words they name),
`lib.persian_music` (the required bed and its licence record), `lib.persian_assets`
(the video-only footage gate), and `lib.persian_scenes` (the subject-anchor,
co-presence and banned-vocabulary rules that decide what the footage is *of*).

The emphasis throughout is on the **rejections**. A gate that accepts good input is
easy to write and easy to verify by hand; a gate that reliably rejects bad input under
the conditions where the bad input is tempting is the part that earns its tests. So
each rejection case below names the situation in which an agent would plausibly produce
it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.persian_assets import (
    ImageFootageRejected,
    assert_orientation,
    assert_video_only,
    audit_asset_manifest,
)
from lib.persian_moments import (
    BLOCK_SECONDS,
    FIXATION_SECONDS,
    HOOK_SILHOUETTE_MAX_RATIO,
    HOOK_SILHOUETTE_MIN_RATIO,
    MAX_TEXT_COVERAGE,
    MIN_GAP_SECONDS,
    MIN_SECONDS,
    READ_CPS,
    SOURCE_READ_WEIGHT,
    audit_moments,
    build_moments,
    is_claim_qualifier_hook,
    is_flat_display_hook,
    is_poster_stack_hook,
)
from lib.persian_music import (
    KNOWN_PERMISSIVE_LICENSES,
    PIXABAY_CONTENT_LICENSE,
    audit_music,
    build_music_track,
)
from lib.persian_scenes import (
    BANNED_QUERY_TERMS,
    MIN_SUBJECT_FRACTION,
    audit_opening_semantic_shots,
    audit_scene_plan,
)
from lib.persian_srt import (
    MAX_CUE_SECONDS,
    MAX_CUE_VISIBLE_CHARS,
    MIN_CUE_SECONDS,
    TimedWord as SrtTimedWord,
    _merge_short_groups,
    _rebalance_short_groups,
    audit_cues,
    build_cues,
    render_srt,
)
from lib.persian_sync import (
    ANCHOR_HOLD_SECONDS,
    ANCHOR_LEAD_IN_SECONDS,
    TimedWord,
    audit_sync,
    find_anchor_span,
    retime_moments,
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
        assert all(len(cue.text.split()) > 1 for cue in cues)
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
        cues = build_cues(_words("بله، خیر، شاید، حتماً، البته."))
        # Every cue except possibly a forced final one clears the minimum.
        below = [c for c in cues if c.duration < MIN_CUE_SECONDS]
        assert not below, [(c.id, c.duration, c.text) for c in below]

    def test_quoted_question_hard_boundary_survives_short_cue_repair(self) -> None:
        words = [
            {"word": "«چی", "start": 0.0, "end": 0.2},
            {"word": "باعث", "start": 0.2, "end": 0.4},
            {"word": "شده", "start": 0.4, "end": 0.6},
            {"word": "سخت؟»", "start": 0.6, "end": 0.8},
            {"word": "شاید", "start": 0.8, "end": 1.15},
            {"word": "دلیلش", "start": 1.15, "end": 1.55},
            {"word": "ترس", "start": 1.55, "end": 1.9},
            {"word": "باشه.", "start": 1.9, "end": 2.3},
        ]
        cues = build_cues(words, persian_digits=False, max_visible_chars=56)
        assert " ".join(cue.text for cue in cues) == " ".join(word["word"] for word in words)
        assert cues[0].text.endswith("سخت؟»")
        assert cues[1].text.startswith("شاید دلیلش")
        assert cues[0].duration < MIN_CUE_SECONDS

    def test_rebalance_does_not_borrow_across_a_strong_boundary(self) -> None:
        groups = [
            [
                SrtTimedWord("اول", 0.0, 1.3),
                SrtTimedWord("باشه؟", 1.3, 1.6),
            ],
            [
                SrtTimedWord("شاید", 1.6, 2.0),
                SrtTimedWord("دلیلش", 2.0, 2.4),
            ],
        ]
        repaired = _rebalance_short_groups(groups, max_visible_chars=56)
        assert repaired == groups

    def test_merge_does_not_cross_a_quoted_strong_boundary(self) -> None:
        groups = [
            [SrtTimedWord("باشه؟»", 0.0, 0.8)],
            [SrtTimedWord("شاید", 0.8, 1.4), SrtTimedWord("دلیلش", 1.4, 2.0)],
        ]
        assert _merge_short_groups(groups, max_visible_chars=56) == groups

    def test_tight_caption_budget_rebalances_boundary_instead_of_flashing(self) -> None:
        """A near-full neighbour should lend a word instead of forcing a 0.96s cue."""
        words = [
            {"word": "کم‌کم", "start": 23.42, "end": 24.30},
            {"word": "به", "start": 24.30, "end": 24.38},
            {"word": "چیزی", "start": 24.38, "end": 24.66},
            {"word": "تبدیل", "start": 24.66, "end": 25.02},
            {"word": "می‌شه", "start": 25.02, "end": 25.28},
            {"word": "که", "start": 25.28, "end": 25.46},
            {"word": "فقط", "start": 25.46, "end": 25.80},
            {"word": "برای", "start": 25.80, "end": 26.16},
            {"word": "گرفتن", "start": 26.16, "end": 26.58},
            {"word": "جایزه", "start": 26.58, "end": 27.06},
            {"word": "انجامش", "start": 27.06, "end": 27.44},
            {"word": "می‌دن.", "start": 27.44, "end": 27.74},
            {"word": "از", "start": 27.74, "end": 28.04},
            {"word": "طرفی،", "start": 28.04, "end": 28.40},
            {"word": "بچه", "start": 28.40, "end": 29.14},
            {"word": "ممکنه", "start": 29.14, "end": 29.50},
            {"word": "به", "start": 29.50, "end": 29.62},
            {"word": "پاداش", "start": 29.62, "end": 29.94},
            {"word": "عادت", "start": 29.94, "end": 30.30},
            {"word": "کنه", "start": 30.30, "end": 30.62},
            {"word": "و", "start": 30.62, "end": 30.90},
            {"word": "برای", "start": 30.90, "end": 31.16},
            {"word": "گرفتن", "start": 31.16, "end": 31.54},
            {"word": "همون", "start": 31.54, "end": 31.88},
            {"word": "نتیجه،", "start": 31.88, "end": 32.30},
        ]
        cues = build_cues(
            words, persian_digits=False, max_visible_chars=56
        )
        assert " ".join(cue.text for cue in cues) == " ".join(word["word"] for word in words)
        assert all(cue.duration >= MIN_CUE_SECONDS for cue in cues)
        assert all(visible_length(cue.text) <= 56 for cue in cues)
        assert not any("انجامش می‌دن. از طرفی،" in cue.text for cue in cues)
        boundary = next(i for i, cue in enumerate(cues) if cue.text.endswith("می‌دن."))
        assert cues[boundary + 1].text.startswith("از طرفی،")

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

    def test_word_timings_are_not_carried_on_the_cue(self) -> None:
        """Per-word timings existed for a karaoke cursor that no longer exists.

        Asserted as an absence rather than left untested: dead data that looks live is
        how a future reader concludes something depends on it.
        """
        cue = build_cues(_words("یک دو سه چهار"))[0]
        assert not hasattr(cue, "words")

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
        from lib.persian_srt import PersianCue

        cue = PersianCue(
            id="cue-1",
            text="این جمله بسیار طولانی است و در زمان بسیار کوتاهی نمایش داده می‌شود",
            start_seconds=0.0,
            end_seconds=1.2,
        )
        problems = audit_cues([cue])
        assert any("chars/sec" in problem for problem in problems)

    def test_audit_reports_internal_hard_sentence_boundary(self) -> None:
        from lib.persian_srt import PersianCue

        cue = PersianCue(
            id="a",
            text="«چی باعث شده سخت؟» شاید دلیلش ترس باشه",
            start_seconds=0.0,
            end_seconds=3.0,
        )
        problems = audit_cues([cue])
        assert any("hard sentence boundary" in problem for problem in problems)

    def test_audit_catches_overlapping_cues(self) -> None:
        """SRT consumers disagree about overlaps, so the file stops being portable."""
        from lib.persian_srt import PersianCue

        problems = audit_cues(
            [
                PersianCue(id="a", text="یک", start_seconds=0.0, end_seconds=3.0),
                PersianCue(id="b", text="دو", start_seconds=2.0, end_seconds=5.0),
            ]
        )
        assert any("overlaps" in problem for problem in problems)

    def test_audit_catches_a_flash_cue(self) -> None:
        from lib.persian_srt import PersianCue

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
    @pytest.fixture(autouse=True)
    def _clip_on_disk(self, tmp_path, monkeypatch):
        """A real file at the default asset's path.

        The audit checks that `path` resolves, because a path that does not is the
        black-beat fault it exists to catch. So the fixture has to create one — an
        audit that passes over a nonexistent file is not testing anything.
        """
        clip = tmp_path / "a.mp4"
        clip.write_bytes(b"\x00" * 64)
        monkeypatch.chdir(tmp_path)
        self._clip = clip

    def _asset(self, **overrides) -> dict:
        base = {
            "beat_id": "b1",
            "semantic_beat_id": "b1",
            "kind": "video",
            "path": "a.mp4",
            "duration_seconds": 12.0,
            "source_in_seconds": 0.0,
            "width": 1080,
            "height": 1920,
            "provider": "pexels",
            "original_url": "https://example.test/1",
            "license": "Pexels License",
            "attribution": "Video by Someone on Pexels",
            "narration_span": "هر روز صبح قهوه",
            "query": "coffee pour close up",
            "candidate_rank": 1,
            "selection_reason": "فنجان قهوه و دست در قاب دیده می‌شود",
            "relevance_reason": "عمل ریختن قهوه مستقیماً beat را نشان می‌دهد",
            "affect_match": True,
            "staged_stock_risk": "low",
            "human_presence": True,
            "shows_subject": True,
            "fallback_level": "exact_literal",
            "frame_review": {
                "start": True, "middle": True, "end": True,
                "observed": "قهوه و دست در کل پنجرهٔ انتخابی در قاب می‌مانند",
            },
        }
        base.update(overrides)
        return base

    def test_a_complete_manifest_audits_clean(self) -> None:
        manifest = {"assets": [self._asset()]}
        scene_plan = {"beats": [{"id": "b1", "duration_seconds": 5.0, "typographic": False}]}
        assert audit_asset_manifest(manifest, scene_plan) == []

    def test_visual_events_are_independently_sourced_inside_one_semantic_beat(self) -> None:
        second = self._clip.parent / "b.mp4"
        second.write_bytes(b"\x00" * 64)
        scene_plan = {
            "beats": [{
                "id": "b1",
                "duration_seconds": 5.0,
                "visual_events": [
                    {
                        "id": "b1-e1", "duration_seconds": 2.0,
                        "narration_span": "هر روز صبح قهوه",
                        "queries": ["coffee pour close up", "steam coffee cup"],
                        "desired_affect": "curiosity", "human_presence": True,
                        "shows_subject": True, "fallback_level": "exact_literal",
                        "importance": 2,
                    },
                    {
                        "id": "b1-e2", "duration_seconds": 3.0,
                        "narration_span": "هر روز صبح قهوه",
                        "queries": ["coffee pour close up", "hands coffee desk"],
                        "desired_affect": "recognition", "human_presence": True,
                        "shows_subject": True, "fallback_level": "exact_literal",
                        "importance": 1,
                    },
                ],
            }]
        }
        manifest = {"assets": [
            self._asset(beat_id="b1", semantic_beat_id="b1", visual_event_id="b1-e1", path="a.mp4"),
            self._asset(beat_id="b1", semantic_beat_id="b1", visual_event_id="b1-e2", path="b.mp4"),
        ]}
        assert audit_asset_manifest(manifest, scene_plan) == []

    def test_explicit_visual_event_assets_must_name_the_event(self) -> None:
        scene_plan = {
            "beats": [{
                "id": "b1",
                "duration_seconds": 5.0,
                "visual_events": [{
                    "id": "b1-e1", "duration_seconds": 5.0,
                    "narration_span": "هر روز صبح قهوه",
                    "queries": ["coffee pour close up", "steam coffee cup"],
                    "desired_affect": "curiosity", "human_presence": True,
                    "shows_subject": True, "fallback_level": "exact_literal",
                    "importance": 2,
                }],
            }]
        }
        problems = audit_asset_manifest({"assets": [self._asset()]}, scene_plan)
        assert any("missing visual_event_id" in problem for problem in problems)
        assert any("b1-e1: no asset" in problem for problem in problems)

    def _explicit_scene_plan(self, **event_overrides) -> dict:
        event = {
            "id": "b1-e1", "duration_seconds": 5.0,
            "narration_span": "هر روز صبح قهوه",
            "queries": ["coffee pour close up", "steam coffee cup"],
            "desired_affect": "curiosity", "human_presence": True,
            "shows_subject": True, "fallback_level": "exact_literal",
            "importance": 2,
        }
        event.update(event_overrides)
        return {"beats": [{"id": "b1", "duration_seconds": 5.0, "visual_events": [event]}]}

    @pytest.mark.parametrize(
        "field",
        [
            "semantic_beat_id", "narration_span", "query", "candidate_rank",
            "selection_reason", "relevance_reason", "affect_match",
            "staged_stock_risk", "human_presence", "shows_subject",
            "source_in_seconds", "duration_seconds", "fallback_level", "frame_review",
        ],
    )
    def test_explicit_visual_event_assets_require_quality_evidence(self, field: str) -> None:
        asset = self._asset(visual_event_id="b1-e1")
        asset.pop(field)
        problems = audit_asset_manifest({"assets": [asset]}, self._explicit_scene_plan())
        assert any(field.split("_")[0] in problem or field in problem for problem in problems)

    def test_selected_query_must_come_from_the_event(self) -> None:
        asset = self._asset(visual_event_id="b1-e1", query="generic happy office people")
        problems = audit_asset_manifest({"assets": [asset]}, self._explicit_scene_plan())
        assert any("not one of the authored event queries" in problem for problem in problems)

    def test_wrong_affect_or_high_staged_stock_risk_is_rejected(self) -> None:
        asset = self._asset(
            visual_event_id="b1-e1", affect_match=False, staged_stock_risk="high"
        )
        problems = audit_asset_manifest({"assets": [asset]}, self._explicit_scene_plan())
        assert any("affect_match is false" in problem for problem in problems)
        assert any("staged_stock_risk is high" in problem for problem in problems)

    def test_human_presence_and_subject_must_survive_selection(self) -> None:
        asset = self._asset(
            visual_event_id="b1-e1", human_presence=False, shows_subject=False
        )
        problems = audit_asset_manifest({"assets": [asset]}, self._explicit_scene_plan())
        assert any("requires human presence" in problem for problem in problems)
        assert any("subject continuity was lost" in problem for problem in problems)

    def test_nonliteral_fallback_requires_reason_and_matches_plan(self) -> None:
        scene_plan = self._explicit_scene_plan(fallback_level="adjacent_metaphor")
        asset = self._asset(visual_event_id="b1-e1", fallback_level="adjacent_metaphor")
        problems = audit_asset_manifest({"assets": [asset]}, scene_plan)
        assert any("fallback_reason" in problem for problem in problems)
        asset["fallback_reason"] = "literal and emotional-human candidates were unusable after inspection"
        assert audit_asset_manifest({"assets": [asset]}, scene_plan) == []

    def test_frame_review_requires_start_middle_end_and_observation(self) -> None:
        asset = self._asset(
            visual_event_id="b1-e1",
            frame_review={"start": True, "middle": False, "end": True, "observed": ""},
        )
        problems = audit_asset_manifest({"assets": [asset]}, self._explicit_scene_plan())
        assert any("frame_review.middle" in problem for problem in problems)
        assert any("frame_review.observed" in problem for problem in problems)

    @pytest.mark.parametrize(
        "field", ["provider", "original_url", "license", "attribution"]
    )
    def test_missing_provenance_is_reported(self, field: str) -> None:
        """Both stock licences require attribution."""
        problems = audit_asset_manifest({"assets": [self._asset(**{field: None})]})
        assert any(field in problem for problem in problems)

    def test_reward_opening_asset_requires_direction_match_and_dense_frame_review(self) -> None:
        scene_plan = self._explicit_scene_plan(
            narrative_role="hook", semantic_role="reward_problem_hook",
            semantic_direction="child_resistance",
        )
        asset = self._asset(
            visual_event_id="b1-e1", semantic_role="reward_problem_hook",
            semantic_direction="child_resistance", opening_semantic_match=True,
            frame_review={
                "start": True, "middle": True, "midpoint_before_1_5": True,
                "at_3_seconds": True, "end": True,
                "observed": "کودک در حضور والد از انجام کار مقاومت نشان می‌دهد",
            },
        )
        assert audit_asset_manifest({"assets": [asset]}, scene_plan) == []
        asset["semantic_direction"] = "child_to_parent_gift"
        problems = audit_asset_manifest({"assets": [asset]}, scene_plan)
        assert any("semantic_direction must preserve" in problem for problem in problems)

    def test_reward_opening_asset_rejects_missing_three_second_sample(self) -> None:
        scene_plan = self._explicit_scene_plan(
            narrative_role="hook", semantic_role="reward_problem_hook",
            semantic_direction="child_distress",
        )
        asset = self._asset(
            visual_event_id="b1-e1", semantic_role="reward_problem_hook",
            semantic_direction="child_distress", opening_semantic_match=True,
            frame_review={
                "start": True, "middle": True, "midpoint_before_1_5": True,
                "end": True, "observed": "کودک ناراحت و والد در قاب است",
            },
        )
        problems = audit_asset_manifest({"assets": [asset]}, scene_plan)
        assert any("frame_review.at_3_seconds" in problem for problem in problems)

    def test_public_path_is_not_required(self) -> None:
        """It was required, and nothing read it.

        `persian_compose._stage()` copies each shot's `source` into
        `public/persian/<run-id>/` at render time and deletes the directory afterwards;
        it never reads `public_path`. The coffee run recorded `clips/pexels_*.mp4` for
        all twelve assets, nothing was ever written to `public/clips/`, and the video
        rendered correctly — so the field was inert and the check taught the stage to
        satisfy a requirement instead of a need.
        """
        scene_plan = {"beats": [{"id": "b1", "duration_seconds": 5.0}]}
        assert audit_asset_manifest({"assets": [self._asset()]}, scene_plan) == []

    def test_a_path_that_does_not_exist_is_reported(self) -> None:
        """The real black-beat fault, which the `public_path` check displaced.

        `persian_compose` raises `FileNotFoundError` on a missing file — but only at
        compose time, after the edit stage has been approved. Catching it here costs
        nothing; catching it there costs two gates and a render.
        """
        problems = audit_asset_manifest({"assets": [self._asset(path="absent.mp4")]})
        assert any("does not exist" in problem for problem in problems)

    def test_an_asset_with_no_path_at_all_is_reported(self) -> None:
        asset = self._asset()
        del asset["path"]
        problems = audit_asset_manifest({"assets": [asset]})
        assert any("no path" in problem for problem in problems)

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


    def test_nasa_is_outside_the_persian_provider_allowlist(self) -> None:
        problems = audit_asset_manifest(
            {"assets": [self._asset(provider="nasa")]}
        )
        assert any("outside the Persian production allowlist" in p for p in problems)

    @pytest.mark.parametrize("provider", ["pexels", "pixabay", "pixabay_video"])
    def test_approved_persian_video_providers_pass(self, provider: str) -> None:
        problems = audit_asset_manifest(
            {"assets": [self._asset(provider=provider)]}
        )
        assert not any("provider" in p and "allowlist" in p for p in problems)


class TestSrtRendering:
    """The sidecar file itself. Every assertion here is a real player's requirement."""

    def test_a_cue_becomes_a_numbered_block(self) -> None:
        srt = render_srt(build_cues(_words("سلام دنیا.")))
        assert srt.startswith("1\r\n")
        assert " --> " in srt

    def test_numbering_is_contiguous(self) -> None:
        """Several players stop parsing at the first non-sequential index.

        Silently — the captions simply end there, which looks like a truncated file
        rather than a numbering bug.
        """
        cues = build_cues(_words("جملهٔ اول. جملهٔ دوم. جملهٔ سوم. جملهٔ چهارم."))
        numbers = [
            int(line)
            for line in render_srt(cues).splitlines()
            if line.strip().isdigit() and "-->" not in line
        ]
        assert numbers == list(range(1, len(cues) + 1))

    def test_timestamps_use_a_comma_and_three_millisecond_digits(self) -> None:
        srt = render_srt(build_cues(_words("سلام دنیا.")))
        stamp = srt.splitlines()[1].split(" --> ")[0]
        assert len(stamp) == 12 and stamp[8] == "," and stamp[2] == stamp[5] == ":"

    def test_no_bidi_control_is_injected(self) -> None:
        """RLM looks helpful and is not.

        The bidi algorithm already derives direction from the first strong character,
        and some players paint the mark as a visible box while others hand it to a
        translation service as part of the text.
        """
        srt = render_srt(build_cues(_words("سلام دنیا.")))
        assert "\u200f" not in srt and "\u202b" not in srt

    def test_zwnj_survives_into_the_file(self) -> None:
        """ZWNJ is orthography, not formatting — «می‌رود» is one word."""
        assert "\u200c" in render_srt(build_cues(_words("او می‌رود.")))

    def test_truncated_milliseconds_cannot_recreate_an_overlap(self) -> None:
        """Rounding up would push a cue's end past the next cue's start.

        Consecutive cues are separated by `CUE_GAP_SECONDS`, which is under one
        millisecond, so rounding reintroduces the overlap in the output file only —
        where `audit_cues` can no longer see it.
        """
        cues = build_cues(_words("جملهٔ اول. جملهٔ دوم. جملهٔ سوم."))
        stamps = [
            line.split(" --> ")
            for line in render_srt(cues).splitlines()
            if " --> " in line
        ]
        for (_, earlier_end), (later_start, _) in zip(stamps, stamps[1:]):
            assert earlier_end <= later_start


def _moment(**overrides: object) -> dict:
    """A well-formed statement moment in the segment model.

    One lead setting up one hero — the canonical shape. Tests override whatever
    their case needs; the defaults must always audit clean so a failure means the
    thing under test, not the fixture.
    """
    base: dict = {
        "kind": "statement",
        "startSeconds": 2.0,
        "endSeconds": 6.0,
        "segments": [
            {"role": "lead", "text": "نتیجهٔ مطالعه:"},
            {"role": "hero", "text": "قهوه فقط بیدارت نمی‌کنه"},
        ],
    }
    base.update(overrides)
    return base


def _figure(**overrides: object) -> dict:
    """The user's canonical figure: the lead above, the quantity with its unit below."""
    base: dict = {
        "kind": "figure",
        "startSeconds": 6.0,
        "endSeconds": 11.0,
        "segments": [
            {"role": "lead", "text": "مطالعهٔ دانشگاه اولوی فنلاند روی"},
            {"role": "hero", "text": "۲۲۶۴ نفر"},
        ],
    }
    base.update(overrides)
    return base


class TestMomentConstruction:
    def test_moments_are_sorted_by_start(self) -> None:
        """Every pacing rule is about adjacency, which is meaningless unsorted."""
        moments = build_moments(
            [
                _moment(
                    startSeconds=8.0,
                    endSeconds=12.0,
                    segments=[{"role": "hero", "text": "دومی"}],
                ),
                _moment(
                    startSeconds=2.0,
                    endSeconds=6.0,
                    segments=[{"role": "hero", "text": "اولی"}],
                ),
            ]
        )
        assert [m.hero.text for m in moments] == ["اولی", "دومی"]  # type: ignore[union-attr]

    def test_both_timing_spellings_are_accepted(self) -> None:
        from_camel = build_moments([_moment()])
        from_snake = build_moments(
            [
                {
                    "kind": "statement",
                    "start": 2.0,
                    "end": 6.0,
                    "segments": [{"role": "hero", "text": "سلام"}],
                }
            ]
        )
        assert from_camel[0].start_seconds == from_snake[0].start_seconds

    def test_an_unknown_kind_is_refused(self) -> None:
        """The kind is editorial metadata — but it is still required metadata."""
        with pytest.raises(ValueError, match="kind"):
            build_moments([_moment(kind="headline")])

    def test_missing_timing_is_refused(self) -> None:
        with pytest.raises(ValueError, match="missing timing"):
            build_moments(
                [{"kind": "statement", "segments": [{"role": "hero", "text": "سلام"}]}]
            )

    def test_retired_keys_are_refused_outright(self) -> None:
        """Each retired key implies the slot arrangement the user rejected.

        An agent migrating an old artifact will reach for these first, so the
        refusal must name the shape it refuses and say what to do instead.
        """
        for key, value in (
            ("text", "۲۲۶۴"),
            ("label", "مطالعهٔ اولو"),
            ("kicker", "نتیجهٔ اصلی"),
            ("unit", "نفر"),
        ):
            with pytest.raises(ValueError, match="retired key"):
                build_moments([_moment(**{key: value})])

    def test_a_retired_key_is_refused_even_when_segments_are_present(self) -> None:
        """Half-migrated input — segments plus a leftover satellite — is still refused.

        This is the tempting shape: an old artifact edited until it *looks* new. A
        warning here would let the slot model survive inside the new one.
        """
        with pytest.raises(ValueError, match="retired key"):
            build_moments([_moment(unit="نفر")])

    def test_segments_are_required(self) -> None:
        with pytest.raises(ValueError, match="no segments"):
            build_moments([{"kind": "statement", "startSeconds": 2.0, "endSeconds": 6.0}])

    def test_an_unknown_role_is_refused(self) -> None:
        with pytest.raises(ValueError, match="role"):
            build_moments(
                [_moment(segments=[{"role": "headline", "text": "سلام"}])]
            )

    def test_an_empty_segment_is_refused(self) -> None:
        """An empty segment reserves vertical space and paints nothing."""
        with pytest.raises(ValueError, match="no text"):
            build_moments([_moment(segments=[{"role": "hero", "text": "  "}])])

    def test_a_negative_reveal_is_refused(self) -> None:
        with pytest.raises(ValueError, match="revealAfterSeconds"):
            build_moments(
                [
                    _moment(
                        segments=[
                            {"role": "hero", "text": "۴۶ سال"},
                            {
                                "role": "lead",
                                "text": "با پیگیری",
                                "revealAfterSeconds": -1.0,
                            },
                        ]
                    )
                ]
            )

    def test_digits_become_persian(self) -> None:
        moments = build_moments(
            [
                _figure(
                    segments=[
                        {"role": "lead", "text": "مطالعهٔ اولوی فنلاند روی"},
                        {"role": "hero", "text": "2264 نفر"},
                    ]
                )
            ]
        )
        hero = moments[0].hero
        assert hero is not None and hero.text == "۲۲۶۴ نفر"  # type: ignore[union-attr]

    def test_anchor_text_digits_are_left_alone(self) -> None:
        """The anchor names the SPOKEN words, and the transcriber spoke digits."""
        moments = build_moments([_moment(anchorText="روی 2264 فرد")])
        assert moments[0].anchor_text == "روی 2264 فرد"

    def test_arabic_letters_are_folded(self) -> None:
        """Normalization happens here because the renderer paints exactly these bytes."""
        moments = build_moments(
            [
                _moment(
                    segments=[
                        {"role": "lead", "text": "نتیجهٔ مطالعه:"},
                        {"role": "hero", "text": "كي مي‌رود"},
                    ]
                )
            ]
        )
        hero = moments[0].hero
        assert hero is not None
        assert "ك" not in hero.text and "ي" not in hero.text

    def test_props_carry_segments_in_authored_order(self) -> None:
        """The array order is the reading order — the renderer paints it verbatim."""
        props = build_moments([_figure()])[0].to_props()
        assert [segment["role"] for segment in props["segments"]] == ["lead", "hero"]
        assert props["segments"][0]["text"] == "مطالعهٔ دانشگاه اولوی فنلاند روی"
        assert props["segments"][1]["text"] == "۲۲۶۴ نفر"

    def test_a_zero_reveal_is_omitted_from_props(self) -> None:
        """Absent and zero mean the same thing; the props file stays minimal."""
        props = build_moments([_moment()])[0].to_props()
        assert "revealAfterSeconds" not in props["segments"][0]

    def test_an_authored_reveal_is_carried_into_props(self) -> None:
        props = build_moments(
            [
                _moment(
                    segments=[
                        {"role": "lead", "text": "میانگین سنی:"},
                        {"role": "hero", "text": "۴۶ سال"},
                        {
                            "role": "hero",
                            "text": "۱۲ ساله",
                            "revealAfterSeconds": 3.0,
                        },
                    ],
                    startSeconds=10.0,
                    endSeconds=18.0,
                )
            ]
        )[0].to_props()
        assert props["segments"][-1]["revealAfterSeconds"] == 3.0

    def test_anchor_text_is_carried_into_props(self) -> None:
        props = build_moments([_moment(anchorText="نتیجه عجیب")])[0].to_props()
        assert props["anchorText"] == "نتیجه عجیب"

    def test_a_missing_anchor_is_simply_absent(self) -> None:
        props = build_moments([_moment()])[0].to_props()
        assert "anchorText" not in props


class TestMomentAudit:
    def test_a_designed_set_audits_clean(self) -> None:
        """The canonical set: the user's figure, a term, a claim — all anchored."""
        moments = build_moments(
            [
                _moment(startSeconds=0.4, endSeconds=5.0),
                _figure(startSeconds=6.0, endSeconds=11.0),
                _moment(startSeconds=12.5, endSeconds=17.0),
            ]
        )
        assert audit_moments(moments, duration_seconds=66.0).problems == []

    def test_a_gap_below_the_floor_is_a_problem(self) -> None:
        """The gap floor is what makes the output structurally not a caption track."""
        moments = build_moments(
            [
                _moment(startSeconds=2.0, endSeconds=6.0),
                _moment(startSeconds=6.0 + MIN_GAP_SECONDS / 2, endSeconds=11.0),
            ]
        )
        problems = audit_moments(moments, duration_seconds=66.0).problems
        assert any("empty frame" in problem for problem in problems)

    def test_an_overlap_is_a_problem(self) -> None:
        moments = build_moments(
            [
                _moment(startSeconds=2.0, endSeconds=7.0),
                _moment(startSeconds=5.0, endSeconds=10.0),
            ]
        )
        assert any(
            "overlaps" in problem
            for problem in audit_moments(moments, duration_seconds=66.0).problems
        )

    def test_a_flash_moment_is_a_problem(self) -> None:
        moments = build_moments(
            [_moment(startSeconds=2.0, endSeconds=2.0 + MIN_SECONDS / 2)]
        )
        assert any(
            "flash" in problem
            for problem in audit_moments(moments, duration_seconds=66.0).problems
        )

    def test_a_moment_over_nine_seconds_stalls(self) -> None:
        from lib.persian_moments import MAX_SECONDS

        moments = build_moments([_moment(startSeconds=2.0, endSeconds=2.0 + MAX_SECONDS + 1)])
        assert any(
            "stalled" in problem
            for problem in audit_moments(moments, duration_seconds=66.0).problems
        )

    def test_wall_to_wall_text_exceeds_the_coverage_ceiling(self) -> None:
        """The one rule a well-behaved caption track cannot satisfy.

        Every individual moment here is legal: long enough to read, short enough not
        to stall, and properly spaced. Only their total coverage is wrong, which is
        exactly the failure mode a per-moment rule cannot catch.
        """
        moments = build_moments(
            [
                _moment(startSeconds=index * 4.5, endSeconds=index * 4.5 + 3.5)
                for index in range(12)
            ]
        )
        audit = audit_moments(moments, duration_seconds=60.0)
        assert audit.text_coverage > MAX_TEXT_COVERAGE
        assert any("caption track" in problem for problem in audit.problems)

    def test_a_moment_past_the_end_is_a_problem(self) -> None:
        moments = build_moments([_moment(startSeconds=60.0, endSeconds=64.0)])
        assert any(
            "past the video" in problem
            for problem in audit_moments(moments, duration_seconds=62.0).problems
        )

    def test_a_late_first_moment_is_a_problem(self) -> None:
        """Feeds autoplay muted: an empty opening is a blank first impression.

        The hook *layer* was deleted for being a second text layer, not for opening
        with type — so the refusal message must not read as "no hooks".
        """
        from lib.persian_moments import OPENING_MAX_START_SECONDS

        moments = build_moments(
            [
                _moment(startSeconds=OPENING_MAX_START_SECONDS + 1.5, endSeconds=6.5),
                _moment(startSeconds=10.0, endSeconds=14.0),
            ]
        )
        problems = audit_moments(moments, duration_seconds=66.0).problems
        assert any("first moment" in problem or "opening" in problem for problem in problems)

    def test_no_hero_is_a_problem(self) -> None:
        """Nothing emphasised is a caption, not a moment."""
        moments = build_moments(
            [
                _moment(
                    segments=[{"role": "lead", "text": "نتیجهٔ مطالعه:"}],
                )
            ]
        )
        assert any(
            "hero" in problem
            for problem in audit_moments(moments, duration_seconds=66.0).problems
        )

    def test_two_heroes_in_one_reveal_step_is_a_problem(self) -> None:
        """Two heroes arriving together compete; neither reads as the emphasis."""
        moments = build_moments(
            [
                _moment(
                    segments=[
                        {"role": "hero", "text": "۴۶ سال"},
                        {"role": "hero", "text": "۱۲ ساله"},
                    ],
                    startSeconds=2.0,
                    endSeconds=8.0,
                )
            ]
        )
        assert any(
            "hero" in problem
            for problem in audit_moments(moments, duration_seconds=66.0).problems
        )

    def test_one_hero_per_build_step_is_legal(self) -> None:
        """A build is two or three phrases arriving in turn; each needs its own emphasis.

        This is the additive case the user asked for — earlier lines stay and dim
        — and it must not be refused by the one-hero rule, which is per step.
        """
        moments = build_moments(
            [
                _moment(
                    startSeconds=2.0,
                    endSeconds=10.0,
                    segments=[
                        {"role": "lead", "text": "در مردها:"},
                        {"role": "hero", "text": "قند خون متعادل‌تر"},
                        {
                            "role": "lead",
                            "text": "و در همان گروه",
                            "revealAfterSeconds": 4.0,
                        },
                        {
                            "role": "hero",
                            "text": "تستوسترون آزاد بالاتر",
                            "revealAfterSeconds": 4.0,
                        },
                    ],
                )
            ]
        )
        audit = audit_moments(moments, duration_seconds=66.0)
        assert not [p for p in audit.problems if "hero" in p]

    def test_a_bare_figure_is_the_rejected_frame(self) -> None:
        """«۲۲۶۴» with nothing saying what it counts — «معلوم نیست در مورد چیه».

        The slot model could not enforce this because there was no sentence to
        check; the segment model refuses it because the phrase is missing.
        """
        moments = build_moments(
            [
                _figure(
                    segments=[{"role": "hero", "text": "۲۲۶۴"}],
                    startSeconds=0.4,
                    endSeconds=4.5,
                )
            ]
        )
        assert any(
            "lead" in problem or "tail" in problem
            for problem in audit_moments(moments, duration_seconds=66.0).problems
        )

    def test_a_bare_term_is_the_unglossed_acronym(self) -> None:
        """An unglossed acronym tells the viewer they missed something."""
        moments = build_moments(
            [
                _moment(
                    kind="term",
                    segments=[{"role": "hero", "text": "SHBG"}],
                    startSeconds=0.4,
                    endSeconds=4.5,
                )
            ]
        )
        assert any(
            "lead" in problem or "tail" in problem
            for problem in audit_moments(moments, duration_seconds=66.0).problems
        )

    def test_a_hero_over_thirty_chars_is_a_problem(self) -> None:
        """Past 30 characters the emphasis is a poster line that has not been cut."""
        moments = build_moments(
            [
                _moment(
                    segments=[
                        {"role": "lead", "text": "نتیجه:"},
                        {
                            "role": "hero",
                            "text": "کسایی که قهوهٔ بیشتری می‌خورن چربی بدنشون کمتره",
                        },
                    ],
                    startSeconds=2.0,
                    endSeconds=8.0,
                )
            ]
        )
        assert any(
            "hero" in problem
            for problem in audit_moments(moments, duration_seconds=66.0).problems
        )

    def test_two_sources_is_a_problem(self) -> None:
        moments = build_moments(
            [
                _moment(
                    segments=[
                        {"role": "lead", "text": "نتیجه:"},
                        {"role": "hero", "text": "۴۶ سال"},
                        {"role": "source", "text": "دانشگاه اولو"},
                        {"role": "source", "text": "Nutrients"},
                    ],
                    startSeconds=2.0,
                    endSeconds=8.0,
                )
            ]
        )
        assert any(
            "source" in problem
            for problem in audit_moments(moments, duration_seconds=66.0).problems
        )

    def test_a_source_not_last_is_a_problem(self) -> None:
        """A citation appended to the phrase interrupts it anywhere else."""
        moments = build_moments(
            [
                _moment(
                    segments=[
                        {"role": "source", "text": "دانشگاه اولو"},
                        {"role": "hero", "text": "۴۶ سال"},
                    ],
                    startSeconds=2.0,
                    endSeconds=8.0,
                )
            ]
        )
        assert any(
            "last" in problem
            for problem in audit_moments(moments, duration_seconds=66.0).problems
        )

    def test_reading_time_includes_the_lead(self) -> None:
        """A figure with a long lead needs longer than the figure alone suggests."""
        bare = build_moments(
            [
                _figure(
                    segments=[
                        {"role": "lead", "text": "شرکت‌کنندگان:"},
                        {"role": "hero", "text": "۲۲۶۴ نفر"},
                    ],
                    startSeconds=2.0,
                    endSeconds=6.0,
                )
            ]
        )[0]
        dressed = build_moments(
            [
                _figure(
                    segments=[
                        {
                            "role": "lead",
                            "text": "مطالعهٔ دانشگاه اولوی فنلاند روی شرکت‌کنندگانِ",
                        },
                        {"role": "hero", "text": "۲۲۶۴ نفر"},
                        {"role": "source", "text": "Nutrients, 2024"},
                    ],
                    startSeconds=2.0,
                    endSeconds=6.0,
                )
            ]
        )[0]
        assert dressed.min_read_seconds > bare.min_read_seconds

    def test_the_reading_floor_is_charged_not_just_characters(self) -> None:
        """Fixation + blocks are dead time the character count never saw.

        A moment whose characters fit in its duration with the old model but not
        with the fixation charge is the exact «بیش از حد سریع رد میشن» complaint.
        """
        moments = build_moments(
            [
                _moment(
                    segments=[
                        {"role": "lead", "text": "نتیجهٔ مطالعه:"},
                        {"role": "hero", "text": "۴۶ سال"},
                    ],
                    startSeconds=2.0,
                    endSeconds=3.9,  # 21 chars / 11cps = 1.9s: old model passes
                )
            ]
        )
        assert any(
            "needs" in problem
            for problem in audit_moments(moments, duration_seconds=66.0).problems
        )

    def test_a_reveal_that_outruns_the_moment_is_a_problem(self) -> None:
        """A build step that arrives with no time left to be read."""
        moments = build_moments(
            [
                _moment(
                    startSeconds=2.0,
                    endSeconds=6.0,
                    segments=[
                        {"role": "lead", "text": "در مردها:"},
                        {"role": "hero", "text": "قند خون متعادل‌تر"},
                        {
                            "role": "hero",
                            "text": "تستوسترون آزاد بالاتر",
                            "revealAfterSeconds": 5.5,
                        },
                    ],
                )
            ]
        )
        assert any(
            "reveal" in problem
            for problem in audit_moments(moments, duration_seconds=66.0).problems
        )

    def test_a_step_window_shorter_than_its_read_is_a_problem(self) -> None:
        """Each reveal step needs its own fixation and reading time, not a share."""
        moments = build_moments(
            [
                _moment(
                    startSeconds=2.0,
                    endSeconds=9.0,
                    segments=[
                        {"role": "lead", "text": "در مردها:"},
                        {"role": "hero", "text": "قند خون متعادل‌تر"},
                        {
                            "role": "lead",
                            "text": "و در همان گروه با پیگیری بلندمدت",
                            "revealAfterSeconds": 3.2,
                        },
                        {
                            "role": "hero",
                            "text": "تستوسترون آزاد بالاتر",
                            "revealAfterSeconds": 3.2,
                        },
                    ],
                )
            ]
        )
        problems = audit_moments(moments, duration_seconds=66.0).problems
        assert any("step" in problem or "needs" in problem for problem in problems)

    def test_a_sparse_set_is_advisory_not_a_failure(self) -> None:
        """Restraint is legitimate; a planning failure is not distinguishable by count.

        The single moment still opens the video — the opening rule is about the
        *first* frame saying something, not about density.
        """
        audit = audit_moments(
            build_moments([_moment(startSeconds=0.4, endSeconds=4.5)]),
            duration_seconds=66.0,
        )
        assert audit.problems == []
        assert any("per minute" in advisory for advisory in audit.advisories)

    def test_an_all_statement_set_is_advisory(self) -> None:
        """Figures set as running text read worst in exactly that arrangement."""
        moments = build_moments(
            [
                _moment(startSeconds=index * 6.0 + 0.5, endSeconds=index * 6.0 + 4.0)
                for index in range(4)
            ]
        )
        audit = audit_moments(moments, duration_seconds=66.0)
        assert any("statement" in advisory for advisory in audit.advisories)

    def test_an_empty_set_is_reported_as_an_advisory(self) -> None:
        audit = audit_moments([], duration_seconds=66.0)
        assert audit.problems == []
        assert any("no moments" in advisory for advisory in audit.advisories)

    def test_a_set_with_no_builds_earns_the_build_advisory(self) -> None:
        """Two facts that belong to one thought should accumulate, not replace."""
        moments = build_moments(
            [
                _moment(startSeconds=index * 6.0 + 0.5, endSeconds=index * 6.0 + 4.0)
                for index in range(6)
            ]
        )
        audit = audit_moments(moments, duration_seconds=66.0)
        assert any("build" in advisory for advisory in audit.advisories)

    def test_a_zero_duration_video_is_a_problem(self) -> None:
        """Coverage and density are undefined without the runtime."""
        audit = audit_moments(build_moments([_moment()]), duration_seconds=0.0)
        assert any("duration_seconds" in problem for problem in audit.problems)

    def test_density_above_the_band_is_a_problem_even_under_the_coverage_ceiling(self) -> None:
        """The second line of defence: brief flickering moments that satisfy coverage.

        Twelve 2.5s moments across 63s cover 48% — under the ceiling — while running
        11.4 per minute, above the 9.0 the model expects. The density ceiling is what
        catches them, because each moment is individually legal.
        """
        from lib.persian_moments import MAX_MOMENTS_PER_MINUTE

        moments = build_moments(
            [
                _moment(startSeconds=index * 4.0, endSeconds=index * 4.0 + 2.5)
                for index in range(12)
            ]
        )
        audit = audit_moments(moments, duration_seconds=63.0)
        assert audit.moments_per_minute > MAX_MOMENTS_PER_MINUTE
        assert any("moments per minute" in problem for problem in audit.problems)


class TestReadingModel:
    """The per-step reading model: fixation + chars/CPS + blocks.

    Each number below pins one term of the formula, because the formula is the
    fix for the measured complaint — moments that passed a pure-cps ceiling and
    still could not be read.
    """

    def test_the_formula_terms_are_the_tokens(self) -> None:
        assert FIXATION_SECONDS == 0.45
        assert READ_CPS == 11.0
        assert BLOCK_SECONDS == 0.3
        assert SOURCE_READ_WEIGHT == 0.5
        assert MIN_SECONDS == 2.4

    def test_a_single_block_step_costs_fixation_plus_chars(self) -> None:
        """One block, one fixation: the floor case of the formula."""
        hero_chars = visible_length("۴۶ سال")
        bare = build_moments(
            [
                _moment(
                    segments=[{"role": "hero", "text": "۴۶ سال"}],
                    startSeconds=0.4,
                    endSeconds=6.0,
                )
            ]
        )[0]
        assert bare.min_read_seconds == pytest.approx(
            max(MIN_SECONDS, FIXATION_SECONDS + hero_chars / READ_CPS)
        )

    def test_a_second_block_in_the_same_step_charges_block_seconds(self) -> None:
        """A lead above a hero is a second block the eye must land on.

        Both fixtures carry enough text to sit above the MIN_SECONDS floor, so the
        difference between them is the lead's term alone — not the difference
        between sitting above and below a floor.
        """
        lead = "میانگین سنی شرکت‌کنندگان در مطالعهٔ فنلاند:"
        bare = build_moments(
            [
                _moment(
                    segments=[
                        {"role": "hero", "text": "تستوسترون آزاد بالاتر گزارش شد"},
                    ]
                )
            ]
        )[0]
        dressed = build_moments(
            [
                _moment(
                    segments=[
                        {"role": "lead", "text": lead},
                        {"role": "hero", "text": "تستوسترون آزاد بالاتر گزارش شد"},
                    ]
                )
            ]
        )[0]
        assert dressed.min_read_seconds == pytest.approx(
            bare.min_read_seconds + visible_length(lead) / READ_CPS + BLOCK_SECONDS
        )
        assert bare.min_read_seconds > MIN_SECONDS  # the floor is not the answer

    def test_source_characters_are_weighted_not_free(self) -> None:
        """A citation is skimmed, not read — but it is still ink on the screen.

        Charged by exactly the weighted term, not the full reading rate; both
        fixtures clear the floor so the delta is the source's own charge.
        """
        hero = "تستوسترون آزاد بالاتر گزارش شد"
        plain = build_moments([_moment(segments=[{"role": "hero", "text": hero}])])[0]
        sourced = build_moments(
            [
                _moment(
                    segments=[
                        {"role": "hero", "text": hero},
                        {"role": "source", "text": "دانشگاه اولو، ۲۰۲۴"},
                    ]
                )
            ]
        )[0]
        extra = (
            visible_length("دانشگاه اولو، ۲۰۲۴") * SOURCE_READ_WEIGHT / READ_CPS
        )
        assert sourced.min_read_seconds - plain.min_read_seconds == pytest.approx(extra)
        assert plain.min_read_seconds > MIN_SECONDS  # the floor is not the answer

    def test_min_read_never_drops_below_the_floor(self) -> None:
        moment = build_moments([_moment(segments=[{"role": "hero", "text": "۴"}])])[0]
        assert moment.min_read_seconds == pytest.approx(MIN_SECONDS)

    def test_steps_are_grouped_by_reveal_time(self) -> None:
        """A build is two or three reveals; each is a step with its own hero."""
        moment = build_moments(
            [
                _moment(
                    startSeconds=2.0,
                    endSeconds=10.0,
                    segments=[
                        {"role": "lead", "text": "میانگین سنی شرکت‌کنندگان:"},
                        {"role": "hero", "text": "۴۶ سال"},
                        {"role": "lead", "text": "با پیگیری", "revealAfterSeconds": 3.0},
                        {"role": "hero", "text": "۱۲ ساله", "revealAfterSeconds": 3.0},
                    ],
                )
            ]
        )[0]
        steps = moment.reveal_steps()
        assert len(steps) == 2
        assert [segment.role for segment in steps[0]] == ["lead", "hero"]
        assert [segment.role for segment in steps[1]] == ["lead", "hero"]

    def test_a_source_attaches_to_the_last_step_not_its_own(self) -> None:
        """The citation is on the whole moment, so it rides the final window."""
        moment = build_moments(
            [
                _moment(
                    startSeconds=2.0,
                    endSeconds=10.0,
                    segments=[
                        {"role": "hero", "text": "۴۶ سال"},
                        {"role": "lead", "text": "با پیگیری", "revealAfterSeconds": 3.0},
                        {"role": "source", "text": "دانشگاه اولو"},
                    ],
                )
            ]
        )[0]
        steps = moment.reveal_steps()
        assert len(steps) == 2
        assert [segment.role for segment in steps[1]] == ["lead", "source"]

    def test_a_build_sums_its_steps_and_the_authored_gaps(self) -> None:
        """min_read_seconds for a build: each step's cost plus the reveals between.

        A build that outruns its own timeline therefore reports *more* time than
        the moment has — which the audit turns into a fault rather than a fast
        frame.
        """
        lead_1, hero_1 = "میانگین سنی شرکت‌کنندگان:", "۴۶ سال"
        lead_2, hero_2 = "با پیگیری", "۱۲ ساله"
        moment = build_moments(
            [
                _moment(
                    startSeconds=2.0,
                    endSeconds=10.5,
                    segments=[
                        {"role": "lead", "text": lead_1},
                        {"role": "hero", "text": hero_1},
                        {"role": "lead", "text": lead_2, "revealAfterSeconds": 2.5},
                        {"role": "hero", "text": hero_2, "revealAfterSeconds": 2.5},
                    ],
                )
            ]
        )[0]
        chars = sum(visible_length(text) for text in (lead_1, hero_1, lead_2, hero_2))
        expected = (
            2 * FIXATION_SECONDS
            + chars / READ_CPS
            + 2 * BLOCK_SECONDS
            + 2.5
        )
        assert moment.min_read_seconds == pytest.approx(max(MIN_SECONDS, expected))


class TestSyncAudit:
    """Binding moments to the narration words they name.

    The predecessor of this module did not exist, and the shipped render is what that
    cost: timings authored for a *previous* narration and rescaled by the duration
    ratio, drifting up to 3.4s against the voice and passing every gate on the way.
    """

    @pytest.fixture
    def words(self) -> list[TimedWord]:
        rows = [
            {"word": "آیا", "start": 0.0, "end": 0.54},
            {"word": "تو", "start": 0.54, "end": 0.70},
            {"word": "هم", "start": 0.70, "end": 0.94},
            {"word": "مطالعهٔ", "start": 1.00, "end": 1.40},
            {"word": "دانشگاه", "start": 1.40, "end": 1.90},
            {"word": "اولو", "start": 1.90, "end": 2.40},
            {"word": "روی", "start": 2.40, "end": 2.80},
            {"word": "۲۲۶۴", "start": 2.80, "end": 3.40},
            {"word": "نفر", "start": 3.40, "end": 3.80},
        ]
        return TimedWord.from_dicts(rows)

    def _anchored_figure(self, **overrides: object) -> dict:
        base = _figure(
            anchorText="مطالعهٔ دانشگاه اولو روی ۲۲۶۴ نفر",
            startSeconds=0.75,
            endSeconds=5.1,
        )
        base.update(overrides)
        return base

    def test_an_anchor_phrase_is_located_in_the_word_stream(self, words) -> None:
        span = find_anchor_span(words, "مطالعهٔ دانشگاه اولو روی ۲۲۶۴ نفر")
        assert span is not None
        first, last = span
        assert words[first].word == "مطالعهٔ"
        assert words[last].word == "نفر"

    def test_a_hero_text_fallback_anchor_is_located(self, words) -> None:
        span = find_anchor_span(words, "۲۲۶۴ نفر")
        assert span is not None
        assert words[span[0]].word == "۲۲۶۴"

    def test_an_anchor_missing_from_the_narration_returns_none(self, words) -> None:
        """«خیار درختی» — the next video's subject, not this narration's words."""
        assert find_anchor_span(words, "خیار درختی") is None

    def test_an_empty_anchor_returns_none(self, words) -> None:
        assert find_anchor_span(words, "   ") is None

    def test_a_transcribed_spelling_still_matches_the_anchor(self, words) -> None:
        """«هورمون‌ها» spoken is often «هورمون ها» transcribed.

        Matching is done on `compare_key`, not string equality, for exactly this
        reason — the common words an anchor is made of are the ones transcribers
        rewrite.
        """
        rows = [
            {"word": "هورمون", "start": 0.0, "end": 0.5},
            {"word": "ها", "start": 0.5, "end": 0.8},
            {"word": "راستی", "start": 0.8, "end": 1.2},
        ]
        assert find_anchor_span(TimedWord.from_dicts(rows), "هورمون‌ها راستی") is not None

    def test_words_with_inverted_spans_are_dropped(self) -> None:
        """A zero or negative span is not a word anyone spoke."""
        words = TimedWord.from_dicts(
            [
                {"word": "سلام", "start": 1.0, "end": 0.5},
                {"word": "دنیا", "start": 0.6, "end": 1.2},
            ]
        )
        assert [timed.word for timed in words] == ["دنیا"]

    def test_a_set_that_matches_the_narration_audits_clean(self, words) -> None:
        moments = build_moments([self._anchored_figure()])
        audit = audit_sync(moments, words)
        assert audit.problems == []
        assert audit.bindings[0].matched_words[0] == "مطالعهٔ"

    def test_sync_audit_to_dict_serializes_its_own_bindings(self, words) -> None:
        moments = build_moments([self._anchored_figure()])
        audit = audit_sync(moments, words)
        payload = audit.to_dict()
        assert payload["passed"] is True
        assert payload["problems"] == []
        assert payload["bindings"][0]["momentId"] == moments[0].id
        assert payload["bindings"][0]["matched"][0] == "مطالعهٔ"

    def test_derived_start_back_leads_the_first_anchor_word(self, words) -> None:
        moments = build_moments([self._anchored_figure()])
        bindings = audit_sync(moments, words).bindings
        assert bindings[0].derived_start == pytest.approx(1.0 - ANCHOR_LEAD_IN_SECONDS)

    def test_derived_end_holds_past_the_last_anchor_word(self, words) -> None:
        moments = build_moments([self._anchored_figure()])
        bindings = audit_sync(moments, words).bindings
        assert bindings[0].derived_end >= 3.8 + ANCHOR_HOLD_SECONDS

    def test_derived_end_respects_reading_time_over_speech(self, words) -> None:
        """The phrase must be readable, not merely coextensive with its speech.

        A short anchor on a moment with long text: reading time extends the end
        past the speech, never shortens it.
        """
        moments = build_moments(
            [
                self._anchored_figure(
                    segments=[
                        {"role": "lead", "text": "مطالعهٔ هم‌گروهی با پیگیری طولانی روی"},
                        {"role": "hero", "text": "۲۲۶۴ نفر"},
                    ],
                )
            ]
        )
        bindings = audit_sync(moments, words).bindings
        assert bindings[0].derived_end == pytest.approx(
            bindings[0].derived_start + moments[0].min_read_seconds
        )

    def test_a_rescaled_timing_set_is_refused_as_drift(self, words) -> None:
        """The exact fault the module exists for.

        These are honest-looking numbers — properly spaced, properly ordered, all
        inside the video — moved 4.25s from where the words are actually spoken.
        The rescaled render shipped because nothing re-derived timings from the
        transcript; here the re-derivation is the gate.
        """
        moments = build_moments([self._anchored_figure(startSeconds=5.0, endSeconds=9.4)])
        problems = audit_sync(moments, words).problems
        assert any("starts at" in p and "a drift" in p for p in problems)

    def test_drift_at_the_limit_is_forgiven(self, words) -> None:
        """0.5s is the threshold a viewer forgives — a beat, not a failure."""
        from lib.persian_sync import MAX_START_DRIFT_SECONDS

        moments = build_moments([self._anchored_figure(startSeconds=1.25, endSeconds=5.6)])
        problems = audit_sync(moments, words).problems
        assert not any("drift" in problem for problem in problems)
        assert MAX_START_DRIFT_SECONDS == 0.5

    def test_an_anchor_that_matches_no_words_is_refused(self, words) -> None:
        """Either the anchor text is wrong for this voiceover, or the timings were
        authored against another narration entirely."""
        moments = build_moments([self._anchored_figure(anchorText="خیار درختی")])
        problems = audit_sync(moments, words).problems
        assert any("was not found in the narration word timings" in p for p in problems)

    def test_a_moment_with_no_anchor_and_no_hero_is_refused(self, words) -> None:
        moments = build_moments(
            [
                dict(
                    kind="statement",
                    startSeconds=0.4,
                    endSeconds=4.2,
                    segments=[{"role": "lead", "text": "فقط یک خط"}],
                )
            ]
        )
        problems = audit_sync(moments, words).problems
        assert any("no anchorText" in problem for problem in problems)

    def test_a_silent_project_skips_the_sync_audit_entirely(self) -> None:
        """No narration, no words, nothing to sync against — vacuous, not failed."""
        moments = build_moments([self._anchored_figure()])
        assert audit_sync(moments, []).problems == []

    def test_retime_moments_rederives_from_the_narration(self, words) -> None:
        """The edit stage's remedy: re-bind, do not nudge numbers by hand."""
        moments = build_moments([self._anchored_figure(startSeconds=5.0, endSeconds=9.4)])
        retimed = retime_moments(moments, words)
        assert retimed[0].start_seconds == pytest.approx(0.75)
        assert retimed[0].end_seconds == pytest.approx(0.75 + moments[0].min_read_seconds)
        # And the retimed set now passes its own audit.
        assert audit_sync(retimed, words).problems == []

    def test_retime_leaves_unlocatable_moments_alone(self, words) -> None:
        moments = build_moments(
            [self._anchored_figure(anchorText="خیار درختی", startSeconds=5.0, endSeconds=9.4)]
        )
        retimed = retime_moments(moments, words)
        assert retimed[0].start_seconds == 5.0

    def test_retime_preserves_everything_but_the_timing(self, words) -> None:
        moments = build_moments([self._anchored_figure()])
        retimed = retime_moments(moments, words)
        assert retimed[0].id == moments[0].id
        assert retimed[0].kind == moments[0].kind
        assert retimed[0].segments == moments[0].segments
        assert retimed[0].anchor_text == moments[0].anchor_text


class TestMusicGate:
    """The required bed, and the licence record that makes its safety checkable.

    The shipped render was delivered with narration and no music, followed by the
    question «می‌خوای موزیک هم اضافه کنم؟» — the edit's own job arriving late. These
    tests pin the gate that makes "optional music" impossible to ship silently.
    """

    def _track(self, **overrides: object) -> dict:
        base = {
            "path": "music/bed.mp3",
            "source": "pixabay_music",
            "license": {
                "name": "Pixabay Content License",
                "url": "https://pixabay.com/music/track/",
                "downloadedAt": "2026-09-01",
            },
            "attribution": "Music by Someone on Pixabay",
            "contentIdRisk": {
                "level": "low",
                "reason": "Pixabay publishes the licence on the track page.",
            },
        }
        base.update(overrides)
        return base

    def test_a_recorded_pixabay_bed_passes(self) -> None:
        audit = audit_music(track=build_music_track(self._track()), narrated=True)
        assert audit.problems == []

    def test_a_narrated_video_with_no_bed_is_a_problem(self) -> None:
        """«a narrated video has no music bed» — the shipped fault, verbatim."""
        audit = audit_music(track=None, narrated=True)
        assert any("no music bed" in problem for problem in audit.problems)

    def test_an_omitted_bed_with_a_recorded_reason_is_an_advisory(self) -> None:
        """An explicit decision, not a default silence — legitimate but on the record."""
        audit = audit_music(
            track=None, narrated=True, omit_music_reason="user supplied none"
        )
        assert audit.problems == []
        assert any("by recorded decision" in advisory for advisory in audit.advisories)

    def test_a_silent_project_may_ship_without_a_bed(self) -> None:
        assert audit_music(track=None, narrated=False).problems == []

    def test_missing_provenance_is_refused_at_build_time(self) -> None:
        """A record with a hole is "we did not check", dressed as data.

        The message must name every missing field, because the caller's remedy is
        to fill exactly those.
        """
        raw = self._track()
        del raw["license"]["downloadedAt"]
        with pytest.raises(ValueError, match="music record is missing .*downloadedAt"):
            build_music_track(raw)

        raw = self._track()
        del raw["license"]["url"]
        with pytest.raises(ValueError, match="music record is missing .*license.url"):
            build_music_track(raw)

        raw = self._track()
        del raw["source"]
        with pytest.raises(ValueError, match="music record is missing .*source"):
            build_music_track(raw)

    def test_a_high_risk_track_is_refused(self) -> None:
        """The one case that cannot be acknowledged away."""
        raw = self._track(
            contentIdRisk={"level": "high", "reason": "Contains recognizable sampled vocals."}
        )
        audit = audit_music(track=build_music_track(raw), narrated=True)
        assert any("high Content-ID risk" in problem for problem in audit.problems)

    def test_unknown_risk_requires_an_explicit_acknowledgement(self) -> None:
        raw = self._track(
            contentIdRisk={"level": "unknown", "reason": "Source does not publish terms."}
        )
        unacknowledged = audit_music(track=build_music_track(raw), narrated=True)
        assert any("unknown Content-ID risk" in p for p in unacknowledged.problems)

        acknowledged = audit_music(
            track=build_music_track(raw), narrated=True, acknowledge_unknown_risk=True
        )
        assert acknowledged.problems == []

    def test_low_risk_must_cite_a_known_permissive_licence(self) -> None:
        """A `low` judgement is only as good as the licence it names."""
        raw = self._track(
            license={"name": "Some Random Licence", "url": "u", "downloadedAt": "d"}
        )
        audit = audit_music(track=build_music_track(raw), narrated=True)
        assert any("claims low risk under licence" in problem for problem in audit.problems)

    def test_the_pixabay_terms_are_encoded_not_just_linked(self) -> None:
        """The audit's statements must be inspectable: permits AND forbids."""
        assert PIXABAY_CONTENT_LICENSE["name"] == "Pixabay Content License"
        assert any(
            "commercial" in permit or "social" in permit
            for permit in PIXABAY_CONTENT_LICENSE["permits"]
        )
        assert any(
            "redistribution" in forbid for forbid in PIXABAY_CONTENT_LICENSE["forbids"]
        )
        assert "Pixabay Content License" in KNOWN_PERMISSIVE_LICENSES


class TestSceneAudit:
    """The footage rules — the ones whose absence produced a video about a check-up.

    Every rule here existed as prose in `scene-director.md` and as a `review_focus` line
    in the manifest before it existed as a check. The prose was read: the repaired coffee
    plan was written directly against the rewritten skill, and it still shipped a
    `medication pills` query on the beat whose script says «دیابت». A beat that feels like
    the exception is exactly when prose loses, so the tests below are written from that
    angle — each one names the situation where an author would plausibly write the fault.
    """

    def _beat(self, index: int = 1, **overrides) -> dict:
        base = {
            "id": f"beat-{index}",
            "duration_seconds": 5.0,
            "camera": "push-in",
            "typographic": False,
            "shows_subject": True,
            "shot_scale": "close up",
            "environment": "kitchen",
            "queries": [
                "close up pouring coffee into cup morning",
                "steam rising from coffee cup kitchen",
            ],
        }
        base.update(overrides)
        return base

    def _event(self, index: int = 1, **overrides) -> dict:
        base = {
            "id": f"beat-1-event-{index}",
            "duration_seconds": 2.5,
            "narration_span": "هر روز صبح قهوه",
            "intent": "make the morning ritual concrete",
            "subject": "coffee",
            "action": "pouring coffee",
            "desired_affect": "curiosity",
            "motif": "morning ritual",
            "visual_search_brief": "real morning coffee ritual, tactile and unstaged",
            "shot_composition": "hands and cup dominate foreground; clean negative space above",
            "human_presence": True,
            "shot_scale": "close up",
            "environment": "kitchen",
            "camera": "push-in",
            "shows_subject": True,
            "fallback_level": "exact_literal",
            "importance": 1,
            "conflict_visibility": "none",
            "queries": ["coffee pour close up", "steam coffee cup"],
        }
        base.update(overrides)
        return base

    def _plan(self, beats: list[dict], subject: str = "coffee") -> dict:
        return {"metadata": {"subject": subject, "beats": beats}}

    def test_a_conforming_plan_audits_clean(self) -> None:
        beats = [
            self._beat(1),
            self._beat(2, shot_scale="overhead", environment="desk"),
            self._beat(3),
        ]
        audit = audit_scene_plan(self._plan(beats))
        assert audit["problems"] == []
        assert audit["subject_fraction"] == 1.0
        assert audit["footage_beats"] == 3

    def test_one_semantic_beat_can_expand_to_multiple_visual_events(self) -> None:
        beat = {
            "id": "beat-1",
            "duration_seconds": 5.0,
            "typographic": False,
            "visual_events": [
                self._event(1, duration_seconds=2.0),
                self._event(
                    2, duration_seconds=3.0, desired_affect="recognition",
                    camera="none", shot_scale="overhead", environment="desk",
                    action="holding coffee beside notebook", motif="work ritual",
                    queries=["coffee cup notebook desk", "hands coffee desk"],
                ),
            ],
        }
        audit = audit_scene_plan(self._plan([beat]))
        assert audit["problems"] == []
        assert audit["footage_beats"] == 1
        assert audit["visual_events"] == 2
        assert audit["uses_visual_events"] is True

    def test_visual_event_duration_and_affect_are_contract_fields(self) -> None:
        event = self._event(1, id="event-1", duration_seconds=4.0)
        event.pop("desired_affect")
        beat = {
            "id": "beat-1",
            "duration_seconds": 5.0,
            "visual_events": [event],
        }
        problems = audit_scene_plan(self._plan([beat]))["problems"]
        assert any("require desired_affect" in problem for problem in problems)
        assert any("does not match semantic beat duration" in problem for problem in problems)

    @pytest.mark.parametrize(
        "field",
        [
            "narration_span", "intent", "subject", "action", "motif",
            "visual_search_brief", "shot_composition", "conflict_visibility",
        ],
    )
    def test_visual_event_semantic_quality_fields_are_required(self, field: str) -> None:
        event = self._event(1, duration_seconds=5.0)
        event.pop(field)
        beat = {"id": "beat-1", "duration_seconds": 5.0, "visual_events": [event]}
        problems = audit_scene_plan(self._plan([beat]))["problems"]
        assert any(f"require {field}" in problem for problem in problems)

    def test_visual_event_human_fallback_and_importance_contract(self) -> None:
        event = self._event(1, duration_seconds=5.0)
        event["human_presence"] = "yes"
        event["fallback_level"] = "typography"
        event["importance"] = 4
        beat = {"id": "beat-1", "duration_seconds": 5.0, "visual_events": [event]}
        problems = audit_scene_plan(self._plan([beat]))["problems"]
        assert any("human_presence must be true or false" in problem for problem in problems)
        assert any("fallback_level must be one of" in problem for problem in problems)
        assert any("importance must be integer 1, 2, or 3" in problem for problem in problems)

    def test_importance_orders_the_bounded_retry_pass(self) -> None:
        beat = {
            "id": "beat-1", "duration_seconds": 5.0,
            "visual_events": [
                self._event(1, importance=1, duration_seconds=2.0),
                self._event(2, importance=3, duration_seconds=3.0, shot_scale="overhead",
                            environment="desk", action="holding coffee", motif="work",
                            queries=["coffee cup notebook desk", "hands coffee desk"]),
            ],
        }
        audit = audit_scene_plan(self._plan([beat]))
        assert audit["problems"] == []
        assert audit["sourcing_order"] == ["beat-1-event-2", "beat-1-event-1"]

    def test_emotional_affect_without_human_presence_is_an_advisory(self) -> None:
        event = self._event(1, duration_seconds=5.0, desired_affect="stress",
                            human_presence=False)
        beat = {"id": "beat-1", "duration_seconds": 5.0, "visual_events": [event]}
        audit = audit_scene_plan(self._plan([beat]))
        assert audit["problems"] == []
        assert any("usually benefits from human presence" in item for item in audit["advisories"])

    def test_reward_opening_event_requires_semantic_role_and_direction(self) -> None:
        event = self._event(
            1, duration_seconds=5.0, narrative_role="hook",
            semantic_role="reward_problem_hook", semantic_direction="child_to_parent_gift",
        )
        beat = {"id": "beat-1", "duration_seconds": 5.0, "visual_events": [event]}
        problems = audit_scene_plan(self._plan([beat]))["problems"]
        assert any("reward_problem_hook semantic_direction" in problem for problem in problems)

    def test_reward_opening_event_accepts_allowed_direction(self) -> None:
        event = self._event(
            1, duration_seconds=5.0, narrative_role="hook",
            semantic_role="reward_problem_hook", semantic_direction="child_resistance",
        )
        beat = {"id": "beat-1", "duration_seconds": 5.0, "visual_events": [event]}
        problems = audit_scene_plan(self._plan([beat]))["problems"]
        assert not any("reward_problem_hook" in problem for problem in problems)

    def test_final_opening_shot_requires_selection_evidence(self) -> None:
        shot = {
            "id": "s1", "visualEventId": "beat-1-event-1",
            "narrativeRole": "hook", "startSeconds": 0.0, "endSeconds": 3.0,
            "semanticRole": "reward_problem_hook", "semanticDirection": "parent_to_child_reward",
            "showsSubject": True, "humanPresence": True,
        }
        problems = audit_opening_semantic_shots([shot])
        assert any("openingSemanticMatch" in problem for problem in problems)
        assert any("selectionReason" in problem for problem in problems)
        shot.update({
            "openingSemanticMatch": True,
            "selectionReason": "والد در قاب جایزه را به کودک می‌دهد",
        })
        assert audit_opening_semantic_shots([shot]) == []

    def test_beats_are_read_from_either_shape(self) -> None:
        """Both shapes are in use, and a plan whose beats are invisible to the gate
        would report a clean audit of nothing — the worst possible failure mode."""
        beats = [self._beat(1), self._beat(2, shot_scale="wide", environment="gym")]
        nested = audit_scene_plan({"metadata": {"subject": "coffee", "beats": beats}})
        flat = audit_scene_plan({"beats": beats, "metadata": {"subject": "coffee"}})
        assert nested["footage_beats"] == flat["footage_beats"] == 2

    def test_an_empty_plan_is_a_problem_not_a_pass(self) -> None:
        audit = audit_scene_plan({"metadata": {"subject": "coffee", "beats": []}})
        assert any("no beats" in problem for problem in audit["problems"])

    # --- Anchor quota ---------------------------------------------------------------

    def test_a_first_beat_without_the_subject_is_reported(self) -> None:
        """The frame that sets what the video is about."""
        beats = [
            self._beat(1, shows_subject=False),
            self._beat(2, shot_scale="wide", environment="gym"),
        ]
        problems = audit_scene_plan(self._plan(beats))["problems"]
        assert any("first footage beat" in problem for problem in problems)

    def test_a_last_beat_without_the_subject_is_reported(self) -> None:
        """The frame the viewer remembers."""
        beats = [
            self._beat(1),
            self._beat(2, shows_subject=False, shot_scale="wide", environment="gym"),
        ]
        problems = audit_scene_plan(self._plan(beats))["problems"]
        assert any("last footage beat" in problem for problem in problems)

    def test_the_forty_percent_floor_is_enforced(self) -> None:
        """Where the check-up video actually lost: 2 of 8 beats showed coffee."""
        beats = [self._beat(1)]
        for index in range(2, 8):
            beats.append(
                self._beat(
                    index,
                    shows_subject=False,
                    shot_scale="wide" if index % 2 else "medium",
                    environment=f"place-{index}",
                )
            )
        beats.append(self._beat(8))
        audit = audit_scene_plan(self._plan(beats))
        assert audit["subject_fraction"] == 0.25
        assert any("floor on" in problem for problem in audit["problems"])

    def test_exactly_forty_percent_passes(self) -> None:
        """A floor, not a majority: the other beats have real work to do."""
        beats = [
            self._beat(1),
            self._beat(2, shows_subject=False, shot_scale="wide", environment="gym"),
            self._beat(3, shows_subject=False, shot_scale="medium", environment="street"),
            self._beat(4, shows_subject=False, shot_scale="overhead", environment="desk"),
            self._beat(5),
        ]
        audit = audit_scene_plan(self._plan(beats))
        assert audit["subject_fraction"] == 0.4
        assert not any("floor on" in problem for problem in audit["problems"])

    def test_typographic_beats_are_excluded_from_the_quota(self) -> None:
        """A beat with no footage cannot show the subject, and counting it as a
        failure would penalise the plan for using the typographic budget."""
        beats = [
            self._beat(1),
            self._beat(2, typographic=True, queries=[], shows_subject=False),
            self._beat(3, shot_scale="overhead", environment="desk"),
        ]
        audit = audit_scene_plan(self._plan(beats))
        assert audit["footage_beats"] == 2
        assert audit["problems"] == []

    def test_a_missing_shows_subject_is_a_problem(self) -> None:
        """It counts as false, so silence fails the quota rather than passing it."""
        beat = self._beat(1)
        del beat["shows_subject"]
        problems = audit_scene_plan(self._plan([beat]))["problems"]
        assert any("no shows_subject" in problem for problem in problems)

    # --- Banned vocabulary -----------------------------------------------------------

    @pytest.mark.parametrize(
        "query",
        [
            "doctor examining patient in clinic",
            "blood test vials laboratory",
            "dna strand rotating",
            "scientist looking into microscope",
            "woman measuring waist with measuring tape",
            "feet on bathroom scale weighing",
            "close up hands coffee cup medication pills table",
        ],
    )
    def test_stock_medical_vocabulary_is_rejected(self, query: str) -> None:
        """Each of these was in the first coffee run's query list."""
        beats = [self._beat(1, queries=[query, "steam rising from coffee cup kitchen"])]
        problems = audit_scene_plan(self._plan(beats))["problems"]
        assert any("banned stock-medical vocabulary" in problem for problem in problems)

    def test_the_real_pills_query_that_survived_the_rewritten_prose(self) -> None:
        """The regression this whole module exists for.

        `close up hands coffee cup medication pills table` was written for coffee beat-10
        *after* the banned-vocabulary rule was rewritten, by an author who had just read
        it, because the beat's script names diabetes and the beat felt exempt. It was not:
        the script names diabetes, not medication.
        """
        queries = [
            "coffee cup beside blood sugar monitor table",
            "close up hands coffee cup medication pills table",
        ]
        audit = audit_scene_plan(self._plan([self._beat(1, queries=queries)]))
        assert any("banned stock-medical vocabulary" in p for p in audit["problems"])

        # And the paired query is deliberately *not* banned. `blood sugar monitor` is the
        # skill's own co-presence example: the fault it illustrates is `glucose meter
        # check` — the monitor *instead of* the cup — which the substitution advisory
        # catches by noticing coffee is absent from the frame, not by banning a word.
        assert not any("blood sugar" in p for p in audit["problems"])

        # Declaring the exemption downgrades the pills query to an advisory. That is
        # correct and it is also the point: the flag cannot decide whether the script
        # really names the term, so it converts a block into something a human must read.
        exempt = audit_scene_plan(
            self._plan([self._beat(1, queries=queries, names_banned_term=True)])
        )
        assert exempt["problems"] == []
        assert len(exempt["advisories"]) == 1
        assert "co-presence, not substitution" in exempt["advisories"][0]

    def test_an_exempt_beat_still_gets_an_advisory(self) -> None:
        """«آزمایش خون» earns the term; it does not earn silence."""
        beats = [
            self._beat(1, queries=["blood test vial beside coffee cup", "coffee cup desk"], names_banned_term=True)
        ]
        audit = audit_scene_plan(self._plan(beats))
        assert audit["problems"] == []
        assert any("allowed because" in advisory for advisory in audit["advisories"])

    def test_the_match_is_case_insensitive(self) -> None:
        beats = [self._beat(1, queries=["DOCTOR with Stethoscope", "coffee cup"])]
        problems = audit_scene_plan(self._plan(beats))["problems"]
        assert any("banned" in problem for problem in problems)

    def test_every_banned_term_is_actually_caught(self) -> None:
        """The list and the matcher cannot drift apart.

        A term added to `BANNED_QUERY_TERMS` in a form the substring match never sees —
        `pills capsules`, the phrase the prose used and nobody types — is a rule that
        reads as enforced and is not.
        """
        for term in BANNED_QUERY_TERMS:
            beats = [self._beat(1, queries=[f"coffee cup and {term} on table", "coffee"])]
            problems = audit_scene_plan(self._plan(beats))["problems"]
            assert any(repr(term) in problem for problem in problems), term

    # --- Substitution ----------------------------------------------------------------

    def test_a_beat_that_leaves_the_subject_entirely_is_an_advisory(self) -> None:
        """Advisory, not a problem: the gym beat is legitimate and the quota bounds
        how many of them there can be."""
        beats = [
            self._beat(1),
            self._beat(
                2,
                shows_subject=False,
                shot_scale="wide",
                environment="gym",
                queries=["slow motion athlete rowing machine gym", "man running treadmill"],
            ),
            self._beat(3, shot_scale="overhead", environment="desk"),
        ]
        audit = audit_scene_plan(self._plan(beats))
        assert audit["problems"] == []
        assert any("substitution is how" in advisory for advisory in audit["advisories"])

    def test_co_presence_clears_the_substitution_advisory(self) -> None:
        beats = [
            self._beat(1),
            self._beat(
                2,
                shows_subject=False,
                shot_scale="wide",
                environment="gym",
                queries=["fit woman holding coffee cup gym", "coffee cup on bench gym"],
            ),
            self._beat(3, shot_scale="overhead", environment="desk"),
        ]
        audit = audit_scene_plan(self._plan(beats))
        assert audit["advisories"] == []

    # --- Adjacent variety ------------------------------------------------------------

    def test_two_adjacent_beats_sharing_scale_and_place_are_reported(self) -> None:
        """They render as one long shot."""
        beats = [self._beat(1), self._beat(2), self._beat(3, shot_scale="wide", environment="gym")]
        problems = audit_scene_plan(self._plan(beats))["problems"]
        assert any("one long shot" in problem for problem in problems)

    def test_a_repeated_subject_is_not_a_violation(self) -> None:
        """The rule this replaced forbade a repeated subject, which is incompatible
        with the anchor quota — the quota requires the subject repeatedly."""
        beats = [
            self._beat(1, shot_scale="close up", environment="kitchen"),
            self._beat(2, shot_scale="overhead", environment="kitchen"),
            self._beat(3, shot_scale="close up", environment="cafe"),
        ]
        audit = audit_scene_plan(self._plan(beats))
        assert all(beat["shows_subject"] for beat in beats)
        assert audit["problems"] == []

    def test_a_missing_shot_scale_is_a_problem_because_it_exempts_the_check(self) -> None:
        beats = [self._beat(1, shot_scale=""), self._beat(2, shot_scale="wide", environment="gym")]
        problems = audit_scene_plan(self._plan(beats))["problems"]
        assert any("no shot_scale" in problem for problem in problems)

    # --- Completeness ----------------------------------------------------------------

    def test_three_queries_per_beat_is_reported(self) -> None:
        """The first run wrote three and downloaded 36 clips to use 12."""
        beats = [self._beat(1, queries=["coffee a", "coffee b", "coffee c"])]
        problems = audit_scene_plan(self._plan(beats))["problems"]
        assert any("paraphrase of the second" in problem for problem in problems)

    def test_a_missing_camera_move_is_reported(self) -> None:
        beats = [self._beat(1, camera="")]
        problems = audit_scene_plan(self._plan(beats))["problems"]
        assert any("no camera move" in problem for problem in problems)

    def test_camera_none_is_a_deliberate_choice_not_a_gap(self) -> None:
        beats = [self._beat(1, camera="none")]
        problems = audit_scene_plan(self._plan(beats))["problems"]
        assert not any("camera" in problem for problem in problems)

    def test_a_plan_without_a_subject_cannot_be_audited(self) -> None:
        """Every other rule is stated against the subject."""
        problems = audit_scene_plan({"metadata": {"beats": [self._beat(1)]}})["problems"]
        assert any("no subject recorded" in problem for problem in problems)

    def test_an_explicit_subject_argument_overrides_the_plan(self) -> None:
        """The brief owns the subject; a plan that disagrees is the plan's bug."""
        audit = audit_scene_plan({"metadata": {"beats": [self._beat(1)]}}, subject="coffee")
        assert not any("no subject" in problem for problem in audit["problems"])

    def test_exceeding_the_typographic_budget_is_reported(self) -> None:
        beats = [
            self._beat(1),
            self._beat(2, typographic=True, queries=[], shows_subject=False),
            self._beat(3, typographic=True, queries=[], shows_subject=False),
            self._beat(4, shot_scale="overhead", environment="desk"),
        ]
        problems = audit_scene_plan(self._plan(beats), typographic_budget=1)["problems"]
        assert any("typographic beats against a budget" in problem for problem in problems)

    def test_the_shipped_coffee_plan_audits_clean(self) -> None:
        """The real artifact, as reconciled. Guards against the checkpoint drifting
        back to a state the gate would reject."""
        plan_path = (
            Path(__file__).resolve().parents[2]
            / "projects"
            / "coffee-hormone-fa"
            / "checkpoint_scene_plan.json"
        )
        if not plan_path.exists():  # pragma: no cover - projects/ is gitignored
            pytest.skip("the coffee project is not present in this checkout")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))["artifacts"]["scene_plan"]
        audit = audit_scene_plan(plan, typographic_budget=1)
        assert audit["problems"] == []
        assert audit["subject_fraction"] >= MIN_SUBJECT_FRACTION


class TestSerializationKeepsTheFloor:
    """The JSON transport must not undercut the reading floor.

    `retime_moments` derives an exact end; `to_props` carries it at 1ms
    granularity; the pacing audit compares the round-tripped span against the
    exact floor. The shipped failure was a moment that needed 8.9455s, serialized
    to 8.945s, and was refused by the compose tool on a set that had passed in
    memory. A floor that does not survive its own transport is not a floor.
    """

    def test_to_props_rounds_the_end_up_not_down(self) -> None:
        import math

        moment = build_moments(
            [_moment(startSeconds=0.0, endSeconds=5.0)]
        )[0]
        # Force a floor that lands strictly between two milliseconds.
        required = moment.min_read_seconds
        assert required > 0
        moment.end_seconds = required  # exact floor, e.g. 4.934545…
        props = moment.to_props()
        serialized_end = props["endSeconds"]
        assert serialized_end >= required, (
            f"end serialized to {serialized_end} but the floor is {required}: "
            "round-half-even lost the fraction of a millisecond that the reading "
            "floor needed, so the JSON round-trip fails an audit the in-memory "
            "set passed"
        )
        assert math.ceil(required * 1000) / 1000 == serialized_end

    def test_a_retimed_set_survives_its_json_round_trip(self) -> None:
        """The compose tool's exact path: JSON in, rebuild, audit.

        Uses a floor that cannot be represented exactly on the millisecond grid,
        which is the arithmetic that produced the shipped refusal.
        """
        words = TimedWord.from_dicts(
            [
                {"word": "الف", "start": 0.0, "end": 0.8},
                {"word": "ب", "start": 0.8, "end": 1.6},
            ]
        )
        # 24 visible chars of hero + fixation charges an awkward floor: the sum
        # lands at x.xxx636…, which rounds DOWN under round-half-even.
        authored = [
            dict(
                id="m-1",
                kind="statement",
                startSeconds=0.0,
                endSeconds=2.0,
                anchorText="الف ب",
                segments=[
                    {"role": "lead", "text": "سرگردانیِ"},
                    {"role": "hero", "text": "کاتبی که خوابیده"},
                ],
            )
        ]
        retimed = retime_moments(build_moments(authored), words)
        serialized = [moment.to_props() for moment in retimed]
        rebuilt = build_moments(serialized)
        audit = audit_moments(rebuilt, duration_seconds=66.0)
        floor_faults = [
            problem
            for problem in audit.problems
            if "needs" in problem and "own text" in problem
        ]
        assert floor_faults == [], (
            f"a set that passed in memory was refused on its own JSON: {floor_faults}"
        )
        sync = audit_sync(rebuilt, words)
        assert sync.problems == []


class TestFlatHookAccent:
    """Inline accent for the flat-hook treatment (`accentWords`).

    The hook is one block at one size with one or two orange keywords. These
    tests pin the pipeline half of the two-enforcer rule; the renderer asserts
    the same in `assertMomentIsWellFormed`.
    """

    def _hook(self, **overrides: object) -> dict:
        base: dict = {
            "kind": "statement",
            "startSeconds": 0.2,
            "endSeconds": 4.2,
            "segments": [
                {
                    "role": "hero",
                    "text": "می‌دونی قهوه با هورمون‌هات چی‌کار می‌کنه؟",
                    "accentWords": ["قهوه", "هورمون‌هات"],
                },
            ],
        }
        base.update(overrides)
        return base

    def test_a_flat_hook_audits_clean(self) -> None:
        """The canonical hook shape passes every gate it is subject to."""
        moments = build_moments(
            [
                self._hook(),
                _figure(startSeconds=6.6, endSeconds=10.9),
            ]
        )
        assert audit_moments(moments, duration_seconds=64.0).problems == []

    def test_an_accent_word_missing_from_the_text_is_refused(self) -> None:
        """A silently dropped accent word is an emphasis nobody sees."""
        segments = [
            {
                "role": "hero",
                "text": "می‌دونی قهوه با هورمون‌هات چی‌کار می‌کنه؟",
                "accentWords": ["اسپرسو"],
            }
        ]
        with __import__("pytest").raises(ValueError, match="not in.*own text"):
            build_moments([self._hook(segments=segments)])

    def test_more_than_three_accent_words_are_refused(self) -> None:
        """Past three keywords the emphasis has visibly become several orange words."""
        segments = [
            {
                "role": "hero",
                "text": "می‌دونی قهوه با هورمون‌هات چی‌کار می‌کنه؟",
                "accentWords": ["می‌دونی", "قهوه", "هورمون‌هات", "چی‌کار"],
            }
        ]
        with __import__("pytest").raises(ValueError, match="at most 3"):
            build_moments([self._hook(segments=segments)])

    def test_accent_on_a_non_hero_is_a_problem(self) -> None:
        """Inline accent lives on the hero — the emphasis in colour, not size."""
        moments = build_moments(
            [
                self._hook(
                    segments=[
                        {
                            "role": "lead",
                            "text": "می‌دونی قهوه",
                            "accentWords": ["قهوه"],
                        },
                        {"role": "hero", "text": "بقیه‌اش"},
                    ]
                ),
                _figure(startSeconds=6.6, endSeconds=10.9),
            ]
        )
        assert any(
            "accentWords on a lead" in problem
            for problem in audit_moments(moments, duration_seconds=64.0).problems
        )

    def test_accent_with_several_blocks_is_a_problem(self) -> None:
        """Several blocks at several sizes are the sized hierarchy already."""
        moments = build_moments(
            [
                self._hook(
                    segments=[
                        {
                            "role": "hero",
                            "text": "می‌دونی قهوه",
                            "accentWords": ["قهوه"],
                        },
                        {"role": "tail", "text": "بقیه‌اش"},
                    ]
                ),
                _figure(startSeconds=6.6, endSeconds=10.9),
            ]
        )
        assert any(
            "content blocks" in problem
            for problem in audit_moments(moments, duration_seconds=64.0).problems
        )

    def test_accent_past_the_first_moment_is_a_problem(self) -> None:
        """One video, one hook: later moments keep the sized model."""
        moments = build_moments(
            [
                _moment(startSeconds=0.2, endSeconds=4.2),
                _figure(
                    startSeconds=6.6,
                    endSeconds=10.9,
                    segments=[
                        {
                            "role": "hero",
                            "text": "۲۲۶۴ نفر",
                            "accentWords": ["نفر"],
                        },
                        {
                            "role": "lead",
                            "text": "مطالعهٔ دانشگاه اولوی فنلاند روی",
                        },
                    ],
                ),
            ]
        )
        assert any(
            "past the first moment" in problem
            for problem in audit_moments(moments, duration_seconds=64.0).problems
        )

    def test_accent_words_survive_the_props_round_trip(self) -> None:
        """`to_props` must carry them — the renderer reads them from the props."""
        moments = build_moments([self._hook()])
        props = moments[0].to_props()
        assert props["segments"][0]["accentWords"] == ["قهوه", "هورمون‌هات"]
        rebuilt = build_moments([props])
        assert rebuilt[0].segments[0].accent_words == ["قهوه", "هورمون‌هات"]
        assert audit_moments(rebuilt, duration_seconds=64.0).problems == []


class TestClaimQualifierHook:
    """The declared hook kind and its two structural styles.

    A hook is declared with `kind: "hook"` — never inferred — and its style
    derives from structure: claim+qualifier (hero + tail, no accentWords) or
    flat display (a single accent-carrying hero). These tests pin the Python
    half; the renderer derives the same from the same segments in `layout.ts`.
    """

    def _hook(self, **overrides: object) -> dict:
        base: dict = {
            "kind": "hook",
            "startSeconds": 0.2,
            "endSeconds": 4.2,
            "segments": [
                {"role": "hero", "text": "فواید عجیب قهوه"},
                {"role": "tail", "text": "روی هورمون‌ها!"},
            ],
        }
        base.update(overrides)
        return base

    def test_a_claim_qualifier_hook_audits_clean(self) -> None:
        """The approved shape passes every gate it is subject to."""
        moments = build_moments(
            [
                self._hook(),
                _figure(startSeconds=6.6, endSeconds=10.9),
            ]
        )
        assert audit_moments(moments, duration_seconds=64.0).problems == []

    def test_the_hook_kind_is_declared_not_inferred(self) -> None:
        moments = build_moments([self._hook()])
        assert moments[0].kind == "hook"
        assert moments[0].to_props()["kind"] == "hook"

    def test_predicates_derive_style_from_structure(self) -> None:
        (hook,) = build_moments([self._hook()])
        assert is_claim_qualifier_hook(hook) is True
        assert is_flat_display_hook(hook) is False
        (flat,) = build_moments(
            [
                {
                    "kind": "hook",
                    "startSeconds": 0.2,
                    "endSeconds": 4.2,
                    "segments": [
                        {
                            "role": "hero",
                            "text": "می‌دونی قهوه با هورمون‌هات چی‌کار می‌کنه؟",
                            "accentWords": ["قهوه", "هورمون‌هات"],
                        },
                    ],
                }
            ]
        )
        assert is_claim_qualifier_hook(flat) is False
        assert is_flat_display_hook(flat) is True
        (ordinary,) = build_moments([_figure()])
        assert is_claim_qualifier_hook(ordinary) is False
        assert is_flat_display_hook(ordinary) is False

    def test_pattern_interrupt_poster_stack_is_a_valid_hook_style(self) -> None:
        (hook,) = build_moments([{
            "id": "opening", "kind": "hook", "purpose": "hook-pattern-interrupt",
            "startSeconds": 0.1, "endSeconds": 4.5,
            "segments": [
                {"role": "lead", "text": "بزرگ‌ترین اشتباه"},
                {"role": "lead", "text": "دربارهٔ"},
                {"role": "hero", "text": "بازی‌های ویدیویی"},
                {"role": "tail", "text": "اینه که فکر کنیم فقط"},
                {"role": "tail", "text": "وقت تلف کردنه!"},
            ],
        }])
        assert is_poster_stack_hook(hook) is True
        assert audit_moments([hook], duration_seconds=12.0).problems == []

    def test_a_hook_matching_no_style_is_a_problem(self) -> None:
        """A hook that matches no style silently loses every hook-scoped token."""
        moments = build_moments(
            [
                self._hook(
                    segments=[
                        {"role": "lead", "text": "نگاه کن"},
                        {"role": "hero", "text": "قهوه"},
                    ]
                ),
                _figure(startSeconds=6.6, endSeconds=10.9),
            ]
        )
        assert any(
            "neither claim+qualifier" in problem
            for problem in audit_moments(moments, duration_seconds=64.0).problems
        )

    def test_a_hook_with_a_source_is_a_problem(self) -> None:
        """The opening frame is not the evidence."""
        moments = build_moments(
            [
                self._hook(
                    segments=[
                        {"role": "hero", "text": "فواید عجیب قهوه"},
                        {"role": "tail", "text": "روی هورمون‌ها!"},
                        {"role": "source", "text": "اولوی فنلاند"},
                    ]
                ),
                _figure(startSeconds=6.6, endSeconds=10.9),
            ]
        )
        assert any(
            "no source citation" in problem
            for problem in audit_moments(moments, duration_seconds=64.0).problems
        )

    def test_a_hook_past_the_first_moment_is_a_problem(self) -> None:
        """One video, one hook: a later hook is a second opening."""
        moments = build_moments(
            [
                _moment(startSeconds=0.2, endSeconds=4.2),
                self._hook(startSeconds=6.6, endSeconds=10.9),
            ]
        )
        assert any(
            "past the first moment" in problem
            for problem in audit_moments(moments, duration_seconds=64.0).problems
        )

    def test_pattern_interrupt_rejects_automatic_one_token_hook(self) -> None:
        moments = build_moments([
            {
                "id": "opening", "kind": "hook",
                "purpose": "hook-pattern-interrupt",
                "startSeconds": 0.1, "endSeconds": 3.0,
                "presentation": {"emphasis": "inline"},
                "segments": [{"role": "hero", "text": "جایزه؟", "accentWords": ["جایزه؟"]}],
            }
        ])
        problems = audit_moments(moments, duration_seconds=12.0).problems
        assert any("Automatic one-word/fragment fallback is forbidden" in p for p in problems)
        assert any("one-token hook may not manufacture impact" in p for p in problems)

    def test_explicit_user_authored_short_hook_round_trips(self) -> None:
        authored = {
            "id": "opening", "kind": "hook",
            "purpose": "hook-pattern-interrupt",
            "userAuthoredShortHook": True,
            "startSeconds": 0.1, "endSeconds": 3.0,
            "presentation": {"emphasis": "none"},
            "segments": [{"role": "hero", "text": "جایزه؟", "accentWords": ["جایزه؟"]}],
        }
        (moment,) = build_moments([authored])
        props = moment.to_props()
        assert props["purpose"] == "hook-pattern-interrupt"
        assert props["userAuthoredShortHook"] is True
        assert props["presentation"] == {"emphasis": "none"}
        rebuilt = build_moments([props])[0]
        assert rebuilt.user_authored_short_hook is True
        assert not any("Automatic one-word/fragment" in p for p in audit_moments([rebuilt], duration_seconds=12.0).problems)

    def test_pattern_interrupt_clause_passes_short_hook_gate(self) -> None:
        moments = build_moments([
            {
                "id": "opening", "kind": "hook",
                "purpose": "hook-pattern-interrupt",
                "startSeconds": 0.1, "endSeconds": 4.5,
                "presentation": {"emphasis": "none"},
                "segments": [
                    {"role": "hero", "text": "به هر کار خوبی"},
                    {"role": "tail", "text": "جایزه می‌دی؟"},
                ],
            }
        ])
        problems = audit_moments(moments, duration_seconds=12.0).problems
        assert not any("hook-pattern-interrupt has only" in p for p in problems)

    def test_the_silhouette_band_is_a_band(self) -> None:
        """Round numbers passing the reference (0.62) and c4 (0.647) and
        refusing the rectangle (0.88) and the sliver (0.489)."""
        assert HOOK_SILHOUETTE_MIN_RATIO == 0.52
        assert HOOK_SILHOUETTE_MAX_RATIO == 0.78
        for passing in (0.62, 0.647, 0.65):
            assert HOOK_SILHOUETTE_MIN_RATIO <= passing <= HOOK_SILHOUETTE_MAX_RATIO
        for failing in (0.88, 0.489):
            assert not (
                HOOK_SILHOUETTE_MIN_RATIO <= failing <= HOOK_SILHOUETTE_MAX_RATIO
            )
