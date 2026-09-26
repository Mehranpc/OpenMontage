# Scene Director — Persian Footage Pipeline

Read the scene-plan phase card first. Load `references/scene-planning.md` only when a query, subject quota, fallback, or audit finding needs detailed examples.

## Output contract

Turn approved script into semantic `beats[]`; each non-typographic beat owns one or more shot-level `visual_events[]`. New plans never use the legacy one-shot-per-beat shape.

Every event declares ID, duration, exact narration span, intent, concrete subject/action, desired affect, motif, visual-search brief, shot composition, human presence, importance 1–3, conflict visibility, ordered fallback level, camera, subject evidence, shot scale/environment, and exactly two English queries. Event durations sum to their beat.

## Visual translation

Queries translate visual intent, not Persian words. Use concrete camera-visible nouns/actions, 3–6 English words, one useful qualifier, and shot type when material. Two queries must be genuinely different angles, not paraphrases.

**When the event carries a typographic moment, one of its two queries must ask for the framing that leaves the declared `negative_space` band readable.** A shot where the subject fills the frame cannot carry type however well it matches the action, and this is the failure that has cost every run: the plan declares 8 moment-carrying events, acquisition returns footage whose subject occupies the band, and the moments collapse — measured at 8 → 6 → 5 → 3 across successive runs, each drop truthful and each one a beat the film lost. Name the empty surface in the query — a lone object on a plain surface, or a wide shot with plain wall/sky/table filling the band — rather than describing the action alone. "phone lying on table wide shot plain wall above" searches for something the moment can use; "man looking at phone at table" does not, and is what the pipeline selects when nobody asks for the space.

The event contract precedes keywords: first state what the viewer should understand/feel and what must be visible; then author search terms.

## Subject continuity

Name the video's subject at plan level. First and last footage events show it literally, and at least 40% of footage events do. For mechanism/study/consequence beats prefer co-presence rather than replacing the subject with generic medical stock.

Banned medical-stock vocabulary is governed by `lib.persian_scenes.BANNED_QUERY_TERMS`. Use it only when the approved script literally earns it, with `names_banned_term: true`; the resulting advisory still requires review.

## Fallback and retention grammar

Fallback order is `exact_literal` → `emotional_human` → `adjacent_metaphor` → `abstract`; typography is terminal beat-level fallback and stays within the brief budget (normally at most two). Importance changes bounded retry order, never candidate/byte budgets.

Emotional beats normally need honest human presence. Every event declares one camera move from `push-in`, `pull-out`, `pan-left`, `pan-right`, or `none`; choose `none` when footage already moves. Adjacent events may not share both shot scale and environment.

The opening visibly establishes subject/conflict/hook semantics; the closing event supports resolution. `reward_problem_hook` must show the correct relationship direction, not a semantically reversed near match.

## Gate

```python
from lib.persian_scenes import audit_scene_plan

report = audit_scene_plan(
    scene_plan,
    target_duration_seconds=script["total_duration_seconds"],
    typographic_budget=brief_budget,
)
assert not report["problems"], report["problems"]
for advisory in report["advisories"]:
    print("advisory:", advisory)
```

The gate owns identity, duration coverage, event metadata, subject quota, banned terms, query count, camera/variety, affect/human policy, importance/fallback, and typography budget. Duration coverage is enforced against the authoritative narration, to one frame: pass `target_duration_seconds` and a plan whose beats do not cover it is refused at `plan_scenes_moments` completion. `sourcing_order` is the only retry priority.

Human review still owns query concreteness, honesty of `shows_subject`, semantic direction, and whether approved Persian text remains normalized. Stop rather than invent footage when the plan has no honest visual strategy or exceeds typography budget.

## Success

Schema-valid `scene_plan`; beat/event timing is complete; the audit has no problems; every advisory has an explicit checkpoint answer; subject continuity and fallback logic are credible; and asset sourcing can execute deterministically without reopening story decisions.