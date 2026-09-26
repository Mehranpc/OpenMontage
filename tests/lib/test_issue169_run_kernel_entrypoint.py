"""#169: the documented run-kernel entry point must be the package module.

`skills/persian-video/SKILL.md` documents `python -m lib.persian_run_kernel run|commit`.
Running a file with `-m` executes it as `__main__`, which is a *second* module instance
from `lib.persian_run_kernel` — the one the workflow imports. `_COMMIT_JOB` is a
module-level `ContextVar`, so the CLI would set it on a copy the workflow never reads
and every media phase commit would fail with "must complete through the run kernel".

That is exactly why this test invokes the entry point through `runpy` rather than
importing and calling functions: importing is what hides the defect, and it is what the
rest of the suite does.
"""

from __future__ import annotations

import runpy

import pytest

from lib import persian_run_kernel as kernel


def test_the_documented_entry_point_runs_the_package_kernel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`python -m lib.persian_run_kernel` must do its work in the package module.

    If it runs its own `main`, the CLI's job identity lives in a different module
    instance from the workflow's guard, and commits through the documented path cannot
    be seen.
    """
    calls: list[object] = []

    def record(argv=None):
        calls.append(argv)
        return 0

    monkeypatch.setattr(kernel, "main", record)

    with pytest.raises(SystemExit):
        runpy.run_module("lib.persian_run_kernel", run_name="__main__")

    assert calls, (
        "the documented entry point must delegate to lib.persian_run_kernel.main(); "
        "running the __main__ copy splits module-level state"
    )


def test_the_entry_point_preserves_the_exit_status(monkeypatch: pytest.MonkeyPatch) -> None:
    """A delegation must not swallow the kernel's exit code -- the front door and the
    runbook both read it."""
    monkeypatch.setattr(kernel, "main", lambda argv=None: 2)

    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("lib.persian_run_kernel", run_name="__main__")

    assert excinfo.value.code == 2
