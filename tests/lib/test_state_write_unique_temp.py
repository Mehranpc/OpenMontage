"""Concurrent state writers must not share one temp file.

L2 on 2026-09-28: the rehearsal's workflow state was read as JSON with "Extra data"
after a foreground command and a durable asset-search job wrote it at once through the
same `persian-video-workflow.json.tmp`. Each writer now uses its own temp name, so
`os.replace` is atomic per writer and a reader always sees one complete document.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from lib import persian_run_kernel as kernel
from lib import persian_video_workflow as workflow


def test_parallel_state_writes_never_interleave(tmp_path: Path) -> None:
    project = tmp_path / "run"
    project.mkdir()
    small = {"v": 1, "pad": "a"}
    large = {"v": 2, "pad": "b" * 200_000}
    errors: list[Exception] = []

    def writer(state: dict) -> None:
        try:
            for _ in range(60):
                workflow._write_state(project, state)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(state,)) for state in (small, large, small, large)]
    for thread in threads:
        thread.start()
    reads = 0
    while any(thread.is_alive() for thread in threads):
        path = project / "persian-video-workflow.json"
        if path.is_file():
            json.loads(path.read_text(encoding="utf-8"))
            reads += 1
    for thread in threads:
        thread.join()
    assert not errors
    assert json.loads((project / "persian-video-workflow.json").read_text(encoding="utf-8"))["v"] in (1, 2)
    assert not list(project.glob("*.tmp"))


def test_kernel_json_writes_use_their_own_temp(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    kernel._atomic_json(path, {"ok": True})
    assert json.loads(path.read_text(encoding="utf-8")) == {"ok": True}
    assert not list(tmp_path.glob("*.tmp"))
