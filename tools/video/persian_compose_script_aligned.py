"""Delivery-safe Persian composer with approved-script-aligned subtitles.

This module intentionally registers a later, stricter implementation under the
existing ``persian_compose`` tool name. Tool discovery is lexical, so it first
registers ``tools.video.persian_compose.PersianCompose`` and then replaces that
entry with :class:`ScriptAlignedPersianCompose`. The renderer itself is inherited;
this layer owns approved captions plus Issue #26 hook/caption presentation contracts.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from lib.persian_srt import render_srt
from lib.persian_text import compare_key, split_words
from lib.persian_captions import (
    BURNED_CAPTION_MODES,
    build_burned_caption_props,
    burned_caption_max_visible_chars,
    resolve_caption_mode,
)
from lib.persian_design import resolve_design
from lib.persian_srt_alignment import (
    SubtitleAlignmentError,
    build_script_aligned_cues,
    build_script_aligned_word_timings,
)
from tools.video.persian_compose import PersianCompose


class ScriptAlignedPersianCompose(PersianCompose):
    """PersianCompose with pre-render script and hook-presentation gates."""

    name = "persian_compose"
    version = "0.5.0"

    _SEMANTIC_POSTER_ROLES = {
        "setup",
        "bridge",
        "subject_hero",
        "connector",
        "payoff",
    }
    _STRUCTURAL_ROLE_BY_SEMANTIC_ROLE = {
        "setup": "lead",
        "bridge": "lead",
        "subject_hero": "hero",
        "connector": "tail",
        "payoff": "tail",
    }
    _SEMANTIC_REPLAY_LIGHT_TOKENS = frozenset({
        "و", "یا", "که", "را", "رو", "به", "در", "از", "این", "اون",
        "فقط", "نه", "با", "برای", "می",
    })

    @staticmethod
    def _runtime_persian(edit_decisions: dict[str, Any]) -> dict[str, Any] | None:
        persian = edit_decisions.get("persian")
        if not isinstance(persian, dict):
            return None
        runtime_persian = dict(persian)
        runtime_persian.pop("_approvedSubtitleScript", None)
        runtime_persian.pop("_hookCaptionHandoff", None)
        runtime_persian.pop("_semanticPosterStack", None)
        metadata = edit_decisions.get("metadata") or {}
        approved_script = metadata.get("persianSubtitleScript") if isinstance(metadata, dict) else None
        hook_handoff = metadata.get("hookCaptionHandoff") if isinstance(metadata, dict) else None
        semantic_poster = metadata.get("semanticPosterStack") if isinstance(metadata, dict) else None
        if approved_script is not None:
            runtime_persian["_approvedSubtitleScript"] = approved_script
            audio = runtime_persian.get("audio")
            if isinstance(audio, dict) and audio.get("wordTimings"):
                runtime_audio = dict(audio)
                # Align the approved script onto the measured speech. This set is the
                # one the script's wording provably belongs to -- it is gated by
                # SubtitleAlignmentError before delivery -- so captions and moment sync
                # both read it. An anchor derived from the approved script must locate
                # without being retyped in ASR spellings (#152).
                runtime_audio["wordTimings"] = build_script_aligned_word_timings(
                    approved_script, audio["wordTimings"]
                )
                runtime_persian["audio"] = runtime_audio
        if hook_handoff is not None:
            # Runtime-only injection keeps the public edit schema stable while making
            # the explicit handoff available before burned-caption geometry freezes.
            runtime_persian["_hookCaptionHandoff"] = hook_handoff
        if semantic_poster is not None:
            # The canonical semantic plan lives in edit metadata. Rehydrate it only
            # for runtime props so the public edit schema remains unchanged while
            # Film Type 2.16 can consume authored meaning instead of guessing from
            # lead/hero/tail position.
            runtime_persian["_semanticPosterStack"] = semantic_poster
        return runtime_persian

    @staticmethod
    def _rehydrate_semantic_poster_stack(
        moments: list[Any], plan: Any
    ) -> list[Any]:
        """Attach canonical semantic roles to the one opening hook at runtime.

        This adapter never invents semantics. The metadata plan must match the
        normalized moment text and structural roles exactly; otherwise render is
        refused before browser layout.
        """
        if not isinstance(plan, dict) or plan.get("version") != "1.0":
            raise ValueError("SEMANTIC_POSTER_INVALID: semanticPosterStack version must be 1.0")
        phrases = plan.get("phrases")
        if not isinstance(phrases, list) or not 2 <= len(phrases) <= 5:
            raise ValueError("SEMANTIC_POSTER_INVALID: semanticPosterStack requires 2-5 phrases")
        hooks = [
            moment for moment in moments
            if isinstance(moment, dict) and moment.get("kind") == "hook"
        ]
        if len(hooks) != 1:
            raise ValueError("SEMANTIC_POSTER_INVALID: semanticPosterStack requires exactly one hook moment")

        roles: list[str] = []
        phrase_texts: list[str] = []
        for index, phrase in enumerate(phrases):
            if not isinstance(phrase, dict):
                raise ValueError(f"SEMANTIC_POSTER_INVALID: phrase {index} must be an object")
            role = str(phrase.get("role") or "").strip()
            text = str(phrase.get("text") or "").strip()
            if role not in ScriptAlignedPersianCompose._SEMANTIC_POSTER_ROLES:
                raise ValueError(f"SEMANTIC_POSTER_INVALID: unsupported semantic role {role!r}")
            if not text:
                raise ValueError(f"SEMANTIC_POSTER_INVALID: phrase {index} has no text")
            roles.append(role)
            phrase_texts.append(text)
        if roles.count("subject_hero") != 1:
            raise ValueError("SEMANTIC_POSTER_INVALID: exactly one subject_hero is required")

        hook = hooks[0]
        raw_segments = hook.get("segments")
        if not isinstance(raw_segments, list):
            raise ValueError("SEMANTIC_POSTER_INVALID: hook segments must be an array")
        content = [segment for segment in raw_segments if isinstance(segment, dict) and segment.get("role") != "source"]
        if len(content) != len(phrases):
            raise ValueError("SEMANTIC_POSTER_INVALID: phrase count does not match normalized hook segments")

        hydrated_content: list[dict[str, Any]] = []
        for index, (segment, role, text) in enumerate(zip(content, roles, phrase_texts, strict=True)):
            actual_text = str(segment.get("text") or "").strip()
            if actual_text != text:
                raise ValueError(
                    f"SEMANTIC_POSTER_INVALID: phrase {index} text does not match normalized hook copy"
                )
            expected_structural = ScriptAlignedPersianCompose._STRUCTURAL_ROLE_BY_SEMANTIC_ROLE[role]
            if segment.get("role") != expected_structural:
                raise ValueError(
                    f"SEMANTIC_POSTER_INVALID: semantic role {role} requires structural role {expected_structural}"
                )
            hydrated_content.append({**segment, "semanticRole": role})

        reconstructed = " ".join(item["text"] for item in hydrated_content).strip()
        authoritative = " ".join(str(plan.get("authoritativeHookText") or "").split())
        if " ".join(reconstructed.split()) != authoritative:
            raise ValueError(
                "SEMANTIC_POSTER_INVALID: runtime phrase concatenation does not reconstruct authoritative hook"
            )

        content_iter = iter(hydrated_content)
        hydrated_segments = [
            dict(segment) if isinstance(segment, dict) and segment.get("role") == "source" else next(content_iter)
            for segment in raw_segments
        ]
        result: list[Any] = []
        for moment in moments:
            if moment is hook:
                result.append({**hook, "segments": hydrated_segments})
            else:
                result.append(moment)
        return result

    def execute(self, inputs: dict[str, Any]):
        edit_decisions = inputs.get("edit_decisions")
        if not isinstance(edit_decisions, dict):
            return super().execute(inputs)
        runtime_persian = self._runtime_persian(edit_decisions)
        if runtime_persian is None:
            return super().execute(inputs)
        runtime_inputs = dict(inputs)
        runtime_decisions = dict(edit_decisions)
        runtime_decisions["persian"] = runtime_persian
        runtime_inputs["edit_decisions"] = runtime_decisions
        return super().execute(runtime_inputs)

    @staticmethod
    def _prepare_typographic_only_composition(persian: dict[str, Any]) -> dict[str, Any]:
        """Derive a center-biased full-canvas layout for text-only opening hooks.

        This is deliberately runtime-only. The authored artifact still records
        ``placement=auto``; the renderer resolves that auto request differently when
        the entire hook is backed by a typographic plate rather than footage. Explicit
        authored placement remains authoritative.
        """
        beats = [item for item in (persian.get("typographicBeats") or []) if isinstance(item, dict)]
        if not beats:
            return persian
        changed = False
        moments: list[Any] = []
        for raw in persian.get("moments") or []:
            if not isinstance(raw, dict) or raw.get("kind") != "hook":
                moments.append(raw)
                continue
            start = float(raw.get("startSeconds") or 0.0)
            end = float(raw.get("endSeconds") or 0.0)
            covered = any(
                float(beat.get("startSeconds") or 0.0) <= start + 1e-6
                and float(beat.get("endSeconds") or 0.0) >= end - 1e-6
                for beat in beats
            )
            if not covered:
                moments.append(raw)
                continue
            presentation = dict(raw.get("presentation") or {})
            if presentation.get("placement") not in {None, "auto"}:
                moments.append(raw)
                continue
            presentation["placement"] = "center"
            moment = dict(raw)
            moment["presentation"] = presentation
            moments.append(moment)
            changed = True
        if not changed:
            return persian
        resolved = dict(persian)
        resolved["moments"] = moments
        return resolved

    def _build_props(
        self,
        persian: dict[str, Any],
        staging_dir: Path,
        run_id: str,
    ) -> tuple[dict[str, Any], list[str]]:
        """Resolve typographic-only composition before browser Film Type layout."""
        runtime = self._prepare_typographic_only_composition(persian)
        return super()._build_props(runtime, staging_dir, run_id)

    @staticmethod
    def _build_moments(
        persian: dict[str, Any], duration_seconds: float, *, v2: bool = False,
        measure_layout: bool = True, adaptive_pixel_typography: bool = False,
        simultaneous_hook_typography: bool = False,
    ) -> list[dict[str, Any]]:
        moments = PersianCompose._build_moments(
            persian,
            duration_seconds,
            v2=v2,
            measure_layout=measure_layout,
            adaptive_pixel_typography=adaptive_pixel_typography,
            simultaneous_hook_typography=simultaneous_hook_typography,
        )
        semantic_plan = persian.get("_semanticPosterStack")
        if semantic_plan is None:
            return moments
        return ScriptAlignedPersianCompose._rehydrate_semantic_poster_stack(
            moments, semantic_plan
        )

    def _build_caption_props(self, persian: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
        """Build approved-script captions before Film Type freezes layout."""
        mode = resolve_caption_mode(
            persian.get("captionMode"), platform_target=persian.get("platformTarget")
        )
        if mode in BURNED_CAPTION_MODES:
            profile_version = None
            raw_design = persian.get("design")
            if isinstance(raw_design, dict) and raw_design.get("profile") == "film-type":
                resolved_design = resolve_design(raw_design)
                if resolved_design is not None:
                    profile_version = str(resolved_design.get("profileVersion") or "")
            burned = self._aligned_subtitle_cues(
                persian,
                max_visible_chars=burned_caption_max_visible_chars(profile_version),
                id_prefix="caption",
                require_words=True,
                min_connector_words=8 if profile_version in {"2.14.0", "2.15.0", "2.16.0"} else 0,
            )
            burned = self._apply_hook_caption_handoff(burned, persian)
            burned = self._suppress_semantically_shadowed_burned_cues(
                burned, persian.get("moments") or []
            )
            burned = self._suppress_stranded_burned_cues(burned, persian.get("moments") or [])
            return mode, build_burned_caption_props(burned)

        self._aligned_subtitle_cues(persian)
        return mode, []

    @staticmethod
    def _hook_window(persian: dict[str, Any]) -> tuple[float, float] | None:
        hooks = [
            item
            for item in (persian.get("moments") or [])
            if isinstance(item, dict) and item.get("kind") == "hook"
        ]
        if not hooks:
            return None
        start = min(float(item.get("startSeconds", 0.0)) for item in hooks)
        end = max(float(item.get("endSeconds", 0.0)) for item in hooks)
        return start, end

    @staticmethod
    def _apply_hook_caption_handoff(cues, persian: dict[str, Any]):
        """Apply the explicit semantic contract between a typographic hook and captions.

        ``semantic_replacement`` means the hook has replaced the opening semantic unit;
        burned captions therefore resume only at the explicitly authored next complete
        unit. ``exact_continuation`` means captions continue the spoken sentence, but a
        cue may not straddle the end of the hook and expose only its hidden remainder.
        The sidecar SRT remains complete in both modes.
        """
        raw = persian.get("_hookCaptionHandoff")
        if raw is None:
            return list(cues)
        if not isinstance(raw, dict):
            raise ValueError("CAPTION_HANDOFF_INVALID: metadata.hookCaptionHandoff must be an object")
        mode = str(raw.get("mode") or "").strip()
        if mode not in {"semantic_replacement", "exact_continuation"}:
            raise ValueError(
                "CAPTION_HANDOFF_INVALID: mode must be semantic_replacement or exact_continuation"
            )
        window = ScriptAlignedPersianCompose._hook_window(persian)
        if window is None:
            raise ValueError("CAPTION_HANDOFF_INVALID: hookCaptionHandoff requires a hook moment")
        _, hook_end = window

        if mode == "semantic_replacement":
            raw_resume = raw.get("resumeAtSeconds")
            if not isinstance(raw_resume, (int, float)) or isinstance(raw_resume, bool):
                raise ValueError(
                    "CAPTION_HANDOFF_INVALID: semantic_replacement requires numeric resumeAtSeconds"
                )
            resume = float(raw_resume)
            if not math.isfinite(resume) or resume < hook_end - 1e-6:
                raise ValueError(
                    "CAPTION_HANDOFF_INVALID: resumeAtSeconds must be finite and at/after the hook end"
                )
            return [cue for cue in cues if cue.start_seconds >= resume - 1e-6]

        visible = [cue for cue in cues if cue.end_seconds > hook_end + 1e-6]
        if visible:
            first = visible[0]
            if first.start_seconds < hook_end - 1e-6:
                raise ValueError(
                    "CAPTION_HANDOFF_FRAGMENT: exact_continuation would reveal only the remainder "
                    "of a cue that began under the typographic hook"
                )
        return list(cues)

    @staticmethod
    def _caption_tokens(text: Any) -> set[str]:
        tokens: set[str] = set()
        for word in split_words(str(text or "")):
            if word == "\n":
                continue
            token = compare_key(word)
            if token:
                tokens.add(token)
        return tokens

    @staticmethod
    def _semantic_caption_tokens(text: Any) -> set[str]:
        return ScriptAlignedPersianCompose._caption_tokens(text) - (
            ScriptAlignedPersianCompose._SEMANTIC_REPLAY_LIGHT_TOKENS
        )

    @staticmethod
    def _rendered_moment_tokens(moment: dict[str, Any]) -> set[str]:
        segments = moment.get("segments") or []
        rendered = " ".join(
            str(segment.get("text") or "")
            for segment in segments
            if isinstance(segment, dict)
        )
        return ScriptAlignedPersianCompose._semantic_caption_tokens(rendered)

    @staticmethod
    def _suppress_semantically_shadowed_burned_cues(
        cues, moments, *, min_anchor_coverage: float = 0.6, min_overlap_ratio: float = 0.5,
        min_rendered_shared_tokens: int = 2, min_rendered_overlap_coefficient: float = 0.5,
    ):
        """Drop burned cues whose handoff would replay an overlapping semantic moment.

        The legacy anchor gate handles cues substantially owned by a moment's authored
        subject window. A second gate compares against the text actually rendered in
        the moment. That catches boundary cues which are hidden while the moment is
        active but would otherwise repaint the same phrase immediately before/after
        the moment. Unrelated overlapping narration remains intact. The sidecar SRT is
        deliberately unaffected.
        """
        kept = []
        for cue in cues:
            cue_tokens = ScriptAlignedPersianCompose._caption_tokens(cue.text)
            cue_semantic_tokens = ScriptAlignedPersianCompose._semantic_caption_tokens(cue.text)
            cue_duration = max(0.0, float(cue.end_seconds) - float(cue.start_seconds))
            shadowed = False
            if cue_duration > 0 and cue_tokens:
                for moment in moments:
                    if not isinstance(moment, dict):
                        continue
                    m0 = float(moment.get("startSeconds", 0.0))
                    m1 = float(moment.get("endSeconds", 0.0))
                    overlap = min(float(cue.end_seconds), m1) - max(float(cue.start_seconds), m0)
                    if overlap <= 0:
                        continue

                    rendered_tokens = ScriptAlignedPersianCompose._rendered_moment_tokens(moment)
                    if cue_semantic_tokens and rendered_tokens:
                        shared = cue_semantic_tokens & rendered_tokens
                        overlap_coefficient = len(shared) / min(
                            len(cue_semantic_tokens), len(rendered_tokens)
                        )
                        if (
                            len(shared) >= min_rendered_shared_tokens
                            and overlap_coefficient + 1e-9 >= min_rendered_overlap_coefficient
                        ):
                            shadowed = True
                            break

                    anchor = str(moment.get("anchorText") or "").strip()
                    if not anchor:
                        continue
                    anchor_tokens = ScriptAlignedPersianCompose._caption_tokens(anchor)
                    if not anchor_tokens:
                        continue
                    anchor_coverage = len(cue_tokens & anchor_tokens) / len(anchor_tokens)
                    overlap_ratio = overlap / cue_duration
                    if (
                        anchor_coverage + 1e-9 >= min_anchor_coverage
                        and overlap_ratio + 1e-9 >= min_overlap_ratio
                    ):
                        shadowed = True
                        break
            if not shadowed:
                kept.append(cue)
        return kept

    @staticmethod
    def _suppress_stranded_burned_cues(cues, moments, *, fragment_seconds: float = 1.0):
        """Drop a burned cue when all paintable time outside moments is a flash."""
        kept = []
        for cue in cues:
            intervals = [(cue.start_seconds, cue.end_seconds)]
            for moment in moments:
                if not isinstance(moment, dict):
                    continue
                m0 = float(moment.get("startSeconds", 0.0))
                m1 = float(moment.get("endSeconds", 0.0))
                if m1 <= m0:
                    continue
                next_intervals = []
                for a, b in intervals:
                    if b <= m0 or a >= m1:
                        next_intervals.append((a, b))
                        continue
                    if a < m0:
                        next_intervals.append((a, min(b, m0)))
                    if b > m1:
                        next_intervals.append((max(a, m1), b))
                intervals = next_intervals
            visible = sum(max(0.0, b - a) for a, b in intervals)
            if visible >= fragment_seconds:
                kept.append(cue)
        return kept

    @staticmethod
    def _aligned_subtitle_cues(
        persian: dict[str, Any],
        *,
        max_visible_chars: int | None = None,
        id_prefix: str = "cue",
        require_words: bool = False,
        min_connector_words: int = 0,
    ) -> list[Any]:
        audio = persian.get("audio") or {}
        word_timings = audio.get("wordTimings")
        if not word_timings:
            if audio.get("narration") or require_words:
                raise ValueError(
                    "narrated/burned Persian captions require audio.wordTimings so "
                    "approved script text can be aligned to the spoken audio"
                )
            return []
        try:
            return build_script_aligned_cues(
                persian.get("_approvedSubtitleScript"),
                word_timings,
                max_visible_chars=max_visible_chars,
                id_prefix=id_prefix,
                min_connector_words=min_connector_words,
            )
        except SubtitleAlignmentError as exc:
            raise ValueError(
                "the approvedScript-backed Persian sidecar SRT is not provably "
                "aligned, so delivery is refused rather than shipping ASR copy or "
                f"a timing gap: {exc}"
            ) from exc

    @staticmethod
    def _write_subtitles(persian: dict[str, Any], output_path: Path) -> tuple[str | None, list[str]]:
        mode = resolve_caption_mode(
            persian.get("captionMode"), platform_target=persian.get("platformTarget")
        )
        if mode == "burned_captions":
            return None, []
        cues = ScriptAlignedPersianCompose._aligned_subtitle_cues(persian)
        if not cues:
            return None, []
        srt_path = output_path.with_suffix(".srt")
        srt_path.write_text(render_srt(cues), encoding="utf-8-sig")
        return str(srt_path), []


__all__ = ["ScriptAlignedPersianCompose"]
