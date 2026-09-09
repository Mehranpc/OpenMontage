#!/usr/bin/env python3
"""One-shot patch for the Persian final-candidate protocol."""
from pathlib import Path
from textwrap import dedent
import re

ROOT = Path(__file__).resolve().parents[2]


def load(path):
    return (ROOT / path).read_text(encoding="utf-8")


def save(path, text):
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def once(text, old, new, label):
    if text.count(old) != 1:
        raise RuntimeError(f"{label}: expected one match, got {text.count(old)}")
    return text.replace(old, new, 1)


def sub_once(text, pattern, replacement, label):
    result, count = re.subn(pattern, replacement, text, count=1, flags=re.M | re.S)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, got {count}")
    return result


# The only default human gate is the rendered compose candidate.
p = "pipeline_defs/persian-footage.yaml"
s = load(p)
s = once(
    s,
    "  - pipelines/persian-footage/compose-director\n  - meta/reviewer\n",
    "  - pipelines/persian-footage/compose-director\n"
    "  - pipelines/persian-footage/final-candidate-protocol\n"
    "  - meta/reviewer\n",
    "required skill",
)
for stage, value in [("idea", "false"), ("script", "false"),
                     ("scene_plan", "false"), ("assets", "false"),
                     ("edit", "false"), ("compose", "true")]:
    pattern = rf"(  - name: {stage}\n(?:(?!\n  - name: ).)*?    human_approval_default: )(?:true|false)"
    s = sub_once(s, pattern, rf"\g<1>{value}", f"{stage} gate")
s = sub_once(
    s,
    r'^      - "render_report\.persian_text_verified = true,[^\n]*$',
    '      - "Initial candidate: delivery_status is final_candidate, human_visual_approval is false, persian_text_verified is false, and compose is awaiting_human"\n'
    '      - "Only explicit approval of that MP4 completes compose with human_approved true; then delivery_status is approved and the two verification booleans may become true"',
    "compose success state",
)
save(p, s)

# A continuation goal cannot forge approval on a pre-compose checkpoint.
p = "lib/checkpoint.py"
s = load(p)
guard = (
    "    # Persian footage has one human gate: the rendered compose candidate.\n"
    "    if pipeline_type == \"persian-footage\" and stage != \"compose\" and human_approved:\n"
    "        raise CheckpointValidationError(\n"
    "            \"APPROVAL PROVENANCE VIOLATION: persian-footage may record \"\n"
    "            \"human_approved=True only on compose after explicit user approval \"\n"
    "            \"of the rendered candidate; a continuation goal is not approval.\"\n"
    "        )\n\n"
)
s = once(s, "    # --- Gate enforcement (GI-4) ---\n", guard + "    # --- Gate enforcement (GI-4) ---\n", "approval guard")
save(p, s)

# Render reports distinguish a complete candidate from an approved delivery.
p = "schemas/artifacts/render_report.schema.json"
s = load(p)
fields = (
    '    "delivery_status": {\n'
    '      "type": "string",\n'
    '      "enum": ["final_candidate", "approved", "rejected"],\n'
    '      "description": "Lifecycle of a rendered candidate; final_candidate awaits the user’s one post-render review."\n'
    '    },\n'
    '    "human_visual_approval": {\n'
    '      "type": "boolean",\n'
    '      "description": "False for automation. Only explicit approval of the rendered output may set it true."\n'
    '    },\n'
)
s = once(s, '    "persian_text_verified": {\n', fields + '    "persian_text_verified": {\n', "report state fields")
old = '      "description": "Set by the compose director, and only when all five measurements agree: verify_frames(...)[\'passed\'] over every moment, check_gap_is_empty over every gap, check_moment_arrangement over every moment with its own roles list, measure_stack_rhythm over every moment with its own fitted lead size, and find_watermark reporting found and not clipped_at_edge. persian_compose returns it false and cannot know otherwise — it renders, it does not look. Setting it true without those measurements defeats the only check that catches the failures this pipeline was built to prevent."\n'
new = '      "description": "False on an automatically produced Persian final candidate. It may become true only after the user approves that render; verification_notes still records the automated measurements and their limits."\n'
s = once(s, old, new, "verified provenance")
save(p, s)

# Sanctioned no-copy browser preflight.
save("lib/persian_preflight.py", dedent(r'''
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
        moments.append({
            "id": moment.get("id"),
            "startSeconds": moment.get("startSeconds"),
            "endSeconds": moment.get("endSeconds"),
            "placement": geometry.get("placement"),
            "rect": geometry.get("rect"),
            "subjectSafety": geometry.get("subjectSafety"),
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
''').lstrip())

# Required orchestration contract.
save("skills/pipelines/persian-footage/final-candidate-protocol.md", dedent(r'''
# Final Candidate Protocol — Persian Footage

## One human gate

Run autonomously from supplied input to one complete rendered **final candidate**.
Do not ask the user to approve idea, queries, assets, typography boxes, or subject
regions separately. Compose first writes `awaiting_human` with
`delivery_status: final_candidate`, `human_visual_approval: false`, and
`persian_text_verified: false`. Only explicit approval of that exact MP4 may rewrite
compose as `completed` with `human_approved: true` and approved delivery fields.

A prompt, continuation goal, retry instruction, agent inspection, successful test,
or silence is not visual approval. If narration audio is already supplied, continue;
waiting for missing audio is an input dependency, not a visual gate.

## Joint footage/type planning

Plan semantic beats first, then solve footage and typography together. Store
`scene_plan.metadata.display_requirements` by beat:

- `exact`: immutable user-mandated display copy, such as an exact opening hook;
- `adaptable`: up to three shorter display candidates grounded in the same narration;
- `none`: no on-screen moment for that beat.

Inspect candidate footage at the start, middle, and end of its intended cropped
window. Estimate conservative normalized subject/action envelopes across camera
motion. These `avoidRegions` are machine-estimated geometry, not human approval;
`[]` means the whole window was inspected and found clear.

Jointly evaluate semantic relevance, subject continuity, negative space, copy mode,
placement, legal Film Type ladder rung, reading dwell, cut alignment, contrast, and
watermark feasibility. Exact copy stays exact. Reject a candidate when truthful
regions block all layouts—never tighten a region because the planner wants its zone.
Prefer one compatible shot long enough for the moment instead of extending a fixed
layout across incompatible cuts.

Persist `edit_decisions` once, only after the entire edit passes preflight. Failed
candidates stay in memory and never create checkpoint history.

## Bounded work

Try at most three footage/layout candidates per beat and twenty probes per video.
At the limit: choose a clearer ranked alternate; shorten only adaptable display copy;
omit a nonessential moment while preserving narration; source a compatible shot for
exact copy; otherwise return one structured blocker. A new user goal may authorize
one new bounded cycle but does not approve visuals.

## No-copy preflight

Use:

```bash
python -m lib.persian_preflight path/to/checkpoint_edit.json
```

It runs the real audits and Film Type browser measurement while validating media
paths without copying them. It writes no checkpoint and leaves no persistent staging.
Never call `PersianCompose._build_props` directly from an agent script and never use
`renders/.prep` for probes. Run `persian_compose` once for the accepted edit; normal
render staging must be cleaned on every exit unless explicit debug retention was
requested.

## Post-render review package

Present the complete MP4 plus entry/stable/exit frames for every moment, both sides
of crossed cuts, warnings for geometry/contrast/watermark/luminance/subtitles, and an
optional separate debug sheet with region boxes. The user reviews once. On rejection,
revise only named scenes and produce a new candidate.
''').lstrip())

# Route existing skills to the protocol and remove contradictory human-review text.
p = "skills/pipelines/persian-footage/executive-producer.md"
s = load(p)
s = once(s, "# Executive Producer — Persian Footage Pipeline\n",
         "# Executive Producer — Persian Footage Pipeline\n\n## Final-candidate protocol\n\nRead `skills/pipelines/persian-footage/final-candidate-protocol.md`. Intermediate stages run autonomously; compose is the single post-render human gate.\n", "executive route")
s = once(s,
    "The script stage **stops and hands the narration text to the user**. This is a real\nhandoff, not a checkpoint to click through — the pipeline cannot continue until the\naudio comes back. Say so plainly and wait.\n",
    "Only when narration audio is missing, hand the narration text to the user and wait\nfor audio as an input dependency. If final narration audio is already supplied,\ntranscribe it and continue autonomously to the rendered candidate.\n", "audio handoff")
save(p, s)

p = "skills/pipelines/persian-footage/edit-director.md"
s = load(p)
s = once(s, "# Edit Director — Persian Footage Pipeline\n",
         "# Edit Director — Persian Footage Pipeline\n\n## Joint planning\n\nRead `final-candidate-protocol.md`. Measure exact/adaptable copy, candidate shot, crop, truthful regions, placement, ladder rung, dwell, cuts, and watermark together with `python -m lib.persian_preflight`. Never persist failed probes.\n", "edit route")
s = once(s,
    "Neither profile detects subjects. Film Type 2.12 instead requires a human-reviewed\n`avoidRegions` array on every overlapping shot (use `[]` only after checking the\nwhole crop/camera move) and rejects any text candidate that intersects it. A wide\n",
    "Neither profile detects subjects. Film Type 2.12 requires conservative machine-estimated\n`avoidRegions` on every overlapping shot (use `[]` only after the agent checks the\nwhole crop/camera move) and rejects intersecting candidates. Human approval applies\nto the complete rendered candidate. A wide\n", "edit regions")
save(p, s)

p = "skills/pipelines/persian-footage/asset-director.md"
s = load(p)
s = once(s,
    "5. **Is there room for text?** Moments occupy a band across the vertical middle —\n   roughly 30%–58% of frame height in vertical, 30%–70% in landscape, anchored to the\n   right. A clip whose subject sits exactly there competes with the type, even through\n   the scrim. Prefer a subject low or left in frame for a beat that carries a moment.\n",
    "5. **Can footage and type be solved together?** Read the provisional display\n   requirement; inspect the cropped window at start/middle/end and record genuine\n   negative space plus conservative subject envelopes. Do not assume a fixed text band.\n   Keep ranked alternatives until no-copy edit preflight chooses a feasible pair.\n", "asset fit")
save(p, s)

p = "skills/pipelines/persian-footage/compose-director.md"
s = load(p)
s = once(s, "# Compose Director — Persian Footage Pipeline\n",
         "# Compose Director — Persian Footage Pipeline\n\n## Final candidate\n\nRead `final-candidate-protocol.md`. Probe with `python -m lib.persian_preflight`, render the accepted edit once, build the review package, and checkpoint compose as `awaiting_human`. Only explicit approval of that MP4 completes compose.\n", "compose route")
s = s.replace("human-reviewed `avoidRegions`", "machine-estimated, whole-shot-reviewed `avoidRegions`")
save(p, s)

p = "skills/pipelines/persian-footage/film-type.md"
s = load(p)
s = once(s,
    "1. **Every overlapping shot must carry reviewed `avoidRegions`**, including\n   `[]` only after a human reviewed the crop and camera move. Both `auto` and\n   explicit placement are refused without that evidence.\n",
    "1. **Every overlapping shot must carry truthful `avoidRegions`**, including\n   `[]` only after the agent inspected the whole cropped window and camera move.\n   Regions may be machine-estimated; human approval occurs after the full candidate.\n   Both `auto` and explicit placement are refused without region evidence.\n", "film regions")
s = once(s,
    "## Subject safety: reviewed geometry, never detection\n\nThere is still no face/person detector or classifier. The edit supplies normalized\nscreen-space envelopes after crop and across camera motion. In 2.12 those reviewed\nregions are mandatory and binding for both auto and explicit typography placement.\nMissing review is a refusal; a blocked wide phrase is an editorial refusal, not an\ninvitation to weaken the region. `subjectSafety` is\n`checked-against-supplied-regions` only after the whole dwell clears them.\n",
    "## Subject safety: supplied geometry, never detection\n\nFilm Type still has no built-in face/person detector or classifier. The edit supplies\nnormalized envelopes after crop and across camera motion. They are mandatory and\nbinding; during autonomous planning they are conservative machine estimates, while\nthe user reviews the final render rather than JSON boxes. Missing geometry is a\nrefusal; a blocked phrase is not permission to weaken a truthful region.\n`subjectSafety` is `checked-against-supplied-regions` only after the dwell clears them.\n", "film safety")
save(p, s)

# Focused regressions.
save("tests/lib/test_persian_final_candidate_protocol.py", dedent(r'''
from pathlib import Path
import pytest
import yaml
from lib.checkpoint import CheckpointValidationError, init_project, write_checkpoint
from lib.persian_preflight import NoCopyPersianCompose, extract_edit_decisions, summarize
from schemas.artifacts import validate_artifact

ROOT = Path(__file__).resolve().parents[2]


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
    init_project("run", title="Run", pipeline_type="persian-footage", pipeline_dir=tmp_path)
    with pytest.raises(CheckpointValidationError, match="GATE VIOLATION"):
        write_checkpoint(tmp_path, "run", "compose", "completed", {},
                         pipeline_type="persian-footage")


def test_candidate_report_schema():
    validate_artifact("render_report", {"version": "1.0", "outputs": [{
        "path": "candidate.mp4", "format": "mp4", "resolution": "1080x1920",
        "duration_seconds": 10}], "delivery_status": "final_candidate",
        "human_visual_approval": False, "persian_text_verified": False})


def test_no_copy_stage_and_helpers(tmp_path):
    source = tmp_path / "clip.mp4"; source.write_bytes(b"x")
    staging = tmp_path / "stage"
    assert NoCopyPersianCompose._stage(source, staging, "x") == str(source)
    assert not staging.exists()
    artifact = {"persian": {"shots": [], "moments": []}}
    assert extract_edit_decisions({"artifacts": {"edit_decisions": artifact}}) is artifact
    result = summarize({"design": {"resolved": {"layoutVersion": 12}},
                        "moments": [], "watermarkPlan": []}, [])
    assert result["mediaCopies"] == 0


def test_protocol_is_required_and_bounded():
    manifest = (ROOT / "pipeline_defs/persian-footage.yaml").read_text()
    protocol = (ROOT / "skills/pipelines/persian-footage/final-candidate-protocol.md").read_text()
    assert "pipelines/persian-footage/final-candidate-protocol" in manifest
    assert "Never call `PersianCompose._build_props` directly" in protocol
    assert "three footage/layout candidates per beat" in protocol
''').lstrip())

print("Applied Persian final-candidate protocol")
