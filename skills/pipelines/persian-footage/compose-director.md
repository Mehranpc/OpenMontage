# Compose Director — Persian Footage Pipeline

Film Type 2.16.0 / layout 16 is the default for every Persian-footage run. Read `film-type.md`, the compose phase card, and `final-candidate-protocol.md`. Never load `film-type-history.md` unless the project explicitly pins an older profile. Detailed measurement recipes and failure rationale are in `references/compose-verification.md`; load only the section needed by a current failure.

## Contract

Render the accepted `edit_decisions` exactly once as the candidate, verify the exact bytes, persist `render_report` and `final_review`, then use the canonical delivery-quality producer to build `quality_report` and checkpoint compose as `awaiting_human`. Do not hand-author `quality_report` or call `write_checkpoint` directly for the final candidate. Only explicit approval of that digest-bound MP4 completes compose. Any unresolved critical finding produces `quality_disposition=needs_decision`, never final delivery.

For a P4-pinned run, finish candidate staging with:

```bash
python -m lib.persian_delivery_quality stage-candidate <project-id> \
  --render-report-json <project>/artifacts/render_report.json \
  --final-review-json <project>/artifacts/final_review.json
```

The producer binds `final_review.output_sha256` to the exact reported MP4 bytes when the review path matches, derives the strict `quality_report` from canonical review/telemetry/cost evidence, and writes the existing compose checkpoint. `shadow` records the full report without adding a new delivery blocker; `enforced` applies the same report through the checkpoint gate. Projects with no run-start policy pin remain legacy/in-flight and are not retroactively migrated.

`render_runtime` MUST be `remotion`. A HyperFrames or ffmpeg substitution is a blocker: the Persian composition depends on Estedad loaded with `FontFace`, canvas measurement, RTL/ZWNJ-aware line breaking, and profile-specific prepared geometry.

## Preflight and render

```python
from lib.persian_preflight import preflight_edit_decisions

preflight = preflight_edit_decisions(edit_decisions)
assert preflight["ok"], preflight
```

Use `persian_compose`, not `video_compose`:

```python
result = registry.get("persian_compose").execute({
    "edit_decisions": edit_decisions,
    "output_path": str(project_dir / "renders" / "final.mp4"),
    "crf": 16,
    "timeout_ms": 60000,
})
```

The tool must refuse retired props, invalid pacing, stale/unanchored timings, duplicate music ownership, missing media, and unresolved profile geometry. Fix the owning upstream artifact; do not hand-nudge timings, weaken gates, switch runtime, or fall back from Film Type to Legacy.

For cheap iteration, render only windows selected from moment/brand-slot boundaries (for example `frames: "0-120"`). Never pick fixed intervals: selective text intentionally leaves much of the timeline empty. Ship only at scale 1.0.

## Verification routing

Choose the instrument by resolved profile:

- Film Type: `lib.persian_film_verify.verify_film_frames` against resolved props; contrast floor 4.5:1; verify rect, shadow, composite, and actual painted frames.
- Explicit Legacy pin: `lib.persian_verify` for scrim plateau, accent-located arrangement, anchor, gaps, rhythm, and fixed watermark.

Never run Legacy accent/scrim checks on Film Type. Film Type has white ink and a diffuse field, so reading order, gap emptiness, and stack rhythm have no equivalent colour-separable pixel instrument. Record them as `not_checked` and inspect every sampled moment/gap frame by eye. A missing check is not a pass.

Sample the midpoint of every moment, the completed state of every build, the midpoint of every gap, caption entry/mid/exit frames, and each Film Type brand slot. Inspect Persian reading order and tofu on actual pixels. Do not set `persian_text_verified` from sampled automation alone.

```python
from lib.persian_film_verify import verify_film_frames

summary = verify_film_frames(frames, props=resolved_props, evidence=evidence)
assert summary["passed"], summary["problems"]
```

## File, motion, captions, and audio

- ffprobe dimensions must exactly match the selected format; duration must be within one second; authored audio streams must exist.
- `post_render_motion_qa.passed` must be true and fail runs empty.
- no contiguous ≥1.0s run may average below YAVG 22; below 30 is a warning.
- `sidecar_only`/`hybrid` require the approved-script SRT; `burned_captions`/`hybrid` require burned cues and retained verification frames.
- Caption pixels must stay readable at phone size and yield while editorial moments are active.
- Narrated delivery requires the licensed music record unless deliberate silence is explicitly recorded. Confirm a consistent bed beneath narration; moment-synchronous ducking indicates stale composition.
- Attributions cover every selected clip.

## Stop conditions

Stop and route upstream for: missing media, non-Remotion runtime, stale digest/evidence, bad sync, copy change, invalid music record, profile/hash mismatch, no legal brand schedule, failed motion/luminance/caption/audio probe, missing delivery evidence, or any critical review finding. Never resolve a render failure by changing runtime/profile or by writing a temporary verifier.

## Success

The exact candidate bytes have matching preflight, probe, profile verification, motion/luminance evidence, caption/audio evidence, render report, final review, quality report, and digest. The candidate is `awaiting_human`, not completed. For thresholds, Legacy diagnostics, watermark ablation, and known-bad detector designs, open `references/compose-verification.md` on demand.
