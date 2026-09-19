"""Project-local scratch/workspace invariants for Persian production.

Canonical production artifacts keep their existing locations. This module owns only
mechanical/ephemeral placement so temporary inputs, probes, helper/debug data, caches,
and runtime-relative writes cannot silently fall back to the repository root.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Mapping


class ProjectWorkspaceError(ValueError):
    """Raised when production scratch would escape its current project."""


_CATEGORY_DIRS = {
    "temporary_inputs": "inputs",
    "probes": "probes",
    "debug": "debug",
    "helpers": "helpers",
    "cache": "cache",
    "generated_evidence": "evidence",
    "runtime": "runtime",
    "temp": "tmp",
}

WORKSPACE_ENV = "OPENMONTAGE_PROJECT_WORKSPACE"
SCRATCH_ENV = "OPENMONTAGE_SCRATCH_DIR"
PROJECT_ENV = "OPENMONTAGE_PROJECT_DIR"


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def project_workspace_root(project_dir: Path) -> Path:
    root = project_dir.expanduser().resolve()
    return root / ".workspace"


def workspace_directory(
    project_dir: Path, category: str, *, create: bool = True
) -> Path:
    """Return one classified mechanical directory inside the current project."""
    key = str(category or "").strip()
    leaf = _CATEGORY_DIRS.get(key)
    if leaf is None:
        raise ProjectWorkspaceError(
            f"unknown project workspace category {key!r}; allowed={sorted(_CATEGORY_DIRS)}"
        )
    project = project_dir.expanduser().resolve()
    path = (project_workspace_root(project) / leaf).resolve()
    if not _inside(path, project):
        raise ProjectWorkspaceError("workspace directory must stay inside the current project")
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def workspace_file(
    project_dir: Path,
    category: str,
    relative_path: str | Path,
    *,
    create_parent: bool = True,
) -> Path:
    """Resolve one classified scratch file and refuse absolute/traversal escapes."""
    raw = Path(relative_path)
    if raw.is_absolute():
        raise ProjectWorkspaceError("workspace file must stay inside the current project")
    root = workspace_directory(project_dir, category, create=True)
    target = (root / raw).resolve()
    if not _inside(target, root):
        raise ProjectWorkspaceError("workspace file must stay inside the current project")
    if create_parent:
        target.parent.mkdir(parents=True, exist_ok=True)
    return target


def project_execution_environment(
    project_dir: Path, *, base: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Return child env that routes relative runtime/temp mechanics into the project."""
    project = project_dir.expanduser().resolve()
    workspace = project_workspace_root(project)
    runtime = workspace_directory(project, "runtime")
    temp = workspace_directory(project, "temp")
    env = dict(os.environ if base is None else base)
    env[PROJECT_ENV] = str(project)
    env[WORKSPACE_ENV] = str(workspace)
    env[SCRATCH_ENV] = str(temp)
    # tempfile-aware children honor these on a fresh process.
    env["TMPDIR"] = str(temp)
    env["TMP"] = str(temp)
    env["TEMP"] = str(temp)
    env["PWD"] = str(runtime)
    return env


def active_scratch_root() -> Path | None:
    raw = str(os.environ.get(SCRATCH_ENV) or "").strip()
    if not raw:
        return None
    root = Path(raw).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    project_raw = str(os.environ.get(PROJECT_ENV) or "").strip()
    if project_raw:
        project = Path(project_raw).expanduser().resolve()
        if not _inside(root, project):
            raise ProjectWorkspaceError(
                "active production scratch directory must stay inside the current project"
            )
    return root


@contextmanager
def scoped_scratch_root(path: Path | None) -> Iterator[Path | None]:
    """Expose a scratch root to nested browser/layout helpers, then restore env."""
    if path is None:
        yield None
        return
    root = path.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    previous = os.environ.get(SCRATCH_ENV)
    os.environ[SCRATCH_ENV] = str(root)
    try:
        yield root
    finally:
        if previous is None:
            os.environ.pop(SCRATCH_ENV, None)
        else:
            os.environ[SCRATCH_ENV] = previous


def repository_root_snapshot(repo_root: Path) -> frozenset[str]:
    """Capture direct root entries so intentional pre-existing private files are baseline."""
    root = repo_root.expanduser().resolve()
    return frozenset(item.name for item in root.iterdir())


def assert_repository_root_unchanged(
    repo_root: Path, before: frozenset[str]
) -> None:
    """Reject only newly introduced root entries; never delete or reinterpret baseline WIP."""
    after = repository_root_snapshot(repo_root)
    gained = sorted(after - frozenset(before))
    if gained:
        raise ProjectWorkspaceError(
            "repository root gained unexpected production scratch entries: "
            + ", ".join(gained)
        )


__all__ = [
    "PROJECT_ENV",
    "SCRATCH_ENV",
    "WORKSPACE_ENV",
    "ProjectWorkspaceError",
    "active_scratch_root",
    "assert_repository_root_unchanged",
    "project_execution_environment",
    "project_workspace_root",
    "repository_root_snapshot",
    "scoped_scratch_root",
    "workspace_directory",
    "workspace_file",
]
