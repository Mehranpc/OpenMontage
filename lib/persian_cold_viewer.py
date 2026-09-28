"""#323: the route to a context-isolated cold viewer for the rendered opening.

The authoring agent must not certify its own hook, and the user who approved the
script is not a cold viewer either. The cold viewer is a fresh reviewer (a new
sub-agent with no conversation context, or a person who has not seen the script)
that receives only what this module prints from the persisted cold-viewer input
artifact. Because the prompt is derived from that artifact alone, authoring
context cannot leak into it.

    python -m lib.persian_cold_viewer prompt <cold_viewer_review_input.json>
    python -m lib.persian_cold_viewer record <cold_viewer_review_input.json> --answer-json <answer.json>

`prompt` validates the artifact and prints the reviewer prompt. `record` validates
the reviewer's answer and prints the canonical `coldViewer` object, bound to the
artifact digest, for `hookQualityReview.coldViewer`.

One answer per input. `record` persists the first answer beside the artifact and
refuses a different second answer for the same digest: on the 2026-09-28 run the
reviewer reported unresolved referents and the agent re-worded the question and
asked fresh reviewers until one passed. A finding is revised by changing the
opening, which re-renders and so produces a new input and digest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from lib.persian_rendered_review import (
    PersianRenderedReviewError,
    validate_cold_viewer_review_input,
)

ANSWER_FIELDS = ("inferredTopic", "inferredClaim", "continuationReason", "unresolvedReferents")


def load_review_input(path: Path) -> tuple[dict[str, Any], str]:
    """Read and validate a persisted cold-viewer input; return it with its digest."""
    raw = Path(path).read_bytes()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PersianRenderedReviewError("cold-viewer review input is unreadable JSON") from exc
    if not isinstance(payload, dict):
        raise PersianRenderedReviewError("cold-viewer review input must be a JSON object")
    validate_cold_viewer_review_input(payload, candidate_sha256=str(payload.get("candidateSha256") or ""))
    return payload, hashlib.sha256(raw).hexdigest()


def _dimensions(path: str) -> str:
    try:
        from PIL import Image

        with Image.open(path) as image:
            return f" ({image.width}x{image.height})"
    except Exception:
        return ""


def reviewer_prompt(payload: Mapping[str, Any], digest: str) -> str:
    """The only text a cold viewer receives. Built from the validated artifact alone."""
    evidence = payload["openingEvidence"]
    missing = [item for item in evidence.get("framePaths") or [] if not Path(item).is_file()]
    if missing:
        raise PersianRenderedReviewError("cold-viewer frames are missing on disk: " + ", ".join(missing))
    lines = [
        "You are a cold viewer. You know nothing about this video beyond what is listed here.",
        "Do not read any other file, script, plan or conversation. Look only at the media below,",
        "as a viewer scrolling past with the sound off.",
        "",
    ]
    if "startSeconds" in evidence and "endSeconds" in evidence:
        lines.append(f"Opening interval: {evidence['startSeconds']}s to {evidence['endSeconds']}s, muted.")
    for frame in evidence.get("framePaths") or []:
        lines.append(f"Frame: {frame}{_dimensions(frame)}")
    if evidence.get("excerptPath"):
        lines.append(f"Muted excerpt: {evidence['excerptPath']}")
    lines += [
        "",
        "View every frame at its native resolution (open the file itself; do not judge",
        "from a downscaled thumbnail). Small text you cannot read at native size counts.",
        "",
        *payload["instructions"],
        "",
        "Answer with one JSON object and nothing else:",
        json.dumps(
            {
                "inferredTopic": "what this opening is about, one phrase",
                "inferredClaim": "the claim or question it puts to you",
                "continuationReason": "what would make you keep watching; empty if nothing",
                "unresolvedReferents": ["each word or sign whose meaning is unclear; [] if none"],
                "reviewInputSha256": digest,
            },
            ensure_ascii=False,
            indent=2,
        ),
    ]
    return "\n".join(lines) + "\n"


def cold_viewer_record(answer: Mapping[str, Any], digest: str) -> dict[str, Any]:
    """Validate a reviewer answer and return the canonical `coldViewer` evidence."""
    if not isinstance(answer, Mapping):
        raise PersianRenderedReviewError("cold-viewer answer must be a JSON object")
    missing = [field for field in ANSWER_FIELDS if field not in answer]
    if missing:
        raise PersianRenderedReviewError("cold-viewer answer is missing: " + ", ".join(missing))
    extras = sorted(set(answer) - set(ANSWER_FIELDS) - {"reviewInputSha256"})
    if extras:
        raise PersianRenderedReviewError("cold-viewer answer has unsupported fields: " + ", ".join(extras))
    if str(answer.get("reviewInputSha256") or digest) != digest:
        raise PersianRenderedReviewError(
            "cold-viewer answer was given for a different review input (reviewInputSha256 mismatch)"
        )
    unresolved = answer["unresolvedReferents"]
    if not isinstance(unresolved, list) or any(not isinstance(item, str) for item in unresolved):
        raise PersianRenderedReviewError("cold-viewer unresolvedReferents must be an array of strings")
    for field in ANSWER_FIELDS[:3]:
        if not isinstance(answer[field], str):
            raise PersianRenderedReviewError(f"cold-viewer {field} must be a string")
    return {
        "evidenceSource": "rendered_opening_only",
        "contextIsolated": True,
        "inferredTopic": answer["inferredTopic"].strip(),
        "inferredClaim": answer["inferredClaim"].strip(),
        "continuationReason": answer["continuationReason"].strip(),
        "unresolvedReferents": [item.strip() for item in unresolved if item.strip()],
        "reviewInputSha256": digest,
    }


def answer_path(review_input: Path) -> Path:
    return Path(review_input).with_name(Path(review_input).stem + ".answer.json")


def persist_answer(review_input: Path, record: Mapping[str, Any]) -> Path:
    """Store the first answer for this input; refuse a different one later."""
    target = answer_path(review_input)
    if target.exists():
        previous = json.loads(target.read_text(encoding="utf-8"))
        if previous != dict(record):
            raise PersianRenderedReviewError(
                "a cold-viewer answer for this review input is already recorded; its findings stand. "
                "Revise the opening and re-render (a new input and digest) instead of asking again"
            )
        return target
    target.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="persian-cold-viewer")
    sub = parser.add_subparsers(dest="command", required=True)
    prompt = sub.add_parser("prompt", help="print the isolated reviewer prompt")
    prompt.add_argument("review_input", type=Path)
    record = sub.add_parser("record", help="validate an answer and print coldViewer evidence")
    record.add_argument("review_input", type=Path)
    record.add_argument("--answer-json", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        payload, digest = load_review_input(args.review_input)
        if args.command == "prompt":
            sys.stdout.write(reviewer_prompt(payload, digest))
            return 0
        try:
            answer = json.loads(args.answer_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PersianRenderedReviewError("cold-viewer answer is unreadable JSON") from exc
        record_obj = cold_viewer_record(answer, digest)
        persist_answer(args.review_input, record_obj)
        print(json.dumps(record_obj, ensure_ascii=False, indent=2))
        return 0
    except (PersianRenderedReviewError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
