# Scene Director — Persian Footage Pipeline

Read the scene-plan phase card first. Load `references/scene-planning.md` only when a query, subject quota, fallback, or audit finding needs detailed examples.

## Output contract

Turn approved script into semantic `beats[]`; each non-typographic beat owns one or more shot-level `visual_events[]`. New plans never use the legacy one-shot-per-beat shape.

Every event declares ID, duration, exact narration span, intent, concrete subject/action, desired affect, motif, visual-search brief, shot composition, human presence, importance 1–3, conflict visibility, ordered fallback level, camera, subject evidence, shot scale/environment, and exactly two English queries. Event durations sum to their beat.

## Visual translation

Queries translate visual intent, not Persian words. Use concrete camera-visible nouns/actions, 3–6 English words, one useful qualifier, and shot type when material. Two queries must be genuinely different angles, not paraphrases.

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

report = audit_scene_plan(scene_plan, typographic_budget=brief_budget)
assert not report["problems"], report["problems"]
for advisory in report["advisories"]:
    print("advisory:", advisory)
```

The gate owns identity, duration coverage, event metadata, subject quota, banned terms, query count, camera/variety, affect/human policy, importance/fallback, and typography budget. `sourcing_order` is the only retry priority.

Human review still owns query concreteness, honesty of `shows_subject`, semantic direction, and whether approved Persian text remains normalized. Stop rather than invent footage when the plan has no honest visual strategy or exceeds typography budget.

## Success

Schema-valid `scene_plan`; beat/event timing is complete; the audit has no problems; every advisory has an explicit checkpoint answer; subject continuity and fallback logic are credible; and asset sourcing can execute deterministically without reopening story decisions.