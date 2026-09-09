"""Keep Persian Footage skill defaults aligned with the Film Type source of truth.

The highest supported Film Type version is read from the ``expected_version``
map in ``lib/persian_film_type.py``. Skill docs may keep historical version
references, but they must not present an older version as current/default, and
the orchestration skills must state the current one.

Four things this guard learned not to do:

* **Do not require the claim and the version on one line.** Reflowed Markdown
  puts ``is the default`` and the version number in different lines of the same
  sentence. The claim line is searched first; if it names no version at all the
  search widens to the surrounding paragraph. The cost of that tolerance is
  stated plainly: a paragraph that names the expected version anywhere
  satisfies every claim line inside it, so a paragraph mixing a current claim
  about an old version with a mention of the new one passes. Splitting the
  paragraph is the fix if that ever matters.
* **Do not take the first decimal number on the line as a version.** These
  documents are full of decimals that are not versions — ``5.6:1`` and
  ``4.5:1`` contrast floors, ``0.58`` and ``0.6`` stack fractions, ``0.45s``
  timings. A candidate now has to be written as ``Film Type <version>`` or be a
  key of the expected map.
* **Do not assert something that is true of any input.** Checking that
  ``max(versions)`` is a member of ``versions`` cannot fail. The map's shape is
  checked instead, and the newest entry is pinned against the profile JSON.
* **Do not check only the label.** A file that dropped its routing block
  entirely used to pass, because there was nothing left to be wrong about.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
PIPELINE_SKILLS = ROOT / "skills" / "pipelines" / "persian-footage"
FILM_TYPE_SOURCE = ROOT / "lib" / "persian_film_type.py"
FILM_TYPE_PROFILE = ROOT / "styles" / "persian-footage" / "film-type.json"
HISTORY_FILENAME = "film-type-history.md"

# The skills that orchestrate a run and must therefore state the active version.
# Stage skills that never mention the profile are deliberately not listed.
ROUTING_SKILLS = (
    "executive-producer.md",
    "edit-director.md",
    "compose-director.md",
)

_VERSION_TOKEN_RE = re.compile(r"\d+\.\d+(?:\.\d+)?")
_FILM_TYPE_VERSION_RE = re.compile(
    r"film\s+type\s+v?(?P<version>\d+\.\d+(?:\.\d+)?)", re.IGNORECASE
)
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


def _newest_version(versions: dict[str, int]) -> str:
    return max(versions, key=_parse_version)


def _find_profile_key(payload: object, key: str) -> object:
    """Locate ``key`` anywhere in the profile JSON, whatever its nesting."""

    if isinstance(payload, dict):
        if key in payload:
            return payload[key]
        for nested in payload.values():
            found = _find_profile_key(nested, key)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for nested in payload:
            found = _find_profile_key(nested, key)
            if found is not None:
                return found
    return None


def _skill_files() -> list[Path]:
    return sorted(
        path for path in PIPELINE_SKILLS.glob("*.md") if path.name != HISTORY_FILENAME
    )


def _paragraphs(text: str) -> list[tuple[int, int, str]]:
    """Return ``(first_line, last_line, joined_text)`` for each blank-line block."""

    blocks: list[tuple[int, int, str]] = []
    current: list[str] = []
    start = 1
    for line_number, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            if not current:
                start = line_number
            current.append(line)
            continue
        if current:
            blocks.append((start, start + len(current) - 1, "\n".join(current)))
            current = []
    if current:
        blocks.append((start, start + len(current) - 1, "\n".join(current)))
    return blocks


def _film_type_versions(text: str, known: dict[str, int]) -> list[str]:
    """Version numbers in ``text`` that are plausibly Film Type versions.

    Either written as ``Film Type 2.11.0``, or exactly equal to a registered
    version. A bare ``5.6`` or ``0.58`` is neither, which is the whole point.
    """

    known_tuples = {_parse_version(key) for key in known}
    found: list[str] = []
    for match in _FILM_TYPE_VERSION_RE.finditer(text):
        found.append(match.group("version"))
    for match in _VERSION_TOKEN_RE.finditer(text):
        token = match.group(0)
        if _parse_version(token) in known_tuples:
            found.append(token)
    return found


def test_expected_version_map_shape() -> None:
    """The map the renderer dispatches on must be ordered and gapless."""

    versions = _expected_version_map()
    assert versions, "expected_version map is empty"

    layouts = list(versions.values())
    assert len(set(layouts)) == len(layouts), f"duplicate layout versions: {layouts}"
    assert sorted(layouts) == list(range(1, len(layouts) + 1)), (
        f"layout versions must form 1..{len(layouts)} with no gaps, got {sorted(layouts)}"
    )

    ordered = sorted(versions, key=_parse_version)
    ordered_layouts = [versions[version] for version in ordered]
    assert ordered_layouts == sorted(ordered_layouts), (
        "layout versions must increase with the profile version: "
        f"{list(zip(ordered, ordered_layouts))}"
    )

    newest = ordered[-1]
    assert versions[newest] == len(versions), (
        f"newest version {newest} should carry the highest layout number"
    )


def test_profile_json_matches_the_newest_registered_version() -> None:
    """The shipped profile is what the hash is computed over; pin it to the map."""

    versions = _expected_version_map()
    newest = _newest_version(versions)

    payload = json.loads(FILM_TYPE_PROFILE.read_text(encoding="utf-8"))
    profile_version = _find_profile_key(payload, "profileVersion")
    layout_version = _find_profile_key(payload, "layoutVersion")

    assert profile_version is not None, "film-type.json declares no profileVersion"
    assert layout_version is not None, "film-type.json declares no layoutVersion"
    assert _parse_version(str(profile_version)) == _parse_version(newest), (
        f"film-type.json ships profileVersion {profile_version} but the newest "
        f"registered version is {newest}"
    )
    assert layout_version == versions[newest], (
        f"film-type.json ships layoutVersion {layout_version} but "
        f"{newest} is registered as layout {versions[newest]}"
    )


def test_persian_footage_skills_do_not_declare_an_older_default() -> None:
    versions = _expected_version_map()
    expected = _newest_version(versions)
    expected_tuple = _parse_version(expected)
    offenders: list[str] = []

    for path in _skill_files():
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        for first, last, block in _paragraphs(text):
            for offset, line in enumerate(lines[first - 1 : last]):
                if not _CURRENT_DEFAULT_RE.search(line):
                    continue
                # Prefer the claim's own line; widen to its paragraph only when
                # the line names no version, which is how reflowed prose reads.
                candidates = _film_type_versions(line, versions)
                scope = "line"
                if not candidates:
                    candidates = _film_type_versions(block, versions)
                    scope = "paragraph"
                if not candidates:
                    continue
                if any(_parse_version(candidate) == expected_tuple for candidate in candidates):
                    continue
                offenders.append(
                    f"{path.relative_to(ROOT)}:{first + offset}: "
                    f"declares Film Type {', '.join(sorted(set(candidates)))} as "
                    f"current/default ({scope} scope); highest registered version "
                    f"is {expected}"
                )

    assert not offenders, "\n".join(offenders)


def test_routing_skills_state_the_current_version() -> None:
    """Absence of a stale label is not the same as presence of a current one."""

    versions = _expected_version_map()
    expected = _newest_version(versions)
    expected_tuple = _parse_version(expected)
    problems: list[str] = []

    for name in ROUTING_SKILLS:
        path = PIPELINE_SKILLS / name
        if not path.exists():
            problems.append(f"{name}: missing from {PIPELINE_SKILLS.relative_to(ROOT)}")
            continue

        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()

        declares_current = False
        for first, last, block in _paragraphs(text):
            if not any(_CURRENT_DEFAULT_RE.search(line) for line in lines[first - 1 : last]):
                continue
            if any(
                _parse_version(candidate) == expected_tuple
                for candidate in _film_type_versions(block, versions)
            ):
                declares_current = True
                break
        if not declares_current:
            problems.append(
                f"{name}: no paragraph declares Film Type {expected} as the default"
            )

        if "film-type.md" not in text:
            problems.append(f"{name}: does not point at film-type.md for the active contract")
        if HISTORY_FILENAME not in text:
            problems.append(f"{name}: does not point at {HISTORY_FILENAME} for older pins")

    assert not problems, "\n".join(problems)
