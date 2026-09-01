"""Environment preparation for Node/npm/npx subprocesses.

Every Node-backed runtime in OpenMontage (Remotion via `npx remotion`,
HyperFrames via `npx hyperframes`) shells out to npm tooling. npm needs a
**writable cache directory** for almost everything it does — including the
read-only-looking `npm view`, which writes registry metadata into
`_cacache/tmp` before answering.

When that directory is not writable, npm fails with `EPERM` and prints a
misleading diagnosis ("Your cache folder contains root-owned files"), which
sends the reader chasing a permissions bug that isn't there. The real causes
seen in practice:

- the agent/CI process runs under a file sandbox that only allows writes
  inside the workspace, so `$HOME/.npm` is off-limits;
- `$HOME` is unset, read-only, or points at a different user;
- a container mounts the home directory read-only.

In all of those cases the runtime is genuinely installable — only the cache
location is wrong. Reporting "HyperFrames is unavailable" there is a false
negative, and a silent one: preflight shows a red capability the user cannot
act on because the printed hint (`sudo chown ...`) does not apply.

This module resolves a cache directory that is actually writable, preferring
the operator's own configuration and falling back to a repo-local cache.
"""

from __future__ import annotations

import os
import platform
import uuid
from pathlib import Path
from typing import Optional

from lib.paths import REPO_ROOT

# Repo-local fallback. Gitignored; regenerable; shared by every Node runtime
# so one warm-up benefits Remotion and HyperFrames alike.
FALLBACK_NPM_CACHE = REPO_ROOT / ".cache" / "npm"

# npm reads the cache location from either spelling of the config env var.
_CACHE_ENV_VARS = ("npm_config_cache", "NPM_CONFIG_CACHE")

# Resolved once per process: probing writability costs a file create/unlink.
_resolved: Optional[dict[str, Optional[str]]] = None


def _default_npm_cache() -> Optional[Path]:
    """Return npm's built-in default cache directory for this platform."""
    if platform.system() == "Windows":
        local_appdata = os.environ.get("LOCALAPPDATA")
        if not local_appdata:
            return None
        return Path(local_appdata) / "npm-cache"
    home = os.environ.get("HOME") or os.path.expanduser("~")
    if not home or home == "~":
        return None
    return Path(home) / ".npm"


def _is_writable(path: Path) -> bool:
    """True only if a file can actually be created inside `path`.

    `os.access(..., W_OK)` is not sufficient: it consults permission bits,
    while sandbox denials and read-only mounts surface only on the real
    syscall. Create-and-remove is the only honest test.
    """
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    probe = path / f".openmontage-write-probe-{uuid.uuid4().hex}"
    try:
        probe.touch()
    except OSError:
        return False
    else:
        try:
            probe.unlink()
        except OSError:
            pass
        return True


def resolve_npm_cache() -> dict[str, Optional[str]]:
    """Decide which npm cache directory Node subprocesses should use.

    Returns a diagnostic dict, cached for the life of the process:

    - ``cache_dir``  — directory to use, or None if none could be prepared
    - ``source``     — ``"operator"`` (already configured via env),
                       ``"default"`` (npm's own default works),
                       ``"fallback"`` (repo-local cache substituted), or
                       ``"unavailable"``
    - ``override``   — True when callers must inject ``npm_config_cache``
    - ``reason``     — why the default was rejected, when it was

    Never raises: a cache problem must degrade to a clear diagnostic, not an
    exception inside a preflight probe.
    """
    global _resolved
    if _resolved is not None:
        return _resolved

    for var in _CACHE_ENV_VARS:
        configured = os.environ.get(var)
        if configured:
            # The operator chose this explicitly — honour it even if the probe
            # would fail, so their configuration stays authoritative and any
            # resulting error names their own directory.
            _resolved = {
                "cache_dir": configured,
                "source": "operator",
                "override": False,
                "reason": None,
            }
            return _resolved

    default = _default_npm_cache()
    if default is not None and _is_writable(default):
        _resolved = {
            "cache_dir": str(default),
            "source": "default",
            "override": False,
            "reason": None,
        }
        return _resolved

    reason = (
        f"npm default cache {default} is not writable"
        if default is not None
        else "npm default cache location could not be determined (HOME unset?)"
    )

    if _is_writable(FALLBACK_NPM_CACHE):
        _resolved = {
            "cache_dir": str(FALLBACK_NPM_CACHE),
            "source": "fallback",
            "override": True,
            "reason": reason,
        }
        return _resolved

    _resolved = {
        "cache_dir": None,
        "source": "unavailable",
        "override": False,
        "reason": (
            f"{reason}; repo-local fallback {FALLBACK_NPM_CACHE} is not writable either"
        ),
    }
    return _resolved


def node_subprocess_env(base: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Environment for an npm/npx subprocess, with a writable cache guaranteed.

    Pass the result as ``subprocess.run(..., env=node_subprocess_env())``.
    When npm's own default cache works, this is just a copy of the current
    environment; the override is added only when it is needed.
    """
    env = dict(os.environ if base is None else base)
    resolved = resolve_npm_cache()
    if resolved["override"] and resolved["cache_dir"]:
        env["npm_config_cache"] = resolved["cache_dir"]
    return env


def reset_cache_for_tests() -> None:
    """Clear the per-process resolution. Test-only."""
    global _resolved
    _resolved = None


if __name__ == "__main__":  # pragma: no cover - shell helper
    # `python -m lib.node_env` prints the resolved cache directory (or an empty
    # line if none could be prepared) so Makefile targets and shell scripts can
    # export npm_config_cache without duplicating the resolution logic:
    #
    #   npm_config_cache="$(python -m lib.node_env)" npx --yes hyperframes doctor
    _info = resolve_npm_cache()
    print(_info["cache_dir"] or "")
