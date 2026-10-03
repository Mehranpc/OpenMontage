"""Human time-range revision for the v3 staged pipeline (#387 increment 5).

The only backward path of v3. A human reviewer names a time range of the current
candidate; it expands to the footage events it overlaps (footage is per event).
Only those events are re-acquired; narration and timing (stage 0) stay locked, and
every footage event outside the range must keep byte-identical manifest evidence
when the new footage lock is written. The rendered frames outside the range are
compared with the previous candidate by decoded-frame MD5 before the new candidate
may stop for human review again.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping, Sequence

REVISION_DIR = "revisions"
SCHEMA = "openmontage.range_revision.v1"
#: Frames at each range edge excluded from the outside-range proof (cut alignment).
EDGE_GUARD_FRAMES = 2


class RangeRevisionError(ValueError):
    """A time-range revision request or proof is invalid."""


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def footage_event_spans(requirements: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Locked timeline position of every footage event, from the stage-0 plan order."""
    cursor = 0.0
    spans: list[dict[str, Any]] = []
    for row in requirements:
        try:
            duration = float(row.get("duration_seconds") or 0.0)
        except (TypeError, ValueError) as exc:
            raise RangeRevisionError("locked plan has a non-numeric event duration") from exc
        if duration <= 0:
            raise RangeRevisionError("locked plan has an event without a positive duration")
        event_id = row.get("visual_event_id")
        if event_id:
            spans.append({"visualEventId": str(event_id), "startSeconds": round(cursor, 6),
                          "endSeconds": round(cursor + duration, 6)})
        cursor += duration
    return spans


def events_in_range(spans: Sequence[Mapping[str, Any]], start: float, end: float) -> list[str]:
    if not (end > start >= 0):
        raise RangeRevisionError("a revision range needs 0 <= --from < --to")
    total = max((float(span["endSeconds"]) for span in spans), default=0.0)
    if start >= total:
        raise RangeRevisionError(f"--from {start} is outside the locked timeline (0-{total}s)")
    hit = [str(span["visualEventId"]) for span in spans
           if float(span["startSeconds"]) < end and float(span["endSeconds"]) > start]
    if not hit:
        raise RangeRevisionError("the range overlaps no footage event")
    return hit


def expanded_range(spans: Sequence[Mapping[str, Any]], events: Sequence[str]) -> dict[str, float]:
    chosen = [span for span in spans if span["visualEventId"] in set(events)]
    return {"startSeconds": min(float(s["startSeconds"]) for s in chosen),
            "endSeconds": max(float(s["endSeconds"]) for s in chosen)}


def manifest_event_digests(manifest: Mapping[str, Any]) -> dict[str, str]:
    """SHA-256 of each event's manifest rows (the footage evidence that must not move)."""
    rows: dict[str, list[Any]] = {}
    for row in manifest.get("assets") or []:
        if isinstance(row, Mapping) and row.get("visual_event_id"):
            rows.setdefault(str(row["visual_event_id"]), []).append(dict(row))
    return {event: _digest(sorted(items, key=_digest)) for event, items in sorted(rows.items())}


def outside_changes(before: Mapping[str, str], after: Mapping[str, str], revised: Sequence[str]) -> list[str]:
    keep = set(before) - set(revised)
    return sorted(event for event in keep if after.get(event) != before.get(event))


def revision_root(project_dir: Path) -> Path:
    from lib.persian_stage_locks import LOCK_DIR

    return Path(project_dir) / LOCK_DIR / REVISION_DIR


def list_revisions(project_dir: Path) -> list[dict[str, Any]]:
    root = revision_root(project_dir)
    if not root.is_dir():
        return []
    records = []
    for path in sorted(root.glob("rev-*/revision.json")):
        records.append(json.loads(path.read_text(encoding="utf-8")))
    return sorted(records, key=lambda item: int(item["revision"]))


def active_revision(project_dir: Path) -> dict[str, Any] | None:
    open_ = [item for item in list_revisions(project_dir) if item.get("status") != "closed"]
    if len(open_) > 1:
        raise RangeRevisionError("more than one open range revision")
    return open_[0] if open_ else None


def write_revision(project_dir: Path, record: Mapping[str, Any]) -> Path:
    path = revision_root(project_dir) / f"rev-{int(record['revision']):03d}" / "revision.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(dict(record), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def keep_previous_candidate(project_dir: Path, revision: int, candidate: Path) -> Path:
    target = revision_root(project_dir) / f"rev-{revision:03d}" / "previous-candidate.mp4"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(candidate, target)
    return target


def _frame_md5(path: Path) -> list[tuple[float, str]]:
    try:
        done = subprocess.run(
            ["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-map", "0:v:0", "-f", "framemd5", "-"],
            capture_output=True, text=True, timeout=1800, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RangeRevisionError(f"cannot decode {path.name}: {exc}") from exc
    if done.returncode != 0:
        raise RangeRevisionError(f"cannot decode {path.name}: {(done.stderr or '')[-400:]}")
    base = Fraction(1, 1)
    frames: list[tuple[float, str]] = []
    for line in done.stdout.splitlines():
        if line.startswith("#tb 0:"):
            num, den = line.split(":", 1)[1].strip().split("/")
            base = Fraction(int(num), int(den))
            continue
        if not line or line.startswith("#"):
            continue
        parts = [item.strip() for item in line.split(",")]
        if len(parts) >= 6 and parts[0] == "0":
            frames.append((float(int(parts[2]) * base), parts[5]))
    return frames


def outside_range_frame_proof(
    previous: Path, candidate: Path, start: float, end: float, *, fps: float = 30.0,
) -> dict[str, Any]:
    """Decoded frames outside [start, end] (minus an edge guard) must be identical."""
    before, after = _frame_md5(Path(previous)), _frame_md5(Path(candidate))
    guard = EDGE_GUARD_FRAMES / float(fps)
    outside = lambda t: t < start - guard or t >= end + guard  # noqa: E731
    left = [(round(t, 4), md5) for t, md5 in before if outside(t)]
    right = [(round(t, 4), md5) for t, md5 in after if outside(t)]
    mismatches = [t for (t, a), (_, b) in zip(left, right) if a != b]
    # A range that covers the whole timeline leaves nothing outside to compare;
    # that is recorded as a vacuous pass, but only when both sides decoded frames.
    passed = bool(before) and bool(after) and len(left) == len(right) and not mismatches
    return {
        "method": "decoded_frame_md5",
        "range": {"startSeconds": start, "endSeconds": end, "edgeGuardFrames": EDGE_GUARD_FRAMES},
        "framesCompared": min(len(left), len(right)),
        "frameCountsEqual": len(left) == len(right),
        "mismatchedFrameTimes": mismatches[:20],
        "mismatchCount": len(mismatches),
        "vacuous": not left and not right,
        "status": "pass" if passed else "fail",
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }
