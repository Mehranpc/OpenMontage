"""Canonical deterministic mastering for Persian final candidates.

The candidate identity is minted only after mastering is complete. Safe renders are
reused byte-for-byte; unsafe renders are mastered once and described by a durable
sidecar so retries are idempotent.
"""
from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping

from lib.persian_rendered_review import measure_rendered_audio_output

MASTERING_POLICY_VERSION = "1.0"
MASTER_TARGET_LUFS = -16.0
MASTER_MIN_LUFS = -20.0
MASTER_MAX_LUFS = -9.0
MASTER_TRUE_PEAK_DBFS = -1.5
MASTER_LRA = 7.0
MASTER_TOLERANCE_DB = 0.05


class PersianFinalizationError(RuntimeError):
    """Raised when canonical mastering cannot produce a policy-safe candidate."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def mastering_policy() -> dict[str, Any]:
    return {
        "version": MASTERING_POLICY_VERSION,
        "targetIntegratedLufs": MASTER_TARGET_LUFS,
        "acceptedIntegratedLufs": [MASTER_MIN_LUFS, MASTER_MAX_LUFS],
        "truePeakCeilingDbfs": MASTER_TRUE_PEAK_DBFS,
        "loudnessRangeLu": MASTER_LRA,
        "videoPolicy": "copy",
        "audioPolicy": "loudnorm-if-required",
    }


def _finite_number(value: object, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
        raise PersianFinalizationError(f"{label} must be a finite number")
    return float(value)


def _measurement_passes(measurement: Mapping[str, Any]) -> bool:
    loudness = _finite_number(measurement.get("outputIntegratedLufs"), "integrated loudness")
    peak = _finite_number(measurement.get("truePeakDbfs"), "true peak")
    return (
        MASTER_MIN_LUFS <= loudness <= MASTER_MAX_LUFS
        and peak <= MASTER_TRUE_PEAK_DBFS + MASTER_TOLERANCE_DB
    )


def _run_ffmpeg_master(source: Path, output: Path, policy: Mapping[str, Any]) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise PersianFinalizationError("ffmpeg is required for canonical mastering")
    output.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
            "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy",
            "-af", (
                f"loudnorm=I={policy['targetIntegratedLufs']}:"
                f"TP={policy['truePeakCeilingDbfs']}:LRA={policy['loudnessRangeLu']}"
            ),
            "-ar", "48000", "-c:a", "aac", "-b:a", "192k", str(output),
        ],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise PersianFinalizationError(
            "canonical mastering failed" + (f": {completed.stderr.strip()}" if completed.stderr else "")
        )


def _sidecar_path(output: Path) -> Path:
    return output.with_suffix(output.suffix + ".mastering.json")


def _load_reusable_master(source: Path, output: Path, policy: Mapping[str, Any]) -> dict[str, Any] | None:
    sidecar = _sidecar_path(output)
    if not output.is_file() or not sidecar.is_file():
        return None
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    input_sha = sha256_file(source)
    candidate_sha = sha256_file(output)
    if (
        data.get("policyVersion") != policy["version"]
        or data.get("inputSha256") != input_sha
        or data.get("candidateSha256") != candidate_sha
    ):
        return None
    return data


def master_final_candidate(
    source: Path,
    output: Path,
    *,
    measure: Callable[[Path], Mapping[str, Any]] = measure_rendered_audio_output,
    run_master: Callable[[Path, Path, Mapping[str, Any]], None] = _run_ffmpeg_master,
) -> dict[str, Any]:
    """Return the only candidate identity eligible for downstream final review.

    If the render already satisfies final audio policy its bytes are canonical and
    are not re-encoded. Otherwise mastering writes ``output`` first; only after the
    mastered bytes are remeasured is ``candidateSha256`` produced.
    """
    source = source.expanduser().resolve()
    output = output.expanduser().resolve()
    if not source.is_file():
        raise PersianFinalizationError(f"render candidate does not exist: {source}")
    policy = mastering_policy()
    input_sha = sha256_file(source)
    initial = dict(measure(source))
    initial["candidateSha256"] = input_sha

    if _measurement_passes(initial):
        return {
            "policyVersion": policy["version"],
            "inputPath": str(source),
            "inputSha256": input_sha,
            "candidatePath": str(source),
            "candidateSha256": input_sha,
            "reencoded": False,
            "reused": True,
            "outputIntegratedLufs": _finite_number(initial.get("outputIntegratedLufs"), "integrated loudness"),
            "truePeakDbfs": _finite_number(initial.get("truePeakDbfs"), "true peak"),
        }

    reusable = _load_reusable_master(source, output, policy)
    if reusable is not None:
        measured = dict(measure(output))
        if _measurement_passes(measured):
            return {
                **reusable,
                "reencoded": True,
                "reused": True,
                "outputIntegratedLufs": _finite_number(measured.get("outputIntegratedLufs"), "integrated loudness"),
                "truePeakDbfs": _finite_number(measured.get("truePeakDbfs"), "true peak"),
            }

    if output == source:
        raise PersianFinalizationError("unsafe render must be mastered to a distinct path")
    run_master(source, output, policy)
    if not output.is_file():
        raise PersianFinalizationError("mastering command did not create its declared output")
    measured = dict(measure(output))
    if not _measurement_passes(measured):
        raise PersianFinalizationError(
            "mastered candidate still violates integrated-loudness or true-peak policy"
        )
    candidate_sha = sha256_file(output)
    result = {
        "policyVersion": policy["version"],
        "inputPath": str(source),
        "inputSha256": input_sha,
        "candidatePath": str(output),
        "candidateSha256": candidate_sha,
        "reencoded": True,
        "reused": False,
        "outputIntegratedLufs": _finite_number(measured.get("outputIntegratedLufs"), "integrated loudness"),
        "truePeakDbfs": _finite_number(measured.get("truePeakDbfs"), "true peak"),
    }
    sidecar = _sidecar_path(output)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    temporary = sidecar.with_suffix(sidecar.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(sidecar)
    result["sidecarPath"] = str(sidecar)
    result["sidecarSha256"] = sha256_file(sidecar)
    return result


__all__ = [
    "MASTERING_POLICY_VERSION", "MASTER_TARGET_LUFS", "MASTER_TRUE_PEAK_DBFS",
    "PersianFinalizationError", "mastering_policy", "master_final_candidate", "sha256_file",
]
