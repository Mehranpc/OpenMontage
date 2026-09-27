"""Refuse a Mac production run on a SHA the offline rehearsal has not passed (#265).

A Mac run is acceptance of real footage and taste, not bug-finding. Before
`bootstrap`, the Mac agent runs `make pre-mac`, which checks:

1. the working tree is clean and HEAD equals the SHA being accepted;
2. that SHA's CI check "P4 stabilization L2 (Chromium + FFmpeg)" succeeded;
   that job runs tests/rehearsal, including test_recorded_run_reaches_awaiting_human.

The check-runs API is public for this repository, so no token is needed; set
GITHUB_TOKEN to raise the rate limit. Exit 0 means go; any other exit means do
not start the run, and the message says why.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

REPO = "Mehranpc/OpenMontage"
REHEARSAL_CHECK = "P4 stabilization L2 (Chromium + FFmpeg)"


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def _check_runs(sha: str) -> list[dict]:
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/commits/{sha}/check-runs?per_page=100",
        headers={"Accept": "application/vnd.github+json",
                 **({"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"} if os.environ.get("GITHUB_TOKEN") else {})},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return list(json.load(response).get("check_runs") or [])


def verdict(sha: str, *, head: str, dirty: bool, runs: list[dict]) -> tuple[bool, str]:
    if dirty:
        return False, "working tree has local changes; a Mac acceptance run must be on a clean checkout"
    if head != sha:
        return False, f"HEAD is {head[:12]}, not the SHA being accepted ({sha[:12]}); check it out first"
    matching = [run for run in runs if run.get("name") == REHEARSAL_CHECK]
    if not matching:
        return False, f"no '{REHEARSAL_CHECK}' check ran on {sha[:12]}; wait for CI or pick a SHA it passed"
    latest = max(matching, key=lambda run: str(run.get("completed_at") or run.get("started_at") or ""))
    if latest.get("status") != "completed":
        return False, f"the rehearsal check on {sha[:12]} is still {latest.get('status')}; wait for it"
    if latest.get("conclusion") != "success":
        return False, (f"the rehearsal check on {sha[:12]} concluded '{latest.get('conclusion')}': "
                       "fix it in CI first; a Mac run does not find bugs")
    return True, f"{sha[:12]}: rehearsal passed in CI; clear for a Mac acceptance run"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pre-mac", description=__doc__.splitlines()[0])
    parser.add_argument("--sha", help="SHA to accept (default: HEAD)")
    args = parser.parse_args(argv)
    head = _git("rev-parse", "HEAD")
    sha = _git("rev-parse", args.sha) if args.sha else head
    dirty = bool(_git("status", "--porcelain", "--untracked-files=no"))
    try:
        runs = _check_runs(sha)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"pre-mac: cannot read CI status for {sha[:12]}: {exc}", file=sys.stderr)
        return 2
    ok, message = verdict(sha, head=head, dirty=dirty, runs=runs)
    print(f"pre-mac: {message}", file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
