"""Asset-manifest gates for the Persian footage pipeline.

The pipeline forbids still-image footage. That rule is stated in the manifest and in
the asset director skill, but a rule stated only in prose is a rule that gets
violated under pressure — specifically at the moment when video results are thin for
one beat and a photo is right there. So it is also a gate here, with a test that
asserts the gate rejects.

The functions in this module raise or return problems; they do not repair. A manifest
that fails these checks represents a decision the agent should revisit (change the
query, or make the beat typographic), not something to paper over.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Optional

from lib.persian_scenes import FALLBACK_LEVELS, REWARD_OPENING_DIRECTIONS

#: Extensions that are unambiguously still images. Checked in addition to a
#: declared `kind`, because an entry can carry `kind: "video"` and a `.jpg` path
#: when a manifest was assembled by hand or copied from another pipeline.
_IMAGE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".avif"}
)

#: Extensions accepted as video.
_VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".webm", ".mkv", ".m4v"})

#: Tools that produce stills. Named so a manifest recording its provenance can be
#: rejected even if the path and kind were both laundered.
_IMAGE_PROVIDER_TOOLS = frozenset(
    {
        "pexels_image",
        "pixabay_image",
        "unsplash_image",
        "image_gen",
        "flux_image",
        "nano_banana",
        "comfyui_image",
        "gpt_image",
        "seedream_image",
    }
)


_PERSIAN_VIDEO_PROVIDER_ALIASES = {
    "pexels": "pexels",
    "pixabay": "pixabay_video",
    "pixabay_video": "pixabay_video",
}
ALLOWED_PERSIAN_VIDEO_PROVIDERS = frozenset({"pexels", "pixabay_video"})
STAGED_STOCK_RISKS = frozenset({"low", "medium", "high"})


def _quality_metadata_problems(
    entry: dict[str, Any], requirement: dict[str, Any]
) -> list[str]:
    """Validate new visual-event selection evidence without breaking legacy manifests."""
    event_id = str(requirement.get("visual_event_id") or "")
    if not event_id:
        return []
    label = event_id
    problems: list[str] = []

    semantic_beat_id = str(entry.get("semantic_beat_id") or "").strip()
    if semantic_beat_id != str(requirement.get("beat_id") or ""):
        problems.append(
            f"{label}: semantic_beat_id must equal {requirement.get('beat_id')!r}"
        )

    narration_span = str(entry.get("narration_span") or "").strip()
    if narration_span != str(requirement.get("narration_span") or "").strip():
        problems.append(
            f"{label}: narration_span must preserve the visual event's source span exactly"
        )

    query = str(entry.get("query") or "").strip()
    if not query:
        problems.append(f"{label}: missing query used to acquire the selected candidate")
    elif query not in [str(q) for q in requirement.get("queries") or []]:
        problems.append(f"{label}: selected query {query!r} is not one of the authored event queries")

    rank = entry.get("candidate_rank")
    if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
        problems.append(f"{label}: candidate_rank must be an integer >= 1")

    for field in ("source_in_seconds", "duration_seconds"):
        if field not in entry:
            problems.append(f"{label}: missing {field}; selected window timing must be explicit")

    for field in ("selection_reason", "relevance_reason"):
        if not str(entry.get(field) or "").strip():
            problems.append(f"{label}: missing {field}; selected footage needs inspectable reasoning")

    # A unit that has to carry typography must be chosen with an eye to where that
    # typography can go. Without this the reviewer judges subject match alone, and
    # footage whose subject fills or crosses the frame is selected happily -- the
    # collision then surfaces at preflight, one moment per repair cycle (#164).
    if requirement.get("carries_moment"):
        frame_review = entry.get("frame_review")
        frame_review = frame_review if isinstance(frame_review, dict) else {}
        observed = str(frame_review.get("placement_space") or "").strip()
        planned = str(requirement.get("negative_space") or "").strip()
        if not observed:
            problems.append(
                f"{label}: carries a typographic moment, so the frame review must record "
                "where the frame is actually clear (`frame_review.placement_space`). "
                "Choosing on subject match alone is how unusable footage reaches an "
                "authored edit."
            )
        elif observed != planned:
            problems.append(
                f"{label}: frame_review.placement_space is {observed!r} but the plan "
                f"reserved {planned!r}; the selected footage does not leave the room the "
                "moment was planned against."
            )

    if str(requirement.get("narrative_role") or "").strip() == "hook":
        expected_role = str(requirement.get("semantic_role") or "").strip()
        expected_direction = str(requirement.get("semantic_direction") or "").strip()
        if str(entry.get("semantic_role") or "").strip() != expected_role:
            problems.append(f"{label}: semantic_role must preserve the opening event's authored role")
        if str(entry.get("semantic_direction") or "").strip() != expected_direction:
            problems.append(f"{label}: semantic_direction must preserve the opening event's authored direction")
        if entry.get("opening_semantic_match") is not True:
            problems.append(f"{label}: opening_semantic_match must be true after inspecting the selected window")

    if not isinstance(entry.get("affect_match"), bool):
        problems.append(f"{label}: affect_match must be true or false")
    elif not entry.get("affect_match"):
        problems.append(
            f"{label}: affect_match is false; a selected clip may not contradict desired_affect "
            f"{requirement.get('desired_affect')!r}"
        )

    risk = str(entry.get("staged_stock_risk") or "").strip().lower()
    if risk not in STAGED_STOCK_RISKS:
        problems.append(f"{label}: staged_stock_risk must be low, medium, or high")
    elif risk == "high":
        problems.append(f"{label}: staged_stock_risk is high; reject the generic/staged candidate")

    if not isinstance(entry.get("human_presence"), bool):
        problems.append(f"{label}: human_presence must be true or false")
    elif requirement.get("human_presence") and not entry.get("human_presence"):
        problems.append(f"{label}: scene plan requires human presence but the selected clip has none")

    if not isinstance(entry.get("shows_subject"), bool):
        problems.append(f"{label}: shows_subject must be true or false on the inspected clip")
    elif requirement.get("shows_subject") and not entry.get("shows_subject"):
        problems.append(f"{label}: subject continuity was lost during asset selection")

    fallback = str(entry.get("fallback_level") or "").strip()
    expected_fallback = str(requirement.get("fallback_level") or "").strip()
    if fallback not in FALLBACK_LEVELS:
        problems.append(f"{label}: asset fallback_level must be one of {', '.join(FALLBACK_LEVELS)}")
    elif fallback != expected_fallback:
        problems.append(
            f"{label}: asset fallback_level {fallback!r} does not match planned level {expected_fallback!r}"
        )
    if fallback and fallback != "exact_literal" and not str(entry.get("fallback_reason") or "").strip():
        problems.append(
            f"{label}: non-literal fallback requires fallback_reason documenting why earlier levels failed"
        )
    if fallback == "emotional_human" and entry.get("human_presence") is False:
        problems.append(f"{label}: emotional_human fallback cannot select a clip with no human presence")

    frame_review = entry.get("frame_review")
    if not isinstance(frame_review, dict):
        problems.append(f"{label}: missing frame_review evidence for start/middle/end inspection")
    else:
        for key in ("start", "middle", "end"):
            if frame_review.get(key) is not True:
                problems.append(f"{label}: frame_review.{key} must be true after inspecting the clip")
        if str(requirement.get("semantic_role") or "").strip() == "reward_problem_hook":
            for key in ("midpoint_before_1_5", "at_3_seconds"):
                if frame_review.get(key) is not True:
                    problems.append(f"{label}: frame_review.{key} must be true for reward_problem_hook opening review")
        if not str(frame_review.get("observed") or "").strip():
            problems.append(f"{label}: frame_review.observed must state what was actually seen")

    if str(requirement.get("semantic_role") or "").strip() == "reward_problem_hook":
        direction = str(entry.get("semantic_direction") or "").strip()
        if direction not in REWARD_OPENING_DIRECTIONS:
            problems.append(f"{label}: reward_problem_hook has an invalid semantic_direction")
        if entry.get("shows_subject") is not True:
            problems.append(f"{label}: reward_problem_hook must visibly show the subject")
        if entry.get("human_presence") is not True:
            problems.append(f"{label}: reward_problem_hook requires visible human presence")

    return problems


def _scene_asset_requirements(
    scene_plan: dict[str, Any],
) -> tuple[list[dict[str, Any]], set[str], set[str]]:
    """Return the footage units an asset manifest must satisfy.

    A semantic beat may now contain multiple ``visual_events``.  Each explicit
    event is independently sourced and therefore independently requires one video
    asset.  Plans without that field keep the historical one-asset-per-beat shape.
    """
    beats = scene_plan.get("beats")
    if beats is None:
        beats = (scene_plan.get("metadata") or {}).get("beats", [])

    requirements: list[dict[str, Any]] = []
    typographic_ids: set[str] = set()
    explicit_event_beats: set[str] = set()
    for beat in beats or []:
        beat_id = str(beat.get("id") or "")
        if beat.get("typographic"):
            typographic_ids.add(beat_id)
            continue
        events = beat.get("visual_events")
        if isinstance(events, list) and events:
            explicit_event_beats.add(beat_id)
            for event in events:
                if not isinstance(event, dict):
                    continue
                requirements.append(
                    {
                        "beat_id": beat_id,
                        "visual_event_id": str(event.get("id") or ""),
                        "duration_seconds": event.get("duration_seconds"),
                        "narration_span": event.get("narration_span"),
                        "queries": list(event.get("queries") or []),
                        "desired_affect": event.get("desired_affect"),
                        "human_presence": event.get("human_presence"),
                        "shows_subject": event.get("shows_subject"),
                        "narrative_role": event.get("narrative_role"),
                        "semantic_role": event.get("semantic_role"),
                        "semantic_direction": event.get("semantic_direction"),
                        "fallback_level": event.get("fallback_level"),
                        "importance": event.get("importance"),
                        # Whether a typographic moment has to sit on this unit, and
                        # where the plan says the frame stays clear for it (#164).
                        "carries_moment": bool(event.get("carries_moment")),
                        "negative_space": str(event.get("negative_space") or ""),
                    }
                )
        else:
            requirements.append(
                {
                    "beat_id": beat_id,
                    "visual_event_id": None,
                    "duration_seconds": beat.get("duration_seconds"),
                }
            )
    return requirements, typographic_ids, explicit_event_beats


def scene_asset_requirements(
    scene_plan: dict[str, Any],
) -> tuple[list[dict[str, Any]], set[str], set[str]]:
    """Expose the canonical scene-plan-to-asset mapping for deterministic tools."""
    return _scene_asset_requirements(scene_plan)


class ImageFootageRejected(ValueError):
    """Raised when a Persian-pipeline manifest contains still-image footage.

    A dedicated exception type rather than a bare ValueError so a caller can
    distinguish this governance rejection from an ordinary validation error and
    report it as the specific pipeline rule it is.
    """


def _entry_paths(entry: dict[str, Any]) -> list[str]:
    """Every path-like field on an asset entry, so a check cannot be evaded.

    Manifests in this repo have used `path`, `file`, `local_path`, and `public_path`
    at various points. Collecting all of them means a new field name does not
    silently open a hole in the gate.
    """
    keys = ("path", "file", "local_path", "public_path", "src", "source")
    return [str(entry[key]) for key in keys if entry.get(key)]


def assert_video_only(manifest: dict[str, Any]) -> None:
    """Raise `ImageFootageRejected` if the manifest carries any still image.

    Three independent signals are checked, because each alone is evadable:
    the declared `kind`, the file extension, and the producing tool. An entry needs
    to be clean on all three.

    Args:
        manifest: The asset_manifest artifact (or its `metadata` body).

    Raises:
        ImageFootageRejected: with every offending entry named. All violations are
            reported at once rather than the first — fixing them one render at a
            time is how a stage burns its revision budget.
    """
    assets = manifest.get("assets")
    if assets is None:
        assets = (manifest.get("metadata") or {}).get("assets", [])

    violations: list[str] = []

    for index, entry in enumerate(assets or []):
        label = entry.get("beat_id") or entry.get("slot_id") or f"asset[{index}]"

        kind = str(entry.get("kind", "")).strip().lower()
        if kind in {"image", "photo", "still"}:
            violations.append(f"{label}: kind={kind!r}")

        for raw_path in _entry_paths(entry):
            suffix = Path(raw_path).suffix.lower()
            if suffix in _IMAGE_EXTENSIONS:
                violations.append(f"{label}: {raw_path} is a still image ({suffix})")
            elif suffix and suffix not in _VIDEO_EXTENSIONS:
                violations.append(
                    f"{label}: {raw_path} has extension {suffix!r}, which is neither "
                    "a known video nor a known image container — declare it explicitly"
                )

        tool = str(entry.get("tool") or entry.get("produced_by") or "").strip().lower()
        if tool in _IMAGE_PROVIDER_TOOLS:
            violations.append(f"{label}: produced by {tool!r}, an image tool")

    if violations:
        raise ImageFootageRejected(
            "The persian-footage pipeline forbids still-image footage "
            "(«استفاده از فوتیج عکس ممنوع»). Offending entries:\n  "
            + "\n  ".join(violations)
            + "\n\nResolve by finding video for the beat, or by marking the beat "
            "typographic within the brief's typographic_beat_budget. Do not "
            "substitute a photo."
        )


def _source_reuse_problems(assets: list[dict[str, Any]]) -> list[str]:
    """Reject overlapping source reuse while permitting distinct reviewed windows.

    Issue #35 makes provider/source identity plus source-time window the durable
    reuse identity. Two events may therefore use the same long source when their
    reviewed windows do not overlap. Legacy manifests without explicit window ends
    stay conservative: repeated identity is still rejected because non-overlap
    cannot be proven.
    """
    problems: list[str] = []
    seen: dict[tuple[str, str], list[tuple[float | None, float | None, str]]] = {}

    for index, entry in enumerate(assets):
        label = str(
            entry.get("visual_event_id")
            or entry.get("beat_id")
            or f"asset[{index}]"
        )
        provider_raw = str(entry.get("provider") or "").strip().lower()
        provider = _PERSIAN_VIDEO_PROVIDER_ALIASES.get(provider_raw, provider_raw)
        source_id = str(entry.get("source_id") or "").strip()
        path = str(entry.get("path") or entry.get("public_path") or "").strip()
        if source_id:
            identity = (provider or "unknown", source_id)
        elif path:
            identity = ("path", path)
        else:
            continue

        start: float | None
        end: float | None
        try:
            start = float(entry["source_in_seconds"])
        except (KeyError, TypeError, ValueError):
            start = None
        try:
            end = float(entry["source_window_end_seconds"])
        except (KeyError, TypeError, ValueError):
            end = None
        if start is None or end is None or end <= start:
            start = end = None

        prior_windows = seen.setdefault(identity, [])
        for prior_start, prior_end, prior_label in prior_windows:
            if None not in (start, end, prior_start, prior_end):
                overlap = min(end, prior_end) - max(start, prior_start) > 1e-6
                if not overlap:
                    continue
                problems.append(
                    f"{label}: overlapping source-time window reuses the source already used by "
                    f"{prior_label} — choose distinct non-overlapping windows"
                )
            else:
                problems.append(
                    f"{label}: reuses the source already used by {prior_label} without "
                    "explicit non-overlapping source-time windows"
                )
        prior_windows.append((start, end, label))

    return problems


def audit_asset_manifest(
    manifest: dict[str, Any],
    scene_plan: Optional[dict[str, Any]] = None,
) -> list[str]:
    """Return every problem found in an asset manifest, as readable strings.

    Complements `assert_video_only`: that one enforces the absolute rule, this one
    reports the conditional faults that need a human judgement. Empty list means
    clean.
    """
    problems: list[str] = []

    assets = manifest.get("assets")
    if assets is None:
        assets = (manifest.get("metadata") or {}).get("assets", [])
    assets = list(assets or [])

    # Provenance. Both Pexels and Pixabay require attribution, so a clip that
    # cannot be attributed must not ship.
    for index, entry in enumerate(assets):
        label = entry.get("beat_id") or f"asset[{index}]"
        for field in ("provider", "original_url", "license", "attribution"):
            if not entry.get(field):
                problems.append(f"{label}: missing {field} — required by the stock licence")

        provider = str(entry.get("provider") or "").strip().lower()
        normalized_provider = _PERSIAN_VIDEO_PROVIDER_ALIASES.get(provider)
        if provider and normalized_provider not in ALLOWED_PERSIAN_VIDEO_PROVIDERS:
            allowed = ", ".join(sorted(ALLOWED_PERSIAN_VIDEO_PROVIDERS))
            problems.append(
                f"{label}: provider {provider!r} is outside the Persian production "
                f"allowlist ({allowed})"
            )

        # The clip has to be findable, and "findable" means on disk at the recorded
        # path. It deliberately does NOT mean `public_path`.
        #
        # This check used to require `public_path`, on the reasoning that Remotion
        # resolves media through `staticFile()` so every clip must already sit under
        # `remotion-composer/public/`. That was true of an earlier design and is false
        # of this one: `persian_compose._stage()` copies each shot's `source` into
        # `public/persian/<run-id>/` at render time and deletes the directory
        # afterwards, and it reads `source`, never `public_path`. Nothing in the
        # rendering path consumes the field.
        #
        # The evidence it was inert: the coffee run recorded `clips/pexels_*.mp4` for
        # all twelve assets, nothing was ever written to `public/clips/`, and the video
        # rendered correctly anyway. A required field that no consumer reads teaches the
        # stage to satisfy a check instead of a need — and it crowds out the check that
        # matters, since a `path` pointing at nothing is exactly the fault that produces
        # the black beat this warning described.
        paths = _entry_paths(entry)
        declared = str(entry.get("path") or "").strip()
        if not paths:
            problems.append(
                f"{label}: no path. `persian_compose` stages each shot's source into "
                "public/ at render time, so the manifest must say where the file is."
            )
        elif declared and not Path(declared).expanduser().exists():
            # Only `path` is resolved, not every path-like field. `_entry_paths` collects
            # all of them so the image gate cannot be evaded by renaming a key, but
            # existence is a different question: `public_path` is relative to the
            # composer's public dir and would fail this check by construction.
            problems.append(
                f"{label}: path {declared!r} does not exist. A missing file is the "
                "black-beat fault: `persian_compose` refuses it with "
                "FileNotFoundError, but only after the edit stage has been approved."
            )

    # Source reuse is window-aware. Distinct non-overlapping windows from one long
    # stock source are legal; overlapping or unverifiable reuse is not.
    problems.extend(_source_reuse_problems(assets))

    if scene_plan is not None:
        requirements, typographic_ids, explicit_event_beats = _scene_asset_requirements(
            scene_plan
        )

        by_beat: dict[str, list[dict[str, Any]]] = {}
        by_event: dict[str, list[dict[str, Any]]] = {}
        for entry in assets:
            beat_id = str(entry.get("beat_id") or "")
            by_beat.setdefault(beat_id, []).append(entry)
            event_id = str(entry.get("visual_event_id") or "").strip()
            if event_id:
                by_event.setdefault(event_id, []).append(entry)
            elif beat_id in explicit_event_beats:
                problems.append(
                    f"{beat_id}: asset {entry.get('path')!r} is missing visual_event_id; "
                    "this semantic beat contains multiple independently sourced events"
                )

        for beat_id in typographic_ids:
            if by_beat.get(beat_id):
                problems.append(
                    f"{beat_id}: marked typographic but has footage assigned — "
                    "one of the two decisions is stale"
                )

        expected_event_ids = {
            str(req["visual_event_id"])
            for req in requirements
            if req.get("visual_event_id")
        }
        for event_id, entries in by_event.items():
            if event_id not in expected_event_ids:
                problems.append(
                    f"visual_event_id {event_id!r} is not present in the scene plan"
                )

        for requirement in requirements:
            beat_id = str(requirement["beat_id"])
            event_id = requirement.get("visual_event_id")
            label = str(event_id or beat_id)
            entries = by_event.get(str(event_id), []) if event_id else by_beat.get(beat_id, [])
            if len(entries) == 0:
                problems.append(f"{label}: no asset")
                continue
            if len(entries) > 1:
                problems.append(f"{label}: {len(entries)} assets, expected exactly 1")

            for entry in entries:
                if event_id and str(entry.get("beat_id") or "") != beat_id:
                    problems.append(
                        f"{label}: asset beat_id {entry.get('beat_id')!r} does not match "
                        f"its semantic beat {beat_id!r}"
                    )
                source_duration = float(entry.get("duration_seconds") or 0.0)
                source_in = float(entry.get("source_in_seconds") or 0.0)
                usable = source_duration - source_in
                needed = float(requirement.get("duration_seconds") or 0.0)
                if needed > 0 and usable > 0 and usable < needed:
                    problems.append(
                        f"{label}: clip provides {usable:.2f}s from its in-point but "
                        f"the visual unit needs {needed:.2f}s — the tail renders black"
                    )
                problems.extend(_quality_metadata_problems(entry, requirement))

    return problems


def assert_orientation(manifest: dict[str, Any], video_format: str) -> list[str]:
    """Report clips whose orientation fights the output format.

    Returned rather than raised: a landscape clip in a vertical video is sometimes
    the right call (a centred subject survives the crop), so this is a judgement to
    surface, not a rule to enforce.
    """
    problems: list[str] = []
    assets = manifest.get("assets") or (manifest.get("metadata") or {}).get("assets", [])

    want_portrait = video_format == "vertical"
    for index, entry in enumerate(assets or []):
        label = entry.get("beat_id") or f"asset[{index}]"
        width = int(entry.get("width") or 0)
        height = int(entry.get("height") or 0)
        if width <= 0 or height <= 0:
            problems.append(f"{label}: dimensions unknown — run ffprobe and record them")
            continue

        is_portrait = height > width
        if want_portrait and not is_portrait:
            problems.append(
                f"{label}: {width}x{height} is landscape in a vertical video — "
                "confirm the subject survives the crop"
            )
        elif not want_portrait and is_portrait:
            problems.append(
                f"{label}: {width}x{height} is portrait in a landscape video — "
                "it will be pillarboxed or heavily cropped"
            )

    return problems


__all__ = [
    "ALLOWED_PERSIAN_VIDEO_PROVIDERS",
    "STAGED_STOCK_RISKS",
    "ImageFootageRejected",
    "assert_video_only",
    "audit_asset_manifest",
    "assert_orientation",
    "scene_asset_requirements",
]
