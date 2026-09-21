"""Shared effective typography plate windows for rendering and retention QA."""
from __future__ import annotations

from typing import Any


def derive_beat_windows(
    authored: list[dict[str, Any]], moments: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Derive each beat's plate windows from the typography inside it.

    A beat carries only id/startSeconds/endSeconds — no moment reference —
    so association is by time overlap: a beat owns exactly the moments its
    authored window overlaps. Owned moments that touch or overlap merge
    into one contiguous run; a gap between owned moments splits the beat
    into one window per run, so no plate ever covers a stretch with no
    typography on it. Moments keep their times (the sync gate owns them);
    the plate moves. Entrance/exit offsets are not subtracted: text is
    arriving or leaving during them, and a plate cut to an animation
    curve would flash footage mid-transition.

    A beat overlapping no moment is refused: an empty plate is near-black
    by design. Time freed when a plate shrinks holds neither footage nor
    beat; the pre-render coverage gate in `execute` refuses the run until
    the edit stage restores footage there.
    """
    derived: list[dict[str, Any]] = []
    for index, beat in enumerate(authored):
        beat_id = str(beat.get("id") or f"beat-{index + 1}")
        start = float(beat["startSeconds"])
        end = float(beat["endSeconds"])
        owned = sorted(
            (
                moment
                for moment in moments
                if float(moment["startSeconds"]) < end
                and float(moment["endSeconds"]) > start
            ),
            key=lambda moment: float(moment["startSeconds"]),
        )
        if not owned:
            raise ValueError(
                f"typographic beat {beat_id} ({start:.1f}-{end:.1f}s) "
                "overlaps no typographic moment. A plate with no typography "
                "is an empty near-black screen, so the render is refused "
                "rather than painting it. Either attach a moment to this "
                "stretch or restore a footage shot under it."
            )
        runs: list[list[dict[str, Any]]] = [[owned[0]]]
        for moment in owned[1:]:
            if float(moment["startSeconds"]) <= float(
                runs[-1][-1]["endSeconds"]
            ):
                runs[-1].append(moment)
            else:
                runs.append([moment])
        for run_index, run in enumerate(runs):
            # Split windows keep the authored id only when nothing split:
            # the composition keys each beat Sequence by id, and two
            # entries sharing one would collide there.
            run_id = (
                beat_id if len(runs) == 1 else f"{beat_id}-{run_index + 1}"
            )
            derived.append(
                {
                    "id": run_id,
                    "startSeconds": min(
                        float(moment["startSeconds"]) for moment in run
                    ),
                    "endSeconds": max(
                        float(moment["endSeconds"]) for moment in run
                    ),
                }
            )
    return derived

