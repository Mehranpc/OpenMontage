"""#387: the v3 opening hook CSS is Mehran's approved design file, declaration for declaration.

Owner decision (#387 comment 5999195805): `Hook_v2_photo.html` exactly, with two approved
changes only: hero Lalezar -> Kahroba and hero 150px -> 140px (Kahroba's single face is
its heavy weight, so the hero asks for 800 instead of Lalezar's 400). Owner review of the
acceptance-3 render added one more: the soft shade spans the full frame width. Every other rule of
the file must reach the renderer unchanged. Pure file checks, no browser.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "tests" / "fixtures" / "issue387_hook_design" / "Hook_v2_photo.html"
HOOK_TSX = ROOT / "remotion-composer" / "src" / "persian" / "filmType" / "designedHook.tsx"
VAZIRMATN = ROOT / "remotion-composer" / "public" / "fonts" / "vazirmatn"
APPROVED_DESIGN_SHA256 = "394223c54f07dff439534524ac33389fb7ed6edeb18e859d71e9977e290419b2"
SELECTORS = {  # design selector -> renderer selector
    ".video-treatment": ".omh-treatment", ".hook-wrap": ".omh-wrap", ".hook-wrap::before": ".omh-wrap::before",
    ".accent-line": ".omh-accent", ".question": ".omh-question", ".question .highlight": ".omh-question .omh-highlight",
    ".bridge": ".omh-bridge", ".hero-wrap": ".omh-hero-wrap", ".hero": ".omh-hero", ".brush": ".omh-brush",
    ".brush::before,.brush::after": ".omh-brush::before,.omh-brush::after",
    ".brush::before": ".omh-brush::before", ".brush::after": ".omh-brush::after",
}
#: Owner review of the acceptance-3 render: the soft shade spans the full 1080px frame
#: (the 110px-inset hook box plus 110px each side), not 55px short of each edge.
APPROVED_SHADE = {"left": "-110px", "right": "-110px"}
APPROVED_HERO = {"font-family": "'KahrobaEditorial','Vazirmatn',sans-serif", "font-size": "140px", "font-weight": "800"}


def _rules(css: str) -> dict[str, dict[str, str]]:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"@media[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", css)
    rules: dict[str, dict[str, str]] = {}
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        key = re.sub(r"\s*,\s*", ",", " ".join(selector.split()))
        decls = rules.setdefault(key, {})
        for decl in body.split(";"):
            if ":" in decl:
                name, value = decl.split(":", 1)
                decls[name.strip()] = re.sub(r"\s+", "", value)
    return rules


def _design_rules() -> dict[str, dict[str, str]]:
    css = re.search(r"<style>(.*?)</style>", DESIGN.read_text(encoding="utf-8"), re.S).group(1)
    rules = _rules(css)
    variables = rules.pop(":root")
    resolve = lambda v: re.sub(r"var\((--[\w-]+)\)", lambda m: variables[m.group(1)], v)  # noqa: E731
    return {k: {n: resolve(v) for n, v in d.items()} for k, d in rules.items()}


def _renderer_rules() -> dict[str, dict[str, str]]:
    source = HOOK_TSX.read_text(encoding="utf-8")
    css = re.search(r"DESIGNED_HOOK_CSS = `(.*?)`;", source, re.S).group(1)
    css = css.replace("${VAZIRMATN_FAMILY}", "Vazirmatn").replace("${KAHROBA_FAMILY}", "KahrobaEditorial")
    return _rules(css)


def test_design_fixture_is_the_approved_file() -> None:
    assert hashlib.sha256(DESIGN.read_bytes()).hexdigest() == APPROVED_DESIGN_SHA256


def test_every_design_rule_reaches_the_renderer_unchanged() -> None:
    design, renderer = _design_rules(), _renderer_rules()
    for selector, target in SELECTORS.items():
        expected = dict(design[selector])
        if selector == ".hero":
            assert expected.pop("font-family") == "'Lalezar','Vazirmatn',sans-serif"
            assert expected.pop("font-size") == "150px" and expected.pop("font-weight") == "400"
            expected.update(APPROVED_HERO)
        if selector == ".hook-wrap::before":
            assert expected["left"] == "-55px" and expected["right"] == "-55px"
            expected.update(APPROVED_SHADE)
        assert renderer[target] == expected, selector


def test_no_animation_and_no_remote_fonts_in_the_renderer() -> None:
    source = HOOK_TSX.read_text(encoding="utf-8")
    css = re.search(r"DESIGNED_HOOK_CSS = `(.*?)`;", source, re.S).group(1)
    assert "animation" not in css and "transition" not in css and "@import" not in css
    assert "useCurrentFrame" not in source and "googleapis" not in source


def test_vazirmatn_is_vendored_with_its_license_and_recorded_hashes() -> None:
    readme = (VAZIRMATN / "README.md").read_text(encoding="utf-8")
    assert (VAZIRMATN / "OFL.txt").read_text(encoding="utf-8").find("SIL OPEN FONT LICENSE") >= 0
    for name in ("Vazirmatn-SemiBold.ttf", "Vazirmatn-ExtraBold.ttf", "Vazirmatn-Black.ttf"):
        digest = hashlib.sha256((VAZIRMATN / name).read_bytes()).hexdigest()
        assert f"`{name}`" in readme and digest in readme, name


def test_glyph_order_check_shapes_vazirmatn_rows_with_the_vendored_files() -> None:
    from lib.persian_film_verify import _row_font
    for weight in (600, 800, 900):
        font = _row_font({"family": "Vazirmatn", "weight": weight, "fontSizePx": 68}, 1.0)
        assert font is not None and Path(font.path).parent == VAZIRMATN
