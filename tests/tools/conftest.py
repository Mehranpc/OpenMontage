"""Deterministic host-runtime fixtures for tool unit tests."""

from __future__ import annotations

import pytest

_HYPERFRAMES_RUNTIME_POLICY_TESTS = {
    "test_runtime_check_fails_when_npm_package_unresolvable",
    "test_runtime_check_succeeds_when_npm_resolves",
    "test_runtime_check_fails_when_published_cli_crashes",
}


@pytest.fixture(autouse=True)
def _isolate_hyperframes_runtime_policy(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep policy unit tests independent of the CI host's Node install."""
    if (
        not request.node.nodeid.startswith("tests/tools/test_hyperframes_compose.py::")
        or request.node.name not in _HYPERFRAMES_RUNTIME_POLICY_TESTS
    ):
        return

    from tools.video.hyperframes_compose import HyperFramesCompose

    monkeypatch.setattr(
        HyperFramesCompose,
        "_node_major_version",
        classmethod(lambda cls: cls._NODE_FLOOR_MAJOR),
    )
    monkeypatch.setattr(
        "tools.video.hyperframes_compose.shutil.which",
        lambda command: f"/mock/bin/{command}",
    )
