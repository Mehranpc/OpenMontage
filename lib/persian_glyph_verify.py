"""Film Type glyph order on lossless stills of the delivered composition (#252).

`glyph_order_check` compares each painted row with a HarfBuzz-shaped reference. On
frames pulled from the H.264 MP4 that signal is too weak to trust (see
`lib/persian_verify.py`), so this renders, per moment, two lossless PNG stills from the
exact props the delivery render used: the frame, and the same frame with only the glyphs
hidden (`verificationHideGlyphs`). Their difference is the painted ink.

Footage is replaced by one black clip. Shot timing and reviewed regions are untouched, so
placement is identical, and the check is about the glyphs, not the picture. Audio is
dropped for the same reason.

    python -m lib.persian_glyph_verify <project-dir> [--props PATH]
"""

from __future__ import annotations

import argparse
import json
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from lib.paths import REPO_ROOT
from lib.persian_film_verify import glyph_order_check

COMPOSER = REPO_ROOT / "remotion-composer"
SCRIPT = COMPOSER / "scripts" / "render-glyph-verification-stills.mjs"
FPS = 30


def stable_frame(moment: dict[str, Any], layout: dict[str, Any], motion: dict[str, Any]) -> tuple[int, list[dict]]:
    """The latest fully-arrived frame of a moment, and the rows painted on it."""
    start, end = float(moment["startSeconds"]), float(moment["endSeconds"])
    local = max(0.0, (end - start) - float(motion.get("exitSeconds", 0.22)) - 0.1)
    rows = [row for row in layout.get("rows") or [] if row.get("role") != "brand"]
    if (moment.get("presentation") or {}).get("sequenceMode") == "replace" and rows:
        shown = max(float(row.get("revealAfterSeconds") or 0.0) for row in rows
                    if float(row.get("revealAfterSeconds") or 0.0) <= local + 1e-9)
        rows = [row for row in rows if float(row.get("revealAfterSeconds") or 0.0) == shown]
    return int(round((start + local) * FPS)), rows


def _black_clip(path: Path, seconds: float, fmt: str) -> None:
    size = "1080x1920" if fmt == "vertical" else "1920x1080"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=black:s={size}:r={FPS}",
         "-t", f"{max(1.0, seconds):.3f}", "-c:v", "libx264", "-preset", "ultrafast",
         "-pix_fmt", "yuv420p", str(path)],
        check=True, timeout=120,
    )


def _geometry(rows: Any) -> list[tuple]:
    return [
        (row.get("text"), row.get("role"), round(float(row.get("fontSizePx") or 0), 2),
         round(float(row.get("baselinePx") or 0), 2), round(float(row.get("widthPx") or 0), 2))
        for row in rows or [] if isinstance(row, dict)
    ]


def verification_props(props: dict[str, Any], clip_rel: str) -> dict[str, Any]:
    out = json.loads(json.dumps(props))
    for shot in out.get("shots") or []:
        shot["source"] = clip_rel
        shot["sourceInSeconds"] = 0.0
    out["audio"] = {}
    # The shot source is part of the Film Type input hash, and a saved layout whose
    # inputs changed is refused as stale. Drop the saved measurement and let the still
    # pass re-measure. `verify_project` then requires the re-measured rows to equal the
    # delivered ones, so the check still runs on the delivered geometry.
    for key in ("filmType", "watermarkPlan", "watermarkPlanMeasured", "watermarkDiagnostics"):
        out.pop(key, None)
    return out


def verify_project(
    project: Path, props_path: Path | None = None, *, reference_rows=None,
) -> dict[str, Any]:
    """`reference_rows(moment_id, rows) -> rows` lets a test corrupt only the reference."""
    props_path = props_path or project / "renders" / "candidate.mp4.props.json"
    props = json.loads(props_path.read_text(encoding="utf-8"))
    if (props.get("design") or {}).get("profile") != "film-type" or not props.get("filmType"):
        raise ValueError("glyph verification needs prepared Film Type props")
    motion = dict(((props.get("design") or {}).get("resolved") or {}).get("motion") or {})
    run_id = secrets.token_hex(4)
    public = COMPOSER / "public" / "persian" / f"glyph-verify-{run_id}"
    public.mkdir(parents=True, exist_ok=True)
    try:
        _black_clip(public / "black.mp4", float(props["durationSeconds"]) + 1.0, props["format"])
        vprops = verification_props(props, f"persian/glyph-verify-{run_id}/black.mp4")
        moments = {m["id"]: m for m in props.get("moments") or []}
        plan = {mid: stable_frame(moments[mid], layout, motion)
                for mid, layout in props["filmType"]["moments"].items() if mid in moments}
        with tempfile.TemporaryDirectory(prefix="glyph-verify-") as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "props.json").write_text(json.dumps(vprops, ensure_ascii=False), encoding="utf-8")
            (tmp_path / "expected_rows.json").write_text(json.dumps(
                {mid: layout.get("rows") for mid, layout in props["filmType"]["moments"].items()},
                ensure_ascii=False), encoding="utf-8")
            (tmp_path / "request.json").write_text(json.dumps(
                {"frames": [{"momentId": mid, "frame": frame} for mid, (frame, _) in plan.items()]}),
                encoding="utf-8")
            done = subprocess.run(
                ["node", str(SCRIPT), str(tmp_path / "props.json"), str(tmp_path / "request.json"),
                 str(tmp_path / "stills")],
                cwd=COMPOSER, capture_output=True, text=True, timeout=1800,
            )
            if done.returncode != 0:
                raise RuntimeError((done.stderr or "")[-2000:])
            # The still pass re-runs Film Type measurement; use the layout it rendered.
            rendered = json.loads((tmp_path / "stills" / "stills.json").read_text(encoding="utf-8"))
            drift = [
                mid for mid, layout in props["filmType"]["moments"].items()
                if _geometry(layout.get("rows")) != _geometry((rendered.get("rows") or {}).get(mid))
            ]
            if drift:
                raise RuntimeError(
                    f"the verification pass measured different row geometry for {drift} than the "
                    "delivered props; this browser/font does not match the delivery render"
                )
            report: dict[str, Any] = {"props": str(props_path), "moments": {}}
            for mid, (frame, rows) in plan.items():
                still = np.asarray(Image.open(tmp_path / "stills" / f"{mid}-frame.png").convert("RGB"), dtype=float)
                bg = np.asarray(Image.open(tmp_path / "stills" / f"{mid}-background.png").convert("RGB"), dtype=float)
                checked = reference_rows(mid, json.loads(json.dumps(rows))) if reference_rows else rows
                layout = {**props["filmType"]["moments"][mid], "rows": checked}
                placement = str(layout.get("placement") or "")
                align = "center" if placement == "center" or placement.endswith("-center") else "right"
                report["moments"][mid] = {"frame": frame, **glyph_order_check(still, bg, layout, props, align=align)}
    finally:
        shutil.rmtree(public, ignore_errors=True)
    statuses = {m["status"] for m in report["moments"].values()}
    report["status"] = ("fail" if "fail" in statuses else
                        "not_checked" if (not statuses or "not_checked" in statuses) else "pass")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("project", type=Path)
    parser.add_argument("--props", type=Path, default=None)
    args = parser.parse_args(argv)
    report = verify_project(args.project.resolve(), args.props)
    out = args.project / "renders" / "glyph_order.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": str(out),
                      "moments": {k: v["status"] for k, v in report["moments"].items()}}, ensure_ascii=False))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
