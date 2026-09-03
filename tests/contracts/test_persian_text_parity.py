"""Python ↔ TypeScript parity for the Persian text layer.

The same text rules exist twice: `lib/persian_text.py` gates the pipeline, and
`remotion-composer/src/persian/text.ts` drives the renderer. That duplication is
unavoidable — one runs in Python before the render, the other in a browser during it —
but it is only safe while the two agree.

When they drift, the failure is quiet and specific: the gate passes text that the
renderer breaks differently than the gate assumed, so a cue that was verified as
readable renders with a stranded «را» or shrunken type. Nothing errors.

These tests run both implementations over one shared corpus and compare outputs. The
corpus is deliberately built from the cases that distinguish the rules rather than from
natural prose, since natural prose exercises maybe three of them.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from lib.persian_text import (
    break_class,
    compare_key,
    measurable_text,
    normalize,
    to_ascii_digits,
    to_persian_digits,
    visible_length,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSER_DIR = REPO_ROOT / "remotion-composer"
TS_MODULE = COMPOSER_DIR / "src" / "persian" / "text.ts"

#: Words chosen so that each exercises a distinct rule. Natural prose would exercise
#: only the common ones and leave the interesting branches untested.
CORPUS_WORDS = [
    # ZWNJ compounds
    "می\u200cروم",
    "نمی\u200cشود",
    "توییت\u200cها",
    "دستی\u200cتر",
    "هم\u200cکلاسی",
    "نیم\u200cفاصله",
    "پس\u200cزمینه",
    # Arabic letters that must fold
    "كي",
    "مي\u200cروم",
    "علىّ",
    "مسأله",
    # Proclitics and enclitics
    "به",
    "از",
    "با",
    "در",
    "برای",
    "که",
    "را",
    "رو",
    "هم",
    "دیگه",
    # Light-verb conjugations
    "کنه",
    "می\u200cکند",
    "شد",
    "باشند",
    "بزنیم",
    # Explicit ezafe
    "واکنشِ",
    "خانه\u200cی",
    "تجربهٔ",
    # Digits and punctuation
    "۱۴۰۳",
    "2024",
    "٥",
    "رفتم،",
    "چرا؟",
    "تمام.",
    "بعد؛",
    "اما",
    "ولی",
    "پس",
    "چون",
    # Mixed scripts
    "Remotion",
    "OpenMontage",
    "fa-IR",
    # Combining marks and edge cases
    "سلام",
    "\u200c",
    "…",
]

#: Whole strings, for the sentence-level functions.
CORPUS_TEXTS = [
    "این جمله نشان می\u200cدهد که نیم\u200cفاصله درست رندر می\u200cشود",
    "شکستن خطِ فارسی باید به گونه\u200cای باشد که حرف اضافه را رها نکند",
    "تجربهٔ ما با Remotion و ۳۰ فریم در ثانیه",
    "سال ۱۴۰۳ و 2024 و ٥",
    "كي مي\u200cروم؟",
    "خوانایی و زیبایی هم\u200cزمان",
    "",
    "\u200c\u200d\u200e\u200f",
]


def _esbuild() -> Path:
    binary = COMPOSER_DIR / "node_modules" / ".bin" / "esbuild"
    if not binary.exists():
        pytest.skip("esbuild not installed; run npm install in remotion-composer")
    return binary


@pytest.fixture(scope="module")
def ts_results() -> dict:
    """Run the TypeScript implementation over the corpus and return its output.

    The module is bundled with esbuild and executed in Node. Bundling rather than
    transpiling in isolation is what makes this a real parity test: it exercises the
    same module graph the renderer imports, so a broken import shows up here.
    """
    if shutil.which("node") is None:
        pytest.skip("node not available")

    esbuild = _esbuild()
    driver = COMPOSER_DIR / ".persian-parity-driver.mjs"
    bundle = COMPOSER_DIR / ".persian-parity-bundle.mjs"

    driver.write_text(
        """
import {
  breakClass, compareKey, measurableText, normalize,
  toAsciiDigits, toPersianDigits, visibleLength,
} from "./src/persian/text.ts";

const words = JSON.parse(process.argv[2]);
const texts = JSON.parse(process.argv[3]);

const out = {
  words: words.map((w) => ({
    normalize: normalize(w),
    measurableText: measurableText(w),
    visibleLength: visibleLength(w),
    compareKey: compareKey(w),
    toPersianDigits: toPersianDigits(w),
    toAsciiDigits: toAsciiDigits(w),
  })),
  breaks: [],
  texts: texts.map((t) => ({
    normalize: normalize(t),
    measurableText: measurableText(t),
    visibleLength: visibleLength(t),
    toPersianDigits: toPersianDigits(t),
  })),
};

for (const a of words) {
  for (const b of words) {
    out.breaks.push(breakClass(a, b));
  }
}

process.stdout.write(JSON.stringify(out));
""",
        encoding="utf-8",
    )

    try:
        build = subprocess.run(
            [
                str(esbuild),
                str(driver),
                "--bundle",
                "--format=esm",
                "--platform=node",
                f"--outfile={bundle}",
                "--log-level=error",
            ],
            capture_output=True,
            text=True,
            timeout=180,
            cwd=COMPOSER_DIR,
        )
        if build.returncode != 0:
            pytest.fail(f"esbuild failed: {build.stderr}")

        run = subprocess.run(
            [
                "node",
                str(bundle),
                json.dumps(CORPUS_WORDS, ensure_ascii=False),
                json.dumps(CORPUS_TEXTS, ensure_ascii=False),
            ],
            capture_output=True,
            text=True,
            timeout=180,
            cwd=COMPOSER_DIR,
        )
        if run.returncode != 0:
            pytest.fail(f"node driver failed: {run.stderr}")
        return json.loads(run.stdout)
    finally:
        driver.unlink(missing_ok=True)
        bundle.unlink(missing_ok=True)


@pytest.mark.parametrize("index", range(len(CORPUS_WORDS)))
def test_normalize_parity(ts_results: dict, index: int) -> None:
    """Letter folding and NFC composition agree.

    Divergence here is the most damaging kind and also the most invisible: the gate
    would fold «كي» to «کی» and the renderer would paint «كي», so the text on the frame
    is not the text that was measured, fitted, and approved — while both sides report
    success.
    """
    word = CORPUS_WORDS[index]
    assert ts_results["words"][index]["normalize"] == normalize(word), (
        f"normalize({word!r}) differs between Python and TypeScript"
    )


@pytest.mark.parametrize("index", range(len(CORPUS_WORDS)))
def test_measurable_text_parity(ts_results: dict, index: int) -> None:
    """The string handed to the measurer agrees.

    This one directly controls line breaking: a character stripped on one side and kept
    on the other changes measured width, which changes where lines break.
    """
    word = CORPUS_WORDS[index]
    assert ts_results["words"][index]["measurableText"] == measurable_text(word)


@pytest.mark.parametrize("index", range(len(CORPUS_WORDS)))
def test_visible_length_parity(ts_results: dict, index: int) -> None:
    """Reading-speed accounting agrees.

    The Python side enforces 21 chars/second at the gate; if the TS side counts
    differently, the renderer's own budget checks disagree with the gate that approved
    the cue.
    """
    word = CORPUS_WORDS[index]
    assert ts_results["words"][index]["visibleLength"] == visible_length(word)


@pytest.mark.parametrize("index", range(len(CORPUS_WORDS)))
def test_compare_key_parity(ts_results: dict, index: int) -> None:
    """Light-verb and enclitic recognition agrees.

    Feeds `break_class` on both sides, so a divergence moves a legal break — the gate
    fits a line the renderer then breaks somewhere else.
    """
    word = CORPUS_WORDS[index]
    assert ts_results["words"][index]["compareKey"] == compare_key(word)


@pytest.mark.parametrize("index", range(len(CORPUS_WORDS)))
def test_digit_conversion_parity(ts_results: dict, index: int) -> None:
    """Digit conversion agrees in both directions."""
    word = CORPUS_WORDS[index]
    assert ts_results["words"][index]["toPersianDigits"] == to_persian_digits(word)
    assert ts_results["words"][index]["toAsciiDigits"] == to_ascii_digits(word)


def test_break_class_parity_over_all_pairs(ts_results: dict) -> None:
    """Every ordered word pair classifies identically.

    All pairs, not a sample: the break rules are a disjunction of several conditions,
    and a sample can easily miss the one pair where two conditions interact — a light
    verb that is also an enclitic, say.
    """
    ts_breaks = ts_results["breaks"]
    mismatches: list[str] = []
    cursor = 0

    for first in CORPUS_WORDS:
        for second in CORPUS_WORDS:
            python_value = break_class(first, second).value
            ts_value = ts_breaks[cursor]
            if python_value != ts_value:
                mismatches.append(
                    f"({first!r}, {second!r}): python={python_value} ts={ts_value}"
                )
            cursor += 1

    assert not mismatches, (
        f"{len(mismatches)} of {cursor} pairs disagree:\n  " + "\n  ".join(mismatches[:20])
    )


@pytest.mark.parametrize("index", range(len(CORPUS_TEXTS)))
def test_sentence_level_parity(ts_results: dict, index: int) -> None:
    """Whole-sentence functions agree, including on empty and controls-only input."""
    text = CORPUS_TEXTS[index]
    result = ts_results["texts"][index]
    assert result["normalize"] == normalize(text)
    assert result["measurableText"] == measurable_text(text)
    assert result["visibleLength"] == visible_length(text)
    assert result["toPersianDigits"] == to_persian_digits(text)


#: Pacing constants both sides enforce, as `(tokens.ts name, Python attribute)`.
#:
#: `lib/persian_moments.py` audits a moment set before a render exists; the composition
#: asserts the same rules when it mounts. Two enforcers of one rule is deliberate — the
#: cheap check catches it in seconds and the late one cannot be bypassed — but it only
#: works while both hold the same number. Drift in either direction is silent: a looser
#: renderer passes what the gate rejected, and a stricter one throws mid-render on a
#: moment set the gate approved.
MOMENT_PACING_CONSTANTS = (
    ("MOMENT_READ_CPS", "READ_CPS"),
    ("MOMENT_MIN_SECONDS", "MIN_SECONDS"),
    ("MOMENT_MAX_SECONDS", "MAX_SECONDS"),
    ("MOMENT_MIN_GAP_SECONDS", "MIN_GAP_SECONDS"),
)


@pytest.mark.parametrize(("token_name", "python_name"), MOMENT_PACING_CONSTANTS)
def test_moment_pacing_constant_matches_renderer(
    token_name: str, python_name: str
) -> None:
    """Each pacing constant is the same number in Python and in the renderer's tokens."""
    from lib import persian_moments

    expected = getattr(persian_moments, python_name)
    tokens = (COMPOSER_DIR / "src" / "persian" / "tokens.ts").read_text(encoding="utf-8")

    for line in tokens.splitlines():
        if line.startswith(f"export const {token_name} ") or line.startswith(
            f"export const {token_name}="
        ):
            value = line.split("=", 1)[1].strip().rstrip(";").split("//")[0].strip()
            assert float(value) == float(expected), (
                f"tokens.ts {token_name}={value} but "
                f"lib.persian_moments.{python_name}={expected}"
            )
            return
    pytest.fail(f"{token_name} not found in tokens.ts")


def test_the_srt_reading_ceiling_is_looser_than_the_moment_ceiling() -> None:
    """The two text layers have different jobs, so they must not share a limit.

    A moment is *designed* to be read at a glance while the footage carries the scene, so
    it is paced at 11 chars/sec. A sidecar subtitle transcribes narration a viewer is
    already hearing, and the narration's own delivery sets its rate — 21 chars/sec, which
    is a readability ceiling rather than a design target.

    Asserted as an inequality rather than two exact numbers because the relationship is
    the actual invariant: if the SRT ceiling were tightened below the moment rate, honest
    narration would start failing its own transcription.
    """
    from lib.persian_moments import READ_CPS
    from lib.persian_srt import MAX_CPS

    assert MAX_CPS > READ_CPS
