# Persian Hook Quality Contract

This contract applies to new Persian short-form production, especially `instagram-reels` and `tiktok`.
It supplements structural retention QA; it does not replace it.

## Core distinction

A pattern interrupt is not automatically a hook. Cuts, motion, typography, zooms, and overlays can orient attention, but the opening still needs a reason to keep watching.
Evaluate the opening as:

1. **Orient** — capture attention perceptually.
2. **Relevance** — make the viewer understand why this matters to them.
3. **Gap / tension** — create a specific missing answer, contradiction, consequence, direct benefit, or micro-suspense.
4. **Payoff promise** — make the value of staying legible.
5. **Begin payoff** — start evidence/example/proof promptly.

Do not claim that these rules predict virality or reproduce Instagram ranking. They are editorial quality gates calibrated from research plus production evidence.

## Required edit evidence

For new short-form production, persist top-level `metadata.hookQuality` inside `edit_decisions` before no-copy preflight:

```json
{
  "version": "1.0",
  "valueProposition": {
    "atSeconds": 0.8,
    "evidence": "What exact viewer value is understandable at this time"
  },
  "semanticTension": {
    "kind": "contradiction",
    "atSeconds": 1.1,
    "evidence": "What exact unanswered tension is established"
  },
  "firstProof": {
    "atSeconds": 2.0,
    "evidence": "What concrete example, demonstration, or evidence begins here"
  },
  "judgements": {
    "semanticPredictionError": {"level": "strong", "rationale": "..."},
    "audienceRelevance": {"level": "strong", "rationale": "..."},
    "concreteness": {"level": "acceptable", "rationale": "..."},
    "hookBodyAlignment": {"level": "strong", "rationale": "..."},
    "visualVoiceAlignment": {"level": "strong", "rationale": "..."}
  },
  "flags": {
    "metaIntroDelay": false,
    "vagueGap": false,
    "fullConclusionRevealed": false
  },
  "perceptualChanges": [
    {"kind": "action", "atSeconds": 0.9, "evidence": "Visible subject action changes the information on screen"}
  ]
}
```

Allowed `semanticTension.kind` values are `question`, `specific_gap`, `contradiction`, `consequence`, `micro_suspense`, and `direct_benefit`.
Judgement levels are `weak`, `acceptable`, or `strong` and always require rationale.

Allowed authored perceptual-change kinds are `shot_change`, `action`, `reaction`, `reveal`, `detail`, `scale_change`, `punch_in`, and `subject_motion`.
Do not author an event merely because a baseline frame exists. Frame zero is the starting state, not a change.
Do not count a typographic moment as the same thing as a meaningful shot/action/reveal change.

## Timing policy

The current thresholds are an **initial conservative calibration policy**, not universal scientific laws:

- value proposition: advisory after 2.0s, blocker after 3.0s;
- semantic tension: advisory after 2.5s, blocker after 4.0s;
- first proof/example: advisory after 4.0s, blocker after 6.0s;
- more than four meaningful changes inside the first 3s: over-editing advisory;
- no meaningful post-start visual change inside the first 3s: under-stimulation advisory, not an automatic semantic failure.

Thresholds may change later only through an explicit versioned decision using enough page-specific post-publish evidence. Post-publish analytics never mutate these values automatically.

## Semantic rules

A specific gap is better than generic mystery. `باورت نمی‌شه چی شد` without a reachable missing answer should be flagged as vague.
A meaningful contradiction is better than random novelty. Surprise must connect to the topic/body.
Audience relevance asks `why should this viewer care?`; unusual information alone is insufficient.
Concrete actions/outcomes are preferred in the opening when abstract language is not grounded quickly.
Visual footage should depict/support the spoken problem, consequence, action, or tension rather than merely look aesthetically pleasant.
Faces and direct gaze may help salience but are never mandatory.

`metaIntroDelay` covers value-delaying setup such as an opening that spends scarce seconds saying it will explain something instead of beginning the explanation.
`fullConclusionRevealed` is an advisory because some openings can reveal one result while retaining another concrete reason to continue; record the remaining reason explicitly in evidence.

## Authority boundary

Hook-quality evidence must describe the approved production honestly. It is not permission to silently rewrite authoritative narration.
The existing opening moment may use only the paraphrase freedom already granted by `edit-director.md`; it may not invent a claim the body never earns.
If the spoken first seconds are fundamentally weak and cannot be repaired by truthful visual/edit choices or an allowed moment paraphrase, use the workflow's editorial revision path rather than rewriting narration inside compose.

## Recovery classes

`HOOK_EVIDENCE` — evidence is missing/malformed; repair metadata without changing approved copy.

`HOOK_TIMING` — value/tension/proof arrives too late; first try edit timing or moving existing proof earlier. If authoritative speech itself causes the delay, request editorial re-authoring rather than trimming meaning invisibly.

`HOOK_VISUAL_ALIGNMENT` — opening footage/perceptual evidence does not support the spoken tension; revise sourcing, window, crop, action, or shot order.

`HOOK_AUTHORING` — the semantic hook itself is vague, irrelevant, or unsupported by the body; use the authorized editorial revision path.

## Final rendered review

Preflight evidence is a prediction about the authored edit. It does not prove the real MP4 feels strong.
For productions carrying `hookQualityAudit`, the `final_review` artifact must also carry `metadata.hookQualityReview` with:

- `strength`: `weak`, `acceptable`, or `strong`;
- non-empty `rationale`;
- at least two opening-specific observations from the real render;
- `mutedHookDirectionConfirmed`;
- `visualVoiceAlignment`;
- `payoffBeginsPromptly`.

A `weak` rendered hook, failed muted direction, weak visual/voice alignment, or delayed payoff blocks presentation even if structural retention QA passed.

## Post-publish calibration

After publication, real platform observations belong in the independent `post_publish_performance` artifact, bound to the exact published MP4 SHA-256.
Use append-only snapshots such as 1h, 4h, 24h, and 72h when available. Missing platform metrics remain null/absent; never fabricate them.
`calibration_mode` is `observational`. No post-publish record authorizes automatic threshold learning, narration rewriting, or policy mutation.
