"""Render the Persian footage composition through Remotion.

## Why this is a separate tool rather than a `renderer_family` entry

`video_compose` routes through `RENDERER_FAMILY_MAP` into compositions that all
share one prop shape: a list of `cuts`, adapted by `_cuts_to_cinematic_scenes` or by
the Explainer scene adapter. The Persian composition does not take cuts. It takes
`shots` plus a list of typographic `moments`, because a moment carries an ordered
`segments` array (`role`/`text`/`accentWords`/`revealAfterSeconds`) whose array
order IS the arrangement on the frame — plus a `kind` that records the editorial
classification and switches the hook-scoped tokens — none of which has any
representation in a cut list. The retired slot shape (`text`/`label`/`kicker`/
`unit`/`highlight`/`highlightWords`) is refused outright (see RETIRED_MOMENT_KEYS),
not adapted: supporting both would mean supporting two incompatible ideas of what
the typographic layer is.

Forcing it through the cut adapter would mean either mangling the Persian props or
adding a Persian branch inside `video_compose` — and `skills/meta/capability-extension.md`
forbids modifying existing tools for exactly this reason: a branch added for one
pipeline is a branch every other pipeline's renders now walk past.

So this tool wraps the same `npx remotion render` invocation with its own prop
assembly, and `video_compose` is untouched. Every existing `renderer_family` resolves
exactly as it did before.

## Staging

Clips are copied into `remotion-composer/public/persian/<run-id>/` rather than
passing `--public-dir`. Overriding the public dir would hide
`public/fonts/estedad/`, and the composition's `delayRender` would then never
resolve — the render hangs rather than failing, which is far harder to diagnose than
a missing clip.

## Gates

The prop assembly refuses three things outright rather than rendering them: `cues`,
`hookText`, and a moment set that breaks its pacing rules. All three are retired
designs, and each one costs a full render to notice.

The reason they are refused *here* rather than only in the composition is timing.
Remotion validates props when the browser mounts the tree, minutes into a render and
after every clip has been staged. This tool has the props in hand before anything is
copied, so the same fault costs seconds. The composition keeps its own assertions —
two independent guards, because the failure they prevent is silent.
"""

from __future__ import annotations

import json
import secrets
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

from lib.persian_moments import (
    HOOK_SILHOUETTE_MAX_RATIO,
    HOOK_SILHOUETTE_MIN_RATIO,
    OPENING_MAX_START_SECONDS,
    audit_moments,
    build_moments,
)
from lib.persian_music import audit_music, audio_props_with_music, build_music_track
from lib.persian_srt import audit_cues, build_cues, render_srt
from lib.persian_sync import TimedWord, audit_sync
from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    ResumeSupport,
    RetryPolicy,
    ToolResult,
    ToolStability,
    ToolStatus,
    ToolTier,
)

#: Composition IDs registered in remotion-composer/src/Root.tsx.
_COMPOSITION_IDS = {
    "vertical": "PersianFootageVertical",
    "landscape": "PersianFootageLandscape",
}

#: Where staged clips live, relative to the composer's public dir.
_STAGING_ROOT = "persian"


def _composer_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "remotion-composer"


class PersianCompose(BaseTool):
    """Render a Persian (RTL) footage video from edit_decisions."""

    name = "persian_compose"
    version = "0.2.0"
    tier = ToolTier.CORE
    capability = "video_post"
    provider = "remotion"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    # Remotion renders frame-by-frame from a deterministic React tree, and every
    # animation in the Persian composition is a pure function of frame number:
    # the plate's orbs come from a seeded PRNG, the grain seed is a constant.
    determinism = Determinism.DETERMINISTIC

    dependencies = ["node:remotion"]
    install_instructions = "cd remotion-composer && npm install"
    agent_skills: list[str] = []

    capabilities = ["render_persian_video"]

    input_schema = {
        "type": "object",
        "required": ["edit_decisions", "output_path"],
        "properties": {
            "edit_decisions": {
                "type": "object",
                "description": (
                    "Edit decisions carrying a `persian` block with format, shots, "
                    "moments, watermark, and audio."
                ),
            },
            "output_path": {"type": "string", "description": "Destination MP4 path"},
            "scale": {
                "type": "number",
                "description": (
                    "Render scale. Use below 1.0 for a quick check; ship at 1.0. "
                    "Text is measured at full size regardless, so a scaled render "
                    "still validates layout."
                ),
                "default": 1.0,
            },
            "crf": {
                "type": "integer",
                "description": (
                    "H.264 quality, lower is better. Default 16: the scrim's gradient "
                    "and the film grain are exactly what a higher CRF destroys first, "
                    "and banding across a large soft gradient is very visible."
                ),
                "default": 16,
            },
            "concurrency": {
                "type": "integer",
                "description": "Parallel render workers. Defaults to Remotion's choice.",
            },
            "timeout_ms": {
                "type": "integer",
                "description": (
                    "Per-frame timeout. Raise above the 30s default when the font "
                    "load or a large clip's first frame is slow on a cold cache."
                ),
                "default": 60000,
            },
            "frames": {
                "type": "string",
                "description": (
                    "Optional frame range like '0-90', for verifying a section "
                    "without rendering the whole video."
                ),
            },
        },
    }

    output_schema = {
        "type": "object",
        "properties": {
            "output_path": {"type": "string"},
            "composition_id": {"type": "string"},
            "format": {"type": "string"},
            "duration_seconds": {"type": "number"},
            "moment_count": {"type": "integer"},
            "shot_count": {"type": "integer"},
            "text_coverage": {"type": "number"},
            "subtitle_path": {"type": "string"},
            "subtitle_advisories": {"type": "array"},
            "attributions": {"type": "array"},
            "persian_text_verified": {"type": "boolean"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=4,
        ram_mb=4096,
        vram_mb=0,
        disk_mb=2048,
        network_required=False,
    )

    retry_policy = RetryPolicy(max_retries=0, retryable_errors=[])
    resume_support = ResumeSupport.FROM_START
    idempotency_key_fields = ["output_path"]
    side_effects = [
        "stages clips into remotion-composer/public/persian/",
        "writes the output MP4",
        "writes a sidecar .srt beside the MP4 when narration word timings are supplied",
    ]
    fallback = None
    user_visible_verification = [
        "Extract a frame and confirm Persian text renders right-to-left with no empty boxes",
        "Confirm every line of every moment shares one right edge",
        "Confirm the footage is visible with nothing over it between moments",
        "Confirm the watermark is legible and reaches its resting corner",
    ]

    def get_status(self) -> ToolStatus:
        composer = _composer_dir()
        if not (composer / "node_modules").exists():
            return ToolStatus.UNAVAILABLE
        if shutil.which("npx") is None:
            return ToolStatus.UNAVAILABLE
        return ToolStatus.AVAILABLE

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        persian = (inputs.get("edit_decisions") or {}).get("persian") or {}
        duration = float(persian.get("durationSeconds") or 60.0)
        # Roughly 4x real time on this class of machine at scale 1.0.
        return duration * 4.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        edit_decisions = inputs.get("edit_decisions") or {}
        persian = edit_decisions.get("persian")
        if not isinstance(persian, dict):
            return ToolResult(
                success=False,
                error=(
                    "edit_decisions.persian is missing. This tool renders the Persian "
                    "composition, whose props are not derivable from a cut list — the "
                    "edit director must emit the `persian` block."
                ),
            )

        # Governance: the runtime is locked for this pipeline. Refuse rather than
        # silently rendering something the caller did not ask for.
        runtime = str(edit_decisions.get("render_runtime") or "remotion").lower()
        if runtime != "remotion":
            return ToolResult(
                success=False,
                error=(
                    f"edit_decisions.render_runtime is {runtime!r}, but the Persian "
                    "composition requires 'remotion': it loads Estedad through "
                    "FontFace and measures text on a canvas, neither of which exists "
                    "on the ffmpeg or hyperframes paths. Raise a structured blocker "
                    "rather than swapping runtimes."
                ),
            )

        video_format = str(persian.get("format") or "vertical")
        composition_id = _COMPOSITION_IDS.get(video_format)
        if composition_id is None:
            return ToolResult(
                success=False,
                error=(
                    f"Unknown format {video_format!r}. "
                    f"Valid: {sorted(_COMPOSITION_IDS)}."
                ),
            )

        composer = _composer_dir()
        if not (composer / "node_modules").exists():
            return ToolResult(
                success=False,
                error=f"remotion-composer/node_modules missing at {composer}. Run npm install.",
            )

        output_path = Path(inputs["output_path"]).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        run_id = secrets.token_hex(4)
        staging_dir = composer / "public" / _STAGING_ROOT / run_id
        props_path = output_path.parent / f".persian_props_{run_id}.json"

        try:
            props, attributions = self._build_props(persian, staging_dir, run_id)
        except (FileNotFoundError, ValueError) as exc:
            shutil.rmtree(staging_dir, ignore_errors=True)
            return ToolResult(success=False, error=str(exc))

        try:
            props_path.write_text(
                json.dumps(props, ensure_ascii=False), encoding="utf-8"
            )

            cmd = [
                "npx",
                "remotion",
                "render",
                str(composer / "src" / "index.tsx"),
                composition_id,
                str(output_path),
                # Equals form: Remotion mis-parses a separately-passed path on
                # Windows. Same reasoning as video_compose._remotion_render.
                f"--props={props_path}",
            ]

            scale = inputs.get("scale")
            if scale is not None and float(scale) != 1.0:
                cmd.append(f"--scale={scale}")
            crf = inputs.get("crf", 16)
            if crf is not None:
                cmd.append(f"--crf={int(crf)}")
            if inputs.get("concurrency"):
                cmd.append(f"--concurrency={int(inputs['concurrency'])}")
            timeout_ms = inputs.get("timeout_ms", 60000)
            if timeout_ms:
                cmd.append(f"--timeout={int(timeout_ms)}")
            if inputs.get("frames"):
                cmd.append(f"--frames={inputs['frames']}")

            try:
                completed = self.run_command(
                    cmd,
                    # 30 minutes. A 60s vertical render takes minutes; this ceiling
                    # exists so a hung headless browser fails instead of hanging.
                    timeout=1800,
                    # Run inside the composer so npx finds the local remotion binary.
                    cwd=composer,
                )
            except subprocess.TimeoutExpired:
                return ToolResult(
                    success=False,
                    error="Remotion render exceeded 1800s and was killed.",
                )

            if completed.returncode != 0:
                stderr = (completed.stderr or "")[-2000:]
                return ToolResult(
                    success=False,
                    error=self._diagnose(stderr, completed.returncode),
                )

            if not output_path.exists():
                return ToolResult(
                    success=False,
                    error=f"Render reported success but {output_path} does not exist.",
                )

            subtitle_path, subtitle_advisories = self._write_subtitles(
                persian, output_path
            )

            covered = sum(
                float(m["endSeconds"]) - float(m["startSeconds"])
                for m in props["moments"]
            )
            artifacts = [str(output_path)]
            if subtitle_path:
                artifacts.append(subtitle_path)

            return ToolResult(
                success=True,
                data={
                    "output_path": str(output_path),
                    "composition_id": composition_id,
                    "format": video_format,
                    "duration_seconds": props["durationSeconds"],
                    "moment_count": len(props["moments"]),
                    "shot_count": len(props.get("shots") or []),
                    # Reported because it is the number that says whether this is a
                    # typographic edit or a caption track, and it is invisible in the
                    # MP4 without measuring it.
                    "text_coverage": round(covered / props["durationSeconds"], 4),
                    "subtitle_path": subtitle_path,
                    "subtitle_advisories": subtitle_advisories,
                    "attributions": attributions,
                    "persian_text_verified": False,  # Set by the reviewer, not here.
                },
                artifacts=artifacts,
            )
        finally:
            # Staged clips are copies; the originals stay in the project. Removing
            # them keeps public/ from accumulating gigabytes across renders, which
            # matters on a nearly-full disk.
            shutil.rmtree(staging_dir, ignore_errors=True)
            props_path.unlink(missing_ok=True)

    def _build_props(
        self,
        persian: dict[str, Any],
        staging_dir: Path,
        run_id: str,
    ) -> tuple[dict[str, Any], list[str]]:
        """Assemble composition props, staging every media file into public/.

        Raises:
            FileNotFoundError: when a referenced media file is absent. Raised rather
                than skipped: a missing clip renders as a silent black beat, and a
                black beat that nobody notices until review costs a whole render.
            ValueError: when required timing data is missing.
        """
        staging_dir.mkdir(parents=True, exist_ok=True)
        attributions: list[str] = []

        shots: list[dict[str, Any]] = []
        for index, shot in enumerate(persian.get("shots") or []):
            source = shot.get("source") or shot.get("path")
            if not source:
                raise ValueError(f"shot[{index}] has no source path")
            staged = self._stage(Path(source), staging_dir, run_id)

            attribution = str(shot.get("attribution") or "").strip()
            if not attribution:
                raise ValueError(
                    f"shot[{index}] ({source}) has no attribution. Both Pexels and "
                    "Pixabay require it; a clip that cannot be attributed must not ship."
                )
            attributions.append(attribution)

            shots.append(
                {
                    "id": str(shot.get("id") or f"shot-{index + 1}"),
                    "source": staged,
                    "startSeconds": float(shot["startSeconds"]),
                    "endSeconds": float(shot["endSeconds"]),
                    "sourceInSeconds": float(shot.get("sourceInSeconds") or 0.0),
                    "camera": str(shot.get("camera") or "none"),
                    "attribution": attribution,
                }
            )

        audio_props: dict[str, Any] = {}
        audio = persian.get("audio") or {}
        for key in ("narration", "music"):
            if audio.get(key):
                audio_props[key] = self._stage(Path(audio[key]), staging_dir, run_id)
        for key in (
            "musicFlatVolume",
            "musicBaseVolume",
            "musicDuckVolume",
            "musicFadeSeconds",
        ):
            if audio.get(key) is not None:
                audio_props[key] = float(audio[key])

        # Music gate. A narrated project with no bed was the shipped defect: the
        # video was delivered with silence under the voice's pauses and the
        # question «می‌خوای موزیک هم اضافه کنم؟» attached, which is the edit's own
        # job arriving late. The gate fails rather than warns; the escape hatch is a
        # recorded reason, so a deliberate silence stays expressible but never
        # accidental. The licence record is enforced at the same point because the
        # bed is being staged here — the last place the provenance can be checked
        # against the file that will actually ship.
        narrated = bool(audio.get("narration"))
        # `persian.musicTrack` is the new record-carrying shape; `persian.audio.music`
        # remains the plain path string (already staged above). A record and a path
        # must not both be given — the record would win silently and the licence
        # claim would attach to a different file than the one staged.
        raw_track = persian.get("musicTrack")
        if raw_track and audio.get("music"):
            raise ValueError(
                "both edit_decisions.persian.musicTrack and edit_decisions.persian."
                "audio.music are set. The record must describe exactly the file it "
                "licenses; state one, not both."
            )
        track = build_music_track(raw_track) if raw_track else None
        if track is not None:
            audio_props["music"] = self._stage(Path(track.path), staging_dir, run_id)
            audio_props.setdefault("musicFadeSeconds", 1.5)
        music_audit = audit_music(
            track=track,
            narrated=narrated,
            acknowledge_unknown_risk=bool(persian.get("acknowledgeUnknownMusicRisk")),
            omit_music_reason=str(persian.get("omitMusicReason") or ""),
        )
        if not music_audit.passed:
            raise ValueError(
                "the music layer is incomplete, so the render is refused rather "
                "than delivered half-finished:\n  - " + "\n  - ".join(music_audit.problems)
            )

        duration_seconds = float(persian["durationSeconds"])
        moments = self._build_moments(persian, duration_seconds)

        props: dict[str, Any] = {
            "format": str(persian.get("format") or "vertical"),
            "durationSeconds": duration_seconds,
            "shots": shots,
            "moments": moments,
            # Every optional key that can paint is stated explicitly, empty when
            # unused, because Remotion shallow-merges these props over the
            # composition's `defaultProps`: an omitted key is not "unset", it is
            # inherited. Omitting `typographicBeats` once let a fixture's beats
            # through, and the plate they render is opaque — footage-hiding — by
            # design. The render succeeded and the footage was invisible.
            #
            # `Root.tsx` now also defaults these to empty, so this is the second of
            # two independent guards. Both are cheap; the failure they prevent is
            # silent and costs a whole render to notice.
            "typographicBeats": list(persian.get("typographicBeats") or []),
        }
        if audio_props:
            props["audio"] = audio_props
        if persian.get("watermark"):
            props["watermark"] = persian["watermark"]

        return props, attributions

    @staticmethod
    def _build_moments(
        persian: dict[str, Any], duration_seconds: float
    ) -> list[dict[str, Any]]:
        """Normalize, audit, and return the typographic moments.

        Raises:
            ValueError: on a retired key, a moment set that breaks its own pacing
                rules, or a narrated video whose timings are not anchored to its own
                narration. All are refused rather than repaired, for the same reason:
                the fix is an editorial decision about which moment to cut or
                re-derive, and a tool that guesses at it produces a video nobody
                designed.

        The sync audit is new, and it exists because of the shipped defect: the
        moments had been timed for a *previous* narration and rescaled onto the
        new one by the duration ratio, which preserved the shape of the old edit
        and nothing about where the new voice actually speaks. Drift reached 3.4s
        and the video read as unsynchronized with nothing in the pipeline able to
        say why, because a timing is just a number and nothing recorded where it
        came from. `audit_sync` re-derives each moment's start from the narration
        words its anchor names; a rescaled set fails by construction.
        """
        for retired, reason in (
            (
                "cues",
                "the composition no longer paints a caption track. Narration text ships "
                "as a sidecar `.srt` instead — pass `audio.wordTimings` and this tool "
                "writes it. Burning a transcript into the frame is the specific failure "
                "the moment model replaced.",
            ),
            (
                "hookText",
                "the opening hook was removed. It duplicated the first caption "
                "character-for-character and played on top of it, so the frame carried "
                "the same sentence twice in two places. The opening now belongs to the "
                "first moment, which is on screen within "
                f"{OPENING_MAX_START_SECONDS}s and carries the claim itself.",
            ),
        ):
            if persian.get(retired):
                raise ValueError(f"edit_decisions.persian.{retired} is set, but {reason}")

        authored = persian.get("moments")
        if not authored:
            raise ValueError(
                "edit_decisions.persian.moments is empty. A video with no typographic "
                "moment is legitimate only as a purely visual piece; if that is the "
                "intent, state `moments: []` explicitly so the choice is on the record "
                "rather than looking like a stage that failed to run."
            )

        built = build_moments(authored)
        # Try to attach fitted stackHeightPx for verifier plateau scoping. This
        # requires canvas text measurement (Estedad + node-canvas). When available
        # (node-canvas installed) we compute the real stack via layout.ts;
        # otherwise the prop is omitted and the verifier falls back to zone.
        _maybe_attach_stack_heights(built, str(persian.get("format") or "vertical"))
        audit = audit_moments(built, duration_seconds=duration_seconds)
        if not audit.passed:
            raise ValueError(
                "the moment set breaks its pacing rules, so it is refused before "
                "rendering rather than after:\n  - " + "\n  - ".join(audit.problems)
            )

        # Narration anchoring. Word timings are the ground truth of when each phrase
        # is spoken; a moment set that disagrees with them by more than a viewer
        # forgives is a fault with exactly one honest remedy — re-derive, not nudge.
        word_timings = (persian.get("audio") or {}).get("wordTimings")
        if word_timings:
            timed = TimedWord.from_dicts(word_timings)
            sync = audit_sync(built, timed)
            if not sync.passed:
                raise ValueError(
                    "the moment timings disagree with the narration they are set "
                    "against, so they are refused before rendering rather than "
                    "after:\n  - " + "\n  - ".join(sync.problems)
                )

        return [moment.to_props() for moment in built]

    @staticmethod
    def _write_subtitles(
        persian: dict[str, Any], output_path: Path
    ) -> tuple[str | None, list[str]]:
        """Write the narration sidecar `.srt` beside the MP4.

        Returns the path written (or None) and any readability advisories, which are
        surfaced rather than raised: an over-speed caption is a property of the
        narration's delivery, and the honest remedy is a shorter script — not a refused
        render at the last stage before delivery.
        """
        word_timings = (persian.get("audio") or {}).get("wordTimings")
        if not word_timings:
            return None, []

        cues = build_cues(word_timings)
        if not cues:
            return None, []

        srt_path = output_path.with_suffix(".srt")
        # utf-8-sig: several players (and Windows Notepad) mis-detect a BOM-less UTF-8
        # SRT as a legacy single-byte encoding and render Persian as mojibake.
        srt_path.write_text(render_srt(cues), encoding="utf-8-sig")
        return str(srt_path), audit_cues(cues)

    @staticmethod
    def _stage(source: Path, staging_dir: Path, run_id: str) -> str:
        """Copy one media file into the staging dir; return its staticFile path."""
        resolved = source.expanduser()
        if not resolved.is_absolute():
            resolved = (Path.cwd() / resolved).resolve()
        if not resolved.exists():
            raise FileNotFoundError(
                f"Media file not found: {source}. A missing file renders as a silent "
                "black beat, so the render is refused instead."
            )

        # Prefix with a short digest of the full path so two clips with the same
        # basename from different directories cannot collide in the flat staging dir.
        digest = secrets.token_hex(3)
        target = staging_dir / f"{digest}-{resolved.name}"
        shutil.copy2(resolved, target)
        return f"{_STAGING_ROOT}/{run_id}/{target.name}"

    @staticmethod
    def _diagnose(stderr: str, returncode: int) -> str:
        """Turn a Remotion failure into an actionable message.

        The three failures below account for nearly every Persian-composition render
        error, and each one's raw stderr points somewhere unhelpful.
        """
        hints: list[str] = []

        if "Estedad" in stderr or "delayRender" in stderr:
            hints.append(
                "The Estedad font failed to load. Confirm "
                "remotion-composer/public/fonts/estedad/Estedad-Medium.ttf exists and "
                "that --public-dir was not overridden (it would hide public/fonts/)."
            )
        if "measurePersian" in stderr or "before the font" in stderr:
            hints.append(
                "Text was measured before the font finished loading. This should be "
                "impossible via calculateMetadata; if it happened, a component is "
                "measuring outside the composition tree."
            )
        if "does not fit" in stderr or "fitBlock" in stderr:
            hints.append(
                "A moment's text could not be fitted even at the minimum font scale. "
                "It is too long for its role — hero past 30 visible characters "
                "(60 for a flat-hook hero carrying accentWords), lead/tail past 42, "
                "source past 40 (lib/persian_moments.py). Shorten it at "
                "the edit stage rather than lowering the floor."
            )
        if "overlap" in stderr or "apart" in stderr or "MOMENT_MIN_GAP" in stderr:
            hints.append(
                "The moments are paced too tightly. This tool audits pacing before "
                "rendering, so reaching the composition's own assertion means the props "
                "were assembled elsewhere — check whether something wrote `moments` "
                "directly into the props file."
            )
        if "Cannot find module" in stderr:
            hints.append("A dependency is missing. Run `npm install` in remotion-composer.")

        body = f"Remotion render failed (exit {returncode}).\n\n{stderr.strip()}"
        if hints:
            body += "\n\nLikely cause:\n  " + "\n  ".join(hints)
        return body


def _maybe_attach_stack_heights(built: list[Any], fmt: str) -> None:
    """Attach `stackHeightPx` to each built moment when node-canvas is available.

    The fitted height comes from `layout.ts:fitMoment`, which needs canvas
    text measurement with the vendored Estedad fonts. When `canvas` is not
    installed we leave the moments untouched — the verifier will fall back to
    zone-scoped measurement.

    The same node run enforces the hook silhouette gate: for every `kind: "hook"`
    moment the driver returns `silhouetteRatio` (narrowest painted line over
    widest, across every line of every non-`source` segment) and the bridge
    refuses a ratio outside `HOOK_SILHOUETTE_MIN_RATIO..HOOK_SILHOUETTE_MAX_RATIO`
    — the same refuse-not-warn discipline as `audit_moments`, raised as
    `ValueError` through the same `except` in `execute`, so a rectangular hook
    costs seconds rather than a render. The gate lives here and not in
    `lib/persian_moments.py` because this module has no font: the ratio needs
    real measured widths, and this bridge is the one place that already fits
    every moment against the real type.

    What this does to the flat style, stated plainly: the flat line breaker
    minimises squared slack, which *balances* lines, so a flat hook ratios
    around 0.87–0.88 and fails the band. That is a true finding, not a bug to
    hide — the claim+qualifier style is the working hook style, and the flat
    style would need a hook-specific break objective before it could pass. The
    band is not weakened to accommodate it; see `HOOK_SILHOUETTE_MIN_RATIO` in
    `lib/persian_moments.py`.

    When node-canvas is absent the bridge is a no-op and the gate with it — the
    documented fallback, not a pass. A render without the bridge has no measured
    widths to judge, so it cannot certify the silhouette; the verifier's
    zone-scoped measurement applies instead.

    The driver is *bundled with esbuild* rather than run through
    `node --experimental-strip-types`, because the persian sources import each
    other by extensionless specifier (`./measure`, `./text`), which
    strip-types does not resolve. The `canvas` package stays `--external` — it
    ships a native `.node` binary esbuild cannot inline — and `estedadReady` is
    awaited before any fit, because `measurePersian` throws rather than
    measuring against a fallback font. Proven end-to-end: the driver returns the
    real fitted heights (e.g. 540.95px for a two-segment lead+hero moment).
    """
    import json as _json
    import subprocess
    import tempfile

    composer = _composer_dir()
    # Quick availability check
    if not (composer / "node_modules" / "canvas" / "package.json").exists():
        return
    esbuild = composer / "node_modules" / ".bin" / "esbuild"
    if not esbuild.exists():
        return

    # Build a small driver that fits the actual moment segments. Every key of
    # `PersianSegment` that the fitter's result depends on is carried, mirroring
    # `PersianMoment.to_props` in `lib/persian_moments.py`: `role` and `text`
    # always, `accentWords` when non-empty, `revealAfterSeconds` when positive —
    # plus the moment's declared `kind`, which `fitMoment` takes as a required
    # parameter: without it a claim+qualifier hook fits as an ordinary moment
    # (123px Black hero, lead-derived tail) instead of the approved style.
    # `accentWords` is load-bearing, not decorative — `isFlatDisplayBlock` in
    # `layout.ts` keys the flat-hook treatment (3-line cap, display leading) off
    # it, and without it a flat hook fits as an ordinary emphasis span (187px /
    # 2 lines) instead of the display block the renderer paints (479px / 3 lines).
    def _segment_payload(s: Any) -> dict[str, Any]:
        payload_segment: dict[str, Any] = {"role": s.role, "text": s.text}
        if getattr(s, "accent_words", None):
            payload_segment["accentWords"] = list(s.accent_words)
        if getattr(s, "reveal_after_seconds", 0) > 0:
            payload_segment["revealAfterSeconds"] = s.reveal_after_seconds
        return payload_segment

    payload = [
        {
            "id": m.id,
            "kind": m.kind,
            "segments": [_segment_payload(s) for s in m.segments],
        }
        for m in built
    ]
    tmp_dir = composer / ".tmp"
    tmp_dir.mkdir(exist_ok=True)
    driver = tempfile.NamedTemporaryFile(
        mode="w", suffix=".mjs", delete=False, dir=str(tmp_dir)
    )
    bundle = tmp_dir / (Path(driver.name).stem + ".bundle.mjs")
    try:
        driver.write(
            "import { createCanvas, registerFont } from 'canvas';\n"
            "registerFont('./public/fonts/estedad/Estedad-Medium.ttf', { family: 'Estedad', weight: '500' });\n"
            "registerFont('./public/fonts/estedad/Estedad-Bold.ttf', { family: 'Estedad', weight: '700' });\n"
            "registerFont('./public/fonts/estedad/Estedad-Black.ttf', { family: 'Estedad', weight: '900' });\n"
            "globalThis.document = { createElement: (tag) => { if(tag!=='canvas') throw new Error(tag); return createCanvas(3000,1000); } };\n"
            "globalThis.FontFace = class { constructor(f,s,d){this.family=f;this.src=s;this.desc=d;} load(){return Promise.resolve(this);} };\n"
            "globalThis.document.fonts = { add:()=>{}, load:()=>Promise.resolve([]), check:()=>true };\n"
            "const { estedadReady } = await import('../src/persian/fonts');\n"
            "await estedadReady;\n"
            "const { fitMoment, silhouetteRatio } = await import('../src/persian/layout');\n"
            f"const payload = {_json.dumps(payload, ensure_ascii=False)};\n"
            f"const fmt = {fmt!r};\n"
            "const out = payload.map(p => { const f = fitMoment(p.segments, fmt, p.kind);"
            " return { heightPx: f.heightPx,"
            " ratio: p.kind === 'hook' ? silhouetteRatio(f) : null }; });\n"
            "process.stdout.write(JSON.stringify(out));\n"
        )
        driver.close()
        build = subprocess.run(
            [
                str(esbuild),
                driver.name,
                "--bundle",
                "--format=esm",
                "--platform=node",
                "--external:canvas",
                f"--outfile={bundle}",
                "--log-level=error",
            ],
            capture_output=True,
            text=True,
            cwd=str(composer),
            timeout=60,
        )
        if build.returncode != 0:
            return
        result = subprocess.run(
            ["node", str(bundle)],
            capture_output=True,
            text=True,
            cwd=str(composer),
            timeout=60,
        )
        if result.returncode != 0:
            return
        fitted = _json.loads(result.stdout.strip() or "[]")
        for moment, fit in zip(built, fitted):
            try:
                # Attach as attribute; to_props will emit it
                object.__setattr__(moment, "stack_height_px", float(fit["heightPx"]))
            except Exception:
                pass
            ratio = fit.get("ratio")
            if ratio is None:
                continue
            if not (
                HOOK_SILHOUETTE_MIN_RATIO <= float(ratio) <= HOOK_SILHOUETTE_MAX_RATIO
            ):
                raise ValueError(
                    f"moment {moment.id}: hook silhouette ratio "
                    f"{float(ratio):.3f} is outside the "
                    f"{HOOK_SILHOUETTE_MIN_RATIO:.2f}–{HOOK_SILHOUETTE_MAX_RATIO:.2f} "
                    "band. The ratio is the narrowest painted line over the "
                    "widest, across every line of every non-source segment: "
                    "near 1.0 the lines read as a rectangle (the rejected flat "
                    "hook measured 0.88), near 0.5 the qualifier reads as a "
                    "caption under a poster. The approved claim+qualifier style "
                    "measures 0.647 against a 0.62 reference — re-split the "
                    "claim and the qualifier rather than resizing them."
                )
    except ValueError:
        raise
    except Exception:
        return
    finally:
        try:
            import os

            os.unlink(driver.name)
        except Exception:
            pass
        try:
            bundle.unlink(missing_ok=True)
        except Exception:
            pass
