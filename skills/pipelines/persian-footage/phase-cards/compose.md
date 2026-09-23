# Phase card — compose

- **Inputs:** `edit_decisions`, `asset_manifest`, `brief`, and pinned profile/policy.
- **Output:** digest-bound render, `render_report`, and `final_review` for the exact bytes.
- **Use:** `persian_compose`, Film Type verifier, opening-only gate, then full render and mastering.
- **Success:** preflight, opening pixels, media probe, motion/luminance, captions, audio, and final review all pass for the same SHA.
- **Stop:** any unresolved blocker, stale evidence, runtime swap, or budget decision point. Never mark final; use `needs_decision`.
- **Details on demand:** `compose-director.md` and `final-candidate-protocol.md`.
