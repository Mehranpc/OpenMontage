# Persian Hook Quality Contract

This contract applies to new Persian short-form production, especially `instagram-reels`, `tiktok`, and `youtube-shorts`. It supplements structural retention QA; it does not replace it. Hook Quality predicts editorial quality, not virality or platform ranking.

## Core distinction

A pattern interrupt is not automatically a hook. Cuts, motion, typography, zooms, and overlays can orient attention, but the opening still needs a reason to keep watching. Treat these as separate editorial functions:

1. **Orient** — capture attention perceptually.
2. **Viewer value** — make the viewer understand why staying is useful or relevant.
3. **Semantic tension** — create a specific missing answer, contradiction, consequence, direct benefit, or micro-suspense.
4. **Concrete payoff/proof** — begin an answer, result, example, demonstration, evidence, or mechanism that materially starts resolving the promise.

`viewerValue`, `semanticTension`, and `firstProof` are distinct concepts. The same observable/spoken event may satisfy more than one only when that is genuinely true and `sharedEvidenceJustifications` records why. Identical timestamps or persuasive prose are not enough to double-count evidence.

## Hook selection authority — Issue #32

Before authoring the opening moment, inspect the workflow `hook_selection`. A user-supplied hook is authoritative: do not shorten, paraphrase, or replace it to make layout easier. If selection is automatic, read the three durable reference files under `docs/reference/persian-hooks/`, classify the source/content type, generate comparative candidates, remove unsupported/exaggerated claims, and rank the survivors for retention. The winner requires score >= 7/10 and content-match 2/2 and must be persisted with `record_hook_selection` before edit staging. “Shorter” is not a ranking objective.

Automatic framing may be conversational and bolder than an abstract, including an honest question whose nuance arrives immediately afterward, but it may not invent a number, effect direction, study population, or unsupported relationship.

For Film Type 2.16, every opening hook is one complete 3–5 second composition and must communicate topic + tension on mute. The renderer uses verified Kahroba editorial type, white support + `#FFEA00` semantic emphasis, right/center Persian alignment, and rendered-pixel Visual Typography policy v2. A plain white subtitle-like overlay is a visual failure even when it technically fits.

## Required edit evidence — Hook Quality v2

For new short-form production, persist top-level `metadata.hookQuality` inside `edit_decisions` before no-copy preflight:

```json
{
  "version": "2.0",
  "viewerValue": {
    "evidenceId": "opening-value-01",
    "atSeconds": 0.8,
    "evidence": "What exact viewer value is understandable at this time"
  },
  "semanticTension": {
    "evidenceId": "opening-tension-01",
    "kind": "contradiction",
    "atSeconds": 1.1,
    "evidence": "What exact unanswered tension is established"
  },
  "firstProof": {
    "evidenceId": "opening-proof-01",
    "kind": "result",
    "atSeconds": 2.0,
    "evidence": "The concrete result/example/demonstration the viewer actually receives"
  },
  "sharedEvidenceJustifications": [
    {
      "evidenceId": "opening-proof-01",
      "concepts": ["viewerValue", "firstProof"],
      "justification": "Use only when this one concrete event genuinely performs both functions."
    }
  ],
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
  ],
  "semanticIntegrity": {
    "sourceText": "بازی فقط وقت تلف کردنه؟",
    "requiredTopicAnchors": ["بازی"],
    "anchorDelivery": "text"
  }
}
```

Allowed `semanticTension.kind` values are `question`, `specific_gap`, `contradiction`, `consequence`, `micro_suspense`, and `direct_benefit`. Allowed concrete `firstProof.kind` values are `answer`, `result`, `example`, `demonstration`, `evidence`, and `mechanism`.

Setup/authority language such as “research shows”, “scientists found”, “a study says”, or “I’ll explain why” is **not** proof unless the actual finding/answer/example has already reached the viewer. `firstProof.atSeconds` is the first time the concrete payoff materially begins, not the beginning of a sentence that merely announces evidence.

Judgement levels are `weak`, `acceptable`, or `strong` and always require rationale, but authored judgements are planning claims rather than final authority. Hook Quality v2 preflight may block weak/malformed evidence but cannot self-certify the production as `strong`; rendered independent review owns final hook strength.

Allowed authored within-shot perceptual-change kinds are `action`, `reaction`, `reveal`, `detail`, `scale_change`, `punch_in`, and `subject_motion`. Shot changes are derived from the actual timeline and must never be authored as evidence. Frame zero is the starting state, not a change. Do not count a typographic moment as the same thing as a meaningful shot/action/reveal change.

## Viewer-visible semantic integrity

For typographic-only hooks, `hookQuality.semanticIntegrity` is required. It records the authored/source meaning and the topic anchors a cold viewer must be able to recover. `requiredTopicAnchors` are checked against the delivered hook text, or against explicit opening visual evidence only when `anchorDelivery` allows visual delivery and the opening is not a text-only plate. Hidden script/metadata never satisfies the viewer-visible contract. A regression such as `بازی فقط وقت تلف کردنه؟` -> `فقط وقت تلف کردنه؟` is a blocking `HOOK_TOPIC_ANCHOR_MISSING`, not a harmless layout compression.

Layout should adapt before meaning is deleted. If a true editorial rewrite is necessary, it must be explicit and evidence-backed rather than performed implicitly to make text fit.

Typographic-only hook duration is also text-aware. Preflight derives a conservative reading-time ceiling from visible characters plus fixation/hold margin. A hold beyond that ceiling is `HOOK_TYPOGRAPHIC_DURATION_EXCESS` unless `typographicDurationJustification` records an intentional editorial reason. This prevents a short black-card hook from sitting static for several seconds merely because its scene span was long.

When a typographic hook overlaps the first spoken sentence, burned captions must use an explicit `hookCaptionHandoff`: `semantic_replacement` resumes at the next complete semantic unit, while `exact_continuation` may continue only if it does not expose a cue fragment that began under the hook. The sidecar SRT remains complete and authoritative in either mode.

## Timing policy

The current thresholds are an **initial conservative calibration policy**, not universal scientific laws:

- viewer value: advisory after 2.0s, blocker after 3.0s;
- semantic tension: advisory after 2.5s, blocker after 4.0s;
- first concrete proof/payoff: advisory after 4.0s, blocker after 6.0s;
- more than four meaningful changes inside the first 3s: over-editing advisory;
- no meaningful post-start visual change inside the first 3s: under-stimulation advisory, not an automatic semantic failure.

Thresholds may change later only through an explicit versioned decision using enough page-specific post-publish evidence. Post-publish analytics never mutate these values automatically.

## Semantic rules

A specific gap is better than generic mystery. `باورت نمی‌شه چی شد` without a reachable missing answer should be flagged as vague. A meaningful contradiction is better than random novelty. Surprise must connect to the topic/body. Audience relevance asks `why should this viewer care?`; unusual information alone is insufficient. Concrete actions/outcomes are preferred in the opening when abstract language is not grounded quickly. Visual footage should depict/support the spoken problem, consequence, action, or tension rather than merely look aesthetically pleasant. Faces and direct gaze may help salience but are never mandatory.

`metaIntroDelay` covers value-delaying setup such as an opening that spends scarce seconds saying it will explain something instead of beginning the explanation. `fullConclusionRevealed` is an advisory because some openings can reveal one result while retaining another concrete reason to continue; record the remaining reason explicitly in evidence.

## Authority boundary

Hook-quality evidence must describe the approved production honestly. It is not permission to silently rewrite authoritative narration. The existing opening moment may use only the paraphrase freedom already granted by `edit-director.md`; it may not invent a claim the body never earns. If authoritative speech itself makes value/tension/payoff arrive too late, use the workflow's editorial revision path rather than trimming meaning invisibly.

## Recovery classes

`HOOK_EVIDENCE` — evidence is missing/malformed; repair metadata without changing approved copy.

`HOOK_TIMING` — viewer value/tension/concrete proof arrives too late; first try edit timing or moving existing proof earlier. If authoritative speech itself causes the delay, request editorial re-authoring.

`HOOK_VISUAL_ALIGNMENT` — opening footage/perceptual evidence does not support the spoken tension; revise sourcing, window, crop, action, or shot order.

`HOOK_AUTHORING` — the semantic hook itself is vague, irrelevant, or unsupported by the body; use the authorized editorial revision path.

## Final rendered review

Preflight evidence is a prediction about the authored edit. It does not prove the real MP4 communicates the hook. For productions whose persisted preflight says Hook Quality is required, `final_review.metadata.hookQualityReview` must use the rendered-v2 contract:

- `version: "2.0"`;
- `reviewSource: "rendered_mp4"`;
- `reviewerRole: "independent_reviewer"` — do not let the authoring/editing role certify its own hook;
- `reviewedCandidateSha256` matching the exact MP4 bytes;
- `strength`: `weak`, `acceptable`, or `strong`;
- non-empty `rationale` and at least two opening-specific observations from the real render;
- `mutedHookDirectionConfirmed`;
- `visualVoiceAlignment`;
- `concretePayoffKind` using the same concrete proof kinds above;
- `actualPayoffSeconds` measured from what the viewer actually receives;
- non-empty `payoffEvidence`;
- `payoffBeginsPromptly`.

A weak rendered hook, failed muted direction, weak visual/voice alignment, non-concrete payoff, digest mismatch, or delayed payoff may be persisted honestly as failed/revise evidence, but it blocks presentation. Only acceptable/strong rendered evidence may advance to presentation.

## Post-publish calibration

After publication, real platform observations belong in the independent `post_publish_performance` artifact, bound to the exact published MP4 SHA-256. Use append-only snapshots such as 1h, 4h, 24h, and 72h when available. Missing platform metrics remain null/absent; never fabricate them. `calibration_mode` is `observational`. No post-publish record authorizes automatic threshold learning, narration rewriting, or policy mutation.
