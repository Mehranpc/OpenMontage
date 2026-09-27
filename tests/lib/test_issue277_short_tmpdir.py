"""#277: children get a TMPDIR short enough for Chromium's singleton socket.

The rehearsal's render aborted with `Socket path too long` because TMPDIR pointed at
`<project>/.workspace/tmp` under a deep pytest path. The first-date project on the Mac
has a 125-byte socket path too, over macOS's 104-byte cap.
"""
from __future__ import annotations

import os
from pathlib import Path

from lib.persian_project_workspace import project_execution_environment

LONG = "deep-" * 16


def test_a_deep_project_gets_a_short_alias_to_its_own_temp(tmp_path: Path) -> None:
    project = tmp_path / LONG / "projects" / "first-date-message-timing"
    project.mkdir(parents=True)
    env = project_execution_environment(project, base={})
    tmpdir = Path(env["TMPDIR"])
    assert len(str(tmpdir)) + len("/com.google.Chrome.XXXXXX/SingletonSocket") < 104
    assert tmpdir.resolve() == (project / ".workspace" / "tmp").resolve()
    assert env["TMP"] == env["TEMP"] == env["TMPDIR"]


def test_the_alias_is_stable_across_calls(tmp_path: Path) -> None:
    project = tmp_path / LONG / "run"
    project.mkdir(parents=True)
    first = project_execution_environment(project, base={})["TMPDIR"]
    second = project_execution_environment(project, base={})["TMPDIR"]
    assert first == second


def test_a_short_project_keeps_its_temp_path(tmp_path: Path, monkeypatch) -> None:
    import lib.persian_project_workspace as ws

    monkeypatch.setattr(ws, "_SOCKET_PATH_LIMIT", 10_000)
    project = tmp_path / "p"
    project.mkdir()
    env = project_execution_environment(project, base={})
    assert Path(env["TMPDIR"]) == (project / ".workspace" / "tmp").resolve()


def test_a_foreign_entry_is_never_clobbered(tmp_path: Path, monkeypatch) -> None:
    import hashlib

    project = tmp_path / LONG / "run2"
    project.mkdir(parents=True)
    alias = Path("/tmp") / f"om-{hashlib.sha256(str(project.resolve()).encode()).hexdigest()[:12]}"
    if alias.is_symlink() or alias.exists():
        os.unlink(alias) if alias.is_symlink() else None
    alias.mkdir(exist_ok=True)
    try:
        env = project_execution_environment(project, base={})
        assert Path(env["TMPDIR"]) == (project / ".workspace" / "tmp").resolve()
        assert alias.is_dir() and not alias.is_symlink()
    finally:
        alias.rmdir()
