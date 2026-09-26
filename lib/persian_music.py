"""Music for a narrated Persian video: required, sourced, licensed, and mixed on record.

Narrated production uses measured loudness to derive the speech-time music gain.
The historical fixed renderer volumes remain as legacy/default values for callers
that do not have production loudness evidence, but they are not the primary mix
policy for Persian production.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
import math
import re
import shutil
import subprocess

RiskLevel = Literal["low", "unknown", "high"]

PIXABAY_CONTENT_LICENSE = {
    "name": "Pixabay Content License",
    "permits": [
        "commercial use",
        "use in monetized social media, including Instagram",
        "modification and incorporation into a larger work",
    ],
    "forbids": [
        "redistribution of the track standalone (as-is or modified)",
        "sale of the track as-is or with minor changes",
        "use as part of an AI training dataset",
        "presenting the authors as endorsing your use",
    ],
    "requires": [],
}

KNOWN_PERMISSIVE_LICENSES: frozenset[str] = frozenset(
    {PIXABAY_CONTENT_LICENSE["name"], "Pixabay Content License"}
)

# Legacy/default renderer levels. Production speech-time gain is derived below.
DEFAULT_MUSIC_FLAT_VOLUME = 0.65
DEFAULT_MUSIC_BASE_VOLUME = 0.72
DEFAULT_MUSIC_DUCK_VOLUME = 0.55
DEFAULT_MUSIC_FADE_SECONDS = 1.5

# Versioned calibration policy. These values are deliberately explicit so later
# post-publish/perceptual calibration requires a policy revision rather than a
# silent constant tweak.
LOUDNESS_MIX_POLICY_VERSION = "1.0"
TARGET_MUSIC_SEPARATION_LU = 10.0
MIN_MUSIC_SEPARATION_LU = 7.0
MAX_MUSIC_SEPARATION_LU = 14.0
MUSIC_AUDIBILITY_FLOOR_LUFS = -36.0
_LUFS_RE = re.compile(r"\bI:\s*(-?[0-9]+(?:\.[0-9]+)?)\s+LUFS")


def effective_music_loudness(source_lufs: float, volume: float) -> float:
    """Return bed loudness after a linear-amplitude renderer gain."""
    if volume <= 0:
        return float("-inf")
    return float(source_lufs) + 20.0 * math.log10(float(volume))


def evaluate_music_separation(
    *,
    narration_lufs: float,
    music_lufs: float,
    music_gain: float,
) -> dict[str, Any]:
    """Evaluate one speech-time gain against the symmetric mix policy."""
    predicted_music = effective_music_loudness(float(music_lufs), float(music_gain))
    separation = float(narration_lufs) - predicted_music
    if separation < MIN_MUSIC_SEPARATION_LU:
        passed = False
        reason = "music_too_loud"
    elif separation > MAX_MUSIC_SEPARATION_LU:
        passed = False
        reason = "music_too_quiet"
    else:
        passed = True
        reason = "ok"
    return {
        "policyVersion": LOUDNESS_MIX_POLICY_VERSION,
        "measuredNarrationLufs": round(float(narration_lufs), 3),
        "measuredMusicLufs": round(float(music_lufs), 3),
        "speechMusicGain": round(float(music_gain), 6),
        "predictedSpeechMusicLufs": round(predicted_music, 3),
        "predictedSeparationLu": round(separation, 3),
        "targetSeparationLu": TARGET_MUSIC_SEPARATION_LU,
        "minSeparationLu": MIN_MUSIC_SEPARATION_LU,
        "maxSeparationLu": MAX_MUSIC_SEPARATION_LU,
        "passed": passed,
        "reason": reason,
    }


def derive_loudness_aware_mix(
    *,
    narration_lufs: float,
    music_lufs: float,
) -> dict[str, Any]:
    """Derive speech-time music gain from measured source loudness.

    The target music level is narration minus TARGET_MUSIC_SEPARATION_LU. Since
    renderer gain is linear amplitude, convert the required dB/LU adjustment with
    10 ** (dB / 20). The returned plan is evaluated through the same symmetric
    policy used for authored/legacy overrides.
    """
    target_music_lufs = float(narration_lufs) - TARGET_MUSIC_SEPARATION_LU
    gain_db = target_music_lufs - float(music_lufs)
    gain = 10.0 ** (gain_db / 20.0)
    plan = evaluate_music_separation(
        narration_lufs=float(narration_lufs),
        music_lufs=float(music_lufs),
        music_gain=gain,
    )
    plan["derivedGainDb"] = round(gain_db, 3)
    return plan


def measure_integrated_loudness(path: Path, *, timeout: int = 60) -> float:
    """Measure integrated LUFS with ffmpeg/ebur128; refuse an unmeasurable source."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is not on PATH, so music audibility cannot be measured")
    completed = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-af",
            "ebur128=framelog=verbose",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"ffmpeg loudness measurement failed for {path} (exit {completed.returncode})"
        )
    matches = _LUFS_RE.findall((completed.stdout or "") + "\n" + (completed.stderr or ""))
    if not matches:
        raise RuntimeError(f"ffmpeg produced no integrated-loudness result for {path}")
    return float(matches[-1])


@dataclass
class MusicTrack:
    path: str
    source: str
    license_name: str
    license_url: str
    downloaded_at: str
    attribution: str = ""
    content_id_risk: RiskLevel = "unknown"
    risk_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "source": self.source,
            "license": {
                "name": self.license_name,
                "url": self.license_url,
                "downloadedAt": self.downloaded_at,
            },
            "attribution": self.attribution,
            "contentIdRisk": {
                "level": self.content_id_risk,
                "reason": self.risk_reason,
                "acknowledged": "Content-ID is third-party fingerprinting; no licence binds it, so no automated check can guarantee zero claim risk on Instagram. Provenance is recorded so any claim can be answered with the licence page.",
            },
        }


@dataclass
class MusicAudit:
    problems: list[str] = field(default_factory=list)
    advisories: list[str] = field(default_factory=list)
    track: MusicTrack | None = None

    @property
    def passed(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict[str, Any]:
        return {
            "problems": list(self.problems),
            "advisories": list(self.advisories),
            "passed": self.passed,
            "track": self.track.to_dict() if self.track else None,
        }


def build_music_track(raw: dict[str, Any]) -> MusicTrack:
    """Normalize a raw music record, refusing absent provenance fields."""
    license_block = raw.get("license") or {}
    risk_block = raw.get("contentIdRisk") or {}
    risk = risk_block.get("level") or "unknown"
    if risk not in ("low", "unknown", "high"):
        raise ValueError(f"music contentIdRisk {risk!r} is not one of low/unknown/high")

    path = str(raw.get("path") or "").strip()
    source = str(raw.get("source") or "").strip()
    license_name = str(license_block.get("name") or raw.get("licenseName") or "").strip()
    license_url = str(license_block.get("url") or raw.get("licenseUrl") or "").strip()
    downloaded_at = str(
        license_block.get("downloadedAt") or raw.get("downloadedAt") or ""
    ).strip()
    missing = [
        name
        for name, value in (
            ("path", path),
            ("source", source),
            ("license.name", license_name),
            ("license.url", license_url),
            ("license.downloadedAt", downloaded_at),
        )
        if not value
    ]
    if missing:
        raise ValueError(
            f"music record is missing {', '.join(missing)}. Provenance is not optional: a bed whose licence page cannot be revisited is a claim about copyright nobody can check."
        )

    return MusicTrack(
        path=path,
        source=source,
        license_name=license_name,
        license_url=license_url,
        downloaded_at=downloaded_at,
        attribution=str(raw.get("attribution") or ""),
        content_id_risk=risk,  # type: ignore[arg-type]
        risk_reason=str(risk_block.get("reason") or ""),
    )



# A recorded omission must decide, not defer. These markers catch a note-to-self
# ("placeholder", "to be attached", "before promote") that would otherwise pass
# the non-empty check and then describe a film that shipped without music (#184).
_DEFERRAL_MARKERS = (
    "placeholder", "pending", "to be attached", "to be added", "to be sourced",
    "tbd", "todo", "will be", "before promote", "not yet", "for now",
)


def defers_rather_than_decides(reason: str) -> bool:
    """Whether a recorded omission reason promises the thing instead of deciding.

    Shared by both music-omission gates -- the compose/edit audit here and the
    rendered-review gate in ``lib.persian_rendered_review`` -- because they ask the
    same question of two different fields and only the first was tightened (#186).
    Coarse by design: this asks whether a reason *is* a reason, never whether it is
    a good one.
    """
    text = reason.strip().casefold()
    return any(marker in text for marker in _DEFERRAL_MARKERS)


def audit_music(
    *,
    track: MusicTrack | None,
    narrated: bool,
    acknowledge_unknown_risk: bool = False,
    omit_music_reason: str = "",
) -> MusicAudit:
    """Gate the music layer and its provenance for a project."""
    audit = MusicAudit(track=track)
    if track is None:
        if narrated:
            if omit_music_reason and defers_rather_than_decides(omit_music_reason):
                audit.problems.append(
                    "the recorded omit_music_reason defers the decision rather than making "
                    f"one: {omit_music_reason!r}. This gate asks only that the reason be "
                    "non-empty, so a placeholder would pass here and then describe a film that "
                    "shipped without music. State why the film is deliberately without a bed, "
                    "or source one."
                )
            elif omit_music_reason:
                audit.advisories.append(
                    "no music bed, by recorded decision: "
                    f"{omit_music_reason!r}. An explicit choice rather than a default silence."
                )
            else:
                audit.problems.append(
                    "a narrated video has no music bed. Music is required in narrated mode; source a licensed bed or record an explicit omit_music_reason."
                )
        return audit

    if track.content_id_risk == "high":
        audit.problems.append(
            f"music {track.path!r} is marked high Content-ID risk: {track.risk_reason} — pick another track."
        )
        return audit

    if track.content_id_risk == "low":
        if track.license_name not in KNOWN_PERMISSIVE_LICENSES:
            audit.problems.append(
                f"music {track.path!r} claims low risk under licence «{track.license_name}», which is not recognized as permitting monetized social media."
            )
        if not track.license_url:
            audit.problems.append(f"music {track.path!r} has no licence URL")

    if track.content_id_risk == "unknown" and not acknowledge_unknown_risk:
        audit.problems.append(
            f"music {track.path!r} has unknown Content-ID risk and the record does not acknowledge it."
        )
    return audit


def audio_props_with_music(
    *,
    narration: str | None,
    music_path: str | None,
    narration_lufs: float | None = None,
    music_lufs: float | None = None,
) -> dict[str, Any] | None:
    """Build renderer audio props, deriving speech gain when measurements exist."""
    if narration is None and music_path is None:
        return None
    props: dict[str, Any] = {}
    if narration is not None:
        props["narration"] = narration
    if music_path is not None:
        duck = DEFAULT_MUSIC_DUCK_VOLUME
        if narration_lufs is not None and music_lufs is not None:
            duck = float(
                derive_loudness_aware_mix(
                    narration_lufs=narration_lufs,
                    music_lufs=music_lufs,
                )["speechMusicGain"]
            )
        props.update(
            {
                "music": music_path,
                "musicFlatVolume": DEFAULT_MUSIC_FLAT_VOLUME,
                "musicBaseVolume": DEFAULT_MUSIC_BASE_VOLUME,
                "musicDuckVolume": duck,
                "musicFadeSeconds": DEFAULT_MUSIC_FADE_SECONDS,
            }
        )
    return props


__all__ = [
    "PIXABAY_CONTENT_LICENSE",
    "KNOWN_PERMISSIVE_LICENSES",
    "DEFAULT_MUSIC_FLAT_VOLUME",
    "DEFAULT_MUSIC_BASE_VOLUME",
    "DEFAULT_MUSIC_DUCK_VOLUME",
    "DEFAULT_MUSIC_FADE_SECONDS",
    "LOUDNESS_MIX_POLICY_VERSION",
    "TARGET_MUSIC_SEPARATION_LU",
    "MIN_MUSIC_SEPARATION_LU",
    "MAX_MUSIC_SEPARATION_LU",
    "MUSIC_AUDIBILITY_FLOOR_LUFS",
    "effective_music_loudness",
    "evaluate_music_separation",
    "derive_loudness_aware_mix",
    "measure_integrated_loudness",
    "MusicTrack",
    "MusicAudit",
    "build_music_track",
    "audit_music",
    "audio_props_with_music",
]
