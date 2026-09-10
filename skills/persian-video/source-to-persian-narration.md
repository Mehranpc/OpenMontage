# Source to Persian Narration

Use this capability only when `persian-video status` reports `prepare_narration` or `align_script_timing`.

## `prepare_narration`

Read the current project's workflow state and declared input only. The state's `input.prepare_mode` decides the narrow task:

- `transcribe_existing_narration`: transcribe the supplied narration with word timings; do not rewrite what was spoken.
- `use_approved_persian_script`: treat the supplied Persian script as approved copy.
- `author_persian_narration`: author the Persian narration from the supplied raw source.
- `translate_and_author_persian_narration`: derive a natural Persian narration from the supplied English article.

Run the canonical `idea` then `script` work through `pipeline_defs/persian-footage.yaml`, `idea-director.md`, and `script-director.md`; checkpoint them normally. This capability does not redefine their content or orthography rules.

For authored/script inputs, if no matching narration audio exists yet, present the approved narration text and stop for the user to provide/record audio (or explicitly choose an allowed TTS path). Do not manufacture timing from another project or scale old timing to fit.
## `align_script_timing`

Read `skills/pipelines/persian-footage/subtitle-alignment.md` before doing alignment. The approved script owns every delivered character; ASR owns timing only. Persist enough evidence in the current project to bind the approved script hash to the narration/timing source.

A successful alignment must be reproducible from current-project inputs and must pass the repository's alignment gates. Do not read sibling project SRTs, word timings, narration, or edit decisions as examples.

Record the phase attempt before work and phase completion only after the relevant canonical checkpoints/artifacts have been persisted and alignment evidence is inside the current project. If alignment is uncertain, leave the phase active and surface the blocker instead of forcing a match.

Next routing is always obtained from:

```bash
python -m lib.persian_video_workflow status <project-id>
```
