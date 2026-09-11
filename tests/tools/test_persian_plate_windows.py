"""Plate windows are derived from typography, never authored independently.

A typographic beat paints an opaque near-black plate (voidBackground #0B0B0C,
luma ~17 where 16 is pure black). An authored window wider than the type it
covers would leave empty black frame on screen, so each window is cut to the
span of the typography inside it — never passed through verbatim.

Association is by time overlap: beats carry only id/startSeconds/endSeconds
(schema: edit_decisions.schema.json `typographicBeats`; types.ts
`PersianTypographicBeat`) — no moment reference exists. So a beat owns exactly
the moments it overlaps, and each contiguous run of owned moments gets its own
window; a gap between owned moments splits the beat rather than plating the gap.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from tools.video.persian_compose import PersianCompose


@pytest.fixture
def clip(tmp_path: Path) -> Path:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"\x00" * 64)
    return path


@pytest.fixture
def staging(tmp_path: Path) -> Path:
    return tmp_path / "staging"


def _moment(
    moment_id: str, start: float, end: float, hero: str = "سلام دنیا"
) -> dict:
    return {
        "id": moment_id,
        "kind": "statement",
        "startSeconds": start,
        "endSeconds": end,
        "segments": [
            {"role": "lead", "text": "پیام این ویدیو:"},
            {"role": "hero", "text": hero},
        ],
    }


def _persian(clip: Path, moments: list[dict], beats: list[dict]) -> dict:
    return {
        # Explicit Legacy opt-out (see test_persian_default_film_type.py):
        # these tests pin design-independent plate-window gates.
        "design": {"version": 2, "profile": "legacy"},
        "format": "vertical",
        "durationSeconds": 20.0,
        "shots": [
            {
                "id": "s1",
                "source": str(clip),
                "startSeconds": 0.0,
                "endSeconds": 20.0,
                "sourceInSeconds": 0.0,
                "camera": "none",
                "attribution": "Video by Someone on Pexels",
            }
        ],
        "moments": moments,
        "typographicBeats": beats,
    }


def _build(persian: dict, staging: Path) -> tuple[dict, list[str]]:
    return PersianCompose()._build_props(persian, staging, "run-test")


def _opener() -> dict:
    """First moment within the 0.6s opening deadline, so fixtures reach beats."""
    return _moment("moment-1", 0.4, 4.0, hero="نور")


class TestPlateWindowDerivation:
    def test_a_wider_authored_window_shrinks_to_the_type_span(
        self, clip: Path, staging: Path
    ) -> None:
        """A plate wider than its type leaves empty black frame: cut to the span."""
        moments = [_opener(), _moment("moment-7", 5.0, 8.0)]
        beats = [{"id": "beat-8", "startSeconds": 4.2, "endSeconds": 10.0}]
        props, _ = _build(_persian(clip, moments, beats), staging)
        assert props["typographicBeats"] == [
            {"id": "beat-8", "startSeconds": 5.0, "endSeconds": 8.0}
        ]

    def test_a_beat_matching_its_type_is_unchanged(
        self, clip: Path, staging: Path
    ) -> None:
        moments = [_moment("moment-1", 0.4, 4.4)]
        beats = [{"id": "b1", "startSeconds": 0.4, "endSeconds": 4.4}]
        props, _ = _build(_persian(clip, moments, beats), staging)
        assert props["typographicBeats"] == beats

    def test_a_beat_spanning_two_moments_splits_around_their_gap(
        self, clip: Path, staging: Path
    ) -> None:
        """A min-max union would plate the 7.6-8.6s gap with no type on it."""
        owned = [
            {"id": "m2", "startSeconds": 5.0, "endSeconds": 7.6},
            {"id": "m3", "startSeconds": 8.6, "endSeconds": 11.4},
        ]
        derived = PersianCompose._derive_beat_windows(
            [{"id": "b1", "startSeconds": 4.2, "endSeconds": 12.0}], owned
        )
        assert derived == [
            {"id": "b1-1", "startSeconds": 5.0, "endSeconds": 7.6},
            {"id": "b1-2", "startSeconds": 8.6, "endSeconds": 11.4},
        ]

    def test_touching_moments_merge_into_one_window(
        self, clip: Path, staging: Path
    ) -> None:
        owned = [
            {"id": "m2", "startSeconds": 5.0, "endSeconds": 7.6},
            {"id": "m3", "startSeconds": 7.6, "endSeconds": 11.4},
        ]
        derived = PersianCompose._derive_beat_windows(
            [{"id": "b1", "startSeconds": 4.2, "endSeconds": 12.0}], owned
        )
        assert derived == [
            {"id": "b1", "startSeconds": 5.0, "endSeconds": 11.4}
        ]

    def test_a_whole_timeline_covered_by_shots_needs_no_footage_return(
        self, clip: Path, staging: Path
    ) -> None:
        """A split whose freed seconds still hold footage is not a coverage gap."""
        persian = _persian(
            clip,
            [_opener(), _moment("moment-2", 5.0, 7.6, hero="نور")],
            [{"id": "b1", "startSeconds": 4.2, "endSeconds": 8.0}],
        )
        props, _ = _build(persian, staging)
        assert props["typographicBeats"] == [
            {"id": "b1", "startSeconds": 5.0, "endSeconds": 7.6}
        ]

    def test_a_moment_touching_only_the_beat_edge_does_not_count(
        self, clip: Path, staging: Path
    ) -> None:
        """Zero-width contact is not overlap: the type is never on screen inside."""
        moments = [_opener(), _moment("moment-2", 5.0, 7.6, hero="نور")]
        beats = [{"id": "b1", "startSeconds": 7.6, "endSeconds": 10.0}]
        with pytest.raises(ValueError, match="b1"):
            _build(_persian(clip, moments, beats), staging)

    def test_the_moment_times_are_never_mutated(
        self, clip: Path, staging: Path
    ) -> None:
        """The sync gate owns moment timing; the plate moves to the type."""
        moments = [_moment("moment-1", 0.4, 4.4)]
        beats = [{"id": "b1", "startSeconds": 0.0, "endSeconds": 6.0}]
        props, _ = _build(_persian(clip, moments, beats), staging)
        assert props["moments"][0]["startSeconds"] == pytest.approx(0.4)
        assert props["moments"][0]["endSeconds"] == pytest.approx(4.4)


class TestBeatWithNoTypography:
    def test_a_beat_with_no_moment_is_a_hard_failure_naming_the_beat(
        self, clip: Path, staging: Path
    ) -> None:
        """An empty plate is the original bug in a new costume: refused, not
        dropped (footage returns silently) and not painted (black ships)."""
        moments = [_moment("moment-1", 0.4, 4.4)]
        beats = [{"id": "beat-9", "startSeconds": 10.0, "endSeconds": 14.0}]
        with pytest.raises(ValueError, match="beat-9"):
            _build(_persian(clip, moments, beats), staging)

    def test_the_failure_names_the_beat_window(
        self, clip: Path, staging: Path
    ) -> None:
        moments = [_moment("moment-1", 0.4, 4.4)]
        beats = [{"id": "beat-9", "startSeconds": 10.0, "endSeconds": 14.0}]
        with pytest.raises(ValueError, match="10.0.*14.0|10.*14"):
            _build(_persian(clip, moments, beats), staging)

    def test_no_beats_still_means_no_beats(self, clip: Path, staging: Path) -> None:
        props, _ = _build(
            _persian(clip, [_moment("moment-1", 0.4, 4.4)], []), staging
        )
        assert props["typographicBeats"] == []


class TestPreRenderCoverageGate:
    """The coverage gate lives on the execute path, before any rendering starts.

    `_build_props` is a pure transformation also used by the studio preview
    and by minimal-fixture tests, so it stays gate-free; the gate fires in
    `execute` where the ~200s render is about to be paid for.
    """

    def _execute(self, persian: dict, tmp_path: Path, monkeypatch) -> object:
        from tools.video.persian_compose import PersianCompose

        tool = PersianCompose()
        monkeypatch.setattr(tool, "run_command", lambda *a, **k: (_ for _ in ()).throw(AssertionError("render must not start")))
        inputs = {
            "edit_decisions": {"persian": persian, "render_runtime": "remotion"},
            "output_path": str(tmp_path / "out.mp4"),
        }
        return tool.execute(inputs)

    def test_an_uncovered_gap_fails_before_render(
        self, clip: Path, tmp_path: Path, monkeypatch
    ) -> None:
        """A 0.5s hole between shots names its range and never reaches the renderer."""
        persian = _persian(
            clip,
            [_opener(), _moment("moment-2", 6.0, 9.0, hero="نور")],
            [],
        )
        persian["shots"] = [
            {
                "id": "s1",
                "source": str(clip),
                "startSeconds": 0.0,
                "endSeconds": 5.0,
                "sourceInSeconds": 0.0,
                "camera": "none",
                "attribution": "Video by Someone on Pexels",
            },
            {
                "id": "s2",
                "source": str(clip),
                "startSeconds": 5.5,
                "endSeconds": 20.0,
                "sourceInSeconds": 0.0,
                "camera": "none",
                "attribution": "Video by Someone on Pexels",
            },
        ]
        result = self._execute(persian, tmp_path, monkeypatch)
        assert result.success is False
        assert "5.0-5.5s" in (result.error or "")

    def test_rounding_noise_stays_quiet_before_render(
        self, clip: Path, tmp_path: Path, monkeypatch
    ) -> None:
        """A sub-millisecond seam between shots is float noise, not a failure:
        the gate passes and the (mocked) renderer is reached."""
        import subprocess

        from tools.video.persian_compose import PersianCompose

        persian = _persian(
            clip,
            [_opener(), _moment("moment-2", 6.0, 9.0, hero="نور")],
            [],
        )
        persian["shots"] = [
            {
                "id": "s1",
                "source": str(clip),
                "startSeconds": 0.0,
                "endSeconds": 5.0004,
                "sourceInSeconds": 0.0,
                "camera": "none",
                "attribution": "Video by Someone on Pexels",
            },
            {
                "id": "s2",
                "source": str(clip),
                "startSeconds": 5.0,
                "endSeconds": 20.0,
                "sourceInSeconds": 0.0,
                "camera": "none",
                "attribution": "Video by Someone on Pexels",
            },
        ]
        tool = PersianCompose()
        calls: list = []
        fake_path = tmp_path / "out.mp4"

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            fake_path.write_bytes(b"\x00" * 64)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(tool, "run_command", fake_run)
        monkeypatch.setattr(
            "tools.video.persian_compose.audit_render_luminance",
            lambda *a, **k: mock.Mock(
                passed=True, warn_runs=[], dead_runs=[], to_dict=lambda: {}
            ),
        )
        monkeypatch.setattr(
            "tools.video.persian_compose.audit_render_motion",
            lambda *a, **k: mock.Mock(
                passed=True, warn_runs=[], fail_runs=[], to_dict=lambda: {}
            ),
        )
        result = tool.execute(
            {
                "edit_decisions": {"persian": persian, "render_runtime": "remotion"},
                "output_path": str(fake_path),
            }
        )
        assert calls, "the render must start when only rounding noise separates shots"
        assert result.success is True


class TestPostRenderMotionGate:
    def test_a_long_near_frozen_render_is_refused(self, clip: Path, tmp_path: Path, monkeypatch) -> None:
        import subprocess
        from types import SimpleNamespace

        persian = _persian(clip, [_opener()], [])
        tool = PersianCompose()
        fake_path = tmp_path / "out.mp4"

        def fake_run(cmd, **kwargs):
            fake_path.write_bytes(b"mocked-output")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(tool, "run_command", fake_run)
        monkeypatch.setattr(
            "tools.video.persian_compose.audit_render_luminance",
            lambda *a, **k: mock.Mock(
                passed=True, warn_runs=[], dead_runs=[], to_dict=lambda: {"passed": True}
            ),
        )
        frozen = SimpleNamespace(
            start_seconds=4.0, end_seconds=14.0, mean_abs_delta=0.1
        )
        monkeypatch.setattr(
            "tools.video.persian_compose.audit_render_motion",
            lambda *a, **k: mock.Mock(
                passed=False, warn_runs=[], fail_runs=[frozen],
                to_dict=lambda: {"passed": False, "failRuns": [{"startSeconds": 4.0, "endSeconds": 14.0}]},
            ),
        )
        result = tool.execute({
            "edit_decisions": {"persian": persian, "render_runtime": "remotion"},
            "output_path": str(fake_path),
        })
        assert result.success is False
        assert "anti-slideshow" in (result.error or "")
        assert result.data["post_render_motion_qa"]["passed"] is False


class TestFfmpegMissingAfterRender:
    def test_an_unmeasurable_render_is_refused_not_raised(
        self, clip: Path, tmp_path: Path, monkeypatch
    ) -> None:
        """After a ~200s render, a missing ffmpeg must be an unsuccessful result
        naming the cause — with the file left on disk — not a traceback."""
        import subprocess

        from tools.video.persian_compose import PersianCompose

        persian = _persian(clip, [_opener()], [])
        tool = PersianCompose()
        fake_path = tmp_path / "out.mp4"

        def fake_run(cmd, **kwargs):
            fake_path.write_bytes(b"\x00" * 64)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(tool, "run_command", fake_run)
        monkeypatch.setattr(
            "tools.video.persian_compose.audit_render_luminance",
            mock.Mock(side_effect=RuntimeError("ffmpeg is not on PATH")),
        )
        result = tool.execute(
            {
                "edit_decisions": {"persian": persian, "render_runtime": "remotion"},
                "output_path": str(fake_path),
            }
        )
        assert result.success is False
        assert "ffmpeg" in (result.error or "").lower()
        assert fake_path.exists()
        assert str(fake_path) in (result.artifacts or [])
