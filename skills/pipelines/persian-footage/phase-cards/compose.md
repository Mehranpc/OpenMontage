# Phase card — compose

- **Inputs:** `edit_decisions`, `asset_manifest`, `brief`, and pinned profile/policy.
- **Output:** digest-bound render, `render_report`, `final_review`, and (for P4-pinned runs) strict `quality_report` for the exact bytes.
- **Use:** enforce the canonical ladder before expensive work: schema/copy authority → timing/paths/assets → layout/geometry/subject regions → no-copy Persian font/text preflight → opening-only render/review → full render → mastering → final review. `persian_compose` owns the shared render-independent review rules; do not bypass a failed early stage.
- **Delivery producer:** after persisting `render_report` and `final_review`, run `python -m lib.persian_delivery_quality stage-candidate <project-id> --render-report-json <path> --final-review-json <path>`. Do not hand-author `quality_report` or write the compose `awaiting_human` checkpoint yourself. The producer binds the final review to the exact MP4 SHA, derives time/cost summary from canonical workflow/checkpoint evidence, writes `quality_report`, and uses the existing compose checkpoint as the only delivery ledger.
- **Rollout:** a run-start `shadow` pin still produces the complete report but does not add a new checkpoint blocker; `enforced` uses the same report and the canonical checkpoint delivery gate. A legacy/in-flight project with no pin is not retroactively migrated or enforced.
- **Success:** preflight, opening pixels, media probe, motion/luminance, captions, audio, final review, and delivery evidence all pass for the same SHA.
- **Cache:** visual/browser and subject-region evidence are dependency-scoped; music-only changes preserve those visual caches but invalidate audio and final-review evidence.
- **Execution:** admit only one unresolved current-revision media job per project. A running render blocks another render, and a successful render keeps the slot until its exact bytes are committed; reconcile/reuse that durable identity after a caller crash instead of re-rendering.
- **Stop:** any unresolved blocker, stale evidence, runtime swap, missing delivery check, or budget decision point. Never mark final; use `needs_decision`.
- **Details on demand:** `compose-director.md` and `final-candidate-protocol.md`.
