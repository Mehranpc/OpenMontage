"""#263 item C: a non-Remotion render_runtime is refused with the cheap edit checks.

Compose refuses it only when the render starts, after promotion and preflight. The
field is in the draft.
"""

from __future__ import annotations

import pytest

from lib.persian_edit_contract import collect_persian_edit_diagnostics
from lib.persian_preflight import aggregate_preflight_edit_decisions


def _edit(runtime: str | None) -> dict:
    edit: dict = {"version": "1.0", "renderer_family": "persian-footage", "cuts": [], "persian": {}}
    if runtime is not None:
        edit["render_runtime"] = runtime
    return edit


@pytest.mark.parametrize("runtime", ["ffmpeg", "hyperframes"])
def test_a_swapped_runtime_is_refused_on_the_draft(runtime: str) -> None:
    codes = {item.code for item in collect_persian_edit_diagnostics(_edit(runtime))}
    assert "runtime.not_remotion" in codes


def test_remotion_passes() -> None:
    codes = {item.code for item in collect_persian_edit_diagnostics(_edit("remotion"))}
    assert "runtime.not_remotion" not in codes


def test_the_cheap_precheck_blocks_before_any_browser_pass() -> None:
    report = aggregate_preflight_edit_decisions(_edit("ffmpeg"), cheap_only=True)
    assert report["ok"] is False
    assert "runtime.not_remotion" in {item["code"] for item in report["blockingIssues"]}


# Item G: the design snapshot is resolved with the cheap checks.

def _design_codes(design: object) -> set[str]:
    return {item.code for item in collect_persian_edit_diagnostics({"persian": {"design": design}})}


def test_an_active_film_type_design_resolves() -> None:
    assert "design.snapshot_invalid" not in _design_codes(
        {"version": 2, "profile": "film-type", "seed": "s"}
    )


def test_a_tampered_pinned_snapshot_is_refused_on_the_draft() -> None:
    from lib.persian_design import resolve_design

    pinned = resolve_design({"version": 2, "profile": "film-type", "seed": "s"})
    assert "design.snapshot_invalid" not in _design_codes(pinned)
    tampered = {**pinned, "contentHash": "0" * 64}
    assert "design.snapshot_invalid" in _design_codes(tampered)


def test_an_unversioned_film_type_design_is_refused_on_the_draft() -> None:
    assert "design.snapshot_invalid" in _design_codes({"profile": "film-type", "seed": "s"})
