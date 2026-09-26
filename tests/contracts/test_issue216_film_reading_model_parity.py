"""#216: the Python reading gate charges exactly what the Film Type browser charges.

`lib.persian_moments.PersianMoment.film_step_requirements` must agree with
`filmStepRequirements` in `remotion-composer/src/persian/filmType/layout.ts`, the model
`assertFilmTiming` enforces at render. The old Python model left out the row stagger, the
entrance over fixation and the exit, so moments passed `audit_moments` and were then
refused in the browser.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from lib.persian_moments import audit_moments, build_moments

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSER_DIR = REPO_ROOT / "remotion-composer"
PROFILE = json.loads(
    (REPO_ROOT / "styles" / "persian-footage" / "film-type.json").read_text(encoding="utf-8")
)

CORPUS: list[dict] = [
    {"id": "single-hero", "kind": "statement", "startSeconds": 0.0, "endSeconds": 3.0,
     "segments": [{"role": "hero", "text": "دو روز صبر کردن"}]},
    {"id": "lead-hero-tail", "kind": "statement", "startSeconds": 10.0, "endSeconds": 14.0,
     "segments": [{"role": "lead", "text": "بیشترین تمایل"}, {"role": "hero", "text": "پیام صبح روز بعد"},
                  {"role": "tail", "text": "به ادامهٔ رابطه"}]},
    {"id": "figure-source", "kind": "figure", "startSeconds": 20.0, "endSeconds": 24.5,
     "segments": [{"role": "lead", "text": "در این مطالعه،"}, {"role": "hero", "text": "۵۴۳ نفر"},
                  {"role": "source", "text": "دانشگاه اولو، ۲۰۲۴"}]},
    {"id": "cut-in", "kind": "statement", "startSeconds": 30.0, "endSeconds": 33.0,
     "presentation": {"motion": "cut-in"},
     "segments": [{"role": "hero", "text": "کمتر قابل‌اعتماد"}, {"role": "tail", "text": "می‌دیدند."}]},
    {"id": "build", "kind": "statement", "startSeconds": 40.0, "endSeconds": 46.0,
     "presentation": {"motion": "cut-in", "sequenceMode": "accumulate"},
     "segments": [{"role": "hero", "text": "بلافاصله", "revealAfterSeconds": 0.0},
                  {"role": "hero", "text": "صبح روز بعد", "revealAfterSeconds": 1.6},
                  {"role": "hero", "text": "دو روز بعد", "revealAfterSeconds": 3.4}]},
]


def _ts_requirements() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node not available")
    esbuild = COMPOSER_DIR / "node_modules" / ".bin" / "esbuild"
    if not esbuild.exists():
        pytest.skip("esbuild not installed; run npm install in remotion-composer")
    driver = COMPOSER_DIR / ".film-reading-parity-driver.mjs"
    bundle = COMPOSER_DIR / ".film-reading-parity-bundle.mjs"
    driver.write_text(
        """
import { filmStepRequirements } from "./src/persian/filmType/readingModel.ts";
const moments = JSON.parse(process.argv[2]);
const profile = JSON.parse(process.argv[3]);
const out = {};
for (const m of moments) out[m.id] = filmStepRequirements(m, profile);
process.stdout.write(JSON.stringify(out));
""",
        encoding="utf-8",
    )
    try:
        build = subprocess.run(
            [str(esbuild), str(driver), "--bundle", "--format=esm", "--platform=node",
             f"--outfile={bundle}", "--log-level=error"],
            capture_output=True, text=True, timeout=180, cwd=COMPOSER_DIR,
        )
        if build.returncode != 0:
            pytest.fail(f"esbuild failed: {build.stderr}")
        props = [moment.to_props() for moment in build_moments(CORPUS)]
        run = subprocess.run(
            ["node", str(bundle), json.dumps(props, ensure_ascii=False),
             json.dumps(PROFILE, ensure_ascii=False)],
            capture_output=True, text=True, timeout=180, cwd=COMPOSER_DIR,
        )
        if run.returncode != 0:
            pytest.fail(f"node driver failed: {run.stderr}")
        return json.loads(run.stdout)
    finally:
        driver.unlink(missing_ok=True)
        bundle.unlink(missing_ok=True)


@pytest.fixture(scope="module")
def ts_results() -> dict:
    return _ts_requirements()


@pytest.mark.parametrize("moment_id", [item["id"] for item in CORPUS])
def test_step_requirements_match_the_browser(ts_results: dict, moment_id: str) -> None:
    moment = next(m for m in build_moments(CORPUS) if m.id == moment_id)
    python_rows = moment.film_step_requirements(PROFILE["motion"])
    browser_rows = ts_results[moment_id]
    assert len(python_rows) == len(browser_rows)
    for (start, needed, available), row in zip(python_rows, browser_rows, strict=True):
        assert start == pytest.approx(row["start"], abs=1e-9)
        assert needed == pytest.approx(row["needed"], abs=1e-9)
        assert available == pytest.approx(row["available"], abs=1e-9)


def test_audit_refuses_a_moment_the_plain_model_accepted_but_the_browser_refuses() -> None:
    """The Mac run's failure shape: long enough for the old estimate, short for the render."""
    authored = [dict(CORPUS[1])]
    moment = build_moments(authored)[0]
    plain = moment.min_read_seconds
    film = moment.film_min_read_seconds(PROFILE["motion"])
    assert film > plain
    authored[0] = {**authored[0], "endSeconds": authored[0]["startSeconds"] + (plain + film) / 2}
    between = build_moments(authored)
    plain_audit = audit_moments(between, duration_seconds=60.0)
    film_audit = audit_moments(between, duration_seconds=60.0, film_motion=PROFILE["motion"])
    assert not any("needs" in p and between[0].id in p for p in plain_audit.problems)
    assert any("as Film Type charges it" in p for p in film_audit.problems)


def test_retime_extends_to_the_film_floor() -> None:
    from lib.persian_sync import TimedWord, retime_moments

    moment = build_moments([{**CORPUS[1], "anchorText": "پیام صبح روز بعد"}])[0]
    words = [
        TimedWord(word=w, start=10.0 + i * 0.2, end=10.15 + i * 0.2)
        for i, w in enumerate(["پیام", "صبح", "روز", "بعد"])
    ]
    plain = retime_moments([moment], words)[0]
    film = retime_moments([moment], words, film_motion=PROFILE["motion"])[0]
    assert film.duration == pytest.approx(moment.film_min_read_seconds(PROFILE["motion"]))
    assert film.duration > plain.duration
