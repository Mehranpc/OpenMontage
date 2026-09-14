"""Music for a narrated Persian video: required, sourced, and licensed on record.

## Why "optional music" was the bug

The pipeline shipped `pixabay_music` and `audio_mixer` as *optional* tools in the
compose stage, and the natural reading of an optional tool — by an agent or a human
— is "run it if convenient". The shipped render was therefore delivered with an
empty `assets/music/` directory, a narration, and no bed: a finished video with
silence between the voice's sentences, delivered to the user with the question
«می‌خوای موزیک هم اضافه کنم؟» attached. That question is the edit's own job
arriving late; a deliverable should not ask the client to notice a missing layer.

So in narrated mode music is **required**: `audit_music` fails when the bed is
absent, unless the caller states `omit_music_reason` — an explicit, recorded
decision rather than a default silence.

## Why a licence record, and what it honestly contains

The user's requirement was «مطمئن شو موزیک‌های پیکس‌بی یا منابعی که داره، مشکل
کپی‌رایت در اینستاگرام نداشته باشن». No automated check can *guarantee* that:
Instagram's enforcement includes third-party Content-ID fingerprinting, and a
track can be flagged by a system that never read the licence. What a gate CAN do —
and what this module does — is refuse music whose provenance is not on record:

* **A commercial-use licence name.** Pixabay publishes the "Pixabay Content
  License" on every track page; a track whose licence field says so is recorded.
* **The source.** Where the file came from, as the searchable term and tool used,
  so a re-download is possible and a licence page can be revisited.
* **The licence URL.** The page the licence was read from, so the claim is
  checkable by a human rather than trusted from a string.
* **The download date.** Licences change; the date is what makes an old record
  falsifiable rather than eternally valid.
* **An attribution line** where the licence or the source asks for one.
* **A `content_id_risk` judgement** — low/unknown/high — with the reason recorded,
  not just the rating, so a later reader can disagree with evidence.

The audit refuses `high`, requires `low` to cite the licence, and passes `unknown`
only with an explicit acknowledgement recorded in the same place — never silently.

## The Pixabay Content License, as it stands

Permits use in commercial and monetized social media. Forbids: redistribution of
the track standalone or in a media compilation, sale of the track as-is or with
minor changes, and use of the track *in an AI dataset*. Requires: no
identification of the authors as endorsing your use. This module encodes those
terms as `PIXABAY_CONTENT_LICENSE` and treats a Pixabay-sourced track as
`content_id_risk: low` — low, not zero, because Content-ID is third-party and no
licence with a third party binds it. That boundary is stated in the audit output
rather than papered over.

## The user's own music

A user-supplied file passes with `source: "user-provided"`, its licence unknown by
default, and an acknowledgement recorded — the honest reading of a file whose
provenance the pipeline did not see.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
import math
import re
import shutil
import subprocess

#: Values `content_id_risk` may take. `low` must cite a licence; `high` is refused;
#: `unknown` passes only with a recorded acknowledgement.
RiskLevel = Literal["low", "unknown", "high"]

#: The Pixabay Content License terms, as published on every Pixabay track page.
#: Encoded rather than linked-only so the audit's statements are inspectable.
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

#: Licence names the audit recognizes as permitting monetized social media use.
#: Everything else is `unknown` by default — the caller can still declare it low
#: with a licence URL on record.
KNOWN_PERMISSIVE_LICENSES: frozenset[str] = frozenset(
    {PIXABAY_CONTENT_LICENSE["name"], "Pixabay Content License"}
)

#: Music level the renderer uses when a bed is present but no narration is.
DEFAULT_MUSIC_FLAT_VOLUME = 0.65
#: Music level while narration is present but not speaking.
DEFAULT_MUSIC_BASE_VOLUME = 0.72
#: Music level while the narration speaks.
DEFAULT_MUSIC_DUCK_VOLUME = 0.55
#: Head and tail fade for the bed, seconds.
DEFAULT_MUSIC_FADE_SECONDS = 1.5

#: A source bed below this integrated level is effectively a near-silent file once
#: renderer ducking is applied. This is an audibility floor, not a mix target.
MUSIC_AUDIBILITY_FLOOR_LUFS = -36.0
#: Maximum allowed loudness gap between narration and the ducked music bed.
#: Larger gaps were perceptually silent on mobile even when the source file itself
#: cleared the audibility floor.
MAX_DUCKED_MUSIC_GAP_LU = 15.0
_LUFS_RE = re.compile(r"\bI:\s*(-?[0-9]+(?:\.[0-9]+)?)\s+LUFS")



def effective_music_loudness(source_lufs: float, volume: float) -> float:
    """Return the bed loudness after renderer gain, in LUFS-equivalent dB.

    Renderer volume is linear amplitude, so 20*log10(volume) is the gain applied
    to an integrated loudness measurement.  Zero/negative volume is inaudible by
    definition and returns negative infinity.
    """
    if volume <= 0:
        return float("-inf")
    return float(source_lufs) + 20.0 * math.log10(float(volume))


def measure_integrated_loudness(path: Path, *, timeout: int = 60) -> float:
    """Measure integrated LUFS with ffmpeg/ebur128; refuse an unmeasurable bed."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is not on PATH, so music audibility cannot be measured")
    completed = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostats", "-i", str(path),
         "-af", "ebur128=framelog=verbose", "-f", "null", "-"],
        capture_output=True, text=True, timeout=timeout,
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
    """One music bed, with its provenance on record."""

    #: Path relative to the composition's public dir, as `PersianAudio.music` uses.
    path: str
    #: Tool the file came from — `pixabay_music`, `freesound_music`, a user file.
    source: str
    #: The licence name as published at the source, verbatim.
    license_name: str
    #: URL of the page the licence was read from.
    license_url: str
    #: ISO date the file was downloaded.
    downloaded_at: str
    #: Attribution line, if the licence or the source asks for one.
    attribution: str = ""
    #: The honest judgement, with its reason.
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
                "acknowledged": "Content-ID is third-party fingerprinting; no "
                "licence binds it, so no automated check can guarantee zero claim "
                "risk on Instagram. Provenance is recorded so any claim can be "
                "answered with the licence page.",
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
    """Normalize a raw music record, refusing absent provenance fields.

    Missing provenance is not defaulted — it is rejected, because a record with an
    empty `license_url` is exactly the "we did not check" that the audit exists to
    prevent, dressed as data.
    """
    license_block = raw.get("license") or {}
    risk_block = raw.get("contentIdRisk") or {}
    risk = risk_block.get("level") or "unknown"
    if risk not in ("low", "unknown", "high"):
        raise ValueError(
            f"music contentIdRisk {risk!r} is not one of low/unknown/high"
        )

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
            f"music record is missing {', '.join(missing)}. Provenance is not "
            "optional: a bed whose licence page cannot be revisited is a claim "
            "about copyright nobody can check, and the user asked for exactly that "
            "not to happen."
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


def audit_music(
    *,
    track: MusicTrack | None,
    narrated: bool,
    acknowledge_unknown_risk: bool = False,
    omit_music_reason: str = "",
) -> MusicAudit:
    """Gate the music layer for a project.

    Args:
        track: The music record, or None when the project has no bed.
        narrated: Whether this project carries narration. Silent projects may
            legitimately have no bed (the voice was never the spine), so the
            requirement is scoped to narrated ones.
        acknowledge_unknown_risk: An explicit, recorded acknowledgement that
            Content-ID risk cannot be zero. Required to pass with `unknown` risk.
        omit_music_reason: The recorded reason a narrated project ships without a
            bed. Present → advisory, not fault: an explicit decision, not a default
            silence.

    The requirement being enforced is the user's, verbatim: delivering a narrated
    video with no music and then asking «می‌خوای موزیک هم اضافه کنم؟» is the edit's
    own job arriving late. An optional tool is how it got skipped; required is the
    fix, with an explicit escape hatch so a deliberate silence is still expressible.
    """
    audit = MusicAudit(track=track)

    if track is None:
        if narrated:
            if omit_music_reason:
                audit.advisories.append(
                    "no music bed, by recorded decision: "
                    f"{omit_music_reason!r}. An explicit choice rather than a "
                    "default silence — the pipeline treats it as legitimate but "
                    "keeps it on the record."
                )
            else:
                audit.problems.append(
                    "a narrated video has no music bed. Music is required in "
                    "narrated mode — a finished deliverable with silence under the "
                    "voice's pauses is an unfinished edit, and asking the client "
                    "afterwards is the edit's own job arriving late. Either source "
                    "a bed (pixabay_music is available and needs no key) or record "
                    "an explicit omit_music_reason."
                )
        return audit

    if track.content_id_risk == "high":
        audit.problems.append(
            f"music {track.path!r} is marked high Content-ID risk: {track.risk_reason} "
            "— pick another track. The user asked for Instagram-safe audio, and a "
            "known-risk track is the one case that cannot be acknowledged away."
        )
        return audit

    if track.content_id_risk == "low":
        if track.license_name not in KNOWN_PERMISSIVE_LICENSES:
            audit.problems.append(
                f"music {track.path!r} claims low risk under licence "
                f"«{track.license_name}», which is not one the audit recognizes as "
                "permitting monetized social media. Record the licence terms or "
                "downgrade the judgement to unknown."
            )
        if not track.license_url:
            audit.problems.append(
                f"music {track.path!r} has no licence URL — a low-risk claim that "
                "cannot be revisited is not a claim, it is a hope."
            )

    if track.content_id_risk == "unknown" and not acknowledge_unknown_risk:
        audit.problems.append(
            f"music {track.path!r} has unknown Content-ID risk and the record does "
            "not acknowledge it. Unknown is acceptable only when someone has "
            "consciously accepted it: pass acknowledge_unknown_risk and the "
            "acknowledgement is written into the audit record, so the decision "
            "survives to whoever has to answer a claim."
        )

    return audit


def audio_props_with_music(
    *,
    narration: str | None,
    music_path: str | None,
) -> dict[str, Any] | None:
    """The `PersianAudio` block the compose stage should emit.

    Every music level is stated explicitly rather than left to the renderer's
    defaults, because defaults that live in two places (renderer and pipeline)
    drift apart in exactly one of them, silently.
    """
    if narration is None and music_path is None:
        return None
    props: dict[str, Any] = {}
    if narration is not None:
        props["narration"] = narration
    if music_path is not None:
        props.update(
            {
                "music": music_path,
                "musicFlatVolume": DEFAULT_MUSIC_FLAT_VOLUME,
                "musicBaseVolume": DEFAULT_MUSIC_BASE_VOLUME,
                "musicDuckVolume": DEFAULT_MUSIC_DUCK_VOLUME,
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
    "MUSIC_AUDIBILITY_FLOOR_LUFS",
    "MAX_DUCKED_MUSIC_GAP_LU",
    "effective_music_loudness",
    "measure_integrated_loudness",
    "MusicTrack",
    "MusicAudit",
    "build_music_track",
    "audit_music",
    "audio_props_with_music",
]
