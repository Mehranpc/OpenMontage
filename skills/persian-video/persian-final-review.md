# Persian Final Review

Use this capability only when code reports `final_review` or `awaiting_human`.

Read `skills/pipelines/persian-footage/compose-director.md` and `final-candidate-protocol.md`. Run the canonical media, Persian text, layout/crop, audio, subtitle, and provenance checks against the one current-project candidate. Record measured evidence in the normal `render_report`/review artifacts; do not replace those contracts with prose in workflow state.

The compose checkpoint must be written as `awaiting_human`, never self-approved. Its primary output must be an MP4 inside this project's directory with a 64-character SHA-256 matching the exact file bytes, `delivery_status="final_candidate"`, `human_visual_approval=false`, and `persian_text_verified=false`.

After final QA is persisted, advance the front-door state only through the code API:

```bash
python -m lib.persian_video_workflow attempt <project-id> --phase final_review
python -m lib.persian_video_workflow complete <project-id> --phase final_review --evidence-json final-review-evidence.json
python -m lib.persian_video_workflow complete <project-id> --phase awaiting_human
```
The final command independently re-reads `checkpoint_compose.json`, resolves the reported render path, refuses a render outside this project, re-hashes the MP4 bytes, and only then changes workflow status to `awaiting_human` with `next_phase=null`.

At that point **stop**. Present that exact candidate to the user and wait for explicit approval. Approval and compose completion continue through the existing digest-bound checkpoint protocol; this front-door skill never treats silence, a general goal, or an earlier approval as approval of the candidate.
