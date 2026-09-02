"""Regression guard: the Persian pipeline must not disturb what already worked.

The Persian work added a composition to `Root.tsx`, a tool to `tools/video/`, and a
manifest to `pipeline_defs/`. Each of those is a shared file or a shared registry, and
the failure mode for all three is the same: an addition that quietly changes how an
existing pipeline resolves.

That failure is invisible in normal use — every Persian render can pass while, say,
`documentary-montage` now resolves to the wrong composition. These tests pin the
pre-existing behaviour so the regression surfaces here instead of in someone's render.

The values below are transcribed from the state before the Persian work. They are
intentionally hard-coded rather than derived: a test that computes the expected value
from the same source it is checking cannot detect a change to that source.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT_TSX = REPO_ROOT / "remotion-composer" / "src" / "Root.tsx"

#: Every composition ID registered before the Persian pipeline existed.
PRE_EXISTING_COMPOSITIONS = (
    "Explainer",
    "CinematicRenderer",
    "SignalFromTomorrowWithMusic",
    "TalkingHead",
    "TitledVideo",
    "HeroTitle",
    "ProductReveal",
    "ProductRevealVertical",
    "CaptionOverlayOnly",
    "CollageBurst",
    "LyricOverlay",
    "EndTag",
    "EndTagOverlay",
)

#: renderer_family → composition ID, exactly as it was before this work.
PRE_EXISTING_RENDERER_FAMILIES = {
    "explainer-data": "Explainer",
    "explainer-teacher": "Explainer",
    "cinematic-trailer": "CinematicRenderer",
    "documentary-montage": "CinematicRenderer",
    "product-reveal": "Explainer",
    "screen-demo": "Explainer",
    "presenter": "TalkingHead",
    "animation-first": "Explainer",
}


def _registered_composition_ids() -> list[str]:
    """Composition IDs declared in Root.tsx, by source inspection.

    Parsed from source rather than obtained by running Remotion: this test must fail
    fast in CI without a headless browser, and `npx remotion compositions` takes
    minutes and needs a Chrome download.
    """
    source = ROOT_TSX.read_text(encoding="utf-8")
    return re.findall(r'<Composition\s+id="([^"]+)"', source)


@pytest.mark.parametrize("composition_id", PRE_EXISTING_COMPOSITIONS)
def test_pre_existing_composition_still_registered(composition_id: str) -> None:
    """Every composition that existed before the Persian work still exists.

    Removing or renaming one silently breaks whichever pipeline maps to it, and the
    breakage appears as a Remotion "composition not found" error at render time —
    after the user has already waited through asset acquisition.
    """
    assert composition_id in _registered_composition_ids(), (
        f"Composition {composition_id!r} is no longer registered in Root.tsx. "
        "Pipelines resolve to composition IDs by name; removing one breaks them."
    )


def test_persian_compositions_are_additions_not_replacements() -> None:
    """The Persian compositions were appended, not substituted for anything."""
    ids = _registered_composition_ids()
    assert "PersianFootageVertical" in ids
    assert "PersianFootageLandscape" in ids
    # Every pre-existing ID plus exactly the four new ones: two render targets and
    # two studio-only demo previews.
    assert set(ids) == set(PRE_EXISTING_COMPOSITIONS) | {
        "PersianFootageVertical",
        "PersianFootageLandscape",
        "PersianFootageDemoVertical",
        "PersianFootageDemoLandscape",
    }, f"Unexpected composition set: {sorted(ids)}"


def test_render_targets_do_not_default_to_the_demo_fixture() -> None:
    """The two render targets must default to the empty fixture.

    Remotion shallow-merges `--props` over `defaultProps`, so `defaultProps` is not
    inert: a key the render omits is inherited, not unset. When these compositions
    defaulted to `persianDemoFixture`, every render inherited its two typographic
    beats, and the plate those render is opaque by design — it is an alternative to
    footage, not an overlay. The footage was covered for the first 18 seconds of every
    video while the render reported success.

    Parsed from source because the failure is a one-token change with no runtime
    signal short of measuring pixels.
    """
    source = ROOT_TSX.read_text(encoding="utf-8")

    for composition_id in ("PersianFootageVertical", "PersianFootageLandscape"):
        block = re.search(
            rf'<Composition\s+id="{composition_id}".*?/>', source, re.DOTALL
        )
        assert block is not None, f"{composition_id} is no longer registered"
        assert "persianEmptyFixture" in block.group(0), (
            f"{composition_id} does not default to the empty fixture. Any opaque "
            "default here is inherited by renders that omit the key, which hides "
            "footage without failing the render."
        )
        assert "persianDemoFixture" not in block.group(0), (
            f"{composition_id} defaults to the demo fixture. Its typographic beats "
            "will be inherited by every render that does not pass its own."
        )


def test_composition_ids_are_unique() -> None:
    """No duplicate IDs.

    Remotion resolves by ID; two compositions sharing one means renders silently get
    whichever registered last.
    """
    ids = _registered_composition_ids()
    duplicates = {name for name in ids if ids.count(name) > 1}
    assert not duplicates, f"Duplicate composition IDs: {sorted(duplicates)}"


@pytest.mark.parametrize(
    ("family", "composition"), sorted(PRE_EXISTING_RENDERER_FAMILIES.items())
)
def test_renderer_family_map_unchanged(family: str, composition: str) -> None:
    """Every pre-existing renderer_family resolves to the same composition as before.

    This is the check that matters most. `RENDERER_FAMILY_MAP` is consulted by every
    Remotion pipeline; a Persian entry added carelessly — or a family repointed while
    "tidying" — changes what an unrelated pipeline renders, with no error.
    """
    from tools.video.video_compose import VideoCompose

    assert VideoCompose.RENDERER_FAMILY_MAP.get(family) == composition, (
        f"renderer_family {family!r} now resolves to "
        f"{VideoCompose.RENDERER_FAMILY_MAP.get(family)!r}, expected {composition!r}."
    )


def test_renderer_family_map_gained_nothing() -> None:
    """The Persian pipeline did NOT add a renderer_family entry.

    It renders through its own `persian_compose` tool instead, because the Persian
    composition's props are not a cut list and `video_compose`'s adapters cannot
    produce them. If an entry appears here later, `video_compose` would route Persian
    work into a cut adapter that silently drops the cues.
    """
    from tools.video.video_compose import VideoCompose

    assert VideoCompose.RENDERER_FAMILY_MAP == PRE_EXISTING_RENDERER_FAMILIES, (
        "RENDERER_FAMILY_MAP changed. The Persian pipeline is designed to render "
        "through persian_compose, not through this map."
    )


def test_unknown_renderer_family_still_raises() -> None:
    """The guard against an unset renderer_family still works."""
    from tools.video.video_compose import VideoCompose

    with pytest.raises(ValueError, match="Unknown renderer_family"):
        VideoCompose._get_composition_id("persian-footage")


def test_video_compose_still_available() -> None:
    """Adding a tool did not disturb the existing one's discovery or status."""
    from tools.tool_registry import registry

    registry.ensure_discovered()
    tool = registry.get("video_compose")
    assert tool is not None, "video_compose vanished from the registry"
    assert tool.name == "video_compose"


def test_transcriber_still_available() -> None:
    """The MLX transcriber was added as a second provider, not a replacement."""
    from tools.tool_registry import registry

    registry.ensure_discovered()
    assert registry.get("transcriber") is not None, (
        "transcriber vanished. The MLX tool is an additional provider for the same "
        "capability; it must not displace the portable default."
    )
    assert registry.get("mlx_whisper_transcriber") is not None


def test_pre_existing_manifests_still_load() -> None:
    """Every manifest that shipped before still parses and yields its stages."""
    from lib.checkpoint import get_pipeline_stages

    known = [
        "animated-explainer",
        "documentary-montage",
        "talking-head",
        "framework-smoke",
    ]
    for pipeline in known:
        manifest = REPO_ROOT / "pipeline_defs" / f"{pipeline}.yaml"
        if not manifest.exists():
            continue
        stages = get_pipeline_stages(pipeline)
        assert stages, f"{pipeline} yielded no stages"
