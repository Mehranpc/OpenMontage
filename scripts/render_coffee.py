"""Render coffee-hormones-fa and verify it numerically.

Runs the real `PersianCompose` tool rather than calling Remotion directly, because the
tool is what a pipeline run uses: it gates the props, stages clips into
`remotion-composer/public/`, resolves them through `staticFile()`, writes the sidecar
SRT, and cleans the staging directory afterwards. A hand-rolled `npx remotion render`
would skip all of that and verify something the pipeline never produces.

Verification samples the middle of every moment and the middle of every gap, then
measures each with the instrument that suits it. Middles because the boundaries are
mid-animation — the scrim leads the type in and trails it out over `SCRIM.fadeFrames`,
so a frame near a boundary is a legitimate partial state that no threshold should judge.

**Moments and gaps are measured differently, and conflating them was a real bug.** A
moment frame has a scrim, so brightness separates type from footage and `measure_moment`
applies. A gap frame has none by design, so `ink_mask` sees raw footage and returns
31-99% "ink" — measuring a gap with the moment instrument produced a confident scrim
failure on a frame that was correctly empty. Gaps go to `check_gap_is_empty`, which uses
the accent's colour separation and works with nothing behind it.

The watermark is checked by ablation — a second short render with an empty watermark,
diffed against the first. It cannot be found in a single frame: white type at 0.6 opacity
composites to a value bright footage produces on its own.

Pass `--verify-only` to re-measure an existing `renders/final.mp4` without re-rendering.
The render costs about nine minutes and the disk here is at 99%, so the verification half
has to be runnable on its own.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lib.persian_verify import (  # noqa: E402
    WATERMARK_TOP_FRACTION,
    anchor_report,
    check_gap_is_empty,
    check_moment_arrangement,
    find_watermark,
    verify_frames,
)
from tools.video.persian_compose import PersianCompose  # noqa: E402

#: The project to render. The coffee fixtures moved between directories while the
#: pipeline was being rebuilt, and a hard-coded path kept rendering the *previous*
#: project's edit against the *current* one's narration — silently, because both
#: directories had an `artifacts/edit_decisions.json`. Selecting the target
#: explicitly (`--project name`, or the env var) makes the driver unable to fetch
#: the wrong edit by accident: a missing directory is an error, not a fallback.
DEFAULT_PROJECT = "coffee-hormones-fa"


def _project_root() -> Path:
    for index, arg in enumerate(sys.argv):
        if arg == "--project" and index + 1 < len(sys.argv):
            return REPO_ROOT / "projects" / sys.argv[index + 1]
    import os

    from_env = os.environ.get("PERSIAN_PROJECT")
    return REPO_ROOT / "projects" / (from_env or DEFAULT_PROJECT)


PROJECT = _project_root()
EDIT = PROJECT / "artifacts" / "edit_decisions.json"
OUTPUT = PROJECT / "renders" / "final.mp4"
FRAME_DIR = PROJECT / "renders" / "frames_verify"
FPS = 30

#: Frames of scrim fade at each end of a moment, from `SCRIM.fadeFrames` in `tokens.ts`.
#: A sampled frame must clear this margin from both boundaries or it is a partial state.
FADE_FRAMES = 10


def _frame(source: Path, index: int, target: Path) -> np.ndarray:
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error", "-i", str(source),
                "-vf", f"select=eq(n\\,{index})", "-vsync", "0", "-frames:v", "1",
                str(target),
            ],
            check=True,
        )
    with Image.open(target) as image:
        return np.asarray(image.convert("RGB")).astype(int)


def _gap_spans(moments: list[dict[str, Any]], duration: float) -> list[tuple[float, float]]:
    """Every stretch of runtime with no moment on it, including the head and the tail.

    All of them rather than the largest one, because "the gaps are empty" is a claim about
    the whole video and one sample cannot support it. Nine gaps cost nine PNGs.
    """
    ordered = sorted(moments, key=lambda moment: moment["startSeconds"])
    spans = [(0.0, ordered[0]["startSeconds"])]
    for earlier, later in zip(ordered, ordered[1:]):
        spans.append((earlier["endSeconds"], later["startSeconds"]))
    spans.append((ordered[-1]["endSeconds"], duration))
    return [(lo, hi) for lo, hi in spans if hi - lo > 2 * FADE_FRAMES / FPS]


def main() -> None:
    verify_only = "--verify-only" in sys.argv

    edit = json.loads(EDIT.read_text(encoding="utf-8"))
    persian = edit["persian"]
    fmt = persian["format"]

    if verify_only:
        if not OUTPUT.exists():
            print(f"--verify-only needs an existing render at {OUTPUT}")
            raise SystemExit(1)
        report_path = PROJECT / "artifacts" / "render_report.json"
        previous = json.loads(report_path.read_text(encoding="utf-8"))
        data = {
            key: previous[key]
            for key in (
                "output_path", "composition_id", "format", "duration_seconds",
                "moment_count", "shot_count", "text_coverage", "subtitle_path",
                "attributions",
            )
        }
        data["subtitle_advisories"] = previous.get("subtitle_advisories") or []
        print("=== render skipped (--verify-only) ===")
    else:
        print("=== render ===")
        result = PersianCompose().execute(
            {
                "edit_decisions": edit,
                "output_path": str(OUTPUT),
                # 16 because the scrim's soft gradient is exactly what a higher CRF
                # destroys first, and banding across a large wash is very visible.
                "crf": 16,
            }
        )
        if not result.success:
            print("FAILED:", result.error)
            raise SystemExit(1)
        data = dict(result.data or {})

    for key in (
        "output_path", "composition_id", "format", "duration_seconds",
        "moment_count", "shot_count", "text_coverage", "subtitle_path",
    ):
        print(f"  {key}: {data.get(key)}")
    if data.get("subtitle_advisories"):
        print("  subtitle advisories:", data["subtitle_advisories"])

    print("\n=== sample moment frames ===")
    moment_frames: list[tuple[str, np.ndarray]] = []
    for moment in persian["moments"]:
        index = int((moment["startSeconds"] + moment["endSeconds"]) / 2 * FPS)
        moment_frames.append(
            (moment["id"], _frame(OUTPUT, index, FRAME_DIR / f'{moment["id"]}.png'))
        )
        print(f'  {moment["id"]} frame {index}')

    print("\n=== verify_frames (moments) ===")
    summary = verify_frames(moment_frames, fmt=fmt)
    print(f"  passed: {summary['passed']}")
    for problem in summary["problems"]:
        print(f"  PROBLEM {problem}")

    kinds = {moment["id"]: moment["kind"] for moment in persian["moments"]}
    for label, _ in moment_frames:
        measurement = summary["frames"][label]
        print(
            f'  {label:10s} {kinds[label]:9s} ink {measurement["glyph_pixels"]:6d} '
            f'lines {measurement["line_count"]} '
            f'cols {measurement["glyph_columns"]} '
            f'anchor {measurement["worst_anchor_offset_px"]} '
            f'contrast {measurement["contrast_ratio"]}'
        )

    print("\n=== anchor_report ===")
    anchors = anchor_report(moment_frames, fmt=fmt)
    print(
        f'  {anchors["lines_measured"]} lines, median {anchors["median_offset_px"]}px, '
        f'worst {anchors["worst_offset_px"]}px against {anchors["tolerance_px"]}px'
    )

    print("\n=== gaps are empty ===")
    gap_problems: list[str] = []
    for lo, hi in _gap_spans(persian["moments"], persian["durationSeconds"]):
        index = int((lo + hi) / 2 * FPS)
        gap = check_gap_is_empty(
            _frame(OUTPUT, index, FRAME_DIR / f"gap-{index:05d}.png"), fmt
        )
        print(
            f'  {lo:6.2f}-{hi:6.2f}s frame {index:5d} accent '
            f'{gap["accent_fraction"]:.6f} passed={gap["passed"]}'
        )
        gap_problems.extend(f"gap at {index}: {problem}" for problem in gap["problems"])
    for problem in gap_problems:
        print(f"  PROBLEM {problem}")

    print("\n=== reading order ===")
    # Every moment, not one of them: under the segment model every kind carries an
    # accent hero, so the order check applies to statements too — an improvement on
    # the slot-model era, where only figures and terms had accent heroes and
    # statements could not be checked at all.
    order_problems: list[str] = []
    for moment in persian["moments"]:
        roles = [segment["role"] for segment in moment["segments"]]
        order = check_moment_arrangement(
            _frame(
                OUTPUT,
                int((moment["startSeconds"] + moment["endSeconds"]) / 2 * FPS),
                FRAME_DIR / f'{moment["id"]}.png',
            ),
            roles=roles,
            fmt=fmt,
        )
        print(
            f'  {moment["id"]} {moment["kind"]:9s} roles={"-".join(roles):24s} '
            f'passed={order.get("passed")}'
        )
        order_problems.extend(
            f'{moment["id"]}: {problem}' for problem in order.get("problems", [])
        )
    for problem in order_problems:
        print(f"  PROBLEM {problem}")

    print("\n=== watermark (ablation) ===")
    quiet_frame = int(0.10 * persian["durationSeconds"] * FPS)
    reference_output = PROJECT / "renders" / "no_watermark.mp4"
    painted_path = FRAME_DIR / "wm_painted.png"
    absent_path = FRAME_DIR / "wm_absent.png"
    mark: dict[str, Any] = {"found": False, "reason": "not attempted"}

    if verify_only and absent_path.exists():
        print("  reusing the ablation frame from the previous run")
        mark = find_watermark(
            _frame(OUTPUT, quiet_frame, painted_path),
            expected_top_fraction=WATERMARK_TOP_FRACTION[fmt]["quiet"],
            reference=_frame(absent_path, 0, absent_path),
        )
    else:
        reference_edit = {
            **edit,
            "persian": {**persian, "watermark": {"persianText": "", "latinText": ""}},
        }
        # A five-frame window inside the watermark's quiet phase, which runs to 20% of
        # the runtime. Rendering the whole video twice would cost another ~9 minutes and
        # 30MB for information five frames carry.
        reference_result = PersianCompose().execute(
            {
                "edit_decisions": reference_edit,
                "output_path": str(reference_output),
                "frames": f"{quiet_frame}-{quiet_frame + 4}",
                "crf": 16,
            }
        )
        if not reference_result.success:
            print("  reference render failed:", reference_result.error)
            mark = {"found": False, "reason": str(reference_result.error)}
        else:
            painted = _frame(OUTPUT, quiet_frame, painted_path)
            absent = _frame(reference_output, 0, absent_path)
            mark = find_watermark(
                painted,
                expected_top_fraction=WATERMARK_TOP_FRACTION[fmt]["quiet"],
                reference=absent,
            )
            reference_output.unlink(missing_ok=True)
    print(f"  {mark}")

    # The ablation pair is scaffolding for one measurement, not a deliverable, and the
    # disk here is at 99%. Removed after the mark is located so the frame directory holds
    # only the sampled moments and gaps.
    for path in (painted_path, absent_path):
        path.unlink(missing_ok=True)

    verified = bool(
        summary["passed"]
        and not gap_problems
        and not order_problems
        and mark.get("found")
        and not mark.get("clipped_at_edge")
    )

    worst_contrast = min(
        summary["frames"][label]["contrast_ratio"] for label, _ in moment_frames
    )

    report = {
        "version": "1.0",
        "outputs": [
            {
                "path": str(OUTPUT.relative_to(REPO_ROOT)),
                "format": "mp4",
                "codec": "h264",
                "audio_codec": "aac",
                "resolution": "1080x1920",
                "fps": FPS,
                "duration_seconds": data["duration_seconds"],
                "file_size_bytes": OUTPUT.stat().st_size,
                "platform_target": "generic",
            }
        ],
        "render_grammar": "persian-footage",
        "output_path": str(OUTPUT.relative_to(REPO_ROOT)),
        "composition_id": data["composition_id"],
        "format": data["format"],
        "duration_seconds": data["duration_seconds"],
        "moment_count": data["moment_count"],
        "shot_count": data["shot_count"],
        "text_coverage": data["text_coverage"],
        "subtitle_path": data.get("subtitle_path"),
        "subtitle_advisories": data.get("subtitle_advisories") or [],
        "attributions": data["attributions"],
        "persian_text_verified": verified,
        "verification_frames": sorted(
            str(path.relative_to(REPO_ROOT)) for path in FRAME_DIR.glob("*.png")
        ),
        "verification_notes": [
            f'anchor: {anchors["lines_measured"]} lines, median '
            f'{anchors["median_offset_px"]}px, worst {anchors["worst_offset_px"]}px '
            f'against a {anchors["tolerance_px"]}px tolerance',
            f'contrast: {worst_contrast}:1 at worst, against a 5.6:1 floor',
            "gaps: accent coverage under 0.03% on every sampled gap; a statement "
            "overrunning into a gap is not detectable in pixels and is not claimed",
            f'watermark: rows {mark.get("rows")}, columns {mark.get("columns")}, '
            f'{mark.get("ink_pixels")} ink px, located by ablation diff',
            "intra-word glyph order is not verified in pixels — see "
            "check_moment_arrangement's docstring and tests/contracts/"
            "test_persian_text_parity.py",
        ],
        # Music is now part of the deliverable, not an afterthought: the compose
        # tool refuses a narrated project without a bed or a recorded reason.
        "music_mixed": bool(persian.get("audio", {}).get("music")),
        "music_track": persian.get("musicTrack"),
    }
    target = PROJECT / "artifacts" / "render_report.json"
    target.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\nwrote {target.relative_to(REPO_ROOT)}")
    print(f"persian_text_verified: {verified}")


if __name__ == "__main__":
    main()
