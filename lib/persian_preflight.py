"""Run Persian compose preparation without copying media or writing checkpoints."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import tempfile
from typing import Any
from tools.video.persian_compose import PersianCompose


class NoCopyPersianCompose(PersianCompose):
    @staticmethod
    def _stage(source: str | Path, staging: Path, name: str) -> str:
        del staging, name
        path = Path(source).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Persian preflight source does not exist: {path}")
        return str(path)


def extract_edit_decisions(payload: dict[str, Any]) -> dict[str, Any]:
    artifacts = payload.get("artifacts")
    if isinstance(artifacts, dict) and isinstance(artifacts.get("edit_decisions"), dict):
        payload = artifacts["edit_decisions"]
    if isinstance(payload.get("edit_decisions"), dict):
        payload = payload["edit_decisions"]
    if isinstance(payload.get("persian"), dict):
        return payload
    if "shots" in payload and "moments" in payload:
        return {"persian": payload}
    raise ValueError("Expected a checkpoint, edit_decisions artifact, or raw Persian block")


def summarize(props: dict[str, Any], attributions: list[str]) -> dict[str, Any]:
    design = props.get("design") or {}
    moments = []
    for moment in props.get("moments", []):
        geometry = moment.get("layoutGeometry") or {}
        rect = geometry.get("rect")
        if not isinstance(rect, dict):
            flat = {
                key: geometry[key]
                for key in ("x", "y", "w", "h")
                if isinstance(geometry.get(key), (int, float))
            }
            rect = flat or None
        moments.append({
            "id": moment.get("id"),
            "startSeconds": moment.get("startSeconds"),
            "endSeconds": moment.get("endSeconds"),
            "placement": geometry.get("placement"),
            "rect": rect,
            "subjectSafety": geometry.get("subjectSafety"),
            "geometry": geometry or None,
        })
    return {
        "ok": True,
        "profileVersion": design.get("profileVersion"),
        "layoutVersion": (design.get("resolved") or {}).get("layoutVersion"),
        "contentHash": design.get("contentHash"),
        "durationSeconds": props.get("durationSeconds"),
        "moments": moments,
        "watermarkPlanEntries": len(props.get("watermarkPlan") or []),
        "warnings": list((props.get("filmType") or {}).get("warnings") or []),
        "attributions": list(attributions),
        "mediaCopies": 0,
    }


def preflight_edit_decisions(payload: dict[str, Any]) -> dict[str, Any]:
    edit = extract_edit_decisions(payload)
    with tempfile.TemporaryDirectory(prefix="persian-preflight-") as temp:
        props, attributions = NoCopyPersianCompose()._build_props(
            edit["persian"], Path(temp), "preflight"
        )
    return summarize(props, attributions)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Persian geometry preflight with zero media copies")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        result = preflight_edit_decisions(payload)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"PREFLIGHT REFUSED:\n{exc}")
        return 2
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
