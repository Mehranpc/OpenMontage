"""Explicit Film Type browser prepass; no optional/estimated measurement fallback.

Uses the Remotion packages already installed for the Persian composer. Does not
install dependencies, call providers, replace narration, or change render runtime.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
from typing import Any


def prepare_film_type_props(props: dict[str, Any], composer: Path) -> dict[str, Any]:
    """Return props measured by the same browser/renderer code that will paint.

    Input/output and bundle files are temporary. Media remains in the staging
    directory for the subsequent render; normal cleanup is still owned by the
    compose tool, unless keep_staged_assets was explicitly requested.
    """
    script = composer / "scripts" / "prepare-persian-film-type.mjs"
    if not script.is_file():
        raise ValueError("Film Type preparation script is missing; apply the complete patch.")
    with tempfile.TemporaryDirectory(prefix="persian-film-type-") as temp:
        directory = Path(temp)
        source = directory / "input.json"
        result = directory / "measured.json"
        source.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
        try:
            process = subprocess.run(
                ["node", str(script), str(source), str(result)],
                cwd=composer, capture_output=True, text=True, timeout=180,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f"Film Type browser preparation could not finish: {exc}") from exc
        if process.returncode != 0 or not result.is_file():
            log = process.stderr or process.stdout or "no output"
            detail = log[-4000:]
            for line in log.splitlines():
                if line.startswith("OPENMONTAGE_PREPASS_ERROR="):
                    try:
                        detail = json.loads(line.split("=", 1)[1])["message"]
                        break
                    except (ValueError, KeyError, TypeError):
                        pass
            raise ValueError(
                "Film Type requires real browser font measurement; no estimated "
                "or Legacy fallback was used. Browser preparation failed:\n" + detail
            )
        try:
            prepared = json.loads(result.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise ValueError("Film Type preparation returned invalid JSON") from exc
        if not isinstance(prepared, dict):
            raise ValueError("Film Type preparation returned a non-object")
        measured = prepared.get("filmType")
        design = props.get("design") or {}
        expected_version = {"2.1.0": 1, "2.2.0": 2, "2.3.0": 3, "2.4.0": 4, "2.5.0": 5, "2.6.0": 6, "2.7.0": 7, "2.8.0": 8, "2.9.0": 9, "2.10.0": 10, "2.11.0": 11, "2.12.0": 12, "2.13.0": 13}.get(design.get("profileVersion"))
        if (expected_version is None or (design.get("resolved") or {}).get("layoutVersion") != expected_version
                or not isinstance(measured, dict) or type(measured.get("version")) is not int
                or measured["version"] != expected_version or not measured.get("inputHash")):
            raise ValueError("Film Type preparation did not return measured layout provenance")
        if prepared.get("watermarkPlanMeasured") is not True:
            raise ValueError("Film Type watermark planning was not completed")
        # The prepass may add geometry, never rewrite approved content or timing.
        additions = {"filmType", "watermarkPlan", "watermarkMeasurement", "watermarkPlanMeasured", "moments"}
        for key in (set(props) | set(prepared)) - additions:
            if prepared.get(key) != props.get(key):
                raise ValueError(f"Film Type preparation unexpectedly changed {key}")
        original = props.get("moments", [])
        output = prepared.get("moments", [])
        if len(original) != len(output):
            raise ValueError("Film Type preparation changed the moment count")
        derived = {"layoutGeometry", "stackHeightPx", "stackWidthPx"}
        for before, after in zip(original, output):
            if {k: v for k, v in before.items() if k not in derived} != {k: v for k, v in after.items() if k not in derived}:
                raise ValueError("Film Type preparation changed authored moment content")
        return prepared
