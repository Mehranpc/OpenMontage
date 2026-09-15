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


__all__ = ["materialize_loudness_aware_mix"]
