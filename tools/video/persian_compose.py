"""Render the Persian footage composition through Remotion.

## Why this is a separate tool rather than a `renderer_family` entry

`video_compose` routes through `RENDERER_FAMILY_MAP` into compositions that all
share one prop shape: a list of `cuts`, adapted by `_cuts_to_cinematic_scenes` or by
the Explainer scene adapter. The Persian composition does not take cuts. It takes
`shots` and `cues` with word-level timings, because karaoke emphasis and
Persian-aware line breaking need data that has no representation in a cut list.

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
"""

from __future__ import annotations

import json
import secrets
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

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
    version = "0.1.0"
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
                    "cues, watermark, and audio."
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
                    "H.264 quality, lower is better. Default 16: the glass panel's "
                    "gradients and the film grain are exactly what a higher CRF "
                    "destroys first, and banding in a blurred panel is very visible."
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
            "cue_count": {"type": "integer"},
            "shot_count": {"type": "integer"},
            "attributions": {"type": "array"},
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
    ]
    fallback = None
    user_visible_verification = [
        "Extract a frame and confirm Persian text renders right-to-left with no empty boxes",
        "Confirm no subtitle text extends past the glass panel edge",
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

            return ToolResult(
                success=True,
                data={
                    "output_path": str(output_path),
                    "composition_id": composition_id,
                    "format": video_format,
                    "duration_seconds": props["durationSeconds"],
                    "cue_count": len(props.get("cues") or []),
                    "shot_count": len(props.get("shots") or []),
                    "attributions": attributions,
                    "persian_text_verified": False,  # Set by the reviewer, not here.
                },
                artifacts=[str(output_path)],
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
        for key in ("musicFlatVolume", "musicBaseVolume", "musicDuckVolume"):
            if audio.get(key) is not None:
                audio_props[key] = float(audio[key])

        props: dict[str, Any] = {
            "format": str(persian.get("format") or "vertical"),
            "durationSeconds": float(persian["durationSeconds"]),
            "shots": shots,
            "cues": list(persian.get("cues") or []),
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
        if persian.get("hookText"):
            props["hookText"] = persian["hookText"]
            if persian.get("hookDurationSeconds") is not None:
                props["hookDurationSeconds"] = float(persian["hookDurationSeconds"])
        else:
            # Same reasoning: an absent hook must be an empty hook, not an
            # inherited one.
            props["hookText"] = ""
            props["hookDurationSeconds"] = 0.0

        return props, attributions

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
                "A cue could not be fitted even at the minimum font scale. The cue "
                "text is too long — shorten it at the edit stage rather than lowering "
                "the floor."
            )
        if "Cannot find module" in stderr:
            hints.append("A dependency is missing. Run `npm install` in remotion-composer.")

        body = f"Remotion render failed (exit {returncode}).\n\n{stderr.strip()}"
        if hints:
            body += "\n\nLikely cause:\n  " + "\n  ".join(hints)
        return body
