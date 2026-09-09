"""Film Type 2.5 is the default (and only non-explicit) path for persian-footage.

Locked behavior (grilled 2026-09-08):
- Scope is persian-footage only; enforcement lives in PersianCompose._build_props.
- Absent `persian.design` is REFUSED (Legacy disabled); the agent must set
  {"version": 2, "profile": "film-type", "seed": "<project-id>-film-type-01"}.
- Hidden emergency opt-out: explicit {"version": 2, "profile": "legacy"} still
  renders the Legacy path.
- Explicit quiet-editorial is unchanged.
- lib/persian_design.py semantics are untouched: resolve_design(None) is still
  None there; the refusal happens in the compose tool, not in the library.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from tools.video.persian_compose import PersianCompose

ROOT = Path(__file__).resolve().parents[2]
DESIGN_SCHEMA = json.loads(
    (ROOT / "schemas" / "artifacts" / "edit_decisions.schema.json").read_text(
        encoding="utf-8"
    )
)["properties"]["persian"]["properties"]["design"]


@pytest.fixture
def clip(tmp_path: Path) -> Path:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"\x00" * 64)
    return path


@pytest.fixture
def staging(tmp_path: Path) -> Path:
    return tmp_path / "staging"


def _persian(clip: Path, **overrides: object) -> dict:
    base: dict = {
        "format": "vertical",
        "durationSeconds": 12.0,
        "shots": [
            {
                "id": "s1",
                "source": str(clip),
                "startSeconds": 0.0,
                "endSeconds": 12.0,
                "sourceInSeconds": 0.0,
                "camera": "none",
                "attribution": "Video by Someone on Pexels",
            }
        ],
        "moments": [
            {
                "id": "moment-1",
                "kind": "statement",
                "startSeconds": 0.4,
                "endSeconds": 4.4,
                "segments": [
                    {"role": "lead", "text": "پیام این ویدیو:"},
                    {"role": "hero", "text": "سلام دنیا"},
                ],
            }
        ],
    }
    base.update(overrides)
    return base


def _film_type_design(seed: str = "test-project-film-type-01") -> dict:
    return {"version": 2, "profile": "film-type", "seed": seed}


def _build(persian: dict, staging: Path) -> tuple[dict, list[str]]:
    return PersianCompose()._build_props(persian, staging, "run-test")


class TestAbsentDesignIsRefused:
    def test_absent_design_is_refused_not_legacy(
        self, clip: Path, staging: Path
    ) -> None:
        """No video may render from the Legacy path by accident.

        Absent `persian.design` used to mean Legacy. It now fails loudly and
        tells the caller exactly what to set instead.
        """
        with pytest.raises(ValueError, match="film-type"):
            _build(_persian(clip), staging)

    def test_unversioned_design_is_refused(
        self, clip: Path, staging: Path
    ) -> None:
        """A legacy-shaped object (no version) is still absent design."""
        with pytest.raises(ValueError, match="film-type"):
            _build(_persian(clip, design={"seed": "old"}), staging)

    def test_refusal_names_the_remediation(
        self, clip: Path, staging: Path
    ) -> None:
        """An error that does not say what to do instead gets worked around."""
        with pytest.raises(ValueError, match="persian\\.design"):
            _build(_persian(clip), staging)


class TestHiddenLegacyOptOut:
    def test_explicit_legacy_still_renders_legacy(
        self, clip: Path, staging: Path
    ) -> None:
        """The emergency escape hatch: explicit legacy profile, no design key
        in props, legacy moment path (v2=False refuses empty moments)."""
        props, _ = _build(
            _persian(clip, design={"version": 2, "profile": "legacy"}), staging
        )
        assert "design" not in props

    def test_explicit_legacy_keeps_legacy_empty_moment_refusal(
        self, clip: Path, staging: Path
    ) -> None:
        with pytest.raises(ValueError, match="moments is empty"):
            _build(
                _persian(
                    clip,
                    design={"version": 2, "profile": "legacy"},
                    moments=[],
                ),
                staging,
            )


class TestExplicitPathsUnchanged:
    def test_quiet_editorial_still_resolves(
        self, clip: Path, staging: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # This is a routing unit test, so provide the loaded-font bridge result
        # explicitly instead of depending on an optional native canvas package.
        measurement = {"widthPx": 216.0, "heightPx": 54.0}

        def measured_bridge(built, *args, **kwargs):
            for moment in built:
                object.__setattr__(moment, "stack_height_px", 180.0)
                object.__setattr__(moment, "stack_width_px", 420.0)
                object.__setattr__(
                    moment,
                    "layout_geometry",
                    {"x": 0.30, "y": 0.40, "w": 0.39, "h": 0.10},
                )
            return measurement

        monkeypatch.setattr(
            "tools.video.persian_compose._maybe_attach_stack_heights",
            measured_bridge,
        )
        props, _ = _build(
            _persian(
                clip,
                design={
                    "version": 2,
                    "profile": "quiet-editorial",
                    "seed": "frozen",
                },
            ),
            staging,
        )
        assert props["design"]["profile"] == "quiet-editorial"
        assert props["watermarkMeasurement"] == measurement
        assert props["watermarkPlan"]


class TestDesignSchemaShapes:
    """The checkpoint schema must accept the shapes the tool accepts."""

    def test_legacy_optout_validates_against_schema(self) -> None:
        jsonschema.validate(
            {"version": 2, "profile": "legacy"},
            DESIGN_SCHEMA,
        )

    def test_film_type_seed_design_validates_against_schema(self) -> None:
        jsonschema.validate(
            _film_type_design(),
            DESIGN_SCHEMA,
        )
