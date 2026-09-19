from __future__ import annotations

import lib.persian_edit_workspace as workspace
import lib.persian_preflight as preflight


def test_preflight_policy_version_invalidates_pre_subject_region_cache() -> None:
    digest = "a" * 64
    stale = {
        "artifactSha256": digest,
        "policyVersion": "2.0",
        "ok": False,
    }
    assert preflight.PREFLIGHT_POLICY_VERSION != "2.0"
    assert workspace._valid_cached_report(stale, digest=digest) is False


def test_current_preflight_policy_cache_is_reusable() -> None:
    digest = "b" * 64
    current = {
        "artifactSha256": digest,
        "policyVersion": preflight.PREFLIGHT_POLICY_VERSION,
        "ok": True,
    }
    assert workspace._valid_cached_report(current, digest=digest) is True
