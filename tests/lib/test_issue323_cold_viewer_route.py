"""#323: opening_review names the route to an isolated cold viewer.

On the 2026-09-28 Mac run the authoring agent (rightly) refused to self-certify the
cold-viewer review and asked the user, who approved the script and is not cold
either. The helper prints the reviewer prompt from the persisted artifact alone and
turns the answer into digest-bound `coldViewer` evidence the workflow accepts.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from lib.persian_cold_viewer import cold_viewer_record, load_review_input, main, reviewer_prompt
from lib.persian_rendered_review import PersianRenderedReviewError, build_cold_viewer_review_input

SHA = "a" * 64
ROOT = Path(__file__).resolve().parents[2]


def _artifact(tmp_path: Path, **extra) -> Path:
    from PIL import Image

    frames = []
    for index in range(2):
        frame = tmp_path / f"f{index}.png"
        Image.new("RGB", (1080, 1920)).save(frame)
        frames.append(str(frame))
    payload = build_cold_viewer_review_input(
        candidate_sha256=SHA,
        opening_evidence={"framePaths": frames, "startSeconds": 0.0, "endSeconds": 5.0},
    )
    payload.update(extra)
    path = tmp_path / "cold_viewer_review_input.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _answer(digest: str) -> dict:
    return {
        "inferredTopic": "پیام دادن بعد از قرار اول",
        "inferredClaim": "الان پیام بدهم یا صبر کنم؟",
        "continuationReason": "می‌خواهم جواب را بدانم",
        "unresolvedReferents": [],
        "reviewInputSha256": digest,
    }


def test_prompt_carries_only_the_artifact_evidence_and_its_digest(tmp_path: Path) -> None:
    path = _artifact(tmp_path)
    payload, digest = load_review_input(path)
    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()
    prompt = reviewer_prompt(payload, digest)
    assert "f0.png (1080x1920)" in prompt and "f1.png" in prompt and digest in prompt
    assert "native resolution" in prompt
    assert "script" in prompt.lower()  # told not to read one, and given none


def test_prompt_refuses_frames_missing_on_disk(tmp_path: Path) -> None:
    path = _artifact(tmp_path)
    payload, digest = load_review_input(path)
    (tmp_path / "f1.png").unlink()
    with pytest.raises(PersianRenderedReviewError, match="missing on disk"):
        reviewer_prompt(payload, digest)


def test_an_artifact_carrying_authoring_context_is_refused(tmp_path: Path) -> None:
    path = _artifact(tmp_path, approvedScript="بعد از یه قرار خوب...")
    with pytest.raises(PersianRenderedReviewError, match="authoring context"):
        load_review_input(path)


def test_answer_becomes_context_isolated_evidence_bound_to_the_digest(tmp_path: Path) -> None:
    _, digest = load_review_input(_artifact(tmp_path))
    record = cold_viewer_record(_answer(digest), digest)
    assert record["contextIsolated"] is True
    assert record["evidenceSource"] == "rendered_opening_only"
    assert record["reviewInputSha256"] == digest
    from lib.persian_rendered_review import _validate_cold_viewer

    assert _validate_cold_viewer({"coldViewer": record}) is True


def test_answer_for_another_input_or_with_extra_fields_is_refused(tmp_path: Path) -> None:
    _, digest = load_review_input(_artifact(tmp_path))
    with pytest.raises(PersianRenderedReviewError, match="different review input"):
        cold_viewer_record(_answer("b" * 64), digest)
    with pytest.raises(PersianRenderedReviewError, match="unsupported"):
        cold_viewer_record({**_answer(digest), "contextIsolated": True}, digest)


def test_cli_prompt_and_record(tmp_path: Path, capsys) -> None:
    path = _artifact(tmp_path)
    assert main(["prompt", str(path)]) == 0
    assert "cold viewer" in capsys.readouterr().out
    _, digest = load_review_input(path)
    answer = tmp_path / "answer.json"
    answer.write_text(json.dumps(_answer(digest), ensure_ascii=False), encoding="utf-8")
    assert main(["record", str(path), "--answer-json", str(answer)]) == 0
    assert json.loads(capsys.readouterr().out)["reviewInputSha256"] == digest


def test_skill_names_the_route() -> None:
    text = (ROOT / "skills/persian-video/persian-final-review.md").read_text(encoding="utf-8")
    assert "python -m lib.persian_cold_viewer prompt" in text
    assert "not a cold viewer" in text


def test_a_second_different_answer_for_the_same_input_is_refused(tmp_path: Path, capsys) -> None:
    """The 2026-09-28 run re-asked reviewers until the unresolved referents went away."""
    path = _artifact(tmp_path)
    _, digest = load_review_input(path)
    first = tmp_path / "first.json"
    first.write_text(json.dumps({**_answer(digest), "unresolvedReferents": ["گیرندهٔ پیام"]}, ensure_ascii=False), encoding="utf-8")
    assert main(["record", str(path), "--answer-json", str(first)]) == 0
    assert main(["record", str(path), "--answer-json", str(first)]) == 0  # idempotent
    second = tmp_path / "second.json"
    second.write_text(json.dumps(_answer(digest), ensure_ascii=False), encoding="utf-8")
    capsys.readouterr()
    assert main(["record", str(path), "--answer-json", str(second)]) == 1
    assert "already recorded" in capsys.readouterr().err
