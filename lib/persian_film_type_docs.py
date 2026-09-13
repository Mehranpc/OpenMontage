"""Resolve Film Type documentation from the active/pinned profile version.

The workflow read guard must follow the renderer version.  A static historical
patch path is a reliability bug because it lets the code advance while denying
access to the contract that actually governs that render.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lib.paths import REPO_ROOT


class FilmTypeDocumentationError(ValueError):
    pass


def _version_stem(profile_version: str) -> str:
    parts = profile_version.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise FilmTypeDocumentationError(
            f"invalid Film Type profileVersion {profile_version!r}"
        )
    # Patch notes are versioned by major.minor (2.14-patch.md) while profile
    # snapshots use semantic versions (2.14.0).
    if parts[2] != "0":
        return profile_version
    return ".".join(parts[:2])


def active_film_type_version(*, repo_root: Path = REPO_ROOT) -> str:
    profile_path = repo_root / "styles" / "persian-footage" / "film-type.json"
    try:
        profile: Any = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FilmTypeDocumentationError(
            f"cannot read active Film Type profile: {profile_path}"
        ) from exc
    if not isinstance(profile, dict) or profile.get("profile") != "film-type":
        raise FilmTypeDocumentationError(
            "styles/persian-footage/film-type.json is not a Film Type profile"
        )
    version = str(profile.get("profileVersion") or "").strip()
    _version_stem(version)
    return version


def film_type_patch_path(
    profile_version: str | None = None, *, repo_root: Path = REPO_ROOT
) -> Path:
    version = profile_version or active_film_type_version(repo_root=repo_root)
    path = repo_root / "docs" / f"persian-film-type-{_version_stem(version)}-patch.md"
    if not path.is_file():
        raise FilmTypeDocumentationError(
            f"Film Type {version} has no matching patch document: {path}"
        )
    return path.resolve()


def film_type_contract_paths(
    profile_version: str | None = None, *, repo_root: Path = REPO_ROOT
) -> list[Path]:
    """Return the authoritative docs the read guard should expose for a pin.

    Current behaviour always includes the active contract, the version patch and
    the visual-regression procedure.  Historical reproduction additionally has
    the archive available through the persian-footage skill directory itself.
    """
    patch = film_type_patch_path(profile_version, repo_root=repo_root)
    contract = repo_root / "skills" / "pipelines" / "persian-footage" / "film-type.md"
    regression = repo_root / "docs" / "film-type-visual-regression.md"
    missing = [path for path in (contract, regression) if not path.is_file()]
    if missing:
        raise FilmTypeDocumentationError(
            "required Film Type documentation is missing: "
            + ", ".join(str(path) for path in missing)
        )
    return [contract.resolve(), patch, regression.resolve()]
