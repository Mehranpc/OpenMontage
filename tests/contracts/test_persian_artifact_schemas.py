"""Contract: the Persian artifacts validate against the shared artifact schemas.

The three schemas in `schemas/artifacts/` are contracts between pipeline stages, and all
three declare `additionalProperties: false`. That is the property worth having — an
undeclared key is a typo or a stale writer, and both are silent — but it means adding a
pipeline has two honest options and one dishonest one:

1. declare the new fields, or
2. keep the new data out of the canonical artifact,

against the tempting third of flipping `additionalProperties` to `true`, which was done
during development and is what this file exists to prevent recurring. Flipping it does
not add the Persian fields to the contract; it removes the contract, for every pipeline,
so a misspelled `resolutoin` in an unrelated explainer render stops being an error.

So the tests below assert both halves: that the strictness is still there, and that a
real persian-footage artifact passes under it. Either alone is satisfiable by cheating.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "schemas" / "artifacts"

#: Every schema a persian-footage run writes into.
PERSIAN_ARTIFACTS = ("asset_manifest", "edit_decisions", "render_report")


def _schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


def _validator(name: str) -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(_schema(name))


def _errors(name: str, instance: dict[str, Any]) -> list[str]:
    return [
        f"{list(error.path)}: {error.message}"
        for error in sorted(_validator(name).iter_errors(instance), key=lambda e: list(e.path))
    ]


# ---------------------------------------------------------------------------
# The schemas themselves
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", PERSIAN_ARTIFACTS)
def test_the_schema_is_a_valid_draft_2020_12_schema(name: str) -> None:
    """Guards the rest of this file: an invalid schema validates everything."""
    jsonschema.Draft202012Validator.check_schema(_schema(name))


@pytest.mark.parametrize("name", PERSIAN_ARTIFACTS)
def test_unknown_top_level_keys_are_still_rejected(name: str) -> None:
    """`additionalProperties: false` survives at the root.

    Asserted by *behaviour* rather than by reading the keyword, because a schema can
    lose its strictness in several ways that all leave the keyword looking right — an
    `anyOf` branch without it, a `$ref` that escapes it. What matters is that a key
    nobody declared is an error.
    """
    instance: dict[str, Any] = {
        "version": "1.0",
        # Both required-field sets, so the only complaint left is the stray key.
        "assets": [],
        "cuts": [],
        "render_runtime": "remotion",
        "outputs": [
            {
                "path": "renders/final.mp4",
                "format": "mp4",
                "resolution": "1080x1920",
                "duration_seconds": 1.0,
            }
        ],
        "a_key_nobody_declared": True,
    }
    problems = _errors(name, instance)
    assert any("a_key_nobody_declared" in problem for problem in problems), (
        f"{name}.schema.json accepted an undeclared top-level key. If "
        f"additionalProperties was relaxed to make room for new fields, declare the "
        f"fields instead — relaxing it removes the contract for every pipeline that "
        f"shares this schema. Errors were: {problems}"
    )


@pytest.mark.parametrize("name", PERSIAN_ARTIFACTS)
def test_the_schema_is_valid_json_with_a_trailing_newline(name: str) -> None:
    """A missing trailing newline is what a hand-edit leaves behind.

    Cheap to check and it catches the specific accident of a file rewritten by a script
    that dumped JSON and stopped — which is how these three lost their formatting and
    their strictness at the same time.
    """
    text = (SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8")
    assert text.endswith("\n"), f"{name}.schema.json has no trailing newline"


# ---------------------------------------------------------------------------
# renderer_family / render_grammar
# ---------------------------------------------------------------------------


def test_persian_footage_is_a_declared_renderer_family() -> None:
    """`edit_decisions.renderer_family` accepts this pipeline.

    The field is locked at proposal stage and carried forward unchanged, so a pipeline
    missing from the enum cannot write a schema-valid artifact at all.
    """
    enum = _schema("edit_decisions")["properties"]["renderer_family"]["enum"]
    assert "persian-footage" in enum


def test_persian_footage_is_a_declared_render_grammar() -> None:
    """And `render_report.render_grammar` accepts it on the way out."""
    enum = _schema("render_report")["properties"]["render_grammar"]["enum"]
    assert "persian-footage" in enum


def test_the_two_enums_have_not_drifted_apart() -> None:
    """They name the same thing at two stages, so they must list the same values.

    A family present in one and absent from the other produces an artifact that
    validates at the edit stage and fails at compose, after the render.
    """
    assert set(_schema("edit_decisions")["properties"]["renderer_family"]["enum"]) == set(
        _schema("render_report")["properties"]["render_grammar"]["enum"]
    )


# ---------------------------------------------------------------------------
# The persian block
# ---------------------------------------------------------------------------


def _minimal_persian_block() -> dict[str, Any]:
    return {
        "format": "vertical",
        "durationSeconds": 12.0,
        "shots": [
            {
                "id": "shot-1",
                "source": "assets/clips/pexels_1.mp4",
                "startSeconds": 0.0,
                "endSeconds": 12.0,
                "sourceInSeconds": 1.0,
                "camera": "push-in",
                "attribution": "Video by Someone on Pexels",
            }
        ],
        "moments": [
            {
                "id": "moment-1",
                "kind": "figure",
                "startSeconds": 2.0,
                "endSeconds": 6.0,
                "segments": [
                    {"role": "lead", "text": "مطالعهٔ دانشگاه اولوی فنلاند روی"},
                    {"role": "hero", "text": "۲۲۶۴ نفر"},
                ],
                "anchorText": "دانشمندهای دانشگاه اولو",
            }
        ],
        "typographicBeats": [],
        "audio": {
            "narration": "assets/audio/voiceover.mp3",
            "wordTimings": [{"word": "قهوه", "start": 0.2, "end": 0.6, "probability": 0.99}],
        },
        "watermark": {
            "persianText": "طریقت تسلیم",
            "latinText": "Pathway_of_Surrender",
        },
    }


def _edit_decisions(persian: dict[str, Any]) -> dict[str, Any]:
    """A whole artifact around a `persian` block.

    `cuts` is empty on purpose and that is not a placeholder: the Persian composition is
    the template, its timeline lives in `persian.shots`, and there is no cut list. The
    schema still requires the key, so a Persian artifact carries it empty.
    """
    return {
        "version": "1.0",
        "cuts": [],
        "render_runtime": "remotion",
        "composition_mode": "templated",
        "renderer_family": "persian-footage",
        "persian": persian,
    }


def test_a_complete_persian_edit_decision_validates() -> None:
    problems = _errors("edit_decisions", _edit_decisions(_minimal_persian_block()))
    assert not problems, problems


@pytest.mark.parametrize("kind", ["figure", "term", "statement", "hook"])
def test_every_moment_kind_validates(kind: str) -> None:
    """All four kinds are declared, not just the one the last render happened to use.

    All four share one shape now — the kind no longer decides the arrangement, it
    records an editorial classification — so one segment list exercises them all.
    """
    persian = _minimal_persian_block()
    persian["moments"] = [
        {
            "id": "moment-1",
            "kind": kind,
            "startSeconds": 2.0,
            "endSeconds": 6.0,
            "segments": [
                {"role": "hero", "text": "۲۲۶۴" if kind == "figure" else "SHBG"},
                {"role": "tail", "text": "توضیح"},
            ],
        }
    ]
    assert not _errors("edit_decisions", _edit_decisions(persian))


@pytest.mark.parametrize("key", ["cues", "hookText", "hookDurationSeconds"])
def test_the_retired_caption_and_hook_keys_are_rejected(key: str) -> None:
    """The schema refuses what `persian_compose` refuses.

    Two enforcers of one retirement, deliberately. `persian_compose` raises with a
    replacement-naming message, which is the useful error; the schema catches an edit
    artifact that was written but never composed — a checkpoint a reviewer approves, and
    which then fails minutes into a render instead of at the checkpoint.
    """
    persian = _minimal_persian_block()
    persian[key] = "anything"
    problems = _errors("edit_decisions", _edit_decisions(persian))
    assert any(key in problem for problem in problems), (
        f"edit_decisions.schema.json accepted the retired key {key!r}: {problems}"
    )


@pytest.mark.parametrize("key", ["text", "label", "kicker", "unit"])
def test_the_retired_slot_keys_are_rejected_on_a_moment(key: str) -> None:
    """Slot-per-role moments are refused, not deprecated.

    The slots produced three type sizes on three different left edges with no
    sentence anywhere — the frame rejected as «معلوم نیست در مورد چیه». Keeping
    them in the schema would keep the arrangement they imply available, and a slot
    that exists gets filled.
    """
    persian = _minimal_persian_block()
    persian["moments"][0][key] = "anything"
    problems = _errors("edit_decisions", _edit_decisions(persian))
    assert any(key in problem for problem in problems), (
        f"edit_decisions.schema.json accepted the retired slot {key!r}: {problems}"
    )


@pytest.mark.parametrize("role", ["lead", "hero", "tail", "source"])
def test_every_segment_role_validates(role: str) -> None:
    """All four roles are declared, and a role outside the enum is rejected.

    The roles carry emphasis and size, never position — the array order is the
    position — so an unknown role has no meaning to assign and must fail rather
    than render as an unstyled block.
    """
    persian = _minimal_persian_block()
    persian["moments"][0]["segments"] = [
        {"role": role, "text": "متن"},
        {"role": "hero", "text": "۲۲۶۴ نفر"},
    ]
    assert not _errors("edit_decisions", _edit_decisions(persian))


def test_an_unknown_segment_role_is_rejected() -> None:
    persian = _minimal_persian_block()
    persian["moments"][0]["segments"] = [{"role": "subhead", "text": "متن"}]
    problems = _errors("edit_decisions", _edit_decisions(persian))
    assert any("subhead" in problem for problem in problems), problems


def test_a_flat_hook_single_segment_with_accents_validates() -> None:
    """The kept-working flat style must survive the schema: one hero segment
    carrying accentWords. A minItems of 2 or a missing accentWords declaration
    would reject the style the pipeline still renders."""
    persian = _minimal_persian_block()
    persian["moments"] = [
        {
            "id": "moment-1",
            "kind": "hook",
            "startSeconds": 0.2,
            "endSeconds": 4.2,
            "segments": [
                {
                    "role": "hero",
                    "text": "می‌دونی قهوه با هورمون‌هات چی‌کار می‌کنه؟",
                    "accentWords": ["قهوه", "هورمون‌هات"],
                }
            ],
        }
    ]
    assert not _errors("edit_decisions", _edit_decisions(persian))


def test_a_claim_qualifier_hook_validates() -> None:
    """The approved style: hero claim plus tail qualifier, declared hook."""
    persian = _minimal_persian_block()
    persian["moments"] = [
        {
            "id": "moment-1",
            "kind": "hook",
            "startSeconds": 0.2,
            "endSeconds": 4.2,
            "segments": [
                {"role": "hero", "text": "فواید عجیب قهوه"},
                {"role": "tail", "text": "روی هورمون‌ها!"},
            ],
        }
    ]
    assert not _errors("edit_decisions", _edit_decisions(persian))


def test_a_music_record_with_provenance_validates() -> None:
    """The narrated-mode music requirement is schema-expressible end to end.

    A bed with no licence record fails `persian_compose`'s gate; an artifact that
    cannot even carry the record would force every project through
    `omitMusicReason`, which turns a deliberate silence into the only option.
    """
    persian = _minimal_persian_block()
    persian["musicTrack"] = {
        "path": "assets/music/bed.mp3",
        "source": "pixabay_music",
        "license": {
            "name": "Pixabay Content License",
            "url": "https://pixabay.com/music/search/coffee/",
            "downloadedAt": "2026-09-02",
        },
        "attribution": "Music: Artist from Pixabay",
        "contentIdRisk": {
            "level": "low",
            "reason": "Pixabay Content License permits monetized social media use; "
            "third-party Content-ID cannot be ruled out by any automated check.",
        },
    }
    assert not _errors("edit_decisions", _edit_decisions(persian))


def test_a_music_record_without_a_licence_page_is_rejected() -> None:
    """Provenance is not optional data: a licence nobody can revisit is not a claim.

    The record exists so a Content-ID dispute can be answered with the page it
    was read from; removing the URL keeps the assertion and deletes the evidence.
    """
    persian = _minimal_persian_block()
    persian["musicTrack"] = {
        "path": "assets/music/bed.mp3",
        "source": "pixabay_music",
        "license": {"name": "Pixabay Content License", "downloadedAt": "2026-09-02"},
        "contentIdRisk": {"level": "low"},
    }
    problems = _errors("edit_decisions", _edit_decisions(persian))
    assert any("musicTrack" in problem for problem in problems), problems


@pytest.mark.parametrize("field", ["format", "durationSeconds", "shots", "moments"])
def test_the_persian_block_requires_what_the_renderer_cannot_default(field: str) -> None:
    """Each of these is a hard requirement, and for the same reason.

    Remotion shallow-merges `--props` over `defaultProps`, so an absent key is not
    "unset" — it is *inherited*. A missing `moments` array renders the composition's
    fixture moments over real footage and reports success.
    """
    persian = _minimal_persian_block()
    del persian[field]
    problems = _errors("edit_decisions", _edit_decisions(persian))
    assert any(field in problem for problem in problems), (
        f"{field!r} is optional in the schema: {problems}"
    )


def test_a_shot_without_attribution_is_rejected() -> None:
    """Both stock licences require attribution, so an unattributable shot is a defect.

    `persian_compose` also refuses this, but only at render time — and the licence
    violation is committed by *publishing*, which can happen from an approved edit
    artifact without another render.
    """
    persian = _minimal_persian_block()
    del persian["shots"][0]["attribution"]
    problems = _errors("edit_decisions", _edit_decisions(persian))
    assert any("attribution" in problem for problem in problems), problems


def test_an_unknown_camera_move_is_rejected() -> None:
    """The vocabulary is closed, and an unknown verb silently becomes no move at all."""
    persian = _minimal_persian_block()
    persian["shots"][0]["camera"] = "dolly-zoom"
    problems = _errors("edit_decisions", _edit_decisions(persian))
    assert any("dolly-zoom" in problem for problem in problems), problems


def test_the_declared_moment_fields_match_the_renderer_type() -> None:
    """The schema and `types.ts` describe the same object.

    Parsed out of the TypeScript rather than duplicated as a list, so adding a field to
    `PersianMoment` and forgetting the schema fails here instead of at the first render
    that uses it — where the symptom is a valid-looking artifact whose new field is
    rejected as an additional property.
    """
    types = (
        ROOT / "remotion-composer" / "src" / "persian" / "types.ts"
    ).read_text(encoding="utf-8")

    start = types.index("export interface PersianMoment {")
    body = types[start : types.index("\n}", start)]

    ts_fields = set()
    for line in body.splitlines():
        # Only two-space-indented members belong to PersianMoment itself.
        # Nested members (for example exactText.text/sha256) are properties of
        # their inline object and must not be compared with moment-level schema keys.
        if not line.startswith("  readonly "):
            continue
        name = line[len("  readonly ") :].split(":", 1)[0]
        ts_fields.add(name.rstrip("?"))

    schema_fields = set(
        _schema("edit_decisions")["properties"]["persian"]["properties"]["moments"][
            "items"
        ]["properties"]
    )

    assert ts_fields == schema_fields, (
        f"PersianMoment and the schema disagree. Only in types.ts: "
        f"{sorted(ts_fields - schema_fields)}. Only in the schema: "
        f"{sorted(schema_fields - ts_fields)}."
    )


# ---------------------------------------------------------------------------
# render_report
# ---------------------------------------------------------------------------


def test_the_fields_persian_compose_returns_are_declared() -> None:
    """Every key in the tool's own output schema has a home in the render report.

    The compose director copies these into the artifact. A key the tool returns and the
    schema does not declare fails validation at the last checkpoint of the run, after
    the render is already paid for.
    """
    from tools.video.persian_compose import PersianCompose

    returned = set(PersianCompose.output_schema["properties"])
    declared = set(_schema("render_report")["properties"])

    # `outputs` restates path/format/resolution/duration per file, so the tool's flat
    # equivalents are covered there rather than at the root.
    missing = returned - declared
    assert not missing, (
        f"persian_compose returns {sorted(missing)}, which render_report.schema.json "
        f"does not declare."
    )


def test_a_persian_render_report_validates() -> None:
    report = {
        "version": "1.0",
        "outputs": [
            {
                "path": "projects/x/renders/final.mp4",
                "format": "mp4",
                "codec": "h264",
                "audio_codec": "aac",
                "resolution": "1080x1920",
                "fps": 30,
                "duration_seconds": 66.11,
                "file_size_bytes": 31_697_116,
                "platform_target": "generic",
            }
        ],
        "render_grammar": "persian-footage",
        "output_path": "projects/x/renders/final.mp4",
        "composition_id": "PersianFootageVertical",
        "format": "vertical",
        "duration_seconds": 66.11,
        "moment_count": 13,
        "shot_count": 12,
        "text_coverage": 0.41,
        "subtitle_path": "projects/x/renders/final.srt",
        "subtitle_advisories": [],
        "persian_text_verified": True,
        "verification_frames": ["renders/frames/moment-01.png"],
        "verification_notes": ["moment-1: pass — worst anchor offset 9px of 32"],
        "attributions": ["Video by Someone on Pexels"],
        "music_mixed": False,
        "render_time_seconds": 412.0,
        "warnings": [],
    }
    problems = _errors("render_report", report)
    assert not problems, problems


def test_text_coverage_is_bounded_to_a_fraction() -> None:
    """It is a fraction, and a percentage written into it would read as 41x the runtime.

    Worth pinning because 0.41 and 41 are both plausible-looking values for the same
    measurement, and only one of them means what the reviewer will read it as.
    """
    report = {
        "version": "1.0",
        "outputs": [
            {
                "path": "a.mp4",
                "format": "mp4",
                "resolution": "1080x1920",
                "duration_seconds": 1.0,
            }
        ],
        "text_coverage": 41,
    }
    assert any("text_coverage" in problem for problem in _errors("render_report", report))


# ---------------------------------------------------------------------------
# asset_manifest
# ---------------------------------------------------------------------------


def test_a_persian_asset_manifest_validates() -> None:
    manifest = {
        "version": "1.0",
        "format": "vertical",
        "assets": [
            {
                "id": "beat-1",
                "type": "video",
                "kind": "video",
                "path": "assets/clips/pexels_1.mp4",
                "public_path": "clips/pexels_1.mp4",
                "source_tool": "direct_clip_search",
                "scene_id": "beat-1",
                "beat_id": "beat-1",
                "duration_seconds": 17.5,
                "width": 1080,
                "height": 1920,
                "source_in_seconds": 1.0,
                "provider": "pexels",
                "original_url": "https://www.pexels.com/video/x-1/",
                "license": "Pexels License",
                "attribution": "Video by Someone on Pexels",
                "shows_subject": True,
                "selection_reason": "فنجان قهوه روی میز، بخار در نور صبح",
            }
        ],
        "word_timings": [{"word": "قهوه", "start": 0.0, "end": 0.34, "probability": 0.99}],
        "music": {
            "path": "assets/music/track.mp3",
            "source": "pixabay_music",
            "license": {
                "name": "Pixabay Content License",
                "url": "https://pixabay.com/music/search/coffee/",
                "downloadedAt": "2026-09-02",
            },
            "attribution": "Music by Someone on Pixabay",
            "contentIdRisk": {
                "level": "low",
                "reason": "Pixabay Content License permits monetized social media use; "
                "third-party Content-ID cannot be ruled out by any automated check.",
            },
        },
        "total_cost_usd": 0.0,
        "metadata": {"provider": "pexels", "clips_per_query": 2},
    }
    problems = _errors("asset_manifest", manifest)
    assert not problems, problems


def test_a_manifest_with_no_music_validates() -> None:
    """Music is genuinely optional, and on this machine it is usually absent.

    `pixabay_music` is the only provider and it failed four times on the run under audit,
    so the shipped video has narration only. A schema that required the key would make a
    legitimate run unrepresentable.
    """
    manifest = {
        "version": "1.0",
        "format": "vertical",
        "assets": [
            {
                "id": "beat-1",
                "type": "video",
                "path": "assets/clips/pexels_1.mp4",
                "source_tool": "direct_clip_search",
                "scene_id": "beat-1",
            }
        ],
    }
    assert not _errors("asset_manifest", manifest)


def test_the_subject_quota_fields_are_declared() -> None:
    """`shows_subject` and `selection_reason` are the anchor quota's only evidence.

    Undeclared, they cannot be recorded in the canonical artifact, and the quota becomes
    something the agent asserts in prose instead of something a reviewer can check —
    which is the state the coffee run shipped in.
    """
    asset = _schema("asset_manifest")["properties"]["assets"]["items"]["properties"]
    assert "shows_subject" in asset
    assert "selection_reason" in asset
