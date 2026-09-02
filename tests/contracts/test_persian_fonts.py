"""Invariants of the vendored Estedad font.

The Persian composition measures text on a canvas against Estedad and breaks lines
from those measurements. That makes the font a *load-bearing input to layout*, not a
cosmetic choice: replacing a weight, or losing one from `public/`, silently changes
every line break in every video the pipeline has ever produced.

These tests pin the properties layout depends on. They parse the TTFs directly rather
than trusting the filenames, because a file named `Estedad-Medium.ttf` containing a
different weight is exactly the failure that would otherwise go unnoticed.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FONT_DIR = REPO_ROOT / "remotion-composer" / "public" / "fonts" / "estedad"

#: Weights the renderer requests, and the `usWeightClass` each file must declare.
#: 500/700/900 are the three the composition actually uses; 100 and 300 are vendored
#: for future use and pinned so a re-vendor cannot swap them.
EXPECTED_WEIGHTS = {
    "Estedad-Thin.ttf": 100,
    "Estedad-Light.ttf": 300,
    "Estedad-Medium.ttf": 500,
    "Estedad-Bold.ttf": 700,
    "Estedad-Black.ttf": 900,
}

#: The three weights `fonts.ts` loads. Losing one means the browser synthesizes it,
#: and a synthesized bold has different advance widths than the real one — so text
#: measured against the real face overflows when painted with the fake.
RENDERER_WEIGHTS = ("Estedad-Medium.ttf", "Estedad-Bold.ttf", "Estedad-Black.ttf")


def _read_table_directory(data: bytes) -> dict[str, tuple[int, int]]:
    """Parse a TrueType table directory into {tag: (offset, length)}.

    Hand-rolled rather than using fontTools: this repo does not depend on fontTools,
    and a contract test that requires an extra dependency to run is a contract test
    that gets skipped in CI.
    """
    if len(data) < 12:
        raise ValueError("file too short to be a font")
    num_tables = struct.unpack(">H", data[4:6])[0]
    tables: dict[str, tuple[int, int]] = {}
    for index in range(num_tables):
        base = 12 + index * 16
        tag = data[base : base + 4].decode("ascii", errors="replace")
        offset, length = struct.unpack(">II", data[base + 8 : base + 16])
        tables[tag] = (offset, length)
    return tables


def _us_weight_class(path: Path) -> int:
    """`OS/2.usWeightClass` — the numeric weight the browser matches against."""
    data = path.read_bytes()
    tables = _read_table_directory(data)
    offset, _ = tables["OS/2"]
    # usWeightClass sits at offset 4 in the OS/2 table, in every version.
    return struct.unpack(">H", data[offset + 4 : offset + 6])[0]


def _mac_style(path: Path) -> int:
    """`head.macStyle` — bit 0 is italic, bit 1 is bold."""
    data = path.read_bytes()
    tables = _read_table_directory(data)
    offset, _ = tables["head"]
    return struct.unpack(">H", data[offset + 44 : offset + 46])[0]


def _has_glyph(path: Path, codepoint: int) -> bool:
    """Whether the cmap maps `codepoint` to a non-zero glyph ID.

    Only format 4 subtables are walked, which is what Estedad uses for the BMP.
    """
    data = path.read_bytes()
    tables = _read_table_directory(data)
    cmap_offset, _ = tables["cmap"]

    num_subtables = struct.unpack(">H", data[cmap_offset + 2 : cmap_offset + 4])[0]
    for index in range(num_subtables):
        rec = cmap_offset + 4 + index * 8
        subtable_offset = struct.unpack(">I", data[rec + 4 : rec + 8])[0]
        table = cmap_offset + subtable_offset
        fmt = struct.unpack(">H", data[table : table + 2])[0]
        if fmt != 4:
            continue

        seg_count_x2 = struct.unpack(">H", data[table + 6 : table + 8])[0]
        seg_count = seg_count_x2 // 2
        ends = table + 14
        starts = ends + seg_count_x2 + 2
        deltas = starts + seg_count_x2
        ranges = deltas + seg_count_x2

        for seg in range(seg_count):
            end = struct.unpack(">H", data[ends + seg * 2 : ends + seg * 2 + 2])[0]
            if codepoint > end:
                continue
            start = struct.unpack(">H", data[starts + seg * 2 : starts + seg * 2 + 2])[0]
            if codepoint < start:
                break
            delta = struct.unpack(">h", data[deltas + seg * 2 : deltas + seg * 2 + 2])[0]
            range_offset = struct.unpack(
                ">H", data[ranges + seg * 2 : ranges + seg * 2 + 2]
            )[0]
            if range_offset == 0:
                gid = (codepoint + delta) & 0xFFFF
            else:
                glyph_addr = ranges + seg * 2 + range_offset + (codepoint - start) * 2
                gid = struct.unpack(">H", data[glyph_addr : glyph_addr + 2])[0]
                if gid != 0:
                    gid = (gid + delta) & 0xFFFF
            return gid != 0
    return False


@pytest.mark.parametrize("filename", sorted(EXPECTED_WEIGHTS))
def test_font_file_exists(filename: str) -> None:
    """The file is present under `public/`.

    `public/` specifically: Remotion's `staticFile()` resolves there, and the
    repository's `.gitignore` excludes `public/*` with an explicit negation for this
    directory. A font that exists locally but is gitignored renders as tofu on any
    other checkout.
    """
    assert (FONT_DIR / filename).exists(), (
        f"{filename} missing from {FONT_DIR}. The composition measures text against "
        "Estedad; without it, layout falls back to a different face and every line "
        "break changes."
    )


@pytest.mark.parametrize(("filename", "expected"), sorted(EXPECTED_WEIGHTS.items()))
def test_declared_weight_matches_filename(filename: str, expected: int) -> None:
    """The file's `usWeightClass` matches what its name claims."""
    actual = _us_weight_class(FONT_DIR / filename)
    assert actual == expected, (
        f"{filename} declares usWeightClass {actual}, expected {expected}. "
        "The renderer requests weights numerically, so a mismatch means it gets a "
        "different face than the one text was measured against."
    )


@pytest.mark.parametrize("filename", RENDERER_WEIGHTS)
def test_renderer_weights_are_real_not_synthetic(filename: str) -> None:
    """Each weight is a distinct file, so nothing is synthesized.

    A browser asked for weight 700 with only a 500 available will synthesize bold by
    smearing the outlines. Persian's thin horizontal joins smear badly, and the
    synthesized advance widths differ from the real face's — so measurement and paint
    disagree and text overflows the panel.
    """
    path = FONT_DIR / filename
    assert path.exists()
    # macStyle's bold bit must be clear: these are separate static weights selected
    # numerically, not a single face flagged bold.
    assert _mac_style(path) & 0b10 == 0, (
        f"{filename} sets head.macStyle bold bit. These are static weights selected "
        "by usWeightClass; a macStyle bold flag can make the browser double-bold it."
    )


def test_zwnj_has_no_glyph_which_is_expected() -> None:
    """ZWNJ (U+200C) is absent from the cmap — and that is correct.

    This is the trap the whole measurement layer is built around. ZWNJ is a zero-width
    formatting control: the shaper consumes it to select non-joining letterforms and
    it never becomes a glyph. But a naive `ctx.measureText()` on a string containing it
    can charge for a fallback glyph, making measured width exceed painted width — so
    the layout thinks a line overflows when it does not.

    `measure.ts` measures `measurableText()`, which strips these controls. This test
    pins the premise: if a future Estedad release *added* a ZWNJ glyph, the stripping
    would become wrong and this test would say so.
    """
    path = FONT_DIR / "Estedad-Medium.ttf"
    assert not _has_glyph(path, 0x200C), (
        "Estedad now has a glyph for U+200C. The measurement layer strips ZWNJ before "
        "measuring on the premise that it never renders; that premise is now false."
    )


@pytest.mark.parametrize(
    "codepoint",
    [
        0x0020,  # space
        0x06CC,  # Farsi yeh
        0x06A9,  # keheh
        0x0640,  # tatweel
        0x061F,  # Arabic question mark
        0x060C,  # Arabic comma
        0x06F0,  # Persian zero
        0x06F9,  # Persian nine
    ],
)
def test_required_persian_glyphs_present(codepoint: int) -> None:
    """Every character the pipeline can emit has a glyph.

    Persian digits are here because `to_persian_digits` converts to them
    unconditionally; a missing glyph would turn every number into tofu.
    """
    assert _has_glyph(FONT_DIR / "Estedad-Medium.ttf", codepoint), (
        f"U+{codepoint:04X} has no glyph in Estedad-Medium. The pipeline can emit it, "
        "so it would render as an empty box."
    )


def test_licence_is_vendored() -> None:
    """The OFL text ships beside the fonts.

    SIL OFL 1.1 requires the licence to accompany the font files. Vendoring the
    binaries without it makes the repository non-compliant.
    """
    licence = FONT_DIR / "OFL.txt"
    assert licence.exists(), "OFL.txt missing — required by the licence terms"
    text = licence.read_text(encoding="utf-8")
    assert "SIL OPEN FONT LICENSE" in text.upper()


def test_fonts_are_not_gitignored() -> None:
    """`.gitignore` excludes `public/*` — the negation for fonts must survive.

    Verified by reading the ignore rules rather than by running git, so the test does
    not need a repository. A font that is present locally and ignored is the worst
    case: it works for whoever vendored it and renders tofu for everyone else.
    """
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "!remotion-composer/public/fonts/" in gitignore, (
        ".gitignore no longer negates the font directory. With `public/*` ignored, "
        "the Estedad files would be excluded from the repository."
    )
