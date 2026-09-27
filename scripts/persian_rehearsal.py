"""Offline Persian production rehearsal (#260).

Drives a real recorded run through the production CLI front doors, one subprocess per
command exactly as the production agent does, with only the network/machine providers
replayed from the fixture (see ``lib/persian_rehearsal.py``). Agent judgement (plans,
candidate reviews, region annotations, the edit) comes from the fixture's
``decisions/`` files, which are the JSON the real agent wrote.

    python -m scripts.persian_rehearsal [--fixture DIR] [--work DIR] [--until PHASE]

Every step prints one line with its wall time. The run fails on the first command that
fails, printing the refusal. That is the point: a production refusal shows up here in
minutes instead of an hour into a Mac run.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "rehearsal" / "first-date"
PROJECT_ID = "rehearsal-first-date"


class RehearsalFailure(RuntimeError):
    def __init__(self, step: str, detail: str) -> None:
        super().__init__(f"{step}: {detail}")
        self.step = step
        self.detail = detail


class Rehearsal:
    def __init__(
        self, fixture: Path, work: Path, *, echo: bool = True, user_owns_hook: bool = True,
    ) -> None:
        self.user_owns_hook = user_owns_hook
        self.fixture = fixture.resolve()
        self.decisions = self.fixture / "decisions"
        self.work = work.resolve()
        self.projects = self.work / "projects"
        self.project = self.projects / PROJECT_ID
        self.echo = echo
        self.steps: list[dict[str, Any]] = []
        self.env = dict(os.environ)
        self.env["OPENMONTAGE_PROJECTS_DIR"] = str(self.projects)
        self.env["OPENMONTAGE_REHEARSAL_FIXTURE"] = str(self.fixture)
        self.env["PYTHONPATH"] = str(ROOT) + os.pathsep + self.env.get("PYTHONPATH", "")

    # -- plumbing ---------------------------------------------------------------
    def _log(self, line: str) -> None:
        if self.echo:
            print(line, flush=True)

    def run(self, step: str, module: str, *args: str, expect_fail: bool = False) -> Any:
        started = time.monotonic()
        completed = subprocess.run(
            [sys.executable, "-m", module, *args],
            cwd=ROOT, env=self.env, capture_output=True, text=True,
        )
        elapsed = time.monotonic() - started
        ok = completed.returncode == 0
        self.steps.append({"step": step, "seconds": round(elapsed, 3), "ok": ok})
        self._log(f"{'ok ' if ok else 'ERR'} {elapsed:7.2f}s  {step}")
        if ok == expect_fail:
            detail = (completed.stderr or completed.stdout).strip()[-3000:]
            if expect_fail:
                detail = "expected a refusal but the command succeeded"
            raise RehearsalFailure(step, detail)
        if expect_fail:
            return (completed.stderr or completed.stdout).strip()
        out = completed.stdout.strip()
        try:
            return json.loads(out) if out else None
        except json.JSONDecodeError:
            return out

    def wf(self, step: str, *args: str, **kw: Any) -> Any:
        return self.run(step, "lib.persian_video_workflow", *args, **kw)

    def decision(self, name: str) -> Any:
        text = (self.decisions / name).read_text(encoding="utf-8")
        return json.loads(text.replace("{project}", str(self.project)))

    def write(self, rel: str, value: Any) -> str:
        path = self.project / ".workspace" / "rehearsal" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return str(path)

    def checkpoint(self, stage: str, payload: dict[str, Any]) -> None:
        code = (
            "import json,sys; from pathlib import Path; from lib.checkpoint import write_checkpoint;"
            "p=json.loads(sys.argv[3]);"
            "write_checkpoint(Path(sys.argv[1]), sys.argv[2], p['stage'], 'completed', p['artifacts'],"
            " pipeline_type='persian-footage', metadata=p.get('metadata'), review=p.get('review'))"
        )
        started = time.monotonic()
        completed = subprocess.run(
            [sys.executable, "-c", code, str(self.projects), PROJECT_ID,
             json.dumps({"stage": stage, **payload}, ensure_ascii=False)],
            cwd=ROOT, env=self.env, capture_output=True, text=True,
        )
        elapsed = time.monotonic() - started
        ok = completed.returncode == 0
        self.steps.append({"step": f"checkpoint {stage}", "seconds": round(elapsed, 3), "ok": ok})
        self._log(f"{'ok ' if ok else 'ERR'} {elapsed:7.2f}s  checkpoint {stage}")
        if not ok:
            raise RehearsalFailure(f"checkpoint {stage}", completed.stderr.strip()[-3000:])

    def complete(self, phase: str, evidence: dict[str, Any] | None = None) -> None:
        self.wf(f"attempt {phase}", "attempt", PROJECT_ID, "--phase", phase)
        args = ["complete", PROJECT_ID, "--phase", phase]
        if evidence is not None:
            args += ["--evidence-json", self.write(f"evidence-{phase}.json", evidence)]
        self.wf(f"complete {phase}", *args)

    def _assert_precheck_named(self, refusal: str, codes: Sequence[str]) -> None:
        missing = [code for code in codes if code not in refusal]
        if "[EDIT_PRECHECK]" not in refusal or missing:
            raise RehearsalFailure(
                "edit precheck", f"expected EDIT_PRECHECK naming {list(codes)}; missing {missing}: {refusal[-1500:]}"
            )

    def status(self) -> dict[str, Any]:
        return self.wf("status", "status", PROJECT_ID, "--json")

    # -- phases -----------------------------------------------------------------
    def bootstrap(self) -> None:
        # The front door refuses inputs that live inside the repository, as it should;
        # the user's files live outside it, so the rehearsal stages them the same way.
        inputs = self.work / "user-inputs"
        inputs.mkdir(parents=True, exist_ok=True)
        narration = shutil.copyfile(self.fixture / "narration.mp3", inputs / "narration.mp3")
        script = shutil.copyfile(self.fixture / "approved_script.txt", inputs / "approved_script.txt")
        self.wf(
            "bootstrap", "bootstrap", "--title", "rehearsal: first date message timing",
            "--project-id", PROJECT_ID,
            "--narration", str(narration),
            "--approved-script-file", str(script),
        )

    def prepare_inputs(self) -> None:
        for stage in ("idea", "script"):
            self.checkpoint(stage, self.decision(f"checkpoint-{stage}.json"))
        evidence = self.decision("evidence-prepare_inputs.json")
        state = json.loads((self.project / "persian-video-workflow.json").read_text(encoding="utf-8"))
        evidence["narration_sha256"] = state["input"]["narration"]["sha256"]
        self.complete("prepare_inputs", evidence)

    def align(self) -> None:
        self.wf("alignment-plan", "alignment-plan", PROJECT_ID)
        started = self.wf("alignment-start", "alignment-start", PROJECT_ID)
        job_id = str((started or {}).get("jobId") or (started or {}).get("job_id") or "")
        if not job_id:
            raise RehearsalFailure("alignment-start", f"no job id in {started!r}")
        for _ in range(240):
            result = self.wf("alignment-status", "alignment-status", PROJECT_ID, job_id)
            if str((result or {}).get("status")) in {"succeeded", "failed", "interrupted"}:
                break
            time.sleep(0.25)
        self.wf("alignment-commit", "alignment-commit", PROJECT_ID, job_id)

    def plan(self) -> None:
        self.checkpoint("scene_plan", self.decision("checkpoint-scene_plan.json"))
        self.complete("plan_scenes_moments", self.decision("evidence-plan_scenes_moments.json"))

    def _search(self, retry_pass: int) -> None:
        request = self.write(
            f"search-request-{retry_pass}.json",
            self.decision(f"search-request-{retry_pass}.json"),
        )
        self.wf(
            f"asset-search pass {retry_pass}", "asset-search", PROJECT_ID,
            "--retry-pass", str(retry_pass), "--request", request,
        )

    def _stage_and_review(self, pick: dict[str, Any], label: str) -> str:
        ve = pick["visual_event_id"]
        staged = self.wf(
            f"asset-candidate-stage {ve}{label}", "asset-candidate-stage", PROJECT_ID,
            "--json", self.write(f"stage-{ve}{label}.json", pick["stage"]),
        )
        candidate = str(staged.get("candidateId"))
        self.wf(
            f"asset-candidate-review {ve}{label}", "asset-candidate-review", PROJECT_ID,
            candidate, "--json", self.write(f"review-{ve}{label}.json", pick["review"]),
        )
        return candidate

    def acquire(self) -> None:
        self._search(0)
        # Pass 0 footage the recorded agent reviewed and turned down; the retry pass
        # may only run once every pass-0 candidate has a verdict.
        for pick in self.decision("asset-first-pass.json"):
            candidate = self._stage_and_review(pick, "-pass0")
            self.wf(
                f"asset-candidate-reject {pick['visual_event_id']}", "asset-candidate-reject",
                PROJECT_ID, candidate, "--category", pick["reject"]["category"],
                "--reason", pick["reject"]["reason"],
            )
        picks = self.decision("asset-picks.json")
        retried = {pick["visual_event_id"] for pick in self.decision("asset-first-pass.json")}
        chosen: dict[str, str] = {}
        # Pass-0 footage that was kept is reviewed before the retry, as the gate requires.
        for pick in picks:
            if pick["visual_event_id"] not in retried:
                chosen[pick["visual_event_id"]] = self._stage_and_review(pick, "")
        self._search(1)
        for pick in picks:
            if pick["visual_event_id"] in retried:
                chosen[pick["visual_event_id"]] = self._stage_and_review(pick, "")
        for pick in picks:
            ve = pick["visual_event_id"]
            self.wf(f"asset-candidate-select {ve}", "asset-candidate-select", PROJECT_ID, ve, chosen[ve])
        music = self.wf(
            "assets music search", "assets", "music", "search", PROJECT_ID,
            "--json", self.write("music-request.json", self.decision("music-request.json")),
        )
        self.wf(
            "assets music fetch", "assets", "music", "fetch", PROJECT_ID, str(music["searchId"]),
            "--metadata-json", self.write("music-metadata.json", self.decision("music-metadata.json")),
        )
        self.wf(
            "assets build-manifest", "assets", "build-manifest", PROJECT_ID,
            "--overrides-json", self.write("manifest-overrides.json", self.decision("manifest-overrides.json")),
        )
        self.wf(
            "assets write-checkpoint", "assets", "write-checkpoint", PROJECT_ID,
            "--review-json", self.write("assets-review.json", self.decision("assets-review.json")),
            "--metadata-json", self.write("assets-metadata.json", self.decision("assets-metadata.json")),
        )
        self.complete("acquire_assets", {"asset_manifest_path": "artifacts/asset_manifest.json"})

    def regions(self) -> None:
        self.wf("regions build-sheets", "regions", "build-sheets", PROJECT_ID)
        proposed = self.wf(
            "regions propose", "regions", "propose", PROJECT_ID,
            "--json", self.write("region-annotations.json", self.decision("region-annotations.json")),
        )
        self.complete("review_subject_regions", _region_evidence(proposed))

    def select_hook(self) -> None:
        # No CLI front door exists for automatic hook selection yet, so the production
        # agent calls the library directly; the rehearsal does the same (tracked in #260).
        hook = self.decision("hook-selection.json")
        code = (
            "import json,sys; from pathlib import Path;"
            "from lib.persian_video_workflow import record_hook_selection;"
            "h=json.loads(sys.argv[2]);"
            "record_hook_selection(sys.argv[1], selected_text=h['text'], hook_family=h['hook_family'],"
            " candidates=h['candidates'], score=h['score'], content_match_score=h['content_match_score'],"
            " evidence_checked=h['evidence_checked'], unsupported_claims_rejected=h['unsupported_claims_rejected'],"
            " rationale=h['rationale'])"
        )
        started = time.monotonic()
        completed = subprocess.run(
            [sys.executable, "-c", code, PROJECT_ID, json.dumps(hook, ensure_ascii=False)],
            cwd=ROOT, env=self.env, capture_output=True, text=True,
        )
        elapsed = time.monotonic() - started
        ok = completed.returncode == 0
        self.steps.append({"step": "record_hook_selection", "seconds": round(elapsed, 3), "ok": ok})
        self._log(f"{'ok ' if ok else 'ERR'} {elapsed:7.2f}s  record_hook_selection")
        if not ok:
            raise RehearsalFailure("record_hook_selection", completed.stderr.strip()[-3000:])

    def edit(self) -> None:
        self.select_hook()
        draft = self.write("edit-decisions.json", self.decision("edit-decisions-draft.json"))
        if self.user_owns_hook:
            # Scenario 3: the automatic hook's first proof lands after 6s, so the gate hands
            # the decision to the user, who answers "record this sentence as my hook" (#257).
            self.wf("edit-stage base (expect late-proof refusal)", "edit-stage", PROJECT_ID,
                    "base", "--json", draft, expect_fail=True)
            hook = self.decision("hook-selection.json")["text"]
            self.wf("hook-override", "hook-override", PROJECT_ID, "--text", hook,
                    "--reason", "User owns the hook sentence at the preflight hook gate.")
        # The recorded draft carries three deterministic defects the real run met one
        # browser pass at a time. The precheck must name all of them at once, before
        # any candidate is spent (#267, #269, #271); then the agent applies the
        # remedies each diagnostic names.
        refusal = self.wf("edit-stage base (expect precheck refusal)", "edit-stage", PROJECT_ID,
                          "base", "--json", draft, expect_fail=True)
        self._assert_precheck_named(refusal, ("moments.pacing", "music.mix_too_loud"))
        draft = self.write("edit-decisions.json", _apply_named_remedies(
            self.decision("edit-decisions-draft.json"), self.decision("region-annotations.json"),
        ))
        self.wf("edit-stage base", "edit-stage", PROJECT_ID, "base", "--json", draft)
        self.wf("edit-preflight base", "edit-preflight", PROJECT_ID, "base")
        self.wf("edit-promote base", "edit-promote", PROJECT_ID, "base")
        self.wf("attempt no_copy_preflight", "attempt", PROJECT_ID, "--phase", "no_copy_preflight")
        self.wf("complete no_copy_preflight", "complete", PROJECT_ID, "--phase", "no_copy_preflight",
                "--evidence-json", self.write("evidence-no_copy_preflight.json", {"attempt_id": "base"}))

    # -- driver -----------------------------------------------------------------
    PHASES = ("bootstrap", "prepare_inputs", "align", "plan", "acquire", "regions", "edit")

    def rehearse(self, until: str | None = None) -> dict[str, Any]:
        started = time.monotonic()
        failure: RehearsalFailure | None = None
        try:
            for name in self.PHASES:
                getattr(self, name)()
                if until and name == until:
                    break
        except RehearsalFailure as exc:
            failure = exc
        final = None
        try:
            final = self.status()
        except RehearsalFailure:
            pass
        return {
            "ok": failure is None,
            "failed_step": failure.step if failure else None,
            "failure": failure.detail if failure else None,
            "wall_seconds": round(time.monotonic() - started, 3),
            "next_phase": (final or {}).get("next_phase"),
            "status": (final or {}).get("status"),
            "steps": self.steps,
        }


def _apply_named_remedies(draft: dict[str, Any], annotations: dict[str, Any]) -> dict[str, Any]:
    """What the recorded agent does with the precheck's named remedies."""
    from lib.persian_moments import build_moments
    from lib.persian_scenes import _film_motion
    from lib.persian_sync import retime_moments_from_dicts

    persian = draft["persian"]
    audio = persian["audio"]
    # music.mix_too_loud: let the loudness policy derive the speech-time gain (#267).
    audio.pop("musicDuckVolume", None)
    audio.pop("musicBaseVolume", None)
    # moments.pacing: re-derive timings from the narration, never hand-set (#271).
    retimed = retime_moments_from_dicts(
        build_moments(persian["moments"]), audio["wordTimings"],
        simultaneous_hook_typography=True, film_motion=_film_motion(),
    )
    derived = {moment.id: moment.to_props() for moment in retimed}
    for moment in persian["moments"]:
        props = derived.get(moment["id"])
        if props and moment.get("kind") != "hook":
            moment["startSeconds"], moment["endSeconds"] = props["startSeconds"], props["endSeconds"]
    # visualComplexity is carried from the region review, not invented here (#269).
    reviewed = {
        str(shot["shot_id"]): shot.get("visual_complexity")
        for shot in annotations.get("shots") or [] if shot.get("visual_complexity")
    }
    for shot in persian["shots"]:
        if shot.get("id") in reviewed:
            shot["visualComplexity"] = reviewed[shot["id"]]
    return draft


def _region_evidence(proposed: Any) -> dict[str, Any]:
    if isinstance(proposed, dict):
        for key in ("evidence", "phaseEvidence", "completionEvidence"):
            if isinstance(proposed.get(key), dict):
                return dict(proposed[key])
        if proposed.get("reviewedEvidencePath"):
            return dict(proposed)
    return {}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="persian-rehearsal")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--work", type=Path, default=None)
    parser.add_argument("--until", choices=Rehearsal.PHASES, default=None)
    parser.add_argument("--keep", action="store_true", help="keep the work directory")
    args = parser.parse_args(argv)
    work = args.work or Path(tempfile.mkdtemp(prefix="om-rehearsal-"))
    try:
        result = Rehearsal(args.fixture, work).rehearse(until=args.until)
    finally:
        if args.work is None and not args.keep:
            shutil.rmtree(work, ignore_errors=True)
    print(json.dumps({k: v for k, v in result.items() if k != "steps"}, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
