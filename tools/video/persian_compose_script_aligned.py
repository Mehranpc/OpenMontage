"""Delivery-safe Persian composer with approved-script-aligned subtitles.

This module intentionally registers a later, stricter implementation under the
existing ``persian_compose`` tool name. Tool discovery is lexical, so it first
registers ``tools.video.persian_compose.PersianCompose`` and then replaces that
entry with :class:`ScriptAlignedPersianCompose`. The renderer itself is inherited;
only the sidecar contract changes.

The authoritative subtitle record lives at
``edit_decisions.metadata.persianSubtitleScript`` so existing artifact schemas stay
backward-readable. It contains ``text``, ``sha256``, ``matchPolicy`` and optional
``maxCps``. Raw ``persian.audio.wordTimings`` remain the timing signal used by the
sync gate. They are never copied into delivery text.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lib.persian_srt import render_srt
from lib.persian_captions import (
    BURNED_CAPTION_MAX_VISIBLE_CHARS,
    BURNED_CAPTION_MODES,
    build_burned_caption_props,
    resolve_caption_mode,
)
from lib.persian_srt_alignment import (
    SubtitleAlignmentError,
    build_script_aligned_cues,
)
from tools.video.persian_compose import PersianCompose


class ScriptAlignedPersianCompose(PersianCompose):
    """PersianCompose with a pre-render, script-authoritative SRT gate."""

    # Same public tool identity: registry discovery loads this module after
    # persian_compose.py and deliberately replaces the older implementation.
    name = "persian_compose"
    version = "0.4.0"

    @staticmethod
    def _runtime_persian(edit_decisions: dict[str, Any]) -> dict[str, Any] | None:
        """Return the internal Persian block used by render and no-copy preflight.

        The persisted artifact keeps approved delivery copy in metadata so the public
        schema stays stable. Both execution paths must inject that same record before
        subtitle/caption alignment; duplicating the injection let preflight disagree
        with the render it was supposed to predict.
        """
        persian = edit_decisions.get("persian")
        if not isinstance(persian, dict):
            return None
        runtime_persian = dict(persian)
        runtime_persian.pop("_approvedSubtitleScript", None)
        metadata = edit_decisions.get("metadata") or {}
        approved_script = (
            metadata.get("persianSubtitleScript")
            if isinstance(metadata, dict)
            else None
        )
        if approved_script is not None:
            # Private runtime-only key. It is never written into render props and is
            # not part of the persisted artifact schema.
            runtime_persian["_approvedSubtitleScript"] = approved_script
        return runtime_persian

    def execute(self, inputs: dict[str, Any]):
        """Inject the schema-valid metadata record into an internal render copy."""
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

    def _build_caption_props(
        self, persian: dict[str, Any]
    ) -> tuple[str, list[dict[str, Any]]]:
        """Build approved-script captions before Film Type freezes layout."""
        mode = resolve_caption_mode(
            persian.get("captionMode"), platform_target=persian.get("platformTarget")
        )
        if mode in BURNED_CAPTION_MODES:
            burned = self._aligned_subtitle_cues(
                persian,
                max_visible_chars=BURNED_CAPTION_MAX_VISIBLE_CHARS,
                id_prefix="caption",
                require_words=True,
            )
            return mode, build_burned_caption_props(burned)

        # Sidecar-only still validates approved-script alignment before browser work.
        self._aligned_subtitle_cues(persian)
        return mode, []

    @staticmethod
    def _aligned_subtitle_cues(
        persian: dict[str, Any],
        *,
        max_visible_chars: int | None = None,
        id_prefix: str = "cue",
        require_words: bool = False,
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
            )
        except SubtitleAlignmentError as exc:
            raise ValueError(
                "the approvedScript-backed Persian sidecar SRT is not provably "
                "aligned, so delivery is refused rather than shipping ASR copy or "
                f"a timing gap: {exc}"
            ) from exc

    @staticmethod
    def _write_subtitles(
        persian: dict[str, Any], output_path: Path
    ) -> tuple[str | None, list[str]]:
        mode = resolve_caption_mode(
            persian.get("captionMode"), platform_target=persian.get("platformTarget")
        )
        if mode == "burned_captions":
            return None, []

        cues = ScriptAlignedPersianCompose._aligned_subtitle_cues(persian)
        if not cues:
            return None, []

        srt_path = output_path.with_suffix(".srt")
        # Keep the existing BOM policy for Persian player compatibility.
        srt_path.write_text(render_srt(cues), encoding="utf-8-sig")
        # Alignment, lexical equality, speech coverage, overlap, and reading speed
        # are hard gates. A sidecar that was written therefore has no suppressed
        # advisory.
        return str(srt_path), []


__all__ = ["ScriptAlignedPersianCompose"]
