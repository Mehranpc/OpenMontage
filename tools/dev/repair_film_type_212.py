from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{path}: expected one exact post-migration match, found {count}: {old[:120]!r}"
        )
    path.write_text(text.replace(old, new), encoding="utf-8")


layout = ROOT / "remotion-composer" / "src" / "persian" / "filmType" / "layout.ts"

# The materializer widens FilmProfile.layoutVersion, but the measured output type
# must widen too or strict TypeScript rejects assigning layout version 12.
replace_once(
    layout,
    "export type FilmTypeLayout = {\n  version: 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11; inputHash: string; moments: Record<string, FilmMomentLayout>;",
    "export type FilmTypeLayout = {\n  version: 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12; inputHash: string; moments: Record<string, FilmMomentLayout>;",
)

# 2.12 inherits the versioned asymmetric watermark safe area. Without this
# explicit inequality, it falls back to the old symmetric base.side shortcut.
replace_once(
    layout,
    'if (p.profileVersion !== "2.3.0" && p.profileVersion !== "2.4.0" && p.profileVersion !== "2.5.0" && p.profileVersion !== "2.6.0" && p.profileVersion !== "2.7.0" && p.profileVersion !== "2.8.0" && p.profileVersion !== "2.9.0" && p.profileVersion !== "2.10.0" && p.profileVersion !== "2.11.0") return {top:base.top,bottom:base.bottom,left:base.side,right:base.side};',
    'if (p.profileVersion !== "2.3.0" && p.profileVersion !== "2.4.0" && p.profileVersion !== "2.5.0" && p.profileVersion !== "2.6.0" && p.profileVersion !== "2.7.0" && p.profileVersion !== "2.8.0" && p.profileVersion !== "2.9.0" && p.profileVersion !== "2.10.0" && p.profileVersion !== "2.11.0" && p.profileVersion !== "2.12.0") return {top:base.top,bottom:base.bottom,left:base.side,right:base.side};',
)

# The live profile already allows upper zones. 2.12 must remain in the explicit
# version allow-list or every non-empty watermark fails before schedule search.
replace_once(
    layout,
    'if (!names?.length || names.some(z => !(z in rects) || (repair && p.profileVersion !== "2.8.0" && p.profileVersion !== "2.9.0" && p.profileVersion !== "2.10.0" && p.profileVersion !== "2.11.0" && z.startsWith("upper")))) {',
    'if (!names?.length || names.some(z => !(z in rects) || (repair && p.profileVersion !== "2.8.0" && p.profileVersion !== "2.9.0" && p.profileVersion !== "2.10.0" && p.profileVersion !== "2.11.0" && p.profileVersion !== "2.12.0" && z.startsWith("upper")))) {',
)

# The materializer updates the heading and routing table, but the introductory
# current-default claim is a separate paragraph guarded by the drift test.
film_skill = ROOT / "skills" / "pipelines" / "persian-footage" / "film-type.md"
replace_once(
    film_skill,
    "**One current default.** Every unpinned `persian-footage` run resolves to\n`2.11.0` / `layoutVersion 11`. If any other document, comment, or memory tells\nyou a different version is current, it is stale and this file wins.",
    "**One current default.** Every unpinned `persian-footage` run resolves to\n`2.12.0` / `layoutVersion 12`. If any other document, comment, or memory tells\nyou a different version is current, it is stale and this file wins.",
)

print("Applied Film Type 2.12 post-materialization safety repairs.")
