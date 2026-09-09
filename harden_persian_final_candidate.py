from pathlib import Path

ROOT = Path.cwd()


def replace(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"marker missing in {path}: {old[:80]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace("lib/checkpoint.py", "import json\n", "import hashlib\nimport json\n")

helper = '''def _resolve_render_output_path(
    pipeline_dir: Path,
    project_id: str,
    reported_path: str,
) -> Path:
    """Resolve a report path without guessing between multiple existing files."""
    raw = Path(reported_path).expanduser()
    candidates = [raw] if raw.is_absolute() else [
        pipeline_dir / project_id / raw,
        Path(__file__).resolve().parent.parent / raw,
        Path.cwd() / raw,
    ]
    existing: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if resolved.is_file() and resolved not in existing:
            existing.append(resolved)
    if not existing:
        raise CheckpointValidationError(
            "FINAL CANDIDATE VIOLATION: the primary MP4 does not exist at the "
            f"reported path {reported_path!r}"
        )
    if len(existing) != 1:
        raise CheckpointValidationError(
            "FINAL CANDIDATE VIOLATION: the reported output path is ambiguous; "
            "record one stable absolute MP4 path"
        )
    return existing[0]


def _sha256_render_output(path: Path) -> str:
    """Hash the bytes and refuse a file that changes while it is being read."""
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat()
    fingerprint_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    fingerprint_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    if fingerprint_before != fingerprint_after:
        raise CheckpointValidationError(
            "FINAL CANDIDATE VIOLATION: the primary MP4 changed while its sha256 "
            "was being computed; render or hash it again"
        )
    return digest.hexdigest()


def _render_identity(
    report: dict[str, Any],
    pipeline_dir: Path,
    project_id: str,
) -> tuple[str, str]:
    """Return and verify the primary output path/digest approval identity."""
    outputs = report.get("outputs")
    if not isinstance(outputs, list) or not outputs or not isinstance(outputs[0], dict):
        raise CheckpointValidationError(
            "FINAL CANDIDATE VIOLATION: render_report.outputs[0] is required"
        )
    primary = outputs[0]
    path = str(primary.get("path") or "").strip()
    digest = str(primary.get("sha256") or "").strip().lower()
    if (
        not path
        or str(primary.get("format") or "").strip().lower() != "mp4"
        or len(digest) != 64
        or any(c not in "0123456789abcdef" for c in digest)
    ):
        raise CheckpointValidationError(
            "FINAL CANDIDATE VIOLATION: the primary output needs format='mp4', "
            "a path, and a 64-character sha256"
        )
    resolved_path = _resolve_render_output_path(pipeline_dir, project_id, path)
    actual_digest = _sha256_render_output(resolved_path)
    if actual_digest != digest:
        raise CheckpointValidationError(
            "FINAL CANDIDATE VIOLATION: outputs[0].sha256 does not match the "
            "exact file bytes at outputs[0].path"
        )
    return path, digest


def _validate_persian_compose_lifecycle(
    pipeline_dir: Path,
    project_id: str,
    stage: str,
    status: str,
    artifacts: dict[str, Any],
    human_approved: bool,
    metadata: Optional[dict],
) -> None:
    """Bind Persian approval to a prior awaiting-human candidate and its bytes."""
    if stage != "compose":
        return
    if human_approved and status != "completed":
        raise CheckpointValidationError(
            "APPROVAL PROVENANCE VIOLATION: human_approved=True is valid only "
            "when completing the compose stage"
        )
    if status not in {"awaiting_human", "completed"}:
        return

    # Let the generic manifest gate produce its established message when a
    # completion simply omitted human_approved=True.
    if status == "completed" and not human_approved:
        return

    report = artifacts.get("render_report")
    if not isinstance(report, dict):
        raise CheckpointValidationError(
            "FINAL CANDIDATE VIOLATION: Persian compose requires render_report"
        )
    identity = _render_identity(report, pipeline_dir, project_id)

    if status == "awaiting_human":
        if human_approved:
            raise CheckpointValidationError(
                "APPROVAL PROVENANCE VIOLATION: a final candidate cannot approve itself"
            )
        if (
            report.get("delivery_status") != "final_candidate"
            or report.get("human_visual_approval") is not False
            or report.get("persian_text_verified") is not False
        ):
            raise CheckpointValidationError(
                "FINAL CANDIDATE VIOLATION: awaiting_human requires "
                "delivery_status='final_candidate' and both approval booleans false"
            )
        return

    if (
        report.get("delivery_status") != "approved"
        or report.get("human_visual_approval") is not True
        or not isinstance(report.get("persian_text_verified"), bool)
    ):
        raise CheckpointValidationError(
            "APPROVAL PROVENANCE VIOLATION: approved compose completion requires "
            "delivery_status='approved', human_visual_approval=true, and an explicit "
            "persian_text_verified boolean"
        )

    previous_path = _checkpoint_path(pipeline_dir, project_id, "compose")
    try:
        previous = json.loads(previous_path.read_text(encoding="utf-8"))
        previous_report = previous["artifacts"]["render_report"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CheckpointValidationError(
            "APPROVAL TRANSITION VIOLATION: compose must first persist an "
            "awaiting_human final candidate"
        ) from exc
    if (
        previous.get("version") != "1.0"
        or previous.get("project_id") != project_id
        or previous.get("pipeline_type") != "persian-footage"
        or previous.get("stage") != "compose"
        or previous.get("status") != "awaiting_human"
        or previous.get("human_approval_required") is not True
        or previous.get("human_approved") is not False
    ):
        raise CheckpointValidationError(
            "APPROVAL TRANSITION VIOLATION: the prior compose checkpoint is not an "
            "unapproved awaiting_human candidate for this project"
        )
    if not isinstance(previous_report, dict):
        raise CheckpointValidationError(
            "APPROVAL TRANSITION VIOLATION: the prior render report is invalid"
        )
    if (
        previous_report.get("delivery_status") != "final_candidate"
        or previous_report.get("human_visual_approval") is not False
        or previous_report.get("persian_text_verified") is not False
    ):
        raise CheckpointValidationError(
            "APPROVAL TRANSITION VIOLATION: the prior render report is not a valid "
            "unapproved final candidate"
        )
    if _render_identity(previous_report, pipeline_dir, project_id) != identity:
        raise CheckpointValidationError(
            "APPROVAL TRANSITION VIOLATION: output path or sha256 changed after the "
            "candidate was shown; render a new candidate instead"
        )

    record = (metadata or {}).get("approval_record")
    if not isinstance(record, dict) or (
        record.get("source") != "explicit_user_response"
        or str(record.get("candidate_path") or "").strip() != identity[0]
        or str(record.get("candidate_sha256") or "").strip().lower() != identity[1]
    ):
        raise CheckpointValidationError(
            "APPROVAL PROVENANCE VIOLATION: completion requires metadata.approval_record "
            "with source='explicit_user_response' and the candidate's exact path/hash; "
            "a goal, retry, silence, or agent judgment is not approval"
        )


'''
replace("lib/checkpoint.py", "def write_checkpoint(\n", helper + "def write_checkpoint(\n")
replace(
    "lib/checkpoint.py",
    '''    if pipeline_type == "persian-footage" and stage != "compose" and human_approved:
        raise CheckpointValidationError(
            "APPROVAL PROVENANCE VIOLATION: persian-footage may record "
            "human_approved=True only on compose after explicit user approval "
            "of the rendered candidate; a continuation goal is not approval."
        )

    # --- Gate enforcement (GI-4) ---
''',
    '''    if pipeline_type == "persian-footage" and stage != "compose" and human_approved:
        raise CheckpointValidationError(
            "APPROVAL PROVENANCE VIOLATION: persian-footage may record "
            "human_approved=True only on compose after explicit user approval "
            "of the rendered candidate; a continuation goal is not approval."
        )
    if pipeline_type == "persian-footage":
        _validate_persian_compose_lifecycle(
            pipeline_dir, project_id, stage, status, artifacts, human_approved, metadata
        )

    # --- Gate enforcement (GI-4) ---
''',
)

replace(
    "schemas/artifacts/render_report.schema.json",
    '''          "file_size_bytes": { "type": "integer" },
          "platform_target": { "type": "string" }
''',
    '''          "file_size_bytes": { "type": "integer" },
          "sha256": {
            "type": "string",
            "pattern": "^[0-9a-fA-F]{64}$",
            "description": "Digest of the exact rendered bytes; Persian checkpoint writes recompute and verify it."
          },
          "platform_target": { "type": "string" }
''',
)
replace(
    "schemas/artifacts/render_report.schema.json",
    '''      "description": "False on an automatically produced Persian final candidate. It may become true only after the user approves that render; verification_notes still records the automated measurements and their limits."
''',
    '''      "description": "False on an automatically produced Persian final candidate. It may become true only after the user approves that exact render and all automated text measurements pass; verification_notes records those measurements and their limits."
''',
)

replace(
    "lib/persian_preflight.py",
    '''        moments.append({
            "id": moment.get("id"),
            "startSeconds": moment.get("startSeconds"),
            "endSeconds": moment.get("endSeconds"),
            "placement": geometry.get("placement"),
            "rect": geometry.get("rect"),
            "subjectSafety": geometry.get("subjectSafety"),
        })
''',
    '''        rect = geometry.get("rect")
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
''',
)

replace(
    "pipeline_defs/persian-footage.yaml",
    '''      - "Initial candidate: delivery_status is final_candidate, human_visual_approval is false, persian_text_verified is false, and compose is awaiting_human"
      - "Only explicit approval of that MP4 completes compose with human_approved true; then delivery_status is approved and the two verification booleans may become true"
''',
    '''      - "Initial candidate: delivery_status is final_candidate, human_visual_approval is false, persian_text_verified is false, outputs[0].sha256 matches the MP4 bytes, and compose is awaiting_human"
      - "Only explicit approval of that exact path and sha256 completes compose with human_approved true; metadata.approval_record identifies the user response, delivery_status is approved, and the two verification booleans may become true"
''',
)

replace(
    "skills/pipelines/persian-footage/final-candidate-protocol.md",
    '''`delivery_status: final_candidate`, `human_visual_approval: false`, and
`persian_text_verified: false`. Only explicit approval of that exact MP4 may rewrite
compose as `completed` with `human_approved: true` and approved delivery fields.
''',
    '''`delivery_status: final_candidate`, `human_visual_approval: false`, and
`persian_text_verified: false`. After rendering, compute `outputs[0].sha256` from the
actual MP4 bytes; checkpointing recomputes it and refuses a mismatch. Only explicit
approval of that exact path and digest may rewrite compose as `completed` with
`human_approved: true`, `delivery_status: approved`, and
`human_visual_approval: true`. Preserve the candidate output entry byte-for-byte and
write `metadata.approval_record` with `source: explicit_user_response`,
`candidate_path`, and `candidate_sha256`. A changed render is a new candidate.
''',
)
replace(
    "skills/pipelines/persian-footage/final-candidate-protocol.md",
    '''Present the complete MP4 plus entry/stable/exit frames for every moment, both sides
of crossed cuts, warnings for geometry/contrast/watermark/luminance/subtitles, and an
optional separate debug sheet with region boxes. The user reviews once. On rejection,
revise only named scenes and produce a new candidate.
''',
    '''Present the complete MP4 and its sha256 plus entry/stable/exit frames for every
moment, both sides of crossed cuts, warnings for geometry/contrast/watermark/luminance/
subtitles, and an optional separate debug sheet with region boxes. The user reviews
once. On rejection, revise only named scenes and produce a new candidate.
''',
)

tests = '''import hashlib
import json
from pathlib import Path

import pytest
import yaml

from lib.checkpoint import (
    CheckpointValidationError,
    _validate_persian_compose_lifecycle,
    init_project,
    write_checkpoint,
)
from lib.persian_preflight import NoCopyPersianCompose, extract_edit_decisions, summarize
from schemas.artifacts import validate_artifact

ROOT = Path(__file__).resolve().parents[2]


def _make_candidate(tmp_path: Path, name: str = "candidate.mp4", data: bytes = b"candidate") -> tuple[Path, str]:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path, hashlib.sha256(data).hexdigest()


def _report(
    path: Path,
    status: str,
    approved: bool,
    verified: bool,
    *,
    digest: str | None = None,
    include_digest: bool = True,
) -> dict:
    output = {
        "path": str(path),
        "format": "mp4",
        "resolution": "1080x1920",
        "duration_seconds": 10,
    }
    if include_digest:
        output["sha256"] = digest or hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "version": "1.0",
        "outputs": [output],
        "delivery_status": status,
        "human_visual_approval": approved,
        "persian_text_verified": verified,
    }


def _prior_checkpoint(report: dict) -> dict:
    return {
        "version": "1.0",
        "project_id": "run",
        "pipeline_type": "persian-footage",
        "stage": "compose",
        "status": "awaiting_human",
        "timestamp": "2026-09-09T21:00:00+00:00",
        "checkpoint_policy": "guided",
        "human_approval_required": True,
        "human_approved": False,
        "artifacts": {"render_report": report},
    }


def test_one_post_render_gate():
    data = yaml.safe_load((ROOT / "pipeline_defs/persian-footage.yaml").read_text())
    gates = {s["name"]: s["human_approval_default"] for s in data["stages"]}
    assert gates == {"idea": False, "script": False, "scene_plan": False,
                     "assets": False, "edit": False, "compose": True}


def test_precompose_cannot_claim_approval(tmp_path):
    init_project("run", title="Run", pipeline_type="persian-footage", pipeline_dir=tmp_path)
    with pytest.raises(CheckpointValidationError, match="APPROVAL PROVENANCE"):
        write_checkpoint(tmp_path, "run", "edit", "in_progress", {},
                         pipeline_type="persian-footage", human_approved=True)


def test_compose_completion_requires_approval(tmp_path):
    candidate, _ = _make_candidate(tmp_path)
    init_project("run", title="Run", pipeline_type="persian-footage", pipeline_dir=tmp_path)
    with pytest.raises(CheckpointValidationError, match="GATE VIOLATION"):
        write_checkpoint(
            tmp_path, "run", "compose", "completed",
            {"render_report": _report(candidate, "approved", True, True)},
            pipeline_type="persian-footage",
        )


def test_compose_cannot_self_approve_without_candidate_transition(tmp_path):
    candidate, digest = _make_candidate(tmp_path)
    init_project("run", title="Run", pipeline_type="persian-footage", pipeline_dir=tmp_path)
    with pytest.raises(CheckpointValidationError, match="APPROVAL TRANSITION"):
        write_checkpoint(
            tmp_path, "run", "compose", "completed",
            {"render_report": _report(candidate, "approved", True, True)},
            pipeline_type="persian-footage", human_approved=True,
            metadata={"approval_record": {
                "source": "explicit_user_response",
                "candidate_path": str(candidate),
                "candidate_sha256": digest,
            }},
        )


def test_candidate_requires_sha_and_matching_file_bytes(tmp_path):
    candidate, _ = _make_candidate(tmp_path)
    with pytest.raises(CheckpointValidationError, match="64-character sha256"):
        _validate_persian_compose_lifecycle(
            tmp_path, "run", "compose", "awaiting_human",
            {"render_report": _report(
                candidate, "final_candidate", False, False, include_digest=False
            )},
            False, None,
        )
    with pytest.raises(CheckpointValidationError, match="does not match the exact file bytes"):
        _validate_persian_compose_lifecycle(
            tmp_path, "run", "compose", "awaiting_human",
            {"render_report": _report(
                candidate, "final_candidate", False, False, digest="b" * 64
            )},
            False, None,
        )


def test_approval_is_bound_to_prior_candidate_path_digest_and_bytes(tmp_path):
    project = tmp_path / "run"
    project.mkdir()
    candidate, digest = _make_candidate(project / "renders")
    candidate_report = _report(candidate, "final_candidate", False, False)
    _validate_persian_compose_lifecycle(
        tmp_path, "run", "compose", "awaiting_human",
        {"render_report": candidate_report}, False, None,
    )
    (project / "checkpoint_compose.json").write_text(
        json.dumps(_prior_checkpoint(candidate_report)), encoding="utf-8"
    )
    metadata = {"approval_record": {
        "source": "explicit_user_response",
        "candidate_path": str(candidate),
        "candidate_sha256": digest,
    }}
    approved_report = _report(candidate, "approved", True, True)
    _validate_persian_compose_lifecycle(
        tmp_path, "run", "compose", "completed",
        {"render_report": approved_report}, True, metadata,
    )

    alternate, alternate_digest = _make_candidate(
        project / "renders", "alternate.mp4", b"alternate"
    )
    with pytest.raises(CheckpointValidationError, match="path or sha256 changed"):
        _validate_persian_compose_lifecycle(
            tmp_path, "run", "compose", "completed",
            {"render_report": _report(alternate, "approved", True, True)}, True,
            {"approval_record": {
                "source": "explicit_user_response",
                "candidate_path": str(alternate),
                "candidate_sha256": alternate_digest,
            }},
        )

    candidate.write_bytes(b"overwritten after review")
    with pytest.raises(CheckpointValidationError, match="does not match the exact file bytes"):
        _validate_persian_compose_lifecycle(
            tmp_path, "run", "compose", "completed",
            {"render_report": approved_report}, True, metadata,
        )


def test_completion_requires_explicit_user_approval_record(tmp_path):
    project = tmp_path / "run"
    project.mkdir()
    candidate, digest = _make_candidate(project / "renders")
    candidate_report = _report(candidate, "final_candidate", False, False)
    (project / "checkpoint_compose.json").write_text(
        json.dumps(_prior_checkpoint(candidate_report)), encoding="utf-8"
    )
    with pytest.raises(CheckpointValidationError, match="APPROVAL PROVENANCE"):
        _validate_persian_compose_lifecycle(
            tmp_path, "run", "compose", "completed",
            {"render_report": _report(candidate, "approved", True, True)}, True,
            {"approval_record": {
                "source": "continuation_goal",
                "candidate_path": str(candidate),
                "candidate_sha256": digest,
            }},
        )


def test_candidate_report_schema(tmp_path):
    candidate, _ = _make_candidate(tmp_path)
    validate_artifact(
        "render_report", _report(candidate, "final_candidate", False, False)
    )


def test_no_copy_stage_and_helpers(tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"x")
    staging = tmp_path / "stage"
    assert NoCopyPersianCompose._stage(source, staging, "x") == str(source)
    assert not staging.exists()
    artifact = {"persian": {"shots": [], "moments": []}}
    assert extract_edit_decisions({"artifacts": {"edit_decisions": artifact}}) is artifact
    result = summarize({
        "design": {"resolved": {"layoutVersion": 12}},
        "moments": [{
            "id": "m1",
            "layoutGeometry": {
                "x": .1, "y": .2, "w": .3, "h": .4,
                "placement": "upper-left",
            },
        }],
        "watermarkPlan": [],
    }, [])
    assert result["mediaCopies"] == 0
    assert result["moments"][0]["rect"] == {
        "x": .1, "y": .2, "w": .3, "h": .4,
    }
    assert result["moments"][0]["geometry"]["placement"] == "upper-left"


def test_protocol_is_required_and_bounded():
    manifest = (ROOT / "pipeline_defs/persian-footage.yaml").read_text()
    protocol = (ROOT / "skills/pipelines/persian-footage/final-candidate-protocol.md").read_text()
    assert "pipelines/persian-footage/final-candidate-protocol" in manifest
    assert "Never call `PersianCompose._build_props` directly" in protocol
    assert "three footage/layout candidates per beat" in protocol
    assert "candidate_sha256" in protocol
    assert "recomputes it" in protocol
'''
(ROOT / "tests/lib/test_persian_final_candidate_protocol.py").write_text(
    tests, encoding="utf-8"
)

print("hardened Persian final-candidate lifecycle with byte verification")
