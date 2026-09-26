"""#208: ToolRegistry.get() must find real tools without a prior discovery call."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tools.base_tool import BaseTool
from tools.tool_registry import ToolRegistry

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_fresh_registry_get_finds_a_real_tool():
    reg = ToolRegistry()
    tool = reg.get("direct_clip_search")
    assert tool is not None
    assert tool.name == "direct_clip_search"


def test_unknown_name_is_still_none_and_discovery_runs_once(monkeypatch):
    reg = ToolRegistry()
    calls: list[str] = []
    real = reg.discover

    def counting(package_name: str = "tools"):
        calls.append(package_name)
        return real(package_name)

    monkeypatch.setattr(reg, "discover", counting)
    assert reg.get("no_such_tool_208") is None
    assert reg.get("another_missing_tool_208") is None
    assert calls == ["tools"]


def test_registered_tool_does_not_trigger_discovery(monkeypatch):
    reg = ToolRegistry()
    monkeypatch.setattr(reg, "discover", lambda *a, **k: (_ for _ in ()).throw(AssertionError("discovered")))

    class _Fake(BaseTool):
        name = "fake_208"

        def execute(self, inputs):  # pragma: no cover - never called
            raise NotImplementedError

    fake = _Fake.__new__(_Fake)
    fake.name = "fake_208"
    reg._tools["fake_208"] = fake
    assert reg.get("fake_208") is fake


def test_get_during_discovery_does_not_recurse(monkeypatch):
    reg = ToolRegistry()
    depth: list[int] = []

    def reentrant(package_name: str = "tools"):
        depth.append(1)
        assert len(depth) == 1, "discovery re-entered"
        assert reg.get("still_missing_208") is None
        reg._discovered_packages.add(package_name)
        return []

    monkeypatch.setattr(reg, "discover", reentrant)
    assert reg.get("missing_208") is None
    assert len(depth) == 1


def test_singleton_get_in_a_fresh_process_resolves_the_asset_search_tool():
    """The asset job's lookup in a fresh interpreter (the Mac run crash)."""
    code = (
        "from lib.persian_asset_job import SEARCH_TOOL, default_registry;"
        "t = default_registry.get(SEARCH_TOOL);"
        "print('OK' if t is not None else 'NONE')"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True, timeout=120
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().endswith("OK"), out.stdout + out.stderr
