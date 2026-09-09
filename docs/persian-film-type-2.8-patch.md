# Film Type 2.8: approved shadow default and Reels-safe layout

Incremental patch AFTER 2.7, from repository root:

```sh
git apply --check /path/to/openmontage-film-type-2.8.patch
git apply /path/to/openmontage-film-type-2.8.patch
python -m unittest tests.lib.test_persian_film_type tests.lib.test_persian_film_verify tests.lib.test_persian_reels_safe_area -q
```

Reverse with `git apply -R --check` then `git apply -R` before overlapping edits.

## Default and compatibility
Unpinned film-type resolves to 2.8/layout 8. The approved 2.7 diffuse curve, colour,
strength levels and font ladders are unchanged. defaultStrength becomes strong
(peak 0.44 before subject limiting) for future projects in both formats. Explicit
contrastStrength choices still override the default. Existing complete pins remain
unchanged; 2.7's exact snapshot is archived. Migration requires fresh resolution
and prepass; never relabel hashes or reuse old geometry. This does not modify
projects on the user's filesystem automatically.

## Safe area policy
For vertical 9:16, text AND watermark stay inside:
- top 14%; bottom 35%; left 8%; right 16% excluded.
- At 1080x1920 this is x=86.4..907.2, y=268.8..1248, BEFORE existing extra insets.
- Right exclusion is deliberately larger to reserve the engagement rail.
- Entire text rectangle and entrance travel are constrained, not just anchor points.
- Centre placement is centred within the safe rectangle, not the full video.
- lower-left/right now means lower edge of this safe area, not bottom of the video.
- Column budgets and max stack height derive from remaining safe space.
- Shadow tails can extend outside the text-safe region; shadow softness is unchanged.
- Watermark can also try upper-left/right INSIDE the same safe area to avoid
  otherwise impossible schedules in the reduced region. Old versions retain their
  non-top restriction. Existing text/subject collision rules remain in force.

These margins are a conservative PROJECT policy for Reels, not a claim of one
pixel-exact official UI for all devices. Bottom 35% follows Meta's Reels-ad guidance;
left/right choices are project allowances. Expanded captions/comments, feed/grid
crops and other platforms need separate review. Landscape safe geometry is unchanged.
Reference: https://www.facebook.com/business/help/980593475366490/
Reference: https://www.facebook.com/metaforbusiness/videos/1325026429453881

Do not just translate old layouts upward: that can cover faces. Author accurate
critical subject regions through the whole shot/camera move, then reprepare. Auto
may choose another safe candidate; explicit placement is binding. If no readable
candidate or brand schedule exists, refuse and request editorial reframing/copy
changes. Never relax platform margins or shrink subject regions to make it pass.

## Review overlay
```sh
python scripts/review_reels_safe_area.py FRAME.png FRAME-reels-guide.png
```
Red bands are reserved; the green outline is the conservative review rectangle.
The helper EXIF-normalizes and rejects wrong aspect ratio. It reads the current
profile; use it on 2.8 output, not to certify historical profiles. Never upload the
review overlay as final media. It is not a screenshot of Instagram's actual UI.
Preview the final video in Instagram/Ads Manager as well.

## Validation
47 Python contracts passed. 26 direct Chromium assertions with actual Estedad
passed, including all moment rectangles + entrance travel within the new area,
auto placement, all planned brand positions, default strong, deterministic/frozen
roundtrip, both formats and negative inputs. These fixtures use reviewed-clear
synthetic region lists; they do not certify the user's real subject envelopes.
Browser bundle compiled. Full project TypeScript and full production video render
were not completed here. Existing QA evidence limitations from 2.7 remain; no
numeric contrast or glyph-order certification is inferred from safe geometry.

## Next project run
Back up current edit decisions and output; freshly resolve 2.8 without an old pin,
retain approved text/timing/footage, accurately update hand/face regions, reprepare,
and preview every moment with the overlay. Inspect cuts and entrance/exit. Report
any unfit text/brand schedule instead of deleting safeguards. No fresh media is
required by this patch. Obtain approval before changing content or footage.
