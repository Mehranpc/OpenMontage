"""#325: a kernel telemetry write must not restore a stale `pending_pass`.

In L2 the run kernel (parent) loaded workflow state, the asset worker (child) settled
the pass and cleared `asset_usage.pending_pass`, then the parent wrote its stale copy
back. The next pass was refused as "still pending result accounting". Writers now
hold a per-project lock across load-modify-write.
"""
from __future__ import annotations

import multiprocessing
from pathlib import Path
import time

from lib import persian_video_workflow as workflow

PROJECT = "lost-update"


def _state(tmp_path: Path) -> None:
    root = tmp_path / PROJECT
    root.mkdir(parents=True)
    workflow._write_state(root, {"version": workflow.WORKFLOW_VERSION, "project_id": PROJECT,
                                 "asset_usage": {"pending_pass": 0}, "spans": []})


def _slow_telemetry_writer(pipeline_dir: str, loaded, release) -> None:
    """The kernel shape: load, (slowly) add a span, write the whole state back."""
    with workflow.state_transaction(PROJECT, pipeline_dir=Path(pipeline_dir)):
        state = workflow.load_workflow_state(PROJECT, pipeline_dir=Path(pipeline_dir))
        loaded.set()
        release.wait(5)
        time.sleep(0.2)
        state["spans"].append("job")
        workflow._write_state(Path(pipeline_dir) / PROJECT, state)


@workflow.state_locked
def _settle_pass(project_id: str, *, pipeline_dir: Path) -> None:
    """The worker shape: clear the pending pass."""
    state = workflow.load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    usage = dict(state["asset_usage"])
    usage.pop("pending_pass")
    usage["completed_passes"] = [0]
    state["asset_usage"] = usage
    workflow._write_state(pipeline_dir / project_id, state)


def test_concurrent_writers_do_not_lose_the_worker_settlement(tmp_path: Path) -> None:
    _state(tmp_path)
    ctx = multiprocessing.get_context("spawn")
    loaded, release = ctx.Event(), ctx.Event()
    parent = ctx.Process(target=_slow_telemetry_writer, args=(str(tmp_path), loaded, release))
    parent.start()
    assert loaded.wait(10)
    release.set()
    _settle_pass(PROJECT, pipeline_dir=tmp_path)  # blocks until the parent's write lands
    parent.join(10)
    assert parent.exitcode == 0
    state = workflow.load_workflow_state(PROJECT, pipeline_dir=tmp_path)
    assert "pending_pass" not in state["asset_usage"], "stale telemetry write restored pending_pass"
    assert state["asset_usage"]["completed_passes"] == [0]
    assert state["spans"] == ["job"]


def test_the_lock_is_reentrant_within_a_process(tmp_path: Path) -> None:
    _state(tmp_path)
    with workflow.state_transaction(PROJECT, pipeline_dir=tmp_path):
        _settle_pass(PROJECT, pipeline_dir=tmp_path)
    assert "pending_pass" not in workflow.load_workflow_state(PROJECT, pipeline_dir=tmp_path)["asset_usage"]


def test_real_writers_are_locked() -> None:
    from lib import persian_run_kernel as kernel

    for fn in (workflow.bounded_asset_search_request, workflow.record_asset_search_result,
               workflow.release_asset_search_pass, workflow.complete_phase,
               kernel._persist_job_causal_span, kernel._persist_transition_causal_span):
        assert getattr(fn, "__wrapped__", None) is not None, fn.__name__


def test_the_lock_file_does_not_count_as_project_progress(tmp_path: Path) -> None:
    _state(tmp_path)
    root = tmp_path / PROJECT
    before, _ = workflow._last_project_write(root)
    time.sleep(0.05)
    with workflow.state_transaction(PROJECT, pipeline_dir=tmp_path):
        pass
    assert workflow._last_project_write(root)[0] == before


def _hold(pipeline_dir: str, loaded, release) -> None:
    with workflow.state_transaction(PROJECT, pipeline_dir=Path(pipeline_dir)):
        loaded.set()
        release.wait(10)


def test_a_stuck_holder_fails_with_its_identity_instead_of_hanging(tmp_path: Path, monkeypatch) -> None:
    import pytest

    _state(tmp_path)
    from lib import persian_state_lock

    monkeypatch.setattr(persian_state_lock, "STATE_LOCK_TIMEOUT_SECONDS", 0.5)
    ctx = multiprocessing.get_context("spawn")
    loaded, release = ctx.Event(), ctx.Event()
    holder = ctx.Process(target=_hold, args=(str(tmp_path), loaded, release))
    holder.start()
    try:
        assert loaded.wait(10)
        with pytest.raises(persian_state_lock.StateLockTimeout, match=rf"held by: pid={holder.pid}"):
            with workflow.state_transaction(PROJECT, pipeline_dir=tmp_path):
                pass
    finally:
        release.set()
        holder.join(10)


def test_the_lock_is_reentrant_across_a_main_module_and_its_import(tmp_path: Path) -> None:
    """The CLI runs the workflow as __main__ and the kernel imports it again; on L2
    `complete awaiting_human` waited 120 s on the lock its own process held."""
    import os
    import subprocess
    import sys

    _state(tmp_path)
    # Two module instances in one process, as `python -m lib.persian_video_workflow`
    # plus the kernel's import: both must see one held-lock registry.
    runner = (
        "import sys;"
        "import lib.persian_state_lock;"
        "import lib.persian_video_workflow as a;"
        "import importlib.util as u;"
        "spec=u.spec_from_file_location('__dup__', a.__file__); b=u.module_from_spec(spec);"
        "sys.modules['__dup__']=b; spec.loader.exec_module(b);"
        "from pathlib import Path; p=Path(sys.argv[1]);"
        "lib.persian_state_lock.STATE_LOCK_TIMEOUT_SECONDS=2;"
        "cm=b.state_transaction('lost-update', pipeline_dir=p); cm.__enter__();"
        "cm2=a.state_transaction('lost-update', pipeline_dir=p); cm2.__enter__(); print('ok')"
    )
    done = subprocess.run([sys.executable, "-c", runner, str(tmp_path)], capture_output=True, text=True,
                          timeout=30, cwd=Path(workflow.__file__).resolve().parents[1],
                          env={**os.environ, "PYTHONPATH": str(Path(workflow.__file__).resolve().parents[1])})
    assert done.returncode == 0 and done.stdout.strip() == "ok", done.stderr[-1500:]
