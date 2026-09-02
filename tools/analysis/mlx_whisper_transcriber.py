"""Word-level Persian transcription via mlx-whisper (Apple Silicon).

## Why this exists alongside `transcriber`

`transcriber` wraps faster-whisper, which runs on the CPU through CTranslate2. It
works, but on an Apple-Silicon machine it leaves the GPU idle: a large model that
takes minutes on eight CPU cores takes a fraction of that through MLX, which
compiles to Metal.

More decisively for the Persian pipeline, karaoke subtitle emphasis is only
convincing when each word lights up on the syllable it is spoken. That needs
word-level timestamps from a model large enough to place Persian word boundaries
reliably, and `whisper-large-v3` is the smallest model that does so consistently
for Persian. Running large-v3 on the CPU for a 60-second narration is slow enough
that an agent would be tempted to fall back to a smaller model and accept mushy
timings — which is exactly the compromise this pipeline exists to avoid.

This tool is therefore a **new provider for the same capability**, not a
replacement. `transcriber` remains the portable default; this one is preferred
where it is available and declares itself unavailable everywhere else.

## Why it shells out instead of importing mlx_whisper

`mlx_whisper` lives in whichever interpreter has MLX installed, which is not
necessarily the interpreter running OpenMontage — MLX requires Apple Silicon and
a matching Python build, so pinning it as a hard dependency of this repo would
make `pip install -r requirements.txt` fail on every other platform. Locating an
interpreter that already has it, and calling it as a subprocess, keeps the
dependency optional without vendoring a second environment.

The search order for that interpreter is deliberately explicit rather than
"whatever `python3` resolves to": a shim on `PATH` may point at an interpreter
without MLX, and the resulting `ModuleNotFoundError` mid-render is far more
confusing than an upfront "unavailable".
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
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

#: Candidate interpreters that may carry `mlx_whisper`, in preference order.
#: An explicit override comes first so an operator can point at their own venv
#: without editing this list.
_INTERPRETER_ENV_VAR = "OPENMONTAGE_MLX_PYTHON"

#: Known local environments that ship MLX. These are checked before any PATH
#: lookup because a PATH `python3` is usually the system interpreter, which does
#: not have MLX and would produce a misleading import error at execute() time.
_CANDIDATE_INTERPRETERS: tuple[str, ...] = (
    str(Path.home() / "reels-videos-v2.1.6" / "scripts" / "venv" / "bin" / "python3"),
    str(Path.home() / ".venvs" / "mlx" / "bin" / "python3"),
)

#: Model repository. `large-v3` rather than `large-v3-turbo`: turbo is distilled
#: for speed and its word timestamps drift on Persian, which is precisely the
#: output this tool exists to produce.
_DEFAULT_MODEL = "mlx-community/whisper-large-v3-mlx"


def _probe_interpreter(python_path: str) -> bool:
    """True when `python_path` can import `mlx_whisper`.

    Imports rather than checking for the console script, because the console
    script can exist while the package is broken (a partially removed venv), and
    a broken import is what actually fails the render.
    """
    if not python_path or not Path(python_path).exists():
        return False
    try:
        completed = subprocess.run(
            [python_path, "-c", "import mlx_whisper"],
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def resolve_mlx_python() -> Optional[str]:
    """Locate an interpreter with `mlx_whisper`, or None.

    Order: explicit override, known local environments, then `PATH`. Every
    candidate is probed by import, so a hit is guaranteed usable.
    """
    override = os.environ.get(_INTERPRETER_ENV_VAR)
    if override and _probe_interpreter(override):
        return override

    for candidate in _CANDIDATE_INTERPRETERS:
        if _probe_interpreter(candidate):
            return candidate

    which = shutil.which("python3")
    if which and _probe_interpreter(which):
        return which

    return None


class MlxWhisperTranscriber(BaseTool):
    """Persian-first word-level transcription on Apple Silicon."""

    name = "mlx_whisper_transcriber"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "analysis"
    provider = "mlx_whisper"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    # Whisper decoding is sampled, so two runs of the same audio can differ in
    # wording at temperature > 0. The call below pins temperature to 0, which
    # makes it greedy and reproducible in practice — but the model still runs on
    # GPU kernels whose reduction order is not guaranteed stable across driver
    # versions, so REPRODUCIBLE would overclaim.
    determinism = Determinism.STOCHASTIC

    dependencies = ["python:mlx_whisper"]
    install_instructions = (
        "Requires Apple Silicon.\n"
        "  python3 -m venv ~/.venvs/mlx\n"
        "  ~/.venvs/mlx/bin/pip install mlx-whisper\n"
        f"Or point {_INTERPRETER_ENV_VAR} at an interpreter that already has it."
    )
    agent_skills = ["speech-to-text"]

    capabilities = [
        "transcribe",
        "word_timestamps",
        "language_detection",
    ]

    input_schema = {
        "type": "object",
        "required": ["input_path"],
        "properties": {
            "input_path": {
                "type": "string",
                "description": "Path to the audio or video file to transcribe",
            },
            "language": {
                "type": "string",
                "description": (
                    "ISO 639-1 code. Pass 'fa' for Persian rather than relying on "
                    "auto-detection: Persian is frequently detected as Arabic or "
                    "Urdu on short or music-heavy audio, and a wrong language "
                    "produces a plausible-looking transcript in the wrong script."
                ),
            },
            "model": {
                "type": "string",
                "description": "MLX model repository ID",
                "default": _DEFAULT_MODEL,
            },
            "initial_prompt": {
                "type": "string",
                "description": (
                    "Optional priming text. Useful for proper nouns and for "
                    "biasing spelling toward Persian orthography."
                ),
            },
            "output_dir": {
                "type": "string",
                "description": "Directory for the transcript JSON",
            },
        },
    }

    output_schema = {
        "type": "object",
        "properties": {
            # Same three keys as `transcriber`, so either provider can satisfy a
            # downstream stage without the stage branching on which one ran.
            "segments": {"type": "array"},
            "word_timestamps": {"type": "array"},
            "language": {"type": "string"},
            "duration_seconds": {"type": "number"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=4,
        # large-v3 in MLX holds roughly 3 GB of weights in unified memory.
        ram_mb=6144,
        vram_mb=0,  # Unified memory on Apple Silicon; not separately allocated.
        disk_mb=3200,
        network_required=False,  # After the first model download.
    )

    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["MemoryError"])
    resume_support = ResumeSupport.FROM_START
    idempotency_key_fields = ["input_path", "language", "model"]
    side_effects = ["writes transcript JSON to output_dir"]
    fallback = "transcriber"
    user_visible_verification = [
        "Play the audio and confirm the transcript text matches what is said",
        "Check that word timestamps line up with the spoken words, not just the segments",
    ]

    def get_status(self) -> ToolStatus:
        return (
            ToolStatus.AVAILABLE
            if resolve_mlx_python() is not None
            else ToolStatus.UNAVAILABLE
        )

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        """Roughly 5× faster than real time for large-v3 on an M-series chip."""
        return 45.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        input_path = Path(inputs["input_path"]).expanduser()
        if not input_path.exists():
            return ToolResult(success=False, error=f"Input file not found: {input_path}")

        python_path = resolve_mlx_python()
        if python_path is None:
            return ToolResult(
                success=False,
                error=(
                    "mlx_whisper is not importable from any known interpreter. "
                    + self.install_instructions
                ),
            )

        model = inputs.get("model", _DEFAULT_MODEL)
        language = inputs.get("language")
        initial_prompt = inputs.get("initial_prompt")
        output_dir = Path(inputs.get("output_dir", input_path.parent)).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)

        start = time.time()

        # Run the transcription through a small driver script rather than the
        # `mlx_whisper` CLI. The CLI writes its JSON next to the input and names
        # it after the input stem, which collides when two stages transcribe the
        # same file with different settings; calling the Python API lets the
        # output path and every decoding parameter be stated explicitly.
        with tempfile.TemporaryDirectory(prefix="mlx-whisper-") as tmp:
            payload_path = Path(tmp) / "result.json"
            driver = _DRIVER_TEMPLATE
            request = {
                "audio": str(input_path),
                "model": model,
                "language": language,
                "initial_prompt": initial_prompt,
                "out": str(payload_path),
            }

            try:
                completed = self.run_command(
                    [python_path, "-c", driver, json.dumps(request)],
                    # A 10-minute ceiling. Long enough for a 10-minute narration
                    # at large-v3 speeds, short enough that a hung model download
                    # surfaces as a failure rather than an apparently stuck stage.
                    timeout=600,
                )
            except subprocess.TimeoutExpired:
                return ToolResult(
                    success=False,
                    error=(
                        "mlx_whisper timed out after 600s. If this is the first run, "
                        f"the model {model!r} may still be downloading — run it once "
                        "manually to warm the cache."
                    ),
                )

            if completed.returncode != 0:
                stderr = (completed.stderr or "").strip()
                return ToolResult(
                    success=False,
                    error=f"mlx_whisper failed (exit {completed.returncode}): {stderr[-800:]}",
                )

            if not payload_path.exists():
                return ToolResult(
                    success=False,
                    error="mlx_whisper reported success but produced no transcript JSON",
                )
            raw = json.loads(payload_path.read_text(encoding="utf-8"))

        segments, words = self._normalize(raw)
        detected_language = raw.get("language") or language or "unknown"
        duration = words[-1]["end"] if words else 0.0

        result_data = {
            "segments": segments,
            "word_timestamps": words,
            "language": detected_language,
            "duration_seconds": round(float(duration), 3),
            "model": model,
            "provider": self.provider,
        }

        output_path = output_dir / f"{input_path.stem}_mlx_transcript.json"
        output_path.write_text(
            json.dumps(result_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        return ToolResult(
            success=True,
            data=result_data,
            artifacts=[str(output_path)],
            duration_seconds=round(time.time() - start, 2),
            model=model,
        )

    @staticmethod
    def _normalize(raw: dict[str, Any]) -> tuple[list[dict], list[dict]]:
        """Convert mlx_whisper output to this repo's segment/word shape.

        mlx_whisper emits `{"word": " سلام", "start": …, "end": …}` with a leading
        space on each word (an artifact of how the tokenizer splits). That space
        is stripped here rather than downstream: a word carrying it fails every
        equality comparison against the same word from any other source, which
        silently breaks highlight matching.
        """
        segments: list[dict] = []
        flat_words: list[dict] = []

        for index, seg in enumerate(raw.get("segments") or []):
            seg_words: list[dict] = []
            for word in seg.get("words") or []:
                text = str(word.get("word", "")).strip()
                if not text:
                    continue
                entry = {
                    "word": text,
                    "start": round(float(word.get("start", 0.0)), 3),
                    "end": round(float(word.get("end", 0.0)), 3),
                    "probability": round(float(word.get("probability", 0.0)), 4),
                }
                seg_words.append(entry)
                flat_words.append(entry)

            segments.append(
                {
                    "id": seg.get("id", index),
                    "start": round(float(seg.get("start", 0.0)), 3),
                    "end": round(float(seg.get("end", 0.0)), 3),
                    "text": str(seg.get("text", "")).strip(),
                    "words": seg_words,
                }
            )

        return segments, flat_words


#: Driver executed inside the MLX interpreter.
#:
#: Kept as a string rather than a file on disk so the tool has no runtime data
#: dependency that could go missing, and so the exact decoding parameters are
#: visible next to the reasoning for them.
_DRIVER_TEMPLATE = r"""
import json, sys
import mlx_whisper

request = json.loads(sys.argv[1])

kwargs = {
    "path_or_hf_repo": request["model"],
    "word_timestamps": True,
    # Greedy decoding. The default is a temperature ladder that retries with
    # increasing randomness on low confidence, which makes the same audio
    # transcribe differently between runs — unusable when the timings are
    # baked into a rendered video that may need to be re-rendered.
    "temperature": 0.0,
    # Do not carry context between windows. On a 60-second narration the benefit
    # is small, and a hallucinated phrase in one window propagates into the next.
    "condition_on_previous_text": False,
}
if request.get("language"):
    kwargs["language"] = request["language"]
if request.get("initial_prompt"):
    kwargs["initial_prompt"] = request["initial_prompt"]

result = mlx_whisper.transcribe(request["audio"], **kwargs)

with open(request["out"], "w", encoding="utf-8") as handle:
    json.dump(result, handle, ensure_ascii=False)
"""
