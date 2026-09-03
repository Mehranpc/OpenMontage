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

    # One clip per beat, and no clip serving two beats.
    seen_paths: dict[str, str] = {}
    for index, entry in enumerate(assets):
        label = entry.get("beat_id") or f"asset[{index}]"
        path = entry.get("path") or entry.get("public_path")
        if not path:
            continue
        if path in seen_paths:
            problems.append(
                f"{label}: reuses the clip already used by {seen_paths[path]} "
                "— visible repetition reads as running out of material"
            )
        else:
            seen_paths[str(path)] = str(label)

    if scene_plan is not None:
        beats = scene_plan.get("beats")
        if beats is None:
            beats = (scene_plan.get("metadata") or {}).get("beats", [])
        beats = list(beats or [])

        by_beat: dict[str, list[dict]] = {}
        for entry in assets:
            by_beat.setdefault(str(entry.get("beat_id")), []).append(entry)

        for beat in beats:
            beat_id = str(beat.get("id"))
            if beat.get("typographic"):
                if by_beat.get(beat_id):
                    problems.append(
                        f"{beat_id}: marked typographic but has footage assigned — "
                        "one of the two decisions is stale"
                    )
                continue

            entries = by_beat.get(beat_id, [])
            if len(entries) == 0:
                problems.append(f"{beat_id}: no asset")
                continue
            if len(entries) > 1:
                problems.append(f"{beat_id}: {len(entries)} assets, expected exactly 1")

            beat_duration = float(beat.get("duration_seconds") or 0.0)
            for entry in entries:
                source_duration = float(entry.get("duration_seconds") or 0.0)
                source_in = float(entry.get("source_in_seconds") or 0.0)
                usable = source_duration - source_in
                if beat_duration > 0 and usable > 0 and usable < beat_duration:
                    problems.append(
                        f"{beat_id}: clip provides {usable:.2f}s from its in-point but "
                        f"the beat needs {beat_duration:.2f}s — the tail renders black"
                    )

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
    "ImageFootageRejected",
    "assert_video_only",
    "audit_asset_manifest",
    "assert_orientation",
]
