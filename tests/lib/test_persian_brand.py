"""Canonical brand and byte-exact copy regressions."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from lib.persian_brand import (
    AUTHORIZED_OVERRIDE_PROFILE,
    BrandAuthorizationError,
    CANONICAL_BRAND_PROFILE,
    CANONICAL_LATIN_TEXT,
    CANONICAL_PERSIAN_TEXT,
    canonical_watermark,
    exact_text_record,
    resolve_watermark,
    text_sha256,
    validate_exact_text_record,
)
from lib.persian_moments import build_moments
from tools.video.persian_compose import PersianCompose

ROOT = Path(__file__).resolve().parents[2]
EXACT_HOOK = "زیاد “ببخشید” گفتن همیشه نشانه ادب نیست."


def _authorization() -> dict[str, object]:
    return {
        "authorized": True,
        "source": "explicit_user_response",
        "decisionId": "decision-brand-override-001",
        "reason": "User explicitly requested a one-off alternate lockup.",
        "recordedAt": "2026-09-10T07:30:00Z",
    }


def _minimal_persian(tmp_path: Path) -> dict[str, object]:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"fixture-not-decoded")
    return {
        "format": "vertical",
        "durationSeconds": 12,
        "design": {"version": 2, "profile": "film-type", "seed": "brand-test"},
        "moments": [],
        "shots": [
            {
                "id": "shot-1",
                "source": str(clip),
                "startSeconds": 0,
                "endSeconds": 12,
                "camera": "none",
                "attribution": "Synthetic unit-test fixture",
                "avoidRegions": [],
            }
        ],
    }


def test_missing_watermark_resolves_to_canonical_record() -> None:
    mark = resolve_watermark(None)
    assert mark == canonical_watermark()
    assert mark["brandProfile"] == CANONICAL_BRAND_PROFILE
    assert mark["persianText"] == CANONICAL_PERSIAN_TEXT
    assert mark["latinText"] == CANONICAL_LATIN_TEXT
    assert mark["textHashes"]["persianText"] == text_sha256(CANONICAL_PERSIAN_TEXT)
    assert mark["textHashes"]["latinText"] == text_sha256(CANONICAL_LATIN_TEXT)


@pytest.mark.parametrize(
    "watermark",
    [
        {"persianText": "", "latinText": ""},
        {"persianText": "روایتِ روشن", "latinText": "OpenMontage"},
        {"persianText": CANONICAL_PERSIAN_TEXT, "latinText": "@Pathway_of_Surrender"},
        {"persianText": "طریقت‌تسلیم", "latinText": CANONICAL_LATIN_TEXT},
    ],
)
def test_invented_or_codepoint_drifted_brand_is_refused(watermark) -> None:
    with pytest.raises(BrandAuthorizationError, match="overrideAuthorization"):
        resolve_watermark(watermark)


def test_explicit_override_is_preserved_and_auditable() -> None:
    requested = {
        "persianText": "برند ویژه",
        "latinText": "Special_Brand",
        "overrideAuthorization": _authorization(),
    }
    resolved = resolve_watermark(requested)
    assert resolved["brandProfile"] == AUTHORIZED_OVERRIDE_PROFILE
    assert resolved["persianText"] == requested["persianText"]
    assert resolved["latinText"] == requested["latinText"]
    assert resolved["overrideAuthorization"] == requested["overrideAuthorization"]
    assert resolved["textHashes"]["persianText"] == text_sha256("برند ویژه")


def test_override_requires_explicit_user_source_and_decision_id() -> None:
    requested = {
        "persianText": "برند ویژه",
        "latinText": "Special_Brand",
        "overrideAuthorization": {**_authorization(), "source": "agent_inference"},
    }
    with pytest.raises(BrandAuthorizationError, match="explicit_user_response"):
        resolve_watermark(requested)
    requested["overrideAuthorization"] = {**_authorization(), "decisionId": ""}
    with pytest.raises(BrandAuthorizationError, match="decisionId"):
        resolve_watermark(requested)
    requested["overrideAuthorization"] = {**_authorization(), "reason": ""}
    with pytest.raises(BrandAuthorizationError, match="reason"):
        resolve_watermark(requested)


def test_provided_brand_hashes_must_match_exact_strings() -> None:
    mark = canonical_watermark()
    mark["textHashes"] = {**mark["textHashes"], "latinText": "0" * 64}
    with pytest.raises(ValueError, match="textHashes"):
        resolve_watermark(mark)


def test_exact_hook_hash_is_over_original_utf8_bytes() -> None:
    record = exact_text_record(EXACT_HOOK)
    assert record == {
        "text": EXACT_HOOK,
        "sha256": "38e09ee28aa52aee3a5714a70da53f6a28b89c5f5bda0205b9c5d62ece050ad7",
        "encoding": "utf-8",
        "normalization": "none",
    }
    assert validate_exact_text_record(record) == record


def test_strict_moment_survives_build_and_props_byte_for_byte() -> None:
    exact = "مي‌روم؛ “همین”"
    built = build_moments(
        [
            {
                "id": "strict-1",
                "kind": "statement",
                "startSeconds": 0.2,
                "endSeconds": 4.0,
                "segments": [{"role": "hero", "text": exact}],
                "exactText": exact_text_record(exact),
            }
        ]
    )[0]
    assert built.segments[0].text == exact
    props = built.to_props()
    assert props["segments"][0]["text"] == exact
    assert props["exactText"] == exact_text_record(exact)
    assert build_moments(
        [
            {
                "kind": "statement",
                "startSeconds": 0.2,
                "endSeconds": 4.0,
                "segments": [{"role": "hero", "text": exact}],
            }
        ]
    )[0].segments[0].text != exact


def test_curly_quote_or_whitespace_rewrite_fails_strict_copy() -> None:
    record = exact_text_record(EXACT_HOOK)
    with pytest.raises(ValueError, match="byte-for-byte"):
        build_moments(
            [
                {
                    "kind": "hook",
                    "startSeconds": 0.2,
                    "endSeconds": 4.5,
                    "segments": [
                        {
                            "role": "hero",
                            "text": 'زیاد "ببخشید" گفتن همیشه نشانه ادب نیست.',
                        }
                    ],
                    "exactText": record,
                }
            ]
        )


def test_exact_text_digest_mismatch_is_refused() -> None:
    record = {**exact_text_record(EXACT_HOOK), "sha256": "0" * 64}
    with pytest.raises(ValueError, match="does not match"):
        validate_exact_text_record(record)


def test_compose_defaults_brand_before_staging(tmp_path: Path) -> None:
    persian = _minimal_persian(tmp_path)
    with patch(
        "tools.video.persian_compose.prepare_film_type_props",
        side_effect=lambda props, _composer: props,
    ):
        props, _ = PersianCompose()._build_props(
            persian, tmp_path / "stage", "brand-default"
        )
    assert props["watermark"] == canonical_watermark()


def test_compose_rejects_unauthorized_brand_before_media_staging(tmp_path: Path) -> None:
    persian = _minimal_persian(tmp_path)
    persian["shots"][0]["source"] = str(tmp_path / "does-not-exist.mp4")
    persian["watermark"] = {
        "persianText": "روایتِ روشن",
        "latinText": "OpenMontage",
    }
    stage = tmp_path / "stage"
    with pytest.raises(BrandAuthorizationError):
        PersianCompose()._build_props(persian, stage, "brand-refusal")
    assert not stage.exists()


def test_renderer_default_is_pinned_to_python_canonical_values() -> None:
    typescript = (ROOT / "remotion-composer/src/persian/types.ts").read_text(
        encoding="utf-8"
    )
    assert f'persianText: "{CANONICAL_PERSIAN_TEXT}"' in typescript
    assert f'latinText: "{CANONICAL_LATIN_TEXT}"' in typescript
    assert "@Pathway_of_Surrender" not in typescript
    assert text_sha256(CANONICAL_PERSIAN_TEXT) in typescript
    assert text_sha256(CANONICAL_LATIN_TEXT) in typescript
