"""Per-project workflow-state lock (#325).

The run kernel and a durable worker both rewrite the whole state file; without a
lock a stale copy can overwrite a newer settlement (a resurrected `pending_pass`).

This lives in its own module on purpose: `python -m lib.persian_video_workflow`
runs that file as `__main__`, and the kernel then imports it a second time as
`lib.persian_video_workflow`. A held-lock registry defined there would exist
twice, and the second instance would wait on the lock its own process holds.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import fcntl
import os
from pathlib import Path
import sys
import time

STATE_LOCK_FILENAME = ".workflow-state.lock"
# A state read-modify-write takes milliseconds. A lock held this long is a bug (a
# holder waiting on a process that needs the same lock); fail with the holder named
# instead of hanging the run.
STATE_LOCK_TIMEOUT_SECONDS = float(os.environ.get("OPENMONTAGE_STATE_LOCK_TIMEOUT", "120"))

_HELD: ContextVar[tuple[str, ...]] = ContextVar("persian_state_locks", default=())


class StateLockTimeout(RuntimeError):
    """The state lock stayed held past STATE_LOCK_TIMEOUT_SECONDS."""


@contextmanager
def state_transaction(project_dir: Path):
    """Hold `<project_dir>/.workflow-state.lock`; re-entrant within a process."""
    project_dir = Path(project_dir).resolve()
    key = str(project_dir)
    held = _HELD.get()
    if key in held or not project_dir.is_dir():
        yield
        return
    with (project_dir / STATE_LOCK_FILENAME).open("a+b") as handle:
        deadline = time.monotonic() + STATE_LOCK_TIMEOUT_SECONDS
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    handle.seek(0)
                    holder = handle.read().decode("utf-8", "replace").strip()
                    raise StateLockTimeout(
                        f"workflow state lock was not released within {STATE_LOCK_TIMEOUT_SECONDS:.0f}s; "
                        f"held by: {holder or 'unknown'}"
                    ) from None
                time.sleep(0.05)
        handle.seek(0)
        handle.truncate()
        handle.write(" ".join([f"pid={os.getpid()}", *sys.argv[:4]]).encode("utf-8"))
        handle.flush()
        token = _HELD.set(held + (key,))
        try:
            yield
        finally:
            _HELD.reset(token)
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
