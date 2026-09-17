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
from lib.persian_captions import (
    BURNED_CAPTION_MODES,
    build_burned_caption_props,
    burned_caption_max_visible_chars,
    resolve_caption_mode,
)
from lib.persian_design import resolve_design
from lib.persian_srt_alignment import SubtitleAlignmentError, build_script_aligned_cues
from tools.video.persian_compose import PersianCompose


class ScriptAlignedPersianCompose(PersianCompose):
    """PersianCompose with pre-render script and hook-presentation gates."""

    name = "persian_compose"
    version = "0.5.0"

    @staticmethod
    def _runtime_persian(edit_decisions: dict[str, Any]) -> dict[str, Any] | None:
        persian = edit_decisions.get("persian")
        if not isinstance(persian, dict):
            return None
        runtime_persian = dict(persian)
        runtime_persian.pop("_approvedSubtitleScript", None)
        runtime_persian.pop("_hookCaptionHandoff", None)
        metadata = edit_decisions.get("metadata") or {}
        approved_script = metadata.get("persianSubtitleScript") if isinstance(metadata, dict) else None
        hook_handoff = metadata.get("hookCaptionHandoff") if isinstance(metadata, dict) else None
        if approved_script is not None:
            runtime_persian["_approvedSubtitleScript"] = approved_script
        if hook_handoff is not None:
            # Runtime-only injection keeps the public edit schema stable while making
            # the explicit handoff available before burned-caption geometry freezes.
            runtime_persian["_hookCaptionHandoff"] = hook_handoff
        return runtime_persian

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
                min_connector_words=8 if profile_version in {"2.14.0", "2.15.0"} else 0,
            )
            burned = self._apply_hook_caption_handoff(burned, persian)
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
