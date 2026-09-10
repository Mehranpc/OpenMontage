from __future__ import annotations

import py_compile
import subprocess
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one match in {path}, got {count}: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "lib/persian_moments.py",
    '''        exact_text = (
            validate_exact_text_record(raw.get("exactText"))
            if raw.get("exactText") is not None
            else None
        )
        segments: list[PersianSegment] = []
''',
    '''        exact_text = (
            validate_exact_text_record(raw.get("exactText"))
            if raw.get("exactText") is not None
            else None
        )
        if (
            exact_text is not None
            and " ".join(exact_text["text"].split()) != exact_text["text"]
        ):
            raise ValueError(
                f"{where} strict copy must use one ASCII space between words and "
                "no leading, trailing, repeated, or line-break whitespace; "
                "unsupported whitespace is refused rather than repaired"
            )
        segments: list[PersianSegment] = []
''',
)

layout = "remotion-composer/src/persian/filmType/layout.ts"
replace_once(
    layout,
    '''export async function sha256(value: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(stableJSON(value));
  return [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map(n => n.toString(16).padStart(2,"0")).join("");
}
export function filmProfile(design: PersianDesignSnapshot): FilmProfile {
''',
    '''export async function sha256(value: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(stableJSON(value));
  return [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map(n => n.toString(16).padStart(2,"0")).join("");
}
/** Hash an authored string's raw UTF-8 bytes, without stable-JSON quoting. */
export async function sha256Text(text: string): Promise<string> {
  const bytes = new TextEncoder().encode(text);
  return [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map(n => n.toString(16).padStart(2,"0")).join("");
}
export function filmProfile(design: PersianDesignSnapshot): FilmProfile {
''',
)
replace_once(
    layout,
    '''export function breakFilmLines(text: string, width: number, size: number, weight: number, maxLines: number, version: FilmProfile["profileVersion"] = "2.1.0"): string[] | null {
  const words = splitWords(text);
''',
    '''export function breakFilmLines(text: string, width: number, size: number, weight: number, maxLines: number, version: FilmProfile["profileVersion"] = "2.1.0", preserveExact = false): string[] | null {
  // Strict copy was already validated as single-ASCII-space-separated. Split it
  // directly so NFC/Arabic-letter folding in splitWords can never change paint.
  const words = preserveExact ? text.split(" ") : splitWords(text);
''',
)
replace_once(
    layout,
    '''  const numeric = moment.kind === "figure" && moment.segments.some(s => s.role === "hero" && splitQuantity(s.text));
''',
    '''  const numeric = !moment.exactText && moment.kind === "figure" && moment.segments.some(s => s.role === "hero" && splitQuantity(s.text));
''',
)
replace_once(
    layout,
    '''        const lines = breakFilmLines(piece.text,column - 2 * l.inkPaddingPx,piece.size,piece.weight,piece.max,p.profileVersion);
''',
    '''        const lines = breakFilmLines(piece.text,column - 2 * l.inkPaddingPx,piece.size,piece.weight,piece.max,p.profileVersion,Boolean(moment.exactText));
''',
)
replace_once(
    layout,
    '''  if(await sha256(profile)!==props.design!.contentHash) throw new Error("Film Type profile hash mismatch; re-resolve the design rather than silently changing a frozen snapshot.");
  await document.fonts.load(`${profile.watermark.latinWeight} ${profile.watermark.latinFontPx}px "${profile.watermark.latinFontFamily}"`, "Pathway");
''',
    '''  if(await sha256(profile)!==props.design!.contentHash) throw new Error("Film Type profile hash mismatch; re-resolve the design rather than silently changing a frozen snapshot.");
  for (const moment of props.moments) {
    const record = moment.exactText;
    if (!record) continue;
    if (typeof record.text !== "string" || typeof record.sha256 !== "string" || !/^[0-9a-f]{64}$/.test(record.sha256)) {
      throw new Error(`Moment ${moment.id}: exactText needs an exact string and lowercase SHA-256 digest.`);
    }
    if (await sha256Text(record.text) !== record.sha256) {
      throw new Error(`Moment ${moment.id}: exactText.sha256 does not match the raw UTF-8 display bytes.`);
    }
  }
  await document.fonts.load(`${profile.watermark.latinWeight} ${profile.watermark.latinFontPx}px "${profile.watermark.latinFontFamily}"`, "Pathway");
''',
)

replace_once(
    "remotion-composer/src/persian/types.ts",
    '''  if (moment.exactText) {
    const displayText = moment.segments
''',
    '''  if (moment.exactText) {
    if (
      typeof moment.exactText.text !== "string" ||
      moment.exactText.text.split(/\\s+/u).filter(Boolean).join(" ") !== moment.exactText.text
    ) {
      throw new Error(
        `${where}: strict copy must use one ASCII space between words and no ` +
          `leading, trailing, repeated, or line-break whitespace; unsupported ` +
          `whitespace is refused rather than repaired.`,
      );
    }
    const displayText = moment.segments
''',
)

replace_once(
    "tests/lib/test_persian_brand.py",
    '''def test_curly_quote_or_whitespace_rewrite_fails_strict_copy() -> None:
''',
    '''@pytest.mark.parametrize("text", ["   ", "دو  فاصله", "دو\\nخط", "دو\\tبخش"])
def test_unrenderable_strict_whitespace_is_refused_not_repaired(text: str) -> None:
    with pytest.raises(ValueError, match="one ASCII space"):
        build_moments(
            [
                {
                    "kind": "statement",
                    "startSeconds": 0.2,
                    "endSeconds": 4.0,
                    "segments": [{"role": "hero", "text": text}],
                    "exactText": exact_text_record(text),
                }
            ]
        )


def test_curly_quote_or_whitespace_rewrite_fails_strict_copy() -> None:
''',
)

replace_once(
    "tests/lib/test_persian_ranked_browser.py",
    '''from lib.persian_design import resolve_design, SUPPORTED_FILM_TYPE_28_HASH, SUPPORTED_FILM_TYPE_211_HASH
''',
    '''from lib.persian_brand import exact_text_record
from lib.persian_design import resolve_design, SUPPORTED_FILM_TYPE_28_HASH, SUPPORTED_FILM_TYPE_211_HASH
''',
)
replace_once(
    "tests/lib/test_persian_ranked_browser.py",
    '''    def test_stale_layout_refused(self):
''',
    '''    def test_strict_rows_preserve_arabic_codepoints_quotes_and_zwnj(self):
        exact="مي‌روم؛ “همین”"
        p=self.props();p['moments']=[{
            'id':'strict','kind':'statement','startSeconds':0,'endSeconds':15,
            'presentation':{'placement':'auto'},
            'segments':[{'role':'hero','text':exact}],
            'exactText':exact_text_record(exact),
        }]
        q=self.prepare(p)
        rows=q['filmType']['moments']['strict']['rows']
        self.assertEqual(' '.join(row['text'] for row in rows),exact)
        self.assertEqual(q['moments'][0]['segments'][0]['text'],exact)
        self.assertEqual(q['moments'][0]['exactText'],exact_text_record(exact))

    def test_strict_digest_is_rechecked_in_the_renderer(self):
        exact="مي‌روم؛ “همین”"
        p=self.props();p['moments']=[{
            'id':'strict','kind':'statement','startSeconds':0,'endSeconds':15,
            'presentation':{'placement':'auto'},
            'segments':[{'role':'hero','text':exact}],
            'exactText':{**exact_text_record(exact),'sha256':'0'*64},
        }]
        with self.assertRaisesRegex(ValueError,'sha256'):self.prepare(p)

    def test_stale_layout_refused(self):
''',
)

replace_once(
    "schemas/artifacts/edit_decisions.schema.json",
    '''                  "enum": [
                    "2.1.0",
                    "2.2.0",
                    "2.3.0",
                    "2.4.0",
                    "2.5.0",
                    "2.6.0",
                    "2.7.0",
                    "2.8.0"
                  ]
''',
    '''                  "enum": ["2.1.0", "2.2.0", "2.3.0", "2.4.0", "2.5.0", "2.6.0", "2.7.0", "2.8.0"]
''',
)
replace_once(
    "skills/pipelines/persian-footage/edit-director.md",
    '''not normalize punctuation, Arabic/Persian code points, ZWNJ, whitespace, or digits;
any drift or stale hash is a preflight failure rather than a silent repair.
''',
    '''not normalize punctuation, Arabic/Persian code points, ZWNJ, whitespace, or digits.
Film Type strict copy uses one ASCII space between words; leading, trailing, repeated,
or line-break whitespace is rejected rather than repaired. Any drift or stale hash is
a preflight failure.
''',
)

for file_name in (
    "lib/persian_moments.py",
    "tests/lib/test_persian_brand.py",
    "tests/lib/test_persian_ranked_browser.py",
):
    py_compile.compile(file_name, doraise=True)
subprocess.run(["git", "diff", "--check"], check=True)
print("strict-render review fixes applied")
