"""#329: production agents learn artifact shapes from schemas, never from fixtures.

On the 2026-09-29 Mac run the agent read tests/rehearsal fixtures "for canonical
artifact shapes", because no skill named the schemas and schemas/ was outside the
read allowlist.
"""
from __future__ import annotations

from pathlib import Path

from lib import persian_video_workflow as workflow

ROOT = Path(__file__).resolve().parents[2]


def test_schemas_are_readable_and_tests_are_not() -> None:
    allow = [Path(p) for p in workflow._repo_read_allowlist()]
    assert (ROOT / "schemas" / "artifacts").resolve() in allow
    assert (ROOT / "schemas" / "checkpoints").resolve() in allow
    tests = (ROOT / "tests").resolve()
    assert not any(p == tests or tests in p.parents or p in tests.parents for p in allow)


def test_prepare_inputs_names_each_schema_it_asks_for() -> None:
    text = (ROOT / "skills/persian-video/prepare-production-inputs.md").read_text(encoding="utf-8")
    for schema in ("artifacts/brief.schema.json", "artifacts/script.schema.json",
                   "artifacts/decision_log.schema.json", "checkpoints/checkpoint.schema.json"):
        assert f"schemas/{schema}" in text
        assert (ROOT / "schemas" / schema).is_file()


def test_skill_states_the_read_scope_and_puts_fixtures_off_limits() -> None:
    text = (ROOT / "skills/persian-video/SKILL.md").read_text(encoding="utf-8")
    assert "read_allowlist.repo_paths" in text
    assert "`tests/fixtures/`" in text and "off-limits" in text
