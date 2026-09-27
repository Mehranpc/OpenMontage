"""Production-boundary helpers for the loudness-aware Persian audio policy."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from lib.persian_edit_contract import inspect_persian_audio_mix


def materialize_loudness_aware_mix(
    edit: Mapping[str, Any], *, base_dir: Path
) -> dict[str, Any]:
    """Return a copy whose speech-time music gain is measurement-derived.

    The derived value is materialized before the draft digest is computed. That
    keeps preflight, promotion, and the renderer bound to the same bytes while the
    renderer can continue consuming the stable ``musicDuckVolume`` prop.

    An explicitly authored value is not silently rewritten: contract validation
    must evaluate that override symmetrically and reject unsafe values. This helper
    only fills the speech-time gain when the author did not supply one.
    """
    normalized = deepcopy(dict(edit))
    persian = normalized.get("persian")
    if not isinstance(persian, dict):
        return normalized
    audio = persian.get("audio")
    if not isinstance(audio, dict) or audio.get("musicDuckVolume") is not None:
        return normalized

    evidence = inspect_persian_audio_mix(normalized, base_dir=base_dir)
    if evidence is None:
        return normalized
    audio["musicDuckVolume"] = float(evidence["speechMusicGain"])
    return normalized


def rendered_audio_review_evidence(
    edit: Mapping[str, Any], candidate: Path, *, base_dir: Path
) -> dict[str, Any]:
    """Build final_review.audio_spotcheck's measured fields for one rendered MP4.

    Output loudness and true peak come from the rendered bytes. Speech/music
    separation uses the documented ``source_lufs_plus_render_gain`` method: source
    LUFS measured from the same narration and bed the edit names, plus the
    speech-time gain the renderer actually applied (#288). Without music the
    caller must record ``musicOmittedReason``; nothing is invented here.
    """
    from lib.persian_rendered_review import measure_rendered_audio_output

    rendered = measure_rendered_audio_output(candidate)
    evidence: dict[str, Any] = {**rendered, "measurementSource": "rendered_mp4_plus_mix_policy"}
    mix = inspect_persian_audio_mix(dict(edit), base_dir=base_dir)
    if mix is None:
        evidence["music_present"] = False
        return evidence
    # The render's own props sidecar holds the gain it actually applied.
    props_path = candidate.with_name(candidate.name + ".props.json")
    if not props_path.is_file():
        rendered_name = "rendered.mp4" if candidate.name == "candidate.mp4" else candidate.name
        props_path = candidate.with_name(rendered_name + ".props.json")
    if props_path.is_file():
        import json

        props = json.loads(props_path.read_text(encoding="utf-8"))
        applied = (props.get("audio") or {}).get("musicDuckVolume")
        if applied is not None and abs(float(applied) - float(mix["speechMusicGain"])) > 1e-6:
            raise ValueError(
                f"rendered speech-time music gain {float(applied)} differs from the measured "
                f"mix policy gain {mix['speechMusicGain']}"
            )
    evidence.update({
        "music_present": True,
        "separationMethod": "source_lufs_plus_render_gain",
        "narrationLufs": mix["measuredNarrationLufs"],
        "musicLufs": mix["measuredMusicLufs"],
        "speechMusicGain": mix["speechMusicGain"],
        "speechMusicSeparationLu": mix["predictedSeparationLu"],
    })
    return evidence


__all__ = ["materialize_loudness_aware_mix", "rendered_audio_review_evidence"]
