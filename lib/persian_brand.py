"""Canonical Persian brand and byte-exact display-text governance.

Brand and strict-copy values cross several artifacts before Remotion sees them.
This module deliberately compares and hashes the original UTF-8 bytes: it never
normalizes punctuation, Unicode code points, whitespace, or digits.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

CANONICAL_BRAND_PROFILE = "pathway-of-surrender-v1"
AUTHORIZED_OVERRIDE_PROFILE = "authorized-override"
CANONICAL_PERSIAN_TEXT = "طریقت تسلیم"
CANONICAL_LATIN_TEXT = "Pathway_of_Surrender"
EXACT_TEXT_ENCODING = "utf-8"
EXACT_TEXT_NORMALIZATION = "none"
EXACT_TEXT_HASH_ALGORITHM = "sha256-utf8"
EXPLICIT_AUTHORIZATION_SOURCE = "explicit_user_response"
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


class BrandAuthorizationError(ValueError):
    """Raised when a non-canonical brand has no auditable user authorization."""


def text_sha256(text: str) -> str:
    """Hash the exact UTF-8 bytes of ``text`` without normalization."""
    if not isinstance(text, str):
        raise TypeError("exact display text must be a string")
    return hashlib.sha256(text.encode(EXACT_TEXT_ENCODING)).hexdigest()


def exact_text_record(text: str) -> dict[str, str]:
    """Create the transport record used for byte-exact display strings."""
    if not isinstance(text, str) or text == "":
        raise ValueError("exact display text must be a non-empty string")
    return {
        "text": text,
        "sha256": text_sha256(text),
        "encoding": EXACT_TEXT_ENCODING,
        "normalization": EXACT_TEXT_NORMALIZATION,
    }


def validate_exact_text_record(value: Any) -> dict[str, str]:
    """Validate and return a canonical record without rewriting its text."""
    if not isinstance(value, dict):
        raise ValueError("exactText must be an object")
    text = value.get("text")
    digest = value.get("sha256")
    if not isinstance(text, str) or text == "":
        raise ValueError("exactText.text must be a non-empty string")
    if value.get("encoding") != EXACT_TEXT_ENCODING:
        raise ValueError("exactText.encoding must be 'utf-8'")
    if value.get("normalization") != EXACT_TEXT_NORMALIZATION:
        raise ValueError("exactText.normalization must be 'none'")
    if not isinstance(digest, str) or not _HEX_64.fullmatch(digest):
        raise ValueError("exactText.sha256 must be a lowercase 64-character digest")
    expected = text_sha256(text)
    if digest != expected:
        raise ValueError(
            "exactText.sha256 does not match exactText.text UTF-8 bytes; "
            "do not normalize or repair strict copy"
        )
    return exact_text_record(text)


def _text_hashes(persian_text: str, latin_text: str) -> dict[str, str]:
    return {
        "algorithm": EXACT_TEXT_HASH_ALGORITHM,
        "persianText": text_sha256(persian_text),
        "latinText": text_sha256(latin_text),
    }


def canonical_watermark() -> dict[str, Any]:
    """Return a fresh canonical, audit-ready watermark record."""
    return {
        "brandProfile": CANONICAL_BRAND_PROFILE,
        "persianText": CANONICAL_PERSIAN_TEXT,
        "latinText": CANONICAL_LATIN_TEXT,
        "textHashes": _text_hashes(CANONICAL_PERSIAN_TEXT, CANONICAL_LATIN_TEXT),
    }


def _validated_authorization(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BrandAuthorizationError(
            "non-canonical Persian watermark requires overrideAuthorization"
        )
    if value.get("authorized") is not True:
        raise BrandAuthorizationError(
            "overrideAuthorization.authorized must be the boolean true"
        )
    if value.get("source") != EXPLICIT_AUTHORIZATION_SOURCE:
        raise BrandAuthorizationError(
            "brand override must come from source='explicit_user_response'"
        )
    decision_id = value.get("decisionId")
    reason = value.get("reason")
    if not isinstance(decision_id, str) or not decision_id.strip():
        raise BrandAuthorizationError(
            "brand override authorization requires a non-empty decisionId"
        )
    if not isinstance(reason, str) or not reason.strip():
        raise BrandAuthorizationError(
            "brand override authorization requires a non-empty reason"
        )
    result: dict[str, Any] = {
        "authorized": True,
        "source": EXPLICIT_AUTHORIZATION_SOURCE,
        "decisionId": decision_id,
        "reason": reason,
    }
    if "recordedAt" in value:
        if not isinstance(value["recordedAt"], str) or not value["recordedAt"].strip():
            raise BrandAuthorizationError(
                "overrideAuthorization.recordedAt must be a non-empty string"
            )
        result["recordedAt"] = value["recordedAt"]
    return result


def resolve_watermark(value: Any) -> dict[str, Any]:
    """Default to the canonical brand or validate an explicit override.

    Equality is exact. An added ``@``, a different quote, a ZWNJ change, or any
    other code-point drift is an override and needs the same authorization as a
    wholly different brand.
    """
    if value is None:
        return canonical_watermark()
    if not isinstance(value, dict):
        raise ValueError("edit_decisions.persian.watermark must be an object")
    if "persianText" not in value or "latinText" not in value:
        raise ValueError(
            "an authored watermark must include both persianText and latinText; "
            "omit the whole watermark object to use the canonical brand"
        )
    persian_text = value["persianText"]
    latin_text = value["latinText"]
    if not isinstance(persian_text, str) or not isinstance(latin_text, str):
        raise ValueError("watermark persianText and latinText must be strings")
    hashes = _text_hashes(persian_text, latin_text)
    provided_hashes = value.get("textHashes")
    if provided_hashes is not None and provided_hashes != hashes:
        raise ValueError(
            "watermark textHashes do not match the exact display strings"
        )
    canonical = (
        persian_text == CANONICAL_PERSIAN_TEXT
        and latin_text == CANONICAL_LATIN_TEXT
    )
    if canonical:
        profile = value.get("brandProfile")
        if profile not in (None, CANONICAL_BRAND_PROFILE):
            raise ValueError("canonical watermark carries the wrong brandProfile")
        return canonical_watermark()
    profile = value.get("brandProfile")
    if profile not in (None, AUTHORIZED_OVERRIDE_PROFILE):
        raise BrandAuthorizationError(
            "non-canonical watermark must use brandProfile='authorized-override'"
        )
    authorization = _validated_authorization(value.get("overrideAuthorization"))
    return {
        "brandProfile": AUTHORIZED_OVERRIDE_PROFILE,
        "persianText": persian_text,
        "latinText": latin_text,
        "textHashes": hashes,
        "overrideAuthorization": authorization,
    }


__all__ = [
    "AUTHORIZED_OVERRIDE_PROFILE",
    "BrandAuthorizationError",
    "CANONICAL_BRAND_PROFILE",
    "CANONICAL_LATIN_TEXT",
    "CANONICAL_PERSIAN_TEXT",
    "EXACT_TEXT_ENCODING",
    "EXACT_TEXT_HASH_ALGORITHM",
    "EXACT_TEXT_NORMALIZATION",
    "EXPLICIT_AUTHORIZATION_SOURCE",
    "canonical_watermark",
    "exact_text_record",
    "resolve_watermark",
    "text_sha256",
    "validate_exact_text_record",
]
