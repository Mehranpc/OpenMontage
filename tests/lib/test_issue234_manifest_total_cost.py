"""#234: the canonical manifest states its spend, so delivery quality can assess cost."""

from __future__ import annotations

from pathlib import Path

from lib import persian_asset_commands as commands
from lib.persian_delivery_quality import _known_cost_usd
from tests.lib.test_issue107_deterministic_cli_idempotency import _persian_project_ready_for_assets


def test_built_manifest_carries_total_cost_and_quality_reads_it(tmp_path: Path) -> None:
    _persian_project_ready_for_assets(tmp_path)
    manifest = commands.build_manifest(tmp_path, "run")
    commands.write_assets_checkpoint(tmp_path, "run")
    value, assessed = _known_cost_usd(tmp_path, "run")
    assert assessed is True
    assert value == 0.0
