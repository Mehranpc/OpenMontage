# Film Type visual regression

Every Film Type profile so far has been judged from whatever footage the
current sample project happened to contain. That is how the 2.10 weakness on
flat, untextured backgrounds was found: by luck, because one shot in
`apologizing-for-everything` has a plain orange backdrop and another a plain
grey wall. Luck is not a test.

This document fixes the footage set a profile must survive, and what must be
recorded about it.

## Why not just diff renders

`.gitignore` excludes `renders/`, `projects/`, `output/` and `META/`. That is
correct -- video does not belong in git -- but it means no baseline survives
between versions. So the baseline kept here is deliberately small: a handful
of stills plus the numbers behind them.

## The five backgrounds

A candidate profile must be rendered against all five before it can be
proposed for approval. Each targets a different failure mode:

| # | Background | Failure it exposes |
| --- | --- | --- |
| 1 | Flat bright surface (white/grey wall) | The field has no texture to hide in; the soft ellipse reads as a visible smudge |
| 2 | Flat saturated colour (seamless backdrop) | Same, plus a multiply blend shifting the hue |
| 3 | High-key sky or window blowout | Ink and watermark legibility at maximum luminance |
| 4 | Busy high-frequency texture (foliage, crowd, fur) | Glyph edges dissolving into detail |
| 5 | Dark low-key interior | Field darkening a shot that is already dark; interacts with the luminance gate |

Backgrounds 1 and 2 are the ones historically missing from ad-hoc review, and
they judge the diffuse field most harshly. Do not drop them because "the
footage looks easy".

## What a review run must produce

For each of the five, and for every moment in the run:

1. `profileVersion`, `layoutVersion` and `contentHash` actually resolved --
   read from the rendered props sidecar, not from the profile on disk.
2. Per moment: `strength`, `fieldPeakAlpha`, `subjectSafety`, `rect`, and the
   safe-area margin on the closest edge.
3. The painted field attributes, read from the rendered markup.
4. The complete warning list, verbatim.
5. One still per moment.

Items 1-4 are exactly what `lib/persian_render_geometry.py` emits:

```
python -m lib.persian_render_geometry <render>.mp4.props.json
```

Run the luminance gate (`lib/persian_render_qa.py`) alongside it. Neither
replaces the other: geometry cannot see a dead stretch, and luminance cannot
see a rectangle leaving the safe area.

## What gets committed

Not video. For each accepted profile, commit under
`docs/reference/film-type-<version>/`:

* the geometry report above, as text;
* the five stills, downscaled, one per background.

That is enough to answer "did the field get bigger or darker between these two
versions" without keeping renders in git.

## The rule the numbers cannot express

A green geometry report, a passing luminance gate and five committed stills
still do not constitute approval. They establish that the render is legal.
Whether it is *good* is decided by a person looking at it, and that decision
is never recorded automatically by any script in this repository.
