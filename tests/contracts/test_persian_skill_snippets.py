"""Contract: the Persian pipeline's skills stay executable against the real modules.

Every director skill in `skills/pipelines/persian-footage/` teaches by example: the
agent is expected to copy those snippets and run them. A snippet that imports a name
`lib/` no longer exports, or compares an enum against a string, does not fail loudly —
it fails as a check that silently passes, or as an `ImportError` the agent then works
around by writing its own version of the thing that already exists.

That is the specific risk this pipeline was built to avoid. The compose-director
records six hand-rolled pixel detectors that were tried and defeated by footage; the
reason it points at `lib.persian_verify` instead is that the library's behaviour is
measured. A stale snippet undoes that by sending the agent back to writing its own.

So: every `python` fence must parse, every `from lib.…` import must resolve, and the
enum comparisons that are easy to get subtly wrong are checked by name.
"""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = ROOT / "skills" / "pipelines" / "persian-footage"

_PYTHON_FENCE = re.compile(r"^```python\s*$(.*?)^```\s*$", re.MULTILINE | re.DOTALL)

SKILLS = sorted(SKILL_DIR.glob("*.md"))


def _blocks(path: Path) -> list[tuple[int, str]]:
    """Every python fence in `path`, as (index, source)."""
    return list(enumerate(_PYTHON_FENCE.findall(path.read_text(encoding="utf-8"))))


def _all_blocks() -> list[tuple[Path, int, str]]:
    return [(path, index, src) for path in SKILLS for index, src in _blocks(path)]


BLOCKS = _all_blocks()
BLOCK_IDS = [f"{path.name}:{index}" for path, index, _ in BLOCKS]


def test_the_skills_exist_and_carry_python() -> None:
    """Guards the harvester: a regex that matches nothing would pass every test."""
    assert len(SKILLS) >= 7, f"only found {len(SKILLS)} skills in {SKILL_DIR}"
    assert len(BLOCKS) >= 8, (
        f"only harvested {len(BLOCKS)} python blocks. The fence format probably "
        f"changed, which means the rest of this file is not checking anything."
    )


@pytest.mark.parametrize(("path", "index", "source"), BLOCKS, ids=BLOCK_IDS)
def test_every_snippet_parses(path: Path, index: int, source: str) -> None:
    """A snippet that does not parse cannot be copied and run."""
    try:
        ast.parse(source)
    except SyntaxError as error:  # pragma: no cover - the message is the point
        pytest.fail(
            f"{path.name} block {index} does not parse: {error.msg} "
            f"(line {error.lineno})\n\n{source}"
        )


def _imports(source: str) -> list[tuple[str, list[str]]]:
    """`from lib.x import a, b` occurrences, as (module, names)."""
    tree = ast.parse(source)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("lib."):
            out.append((node.module or "", [alias.name for alias in node.names]))
    return out


IMPORTS = [
    (path.name, module, name)
    for path, _, source in BLOCKS
    for module, names in _imports(source)
    for name in names
]


@pytest.mark.parametrize(
    ("skill", "module", "name"),
    IMPORTS,
    ids=[f"{s}:{m}.{n}" for s, m, n in IMPORTS],
)
def test_every_documented_import_resolves(skill: str, module: str, name: str) -> None:
    """The names the skills tell the agent to import must actually exist.

    Renaming a helper in `lib/` and leaving the skill behind produces an ImportError
    the agent then routes around — usually by reimplementing it worse.
    """
    imported = importlib.import_module(module)
    assert hasattr(imported, name), (
        f"{skill} imports `{name}` from `{module}`, which does not export it. "
        f"Either the skill is stale or the rename is incomplete."
    )


def test_at_least_one_import_was_harvested() -> None:
    """Guards the import harvester the same way, and for the same reason."""
    assert len(IMPORTS) >= 8, f"only harvested {len(IMPORTS)} lib imports"


@pytest.mark.parametrize(("path", "index", "source"), BLOCKS, ids=BLOCK_IDS)
def test_break_class_is_not_compared_against_a_string(
    path: Path, index: int, source: str
) -> None:
    """`BreakClass` is a plain `Enum`, so a string comparison is always unequal.

    A real bug in an earlier version of `script-director.md`: the snippet counted legal
    break points with `break_class(...) != "forbidden"`, which is true for every pair.
    The assertion below it — that a sentence has somewhere legal to break — therefore
    passed on sentences that had nowhere, and the failure only surfaced later as
    unexplained shrunken type.
    """
    if "break_class" not in source:
        pytest.skip("no break_class use in this block")

    for literal in ('"forbidden"', "'forbidden'", '"preferred"', '"allowed"'):
        assert literal not in source, (
            f"{path.name} block {index} compares a break class against the string "
            f"{literal}. BreakClass is not a str subclass, so that comparison is "
            f"always true. Use `BreakClass.FORBIDDEN` and `is`/`is not`."
        )


@pytest.mark.parametrize(("path", "index", "source"), BLOCKS, ids=BLOCK_IDS)
def test_watermark_positions_are_not_hard_coded(
    path: Path, index: int, source: str
) -> None:
    """Positions must come from `WATERMARK_TOP_FRACTION`, not literals.

    The quiet position is derived from the moment zone plus a clearance margin, and the
    resting position differs per format — 11% vertical against 8% landscape. A literal is
    correct in whichever format the author last rendered and silently wrong in the other,
    which is exactly how the landscape watermark came to overlap the text.
    """
    if "find_watermark" not in source:
        pytest.skip("no find_watermark use in this block")

    assert "WATERMARK_TOP_FRACTION" in source, (
        f"{path.name} block {index} calls find_watermark without taking the position "
        f"from WATERMARK_TOP_FRACTION."
    )
