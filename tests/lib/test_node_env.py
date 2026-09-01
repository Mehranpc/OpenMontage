"""Regression tests for the Node/npm subprocess environment.

The bug these lock down: `hyperframes_compose` reported the HyperFrames
runtime UNAVAILABLE on a machine that had Node 22, FFmpeg, npx and a
published package — because npm could not write to `$HOME/.npm`. npm needs a
writable cache even for `npm view`, and its own error text blames root-owned
cache files, which sends the reader after a permissions bug that isn't there.

`provider_menu_summary()` surfaced it as a `runtime_warnings` entry, which the
agent contract requires be reported verbatim to the user — so a false negative
here becomes a user-visible capability the user cannot fix.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from lib import node_env


@pytest.fixture(autouse=True)
def _clear_resolution():
    """Each test resolves from scratch — the module caches per process."""
    node_env.reset_cache_for_tests()
    yield
    node_env.reset_cache_for_tests()


def _clear_cache_env(monkeypatch):
    for var in node_env._CACHE_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_operator_configured_cache_is_honoured(monkeypatch):
    """An explicit npm_config_cache is the operator's decision.

    We must not second-guess it, and we must not add our own override on top:
    any resulting error should name their directory, not ours.
    """
    _clear_cache_env(monkeypatch)
    monkeypatch.setenv("npm_config_cache", "/operator/chosen/cache")

    resolved = node_env.resolve_npm_cache()

    assert resolved["cache_dir"] == "/operator/chosen/cache"
    assert resolved["source"] == "operator"
    assert resolved["override"] is False

    env = node_env.node_subprocess_env({"PATH": "/usr/bin"})
    assert "npm_config_cache" not in env, (
        "The operator already set the cache in their own environment; adding "
        "our override would shadow their configuration."
    )


def test_writable_default_cache_needs_no_override(monkeypatch, tmp_path):
    """When npm's own default works, we change nothing.

    Redirecting the cache unnecessarily would discard the user's warm cache
    and make every first render pay a fresh download.
    """
    _clear_cache_env(monkeypatch)
    home = tmp_path / "home"
    (home / ".npm").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(node_env.platform, "system", lambda: "Darwin")

    resolved = node_env.resolve_npm_cache()

    assert resolved["source"] == "default"
    assert resolved["override"] is False
    assert resolved["cache_dir"] == str(home / ".npm")
    assert resolved["reason"] is None
    assert "npm_config_cache" not in node_env.node_subprocess_env({})


def test_unwritable_default_falls_back_to_repo_cache(monkeypatch, tmp_path):
    """The actual failure mode: default cache exists but writes are denied.

    A sandbox denies the write syscall while the permission bits still look
    fine, so the fallback must trigger on a real create attempt.
    """
    _clear_cache_env(monkeypatch)
    home = tmp_path / "home"
    (home / ".npm").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(node_env.platform, "system", lambda: "Darwin")

    fallback = tmp_path / "repo-cache"
    monkeypatch.setattr(node_env, "FALLBACK_NPM_CACHE", fallback)

    denied = home / ".npm"
    real_is_writable = node_env._is_writable
    monkeypatch.setattr(
        node_env,
        "_is_writable",
        lambda path: False if path == denied else real_is_writable(path),
    )

    resolved = node_env.resolve_npm_cache()

    assert resolved["source"] == "fallback"
    assert resolved["override"] is True
    assert resolved["cache_dir"] == str(fallback)
    assert "not writable" in (resolved["reason"] or ""), (
        "The diagnostic must state why the default was rejected, so a reader "
        "does not chase npm's misleading root-owned-files hint."
    )

    env = node_env.node_subprocess_env({"PATH": "/usr/bin"})
    assert env["npm_config_cache"] == str(fallback)


def test_missing_home_still_resolves_a_cache(monkeypatch, tmp_path):
    """A container or service manager can leave HOME unset entirely."""
    _clear_cache_env(monkeypatch)
    monkeypatch.delenv("HOME", raising=False)
    monkeypatch.setattr(node_env.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(node_env.os.path, "expanduser", lambda p: p)

    fallback = tmp_path / "repo-cache"
    monkeypatch.setattr(node_env, "FALLBACK_NPM_CACHE", fallback)

    resolved = node_env.resolve_npm_cache()

    assert resolved["source"] == "fallback"
    assert resolved["cache_dir"] == str(fallback)


def test_no_writable_location_reports_unavailable(monkeypatch, tmp_path):
    """When nothing is writable we say so plainly instead of guessing.

    Returning a directory that cannot be written would move the failure into
    npm's opaque EPERM output, which is exactly the trap being removed.
    """
    _clear_cache_env(monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(node_env.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(node_env, "FALLBACK_NPM_CACHE", tmp_path / "repo-cache")
    monkeypatch.setattr(node_env, "_is_writable", lambda path: False)

    resolved = node_env.resolve_npm_cache()

    assert resolved["source"] == "unavailable"
    assert resolved["cache_dir"] is None
    assert resolved["override"] is False
    assert "fallback" in (resolved["reason"] or "")


def test_is_writable_detects_a_denied_write(tmp_path):
    """`os.access` consults permission bits; only a real write is honest."""
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        assert node_env._is_writable(locked) is False
    finally:
        locked.chmod(0o700)

    assert node_env._is_writable(tmp_path / "fresh" / "nested") is True


def test_node_subprocess_env_preserves_the_rest_of_the_environment(monkeypatch, tmp_path):
    """Only the cache is adjusted — PATH and friends must survive.

    Dropping PATH would make `npx` unresolvable and turn a cache fix into a
    "command not found" failure.
    """
    _clear_cache_env(monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(node_env.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(node_env, "FALLBACK_NPM_CACHE", tmp_path / "repo-cache")
    monkeypatch.setattr(
        node_env,
        "_is_writable",
        lambda path: path == (tmp_path / "repo-cache"),
    )

    base = {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"}
    env = node_env.node_subprocess_env(base)

    assert env["PATH"] == "/usr/bin:/bin"
    assert env["LANG"] == "en_US.UTF-8"
    assert env["npm_config_cache"] == str(tmp_path / "repo-cache")
    assert "npm_config_cache" not in base, "base dict must not be mutated"


def test_resolution_is_cached_per_process(monkeypatch, tmp_path):
    """Probing costs a create/unlink; the registry calls get_info() repeatedly."""
    _clear_cache_env(monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(node_env.platform, "system", lambda: "Darwin")

    calls: list[Path] = []

    def counting_is_writable(path: Path) -> bool:
        calls.append(path)
        return True

    monkeypatch.setattr(node_env, "_is_writable", counting_is_writable)

    first = node_env.resolve_npm_cache()
    second = node_env.resolve_npm_cache()

    assert first == second
    assert len(calls) == 1, f"expected one probe, got {len(calls)}"


def test_windows_default_uses_localappdata(monkeypatch):
    _clear_cache_env(monkeypatch)
    monkeypatch.setattr(node_env.platform, "system", lambda: "Windows")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\dev\AppData\Local")

    default = node_env._default_npm_cache()

    assert default == Path(r"C:\Users\dev\AppData\Local") / "npm-cache"


def test_hyperframes_runtime_check_reports_the_cache_it_used(monkeypatch):
    """The runtime check must expose the cache decision.

    `make hyperframes-doctor` and the preflight menu are where a user looks
    when the runtime misbehaves; a silent redirect to a different cache
    directory would make a slow first render look inexplicable.
    """
    from tools.video.hyperframes_compose import HyperFramesCompose

    monkeypatch.setattr(HyperFramesCompose, "_npm_resolve_cache", None, raising=False)
    monkeypatch.setattr(HyperFramesCompose, "_cli_probe_cache", None, raising=False)
    monkeypatch.setattr(
        HyperFramesCompose,
        "_resolve_npm_package",
        classmethod(lambda cls: {"version": "0.8.22"}),
    )
    monkeypatch.setattr(
        HyperFramesCompose,
        "_probe_cli",
        classmethod(lambda cls: {"status": "ok"}),
    )

    check = HyperFramesCompose()._runtime_check()

    assert "npm_cache_dir" in check
    assert "npm_cache_source" in check
    assert check["npm_cache_source"] in {
        "operator",
        "default",
        "fallback",
        "unavailable",
    }


def test_npm_resolve_fails_closed_without_a_writable_cache(monkeypatch):
    """No writable cache anywhere → an actionable message, not npm's EPERM.

    The old text ("Your cache folder contains root-owned files ... sudo chown")
    was wrong on this machine and cost real debugging time.
    """
    import shutil as _shutil

    from tools.video.hyperframes_compose import HyperFramesCompose

    monkeypatch.setattr(HyperFramesCompose, "_npm_resolve_cache", None, raising=False)
    monkeypatch.setattr(_shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        node_env,
        "resolve_npm_cache",
        lambda: {
            "cache_dir": None,
            "source": "unavailable",
            "override": False,
            "reason": "nothing writable",
        },
    )
    monkeypatch.setattr(
        "tools.video.hyperframes_compose.resolve_npm_cache",
        lambda: {
            "cache_dir": None,
            "source": "unavailable",
            "override": False,
            "reason": "nothing writable",
        },
    )

    result = HyperFramesCompose._resolve_npm_package()

    assert "error" in result
    assert "writable npm cache" in result["error"], (
        "The error must name the real cause so the user can act on it."
    )


def test_run_command_injects_the_cache_for_node_programs(monkeypatch, tmp_path):
    """Every npm/npx/node call site inherits the fix from base_tool.

    Fixing only hyperframes_compose would leave `npx remotion render` to fail
    the same way the next time the sandbox tightens.
    """
    import subprocess

    from tools.base_tool import BaseTool

    _clear_cache_env(monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(node_env.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(node_env, "FALLBACK_NPM_CACHE", tmp_path / "repo-cache")
    monkeypatch.setattr(
        node_env,
        "_is_writable",
        lambda path: path == (tmp_path / "repo-cache"),
    )

    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    class _Probe(BaseTool):
        name = "probe"

        def execute(self, inputs):  # pragma: no cover - not exercised
            raise NotImplementedError

    _Probe().run_command(["npx", "remotion", "render"])

    env = captured["env"]
    assert env is not None, "node programs must receive a prepared environment"
    assert env["npm_config_cache"] == str(tmp_path / "repo-cache")


def test_run_command_leaves_non_node_programs_alone(monkeypatch):
    """ffmpeg and friends keep inheriting the ambient environment."""
    import subprocess

    from tools.base_tool import BaseTool

    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    class _Probe(BaseTool):
        name = "probe"

        def execute(self, inputs):  # pragma: no cover - not exercised
            raise NotImplementedError

    _Probe().run_command(["ffmpeg", "-version"])

    assert captured["env"] is None


def test_run_command_respects_an_explicit_env(monkeypatch):
    """A caller passing env owns it completely."""
    import subprocess

    from tools.base_tool import BaseTool

    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    class _Probe(BaseTool):
        name = "probe"

        def execute(self, inputs):  # pragma: no cover - not exercised
            raise NotImplementedError

    explicit = {"PATH": "/only/this"}
    _Probe().run_command(["npx", "hyperframes", "doctor"], env=explicit)

    assert captured["env"] == explicit


def test_real_environment_resolves_some_cache():
    """Integration: on this machine, a usable cache must be found.

    If this fails, no Node runtime can work here and preflight should be
    saying so loudly rather than blaming npm.
    """
    node_env.reset_cache_for_tests()
    resolved = node_env.resolve_npm_cache()
    assert resolved["source"] != "unavailable", resolved["reason"]
    assert resolved["cache_dir"]
    assert os.path.isdir(resolved["cache_dir"])
