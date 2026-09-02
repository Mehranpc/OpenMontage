"""Contract: `AGENT_GUIDE.md`'s pipeline table matches `pipeline_defs/`.

That table is the routing surface. A fresh-session agent reads AGENT_GUIDE.md, picks a
pipeline from the table, and never learns about anything missing from it — Rule Zero
sends every production request through a pipeline, and the table is how a pipeline is
found. So a manifest absent from the table is unreachable in practice, and a table row
with no manifest sends the agent to a file that does not exist.

Neither failure produces an error anywhere else. The manifests validate against their
schema, the skills exist, the tests pass, and the pipeline is simply never chosen.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "AGENT_GUIDE.md"
PIPELINE_DIR = ROOT / "pipeline_defs"

#: A table row: `| `name` | description | stability |`
_ROW = re.compile(r"^\|\s*`([a-z0-9-]+)`\s*\|([^|]*)\|\s*([a-z]+)\s*\|\s*$")

#: `framework-smoke` is a test pipeline; the guide labels it `test` rather than
#: repeating the manifest's stability, which would imply it is a production choice.
_STABILITY_OVERRIDES = {"framework-smoke": "test"}


def _guide_rows() -> dict[str, tuple[str, str]]:
    """Every pipeline row in the guide, as name -> (description, stability)."""
    rows: dict[str, tuple[str, str]] = {}
    for line in GUIDE.read_text(encoding="utf-8").splitlines():
        match = _ROW.match(line)
        if match is None:
            continue
        name, description, stability = match.groups()
        if not (PIPELINE_DIR / f"{name}.yaml").exists() and name not in rows:
            # Not every three-column table in the guide is the pipeline table.
            continue
        rows[name] = (description.strip(), stability)
    return rows


def _manifests() -> dict[str, dict]:
    out = {}
    for path in sorted(PIPELINE_DIR.glob("*.yaml")):
        with open(path, encoding="utf-8") as handle:
            out[path.stem] = yaml.safe_load(handle)
    return out


GUIDE_ROWS = _guide_rows()
MANIFESTS = _manifests()


def test_the_guide_has_a_pipeline_table() -> None:
    """Guards the parser itself: a regex that matches nothing would pass everything."""
    assert len(GUIDE_ROWS) >= 10, (
        f"Only found {len(GUIDE_ROWS)} pipeline rows in AGENT_GUIDE.md. The table "
        f"format probably changed, which means the rest of this file is not checking "
        f"anything."
    )


@pytest.mark.parametrize("name", sorted(MANIFESTS))
def test_every_manifest_is_listed_in_the_guide(name: str) -> None:
    """An unlisted pipeline is unreachable: the agent never learns it exists."""
    assert name in GUIDE_ROWS, (
        f"pipeline_defs/{name}.yaml has no row in AGENT_GUIDE.md's pipeline table. "
        f"Add one with its purpose and stability, or the pipeline cannot be routed to."
    )


@pytest.mark.parametrize("name", sorted(GUIDE_ROWS))
def test_every_guide_row_has_a_manifest(name: str) -> None:
    """A row with no manifest sends the agent to a file that is not there."""
    assert name in MANIFESTS, (
        f"AGENT_GUIDE.md lists `{name}` but pipeline_defs/{name}.yaml does not exist."
    )


@pytest.mark.parametrize("name", sorted(set(GUIDE_ROWS) & set(MANIFESTS)))
def test_stability_matches_the_manifest(name: str) -> None:
    """A `beta` pipeline advertised as `production` sets the wrong expectation.

    Stability is what tells the agent whether to warn the user before committing a
    real production run to it.
    """
    expected = _STABILITY_OVERRIDES.get(name, MANIFESTS[name].get("stability"))
    assert GUIDE_ROWS[name][1] == expected, (
        f"AGENT_GUIDE.md says `{name}` is {GUIDE_ROWS[name][1]!r} but its manifest "
        f"says {expected!r}."
    )


@pytest.mark.parametrize("name", sorted(GUIDE_ROWS))
def test_each_row_describes_the_pipeline(name: str) -> None:
    """The description is the only thing the agent routes on."""
    description = GUIDE_ROWS[name][0]
    assert len(description) >= 15, (
        f"`{name}`'s description in AGENT_GUIDE.md is {description!r} — too short to "
        f"distinguish it from the other pipelines."
    )
