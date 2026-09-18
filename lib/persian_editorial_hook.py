"""Canonical editorial-hook authority and selection evidence for Persian reels.

Creative generation still belongs to the agent. This module owns the durable boundary:
a user-supplied hook is immutable authority, while automatic selection must cite the
repo-owned corpus and persist enough evidence to show that retention never outranked
content truth.
"""
from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from typing import Any

HOOK_SELECTION_POLICY_VERSION = "retention-first-v1"
HOOK_REFERENCE_CORPUS = (
    "docs/reference/persian-hooks/hookbook.md",
    "docs/reference/persian-hooks/hook-library-fa.md",
    "docs/reference/persian-hooks/hook-selector-helper.md",
)
MIN_AUTOMATIC_HOOK_SCORE = 7.0
REQUIRED_CONTENT_MATCH_SCORE = 2


class PersianEditorialHookError(ValueError):
    """Raised when hook authority or automatic-selection evidence is invalid."""


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _clean_text(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise PersianEditorialHookError(f"{label} must not be empty")
    return text


def build_initial_hook_selection(user_hook: str | None = None) -> dict[str, Any]:
    """Create the front-door hook decision before any creative selection occurs."""
    if user_hook is not None and str(user_hook).strip():
        text = _clean_text(user_hook, "user hook")
        return {
            "version": "1.0",
            "mode": "user_supplied",
            "text": text,
            "sha256": _sha256_text(text),
            "authoritative": True,
            "may_be_replaced_automatically": False,
            "selection_policy": HOOK_SELECTION_POLICY_VERSION,
            "corpus": list(HOOK_REFERENCE_CORPUS),
        }
    return {
        "version": "1.0",
        "mode": "automatic",
        "authoritative": False,
        "may_be_replaced_automatically": True,
        "selection_policy": HOOK_SELECTION_POLICY_VERSION,
        "corpus": list(HOOK_REFERENCE_CORPUS),
        "status": "selection_required",
    }


def validate_user_hook_unchanged(decision: Mapping[str, Any], selected_text: str) -> None:
    """Refuse downstream replacement of an explicitly supplied hook."""
    if str(decision.get("mode") or "") != "user_supplied":
        return
    expected = _clean_text(decision.get("text"), "authoritative user hook")
    actual = _clean_text(selected_text, "selected hook")
    if actual != expected or _sha256_text(actual) != str(decision.get("sha256") or ""):
        raise PersianEditorialHookError(
            "user-supplied hook is authoritative and cannot be automatically replaced or rewritten"
        )


def _normalized_hook_text(value: object) -> str:
    return " ".join(_clean_text(value, "hook text").split())


def edit_hook_text(payload: Mapping[str, Any]) -> str:
    """Return the one viewer-visible authored hook from an edit payload.

    Visual segmentation (lead/hero/tail or wrapped rows) may change, but the
    selected words and punctuation remain one authoritative sentence.
    """
    persian = payload.get("persian") if isinstance(payload, Mapping) else None
    if not isinstance(persian, Mapping):
        raise PersianEditorialHookError("edit payload requires a persian object")
    moments = persian.get("moments")
    if not isinstance(moments, Sequence) or isinstance(moments, (str, bytes)):
        raise PersianEditorialHookError("edit payload requires Persian moments")
    hooks = [moment for moment in moments if isinstance(moment, Mapping) and str(moment.get("kind") or "") == "hook"]
    if len(hooks) != 1:
        raise PersianEditorialHookError("edit payload must contain exactly one opening hook")
    segments = hooks[0].get("segments")
    if not isinstance(segments, Sequence) or isinstance(segments, (str, bytes)):
        raise PersianEditorialHookError("opening hook requires authored text segments")
    parts = [
        str(segment.get("text") or "").strip()
        for segment in segments
        if isinstance(segment, Mapping) and str(segment.get("role") or "") != "source"
    ]
    visible = " ".join(part for part in parts if part)
    return _normalized_hook_text(visible)


def validate_edit_hook_authority(
    decision: Mapping[str, Any], payload: Mapping[str, Any]
) -> dict[str, Any]:
    """Bind edit staging to the durable front-door hook decision."""
    mode = str(decision.get("mode") or "")
    if mode == "automatic" and str(decision.get("status") or "") != "selected":
        raise PersianEditorialHookError(
            "automatic hook selection required before edit staging"
        )
    if mode not in {"user_supplied", "automatic"}:
        raise PersianEditorialHookError("workflow hook authority mode is invalid")
    expected = _normalized_hook_text(decision.get("text"))
    expected_sha = str(decision.get("sha256") or "").strip().lower()
    if expected_sha != _sha256_text(str(decision.get("text") or "").strip()):
        raise PersianEditorialHookError("workflow selected hook digest is invalid")
    actual = edit_hook_text(payload)
    if actual != expected:
        if mode == "user_supplied":
            raise PersianEditorialHookError(
                "user-supplied hook is authoritative and edit staging cannot rewrite it"
            )
        raise PersianEditorialHookError(
            "edit hook does not match the selected hook; reflow is allowed but rewriting is not"
        )
    return {
        "mode": mode,
        "verified": True,
        "selectedHookSha256": expected_sha,
        "viewerVisibleText": actual,
    }


def finalize_automatic_hook_selection(
    initial: Mapping[str, Any],
    *,
    selected_text: str,
    hook_family: str,
    candidates: Sequence[Mapping[str, Any]],
    score: float,
    content_match_score: int,
    evidence_checked: bool,
    unsupported_claims_rejected: bool,
    rationale: str,
) -> dict[str, Any]:
    """Persist the winning automatic hook with retention and truth evidence."""
    if str(initial.get("mode") or "") != "automatic":
        raise PersianEditorialHookError("automatic selection cannot replace a user-supplied hook")
    text = _clean_text(selected_text, "selected hook")
    family = _clean_text(hook_family, "hook family")
    reason = _clean_text(rationale, "hook selection rationale")
    if not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(float(score)):
        raise PersianEditorialHookError("hook score must be finite")
    if float(score) < MIN_AUTOMATIC_HOOK_SCORE:
        raise PersianEditorialHookError(
            f"automatic hook score must be at least {MIN_AUTOMATIC_HOOK_SCORE:.1f}/10"
        )
    if int(content_match_score) != REQUIRED_CONTENT_MATCH_SCORE:
        raise PersianEditorialHookError("automatic hook requires content-match score 2/2")
    if evidence_checked is not True or unsupported_claims_rejected is not True:
        raise PersianEditorialHookError(
            "automatic hook must verify source support and reject unsupported claims before ranking"
        )
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)) or len(candidates) < 2:
        raise PersianEditorialHookError("automatic hook selection requires comparative candidates")
    return {
        "version": "1.0",
        "mode": "automatic",
        "authoritative": False,
        "may_be_replaced_automatically": True,
        "selection_policy": HOOK_SELECTION_POLICY_VERSION,
        "corpus": list(HOOK_REFERENCE_CORPUS),
        "status": "selected",
        "text": text,
        "sha256": _sha256_text(text),
        "hook_family": family,
        "score": round(float(score), 3),
        "content_match_score": REQUIRED_CONTENT_MATCH_SCORE,
        "evidence_checked": True,
        "unsupported_claims_rejected": True,
        "candidate_count": len(candidates),
        "rationale": reason,
    }


__all__ = [
    "HOOK_SELECTION_POLICY_VERSION",
    "HOOK_REFERENCE_CORPUS",
    "MIN_AUTOMATIC_HOOK_SCORE",
    "REQUIRED_CONTENT_MATCH_SCORE",
    "PersianEditorialHookError",
    "build_initial_hook_selection",
    "validate_user_hook_unchanged",
    "edit_hook_text",
    "validate_edit_hook_authority",
    "finalize_automatic_hook_selection",
]
