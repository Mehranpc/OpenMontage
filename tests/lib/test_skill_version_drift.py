"""Keep Persian Footage skill defaults aligned with the Film Type source of truth.

The highest supported Film Type version is read from the ``expected_version``
map in ``lib/persian_film_type.py``. Skill docs may keep historical version
references, but they must not present an older version as current/default.
"""

from __future__ import annotations

import ast
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
PIPELINE_SKILLS = ROOT / "skills" / "pipelines" / "persian-footage"
FILM_TYPE_SOURCE = ROOT / "lib" / "persian_film_type.py"
HISTORY_FILENAME = "film-type-history.md"

_VERSION_RE = re.compile(r"\b(?P<version>\d+\.\d+(?:\.\d+)?)\b")
_CURRENT_DEFAULT_RE = re.compile(
    r"\bcurrent\s+(?:unpinned\s+)?default\b|"
    r"\b(?<!historical )default\s+path\b|"
    r"\bis\s+the\s+default\b",
    re.IGNORECASE,
)


def _parse_version(version: str) -> tuple[int, int, int]:
    parts = [int(part) for part in version.split(".")]
    parts.extend([0] * (3 - len(parts)))
    return tuple(parts[:3])


def _expected_version_map() -> dict[str, int]:
    tree = ast.parse(FILM_TYPE_SOURCE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "expected_version" for target in node.targets):
            continue
        value = node.value
        if not isinstance(value, ast.Call) or not isinstance(value.func, ast.Attribute) or value.func.attr != "get":
            raise AssertionError("expected_version must call .get() on its version map")
        mapping = value.func.value
        if not isinstance(mapping, ast.Dict):
            raise AssertionError("expected_version must be backed by a dict literal")
        result: dict[str, int] = {}
        for key_node, value_node in zip(mapping.keys, mapping.values):
            if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
                raise AssertionError("expected_version contains a non-string version key")
            if not isinstance(value_node, ast.Constant) or type(value_node.value) is not int:
                raise AssertionError("expected_version contains a non-integer layout version")
            result[key_node.value] = value_node.value
        return result
    raise AssertionError("could not find expected_version assignment in lib/persian_film_type.py")


def _skill_files() -> list[Path]:
    return sorted(
        path for path in PIPELINE_SKILLS.glob("*.md") if path.name != HISTORY_FILENAME
    )


def test_highest_expected_film_type_version() -> None:
    versions = _expected_version_map()
    assert versions
    newest = max(versions, key=_parse_version)
    assert newest in versions


def test_persian_footage_skills_do_not_declare_an_older_default() -> None:
    expected = max(_expected_version_map(), key=_parse_version)
    offenders: list[str] = []

    for path in _skill_files():
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not _CURRENT_DEFAULT_RE.search(line):
                continue
            match = _VERSION_RE.search(line)
            if match and _parse_version(match.group("version")) != _parse_version(expected):
                offenders.append(
                    f"{path.relative_to(ROOT)}:{line_number}: "
                    f"declares Film Type {match.group('version')} as current/default; "
                    f"highest registered version is {expected}"
                )

    assert not offenders, "\n".join(offenders)
