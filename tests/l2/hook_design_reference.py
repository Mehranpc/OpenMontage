"""#387: Mehran's approved opening-hook design, rendered by Chrome straight from his file.

`tests/fixtures/issue387_hook_design/Hook_v2_photo.html` is the owner's design file,
byte for byte. The approval (#387 comment 5999195805) changed exactly two things: the hero
face Lalezar -> Kahroba and the hero size 150px -> 140px. This module applies only those
two edits, swaps the remote Google Fonts link for the same families from local files (the
render must never fetch fonts), and replaces the sample copy and photo. Everything else
in the file is untouched, so its render is the reference the pipeline has to match.
"""
from __future__ import annotations

import html
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "tests" / "fixtures" / "issue387_hook_design" / "Hook_v2_photo.html"
FONTS = ROOT / "remotion-composer" / "public" / "fonts"

GOOGLE_FONTS = ('<link href="https://fonts.googleapis.com/css2?family=Lalezar&family=Vazirmatn:'
                'wght@500;600;700;800;900&display=swap" rel="stylesheet">')
SAMPLE_QUESTION = ('فکر می‌کنی اگه دیر جواب بدی<br>\n        بیشتر بهت '
                   '<span class="highlight">علاقه‌مند</span> می‌شه؟')
SAMPLE_BRIDGE = "دانشمندها یه چیز دیگه می‌گن"
SAMPLE_HERO = "دقیقاً برعکسه"
APPROVED_EDITS = (
    ("font-family:'Lalezar','Vazirmatn',sans-serif;", "font-family:'Kahroba','Vazirmatn',sans-serif;"),
    ("font-size:150px;", "font-size:140px;"),
    ("font-weight:400;\n    letter-spacing:-1px;", "font-weight:800;\n    letter-spacing:-1px;"),
)


def _local_fonts() -> str:
    faces = [(600, "SemiBold"), (800, "ExtraBold"), (900, "Black")]
    css = "".join(
        f"@font-face{{font-family:'Vazirmatn';src:url('{(FONTS / 'vazirmatn' / f'Vazirmatn-{name}.ttf').as_uri()}') "
        f"format('truetype');font-weight:{weight}}}" for weight, name in faces)
    css += (f"@font-face{{font-family:'Kahroba';src:url('{(FONTS / 'kahroba' / 'Kahroba-EB-LC.woff2').as_uri()}') "
            "format('woff2');font-weight:800}")
    return f"<style>{css}</style>"


def reference_html(question: str | None, bridge: str | None, hero: str, photo: Path) -> str:
    """The design file with the approved edits, local fonts, this copy and this photo."""
    source = DESIGN.read_text(encoding="utf-8")
    for old, new in ((GOOGLE_FONTS, _local_fonts()), *APPROVED_EDITS,
                     ('src="photo.jpg"', f'src="{photo.as_uri()}"')):
        assert source.count(old) == 1, old
        source = source.replace(old, new)
    for old, new, present in ((SAMPLE_QUESTION, question, question is not None),
                              (SAMPLE_BRIDGE, bridge, bridge is not None),
                              (SAMPLE_HERO, hero, True)):
        assert source.count(old) == 1, old
        source = source.replace(old, html.escape(new) if present else "")
    if question is None:
        source = source.replace('<h2 class="question">\n        \n      </h2>', "")
    if bridge is None:
        source = source.replace('<div class="bridge">\n        \n      </div>', "")
    return source


def render_reference(chrome: str, page: Path, out: Path) -> None:
    subprocess.run(
        [chrome, "--headless", "--disable-gpu", "--hide-scrollbars", "--allow-file-access-from-files",
         "--force-device-scale-factor=1", "--window-size=1080,1920", "--virtual-time-budget=8000",
         f"--screenshot={out}", page.as_uri()],
        check=True, timeout=180, capture_output=True,
    )
