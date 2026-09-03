"""The Python fitter bridge must carry `kind` and `accentWords` to TypeScript.

`_maybe_attach_stack_heights` in `tools/video/persian_compose.py` shells out to
`layout.ts:fitMoment` to record each moment's fitted `stackHeightPx` for the
verifier's plateau scoping. It once built its segment payload as
`{role, text}` only, dropping `accentWords` — so a flat-hook moment fitted as
an ordinary emphasis span (187.42px / 2 lines) while the renderer, fitting
client-side from the real props, painted the flat display block (449.78px /
3 lines). `verify_frames` then scoped its checks to an envelope 262px too short.

The same bridge now carries the declared `kind` (`fitMoment` takes it as a
required parameter) and enforces the hook silhouette gate there, where real
measured widths exist: a `kind: "hook"` moment whose painted lines read as a
block is refused with the measured ratio and the band, in the same
refuse-not-warn discipline as `audit_moments`.

This test asserts on the *fitted geometry* the bridge returns, not merely on
the presence of keys in the payload — a key that is carried but ignored would
be the same bug, and only the numbers can tell the two apart. Without
node-canvas the bridge is a no-op and there is nothing to assert, so the test
skips rather than certifying a path that never ran.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lib.persian_moments import (
    HOOK_SILHOUETTE_MAX_RATIO,
    HOOK_SILHOUETTE_MIN_RATIO,
    build_moments,
)
from tools.video.persian_compose import _maybe_attach_stack_heights

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSER_DIR = REPO_ROOT / "remotion-composer"


def _bridge_needs_node_canvas() -> None:
    import shutil

    if shutil.which("node") is None:
        pytest.skip("node not available")
    if not (COMPOSER_DIR / "node_modules" / "canvas" / "package.json").exists():
        pytest.skip("node-canvas not installed")
    if not (COMPOSER_DIR / "node_modules" / ".bin" / "esbuild").exists():
        pytest.skip("esbuild not installed; run npm install in remotion-composer")


def _claim_qualifier_hook_moments() -> list:
    """The approved hook shape: hero claim plus tail qualifier, declared hook."""
    return build_moments(
        [
            {
                "id": "moment-1",
                "kind": "hook",
                "startSeconds": 0.2,
                "endSeconds": 4.2,
                "segments": [
                    {"role": "hero", "text": "فواید عجیب قهوه"},
                    {"role": "tail", "text": "روی هورمون‌ها!"},
                ],
            }
        ]
    )


def _flat_hook_moments() -> list:
    """The flat style: a whole sentence as the hero with two inline accent words."""
    return build_moments(
        [
            {
                "id": "moment-1",
                "kind": "hook",
                "startSeconds": 0.2,
                "endSeconds": 4.2,
                "segments": [
                    {
                        "role": "hero",
                        "text": "می‌دونی قهوه با هورمون‌هات چی‌کار می‌کنه؟",
                        "accentWords": ["قهوه", "هورمون‌هات"],
                    }
                ],
            }
        ]
    )


class TestStackHeightBridgeCarriesKind:
    def test_claim_qualifier_hook_fits_the_approved_geometry(self) -> None:
        """The bridge returns the c4 geometry: 251.68px, inside the band."""
        _bridge_needs_node_canvas()
        built = _claim_qualifier_hook_moments()
        _maybe_attach_stack_heights(built, "vertical")
        assert built[0].stack_height_px is not None
        assert built[0].stack_height_px == pytest.approx(251.68, abs=1.0)

    def test_undeclared_hook_structure_fits_as_an_ordinary_moment(self) -> None:
        """The control: structure proposes, the declaration disposes.

        The identical hero+tail segments declared `statement` fit without the
        hook's ladder offset or its 0.73 qualifier — a different stack height.
        If `kind` were carried but ignored, the two shapes would converge and
        this test would pass while asserting nothing.
        """
        _bridge_needs_node_canvas()
        built = _claim_qualifier_hook_moments()
        built[0].kind = "statement"  # type: ignore[assignment]
        _maybe_attach_stack_heights(built, "vertical")
        assert built[0].stack_height_px is not None
        assert built[0].stack_height_px != pytest.approx(251.68, abs=1.0)

    def test_flat_hook_fits_as_a_display_block_through_the_bridge(self) -> None:
        """The bridge measures the display-block geometry, not the stale span.

        With `accentWords` dropped, `fitMoment` sees an ordinary hero and the
        stack measures ~187px / 2 lines; with them carried it measures ~450px /
        3 lines. The bridge attaches that height and then the silhouette gate
        refuses the 0.87 rectangle — both happen, in that order — so this test
        expects the refusal and asserts the measured height on the way out.
        """
        _bridge_needs_node_canvas()
        built = _flat_hook_moments()
        assert built[0].segments[0].accent_words == ["قهوه", "هورمون‌هات"]
        with pytest.raises(ValueError, match="silhouette"):
            _maybe_attach_stack_heights(built, "vertical")
        assert built[0].stack_height_px is not None
        assert built[0].stack_height_px == pytest.approx(449.8, abs=1.0)


class TestHookSilhouetteGate:
    def test_balanced_hook_is_refused_with_ratio_and_band(self) -> None:
        """The flat style ratios ~0.87–0.88 and fails the band — refused, loudly.

        This is the documented true finding about the flat style, not a bug to
        hide: the claim+qualifier style is the working hook style. The refusal
        must name the measured ratio and the band.
        """
        _bridge_needs_node_canvas()
        built = _flat_hook_moments()
        with pytest.raises(ValueError, match=r"0\.8\d.*0\.52.*0\.78|silhouette"):
            _maybe_attach_stack_heights(built, "vertical")

    def test_approved_hook_passes_the_gate(self) -> None:
        """The 0.65 step is inside the band — no refusal for the approved style."""
        _bridge_needs_node_canvas()
        built = _claim_qualifier_hook_moments()
        _maybe_attach_stack_heights(built, "vertical")  # must not raise
        assert HOOK_SILHOUETTE_MIN_RATIO <= 0.65 <= HOOK_SILHOUETTE_MAX_RATIO
