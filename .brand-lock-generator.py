from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(".")


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one match in {path}, got {count}: {old[:80]!r}")
    target.write_text(text.replace(old, new), encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


write(
    "lib/persian_brand.py",
    '''"""Canonical Persian brand and byte-exact display-text governance.

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
''',
)

# Strict moment copy: preserve exact bytes instead of passing through the normalizer.
replace_once(
    "lib/persian_moments.py",
    "from typing import Any, Iterable, Literal\n\nfrom lib.persian_text import (\n",
    "from typing import Any, Iterable, Literal\n\nfrom lib.persian_brand import validate_exact_text_record\nfrom lib.persian_text import (\n",
)
replace_once(
    "lib/persian_moments.py",
    '''    anchor_text: str = ""
    # Fitted total ink+gap height, px at nominal width. Set by the compose
''',
    '''    anchor_text: str = ""
    # Present only for copy that must survive artifact/props transport byte-for-byte.
    exact_text: dict[str, str] | None = None
    # Fitted total ink+gap height, px at nominal width. Set by the compose
''',
)
replace_once(
    "lib/persian_moments.py",
    '''        if self.anchor_text:
            props["anchorText"] = self.anchor_text
        if self.stack_height_px is not None:
''',
    '''        if self.anchor_text:
            props["anchorText"] = self.anchor_text
        if self.exact_text is not None:
            props["exactText"] = dict(self.exact_text)
        if self.stack_height_px is not None:
''',
)
replace_once(
    "lib/persian_moments.py",
    '''        segments: list[PersianSegment] = []
        for seg_index, raw_segment in enumerate(raw_segments):
''',
    '''        exact_text = (
            validate_exact_text_record(raw.get("exactText"))
            if raw.get("exactText") is not None
            else None
        )
        segments: list[PersianSegment] = []
        for seg_index, raw_segment in enumerate(raw_segments):
''',
)
replace_once(
    "lib/persian_moments.py",
    '''            text = _clean(raw_segment.get("text"), persian_digits=persian_digits)
            if not text:
                raise ValueError(
                    f"{where} segment {seg_index} ({role}) has no text. An empty "
                    "segment reserves vertical space and paints nothing."
                )
''',
    '''            if exact_text is None:
                text = _clean(
                    raw_segment.get("text"), persian_digits=persian_digits
                )
            else:
                authored_text = raw_segment.get("text")
                if not isinstance(authored_text, str) or authored_text == "":
                    raise ValueError(
                        f"{where} strict segment {seg_index} ({role}) needs a "
                        "non-empty string; strict copy is never coerced or stripped"
                    )
                text = authored_text
            if not text:
                raise ValueError(
                    f"{where} segment {seg_index} ({role}) has no text. An empty "
                    "segment reserves vertical space and paints nothing."
                )
''',
)
replace_once(
    "lib/persian_moments.py",
    '''        start = raw.get("startSeconds", raw.get("start"))
        end = raw.get("endSeconds", raw.get("end"))
''',
    '''        if exact_text is not None:
            display_text = " ".join(
                segment.text for segment in segments if segment.role != "source"
            )
            if display_text != exact_text["text"]:
                raise ValueError(
                    f"{where} exactText.text does not equal the authored display "
                    "segments byte-for-byte; punctuation, code points, whitespace, "
                    "and digits may not be normalized"
                )

        start = raw.get("startSeconds", raw.get("start"))
        end = raw.get("endSeconds", raw.get("end"))
''',
)
replace_once(
    "lib/persian_moments.py",
    '''                segments=segments,
                anchor_text=_clean(raw.get("anchorText"), persian_digits=False),
            )
''',
    '''                segments=segments,
                anchor_text=_clean(raw.get("anchorText"), persian_digits=False),
                exact_text=exact_text,
            )
''',
)

# Compose boundary: canonicalize before creating/staging anything and persist it.
replace_once(
    "tools/video/persian_compose.py",
    "from lib.persian_design import derive_lockup_size, prepare_v2, resolve_watermark_plan\n",
    "from lib.persian_brand import resolve_watermark\nfrom lib.persian_design import derive_lockup_size, prepare_v2, resolve_watermark_plan\n",
)
replace_once(
    "tools/video/persian_compose.py",
    '''        staging_dir.mkdir(parents=True, exist_ok=True)
        attributions: list[str] = []
''',
    '''        watermark = resolve_watermark(persian.get("watermark"))
        staging_dir.mkdir(parents=True, exist_ok=True)
        attributions: list[str] = []
''',
)
replace_once(
    "tools/video/persian_compose.py",
    '''        moments = (self._build_moments(persian, duration_seconds, v2=True, measure_layout=False) if film_type
                   else self._build_moments(persian, duration_seconds, v2=design_snapshot is not None))
''',
    '''        resolved_persian = {**persian, "watermark": watermark}
        moments = (self._build_moments(resolved_persian, duration_seconds, v2=True, measure_layout=False) if film_type
                   else self._build_moments(resolved_persian, duration_seconds, v2=design_snapshot is not None))
''',
)
replace_once(
    "tools/video/persian_compose.py",
    '''                enforce_silhouette=False, watermark=persian.get("watermark") or {},
''',
    '''                enforce_silhouette=False, watermark=watermark,
''',
)
replace_once(
    "tools/video/persian_compose.py",
    '''        if persian.get("watermark"):
            props["watermark"] = persian["watermark"]
''',
    '''        # Always persist the resolved canonical/authorized brand and exact hashes.
        props["watermark"] = watermark
''',
)

# Renderer contract and default mirror the Python canonical source.
replace_once(
    "remotion-composer/src/persian/types.ts",
    '''  readonly anchorText?: string;
  /**
   * Fitted total ink+gap height in px at nominal width (`FittedMoment.heightPx`
''',
    '''  readonly anchorText?: string;
  /** Byte-exact display record. Strict copy is not normalized before props generation. */
  readonly exactText?: {
    readonly text: string;
    readonly sha256: string;
    readonly encoding: "utf-8";
    readonly normalization: "none";
  };
  /**
   * Fitted total ink+gap height in px at nominal width (`FittedMoment.heightPx`
''',
)
replace_once(
    "remotion-composer/src/persian/types.ts",
    '''export interface PersianWatermark {
  /** Persian side of the lockup. Rendered in an explicit RTL span. */
  readonly persianText: string;
  /** Latin side of the lockup. Rendered in an explicit LTR span. */
  readonly latinText: string;
}
''',
    '''export interface PersianWatermark {
  /** Persian side of the lockup. Rendered in an explicit RTL span. */
  readonly persianText: string;
  /** Latin side of the lockup. Rendered in an explicit LTR span. */
  readonly latinText: string;
  readonly brandProfile?: "pathway-of-surrender-v1" | "authorized-override";
  readonly textHashes?: {
    readonly algorithm: "sha256-utf8";
    readonly persianText: string;
    readonly latinText: string;
  };
  readonly overrideAuthorization?: {
    readonly authorized: true;
    readonly source: "explicit_user_response";
    readonly decisionId: string;
    readonly reason: string;
    readonly recordedAt?: string;
  };
}
''',
)
replace_once(
    "remotion-composer/src/persian/types.ts",
    '''/** The watermark the user specified for this pipeline. */
export const DEFAULT_WATERMARK: PersianWatermark = {
  persianText: "طریقت تسلیم",
  latinText: "@Pathway_of_Surrender",
};
''',
    '''/** One canonical production brand. Missing input resolves to this exact record. */
export const CANONICAL_BRAND_PROFILE = "pathway-of-surrender-v1" as const;
export const DEFAULT_WATERMARK: PersianWatermark = {
  brandProfile: CANONICAL_BRAND_PROFILE,
  persianText: "طریقت تسلیم",
  latinText: "Pathway_of_Surrender",
  textHashes: {
    algorithm: "sha256-utf8",
    persianText: "2c2e0a9a76b57df83e04e712b82f6d51ec3af600b3a697b281f4d06d5331d02a",
    latinText: "aca253429dc44dff47a579cd23c532cb97df69771ad022c2236b66c55b1fd030",
  },
};
''',
)
replace_once(
    "remotion-composer/src/persian/types.ts",
    '''  for (const [index, segment] of moment.segments.entries()) {
''',
    '''  if (moment.exactText) {
    const displayText = moment.segments
      .filter((segment) => segment.role !== "source")
      .map((segment) => segment.text)
      .join(" ");
    if (
      moment.exactText.encoding !== "utf-8" ||
      moment.exactText.normalization !== "none" ||
      displayText !== moment.exactText.text
    ) {
      throw new Error(
        `${where}: exactText does not equal the displayed segments byte-for-byte; ` +
          `strict punctuation, code points, whitespace, and digits may not be normalized.`,
      );
    }
  }

  for (const [index, segment] of moment.segments.entries()) {
''',
)
replace_once(
    "remotion-composer/src/persian/filmType/layout.ts",
    '''    moments:props.moments.map(m=>({id:m.id,kind:m.kind,startSeconds:m.startSeconds,endSeconds:m.endSeconds,segments:m.segments,presentation:m.presentation})),
''',
    '''    moments:props.moments.map(m=>({id:m.id,kind:m.kind,startSeconds:m.startSeconds,endSeconds:m.endSeconds,segments:m.segments,presentation:m.presentation,exactText:m.exactText})),
''',
)

# JSON artifact contract: strict text record plus auditable brand override fields.
schema_path = ROOT / "schemas/artifacts/edit_decisions.schema.json"
schema = json.loads(schema_path.read_text(encoding="utf-8"))
persian_props = schema["properties"]["persian"]["properties"]
moment_props = persian_props["moments"]["items"]["properties"]
moment_props["exactText"] = {
    "type": "object",
    "description": (
        "Byte-exact display record for strict copy. The non-source segment texts, "
        "joined by one ASCII space, must equal text exactly; no punctuation, Unicode, "
        "whitespace, or digit normalization is allowed."
    ),
    "required": ["text", "sha256", "encoding", "normalization"],
    "properties": {
        "text": {"type": "string", "minLength": 1},
        "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "encoding": {"type": "string", "const": "utf-8"},
        "normalization": {"type": "string", "const": "none"},
    },
    "additionalProperties": False,
}
watermark_props = persian_props["watermark"]["properties"]
watermark_props["brandProfile"] = {
    "type": "string",
    "enum": ["pathway-of-surrender-v1", "authorized-override"],
}
watermark_props["textHashes"] = {
    "type": "object",
    "required": ["algorithm", "persianText", "latinText"],
    "properties": {
        "algorithm": {"type": "string", "const": "sha256-utf8"},
        "persianText": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "latinText": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    },
    "additionalProperties": False,
}
watermark_props["overrideAuthorization"] = {
    "type": "object",
    "required": ["authorized", "source", "decisionId", "reason"],
    "properties": {
        "authorized": {"type": "boolean", "const": True},
        "source": {"type": "string", "const": "explicit_user_response"},
        "decisionId": {"type": "string", "minLength": 1},
        "reason": {"type": "string", "minLength": 1},
        "recordedAt": {"type": "string", "minLength": 1},
    },
    "additionalProperties": False,
}
schema_path.write_text(
    json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)

# Existing producer regression now verifies the missing-input canonical default.
replace_once(
    "tests/lib/test_persian_film_type.py",
    "from lib.persian_design import resolve_design",
    "from lib.persian_brand import canonical_watermark\nfrom lib.persian_design import resolve_design",
)
replace_once(
    "tests/lib/test_persian_film_type.py",
    '''                 'shots':[{'id':'s','source':str(clip),'startSeconds':0,'endSeconds':12,'camera':'none','attribution':'Synthetic unit-test fixture','avoidRegions':[]}],
                 'watermark':{'persianText':'','latinText':''}}
''',
    '''                 'shots':[{'id':'s','source':str(clip),'startSeconds':0,'endSeconds':12,'camera':'none','attribution':'Synthetic unit-test fixture','avoidRegions':[]}]}
''',
)
replace_once(
    "tests/lib/test_persian_film_type.py",
    "        self.assertEqual(props['watermark'],persian['watermark'])\n",
    "        self.assertEqual(props['watermark'],canonical_watermark())\n",
)

write(
    "tests/lib/test_persian_brand.py",
    '''"""Canonical brand and byte-exact copy regressions."""
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
''',
)

# Active authoring guidance: one default, explicit override, strict-copy hash.
edit_path = "skills/pipelines/persian-footage/edit-director.md"
replace_once(
    edit_path,
    "## Moments, not captions\n",
    '''## Brand and exact-copy locks

Omit `persian.watermark` to use the one production default: `طریقت تسلیم` and
`Pathway_of_Surrender`. The compose preflight writes both exact strings and their
SHA-256 hashes into render props. Do not add `@`, change spacing, or invent a label.
Any non-canonical lockup — including an empty one — needs the user's explicit decision
inside `overrideAuthorization` with `authorized: true`,
`source: "explicit_user_response"`, a non-empty `decisionId`, and a reason. The
resolved props retain that record; an agent inference is never authorization.

For copy that must survive literally (especially the opening hook), add `exactText` to
the moment using `lib.persian_brand.exact_text_record(text)`. Its `text` must equal the
non-source segment strings joined by one ASCII space. In this mode the pipeline does
not normalize punctuation, Arabic/Persian code points, ZWNJ, whitespace, or digits;
any drift or stale hash is a preflight failure rather than a silent repair.

## Moments, not captions
''',
)
replace_once(
    edit_path,
    '''# Orthography survived the copy into edit_decisions — every segment, not one field.
for moment in moments:
    for segment in moment.segments:
        assert normalize(segment.text) == segment.text
''',
    '''# Ordinary copy is canonicalized; strict copy is verified by its exact UTF-8 hash.
from lib.persian_brand import validate_exact_text_record
for moment in moments:
    if moment.exact_text is not None:
        validate_exact_text_record(moment.exact_text)
    else:
        for segment in moment.segments:
            assert normalize(segment.text) == segment.text
''',
)

# The old handle form is not canonical. Replace it across active source, tests and docs.
allowed_suffixes = {".py", ".ts", ".tsx", ".md", ".json", ".yaml", ".yml"}
for path in ROOT.rglob("*"):
    if not path.is_file() or path.suffix not in allowed_suffixes:
        continue
    if ".git" in path.parts or "node_modules" in path.parts:
        continue
    text = path.read_text(encoding="utf-8")
    if "@Pathway_of_Surrender" in text:
        path.write_text(text.replace("@Pathway_of_Surrender", "Pathway_of_Surrender"), encoding="utf-8")

# The new module and tests themselves must not accidentally conceal the historical
# regression fixture; restore that one test input after the repository-wide cleanup.
test_path = ROOT / "tests/lib/test_persian_brand.py"
test_text = test_path.read_text(encoding="utf-8")
test_text = test_text.replace(
    '{"persianText": CANONICAL_PERSIAN_TEXT, "latinText": "Pathway_of_Surrender"},\n        {"persianText": "طریقت‌تسلیم"',
    '{"persianText": CANONICAL_PERSIAN_TEXT, "latinText": "@Pathway_of_Surrender"},\n        {"persianText": "طریقت‌تسلیم"',
    1,
)
test_path.write_text(test_text, encoding="utf-8")

print("brand/exact-text patch applied")
''