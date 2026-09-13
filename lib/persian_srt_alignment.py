"""Align approved Persian script copy to ASR word timings for sidecar subtitles.

The approved script owns every delivered character. ASR is used only as a clock:
its possibly misspelled words are sequence-aligned to the script, then discarded.
Any uncertain alignment, malformed Persian copy, uncovered speech, overlap, or
reading-speed violation is fatal so an unaligned SRT cannot silently ship.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Iterable, Mapping, Sequence

from lib.persian_srt import MAX_CPS, PersianCue, TimedWord, audit_cues, build_cues
from lib.persian_text import (
    ZWNJ,
    compare_key,
    normalize,
    to_ascii_digits,
    to_persian_digits,
    visible_length,
)

MATCH_POLICIES = frozenset({"exact", "normalized"})
MAX_ALIGNMENT_GROUP = 3
MIN_GROUP_SIMILARITY = 0.28
MIN_OVERALL_SIMILARITY = 0.55
MAX_ASR_INSERTION_FRACTION = 0.20
COVERAGE_EPSILON_SECONDS = 0.08
TIMING_EPSILON_SECONDS = 0.001
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MISSING_ZWNJ_RE = re.compile(r"(?<!\S)(?:می|نمی) (?=\S)")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+[،؛؟.!:…]")


class SubtitleAlignmentError(ValueError):
    """The SRT cannot be proved to match the approved script and narration."""


@dataclass(frozen=True)
class ApprovedScript:
    text: str
    display_text: str
    match_policy: str
    sha256: str
    max_cps: float


@dataclass(frozen=True)
class _Token:
    surface: str
    key: str


@dataclass(frozen=True)
class _AsrWord:
    surface: str
    key: str
    start: float
    end: float


@dataclass
class _Match:
    script_start: int
    script_end: int
    asr_start: int
    asr_end: int
    similarity: float
    extended_asr_start: int | None = None
    extended_asr_end: int | None = None


def _fail(problems: Sequence[str]) -> None:
    raise SubtitleAlignmentError(
        "script-aligned subtitle validation failed:\n  - " + "\n  - ".join(problems)
    )


def _parse_approved_script(raw: Mapping[str, Any] | None) -> ApprovedScript:
    if not isinstance(raw, Mapping):
        _fail([
            "metadata.persianSubtitleScript is required when audio.wordTimings is present; "
            "ASR wording is timing evidence, never delivery copy"
        ])

    text = raw.get("text")
    if not isinstance(text, str) or not text:
        _fail(["approvedScript.text must be a non-empty string"])

    digest = raw.get("sha256")
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        _fail(["approvedScript.sha256 must be a lowercase 64-character SHA-256 digest"])
    actual_digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if digest != actual_digest:
        _fail([
            "approvedScript.sha256 does not match the exact UTF-8 bytes of "
            "approvedScript.text"
        ])

    policy = str(raw.get("matchPolicy") or "")
    if policy not in MATCH_POLICIES:
        _fail(["approvedScript.matchPolicy must be 'exact' or 'normalized'"])

    try:
        max_cps = float(raw.get("maxCps", MAX_CPS))
    except (TypeError, ValueError):
        _fail(["approvedScript.maxCps must be a number"])
    if not math.isfinite(max_cps) or max_cps <= 0 or max_cps > MAX_CPS:
        _fail([
            f"approvedScript.maxCps must be greater than zero and no higher than "
            f"the repository ceiling of {MAX_CPS:g}"
        ])

    problems = _audit_script_text(text, policy)
    if problems:
        _fail(problems)

    display_text = text if policy == "exact" else to_persian_digits(normalize(text))
    return ApprovedScript(
        text=text,
        display_text=display_text,
        match_policy=policy,
        sha256=digest,
        max_cps=max_cps,
    )


def _audit_script_text(text: str, match_policy: str) -> list[str]:
    problems: list[str] = []
    if text != text.strip(" "):
        problems.append("approved script has leading or trailing spaces")
    if any(ch.isspace() and ch != " " for ch in text):
        problems.append(
            "approved script must use one ASCII space between tokens; tabs, newlines, "
            "and other whitespace are not accepted"
        )
    if "  " in text:
        problems.append("approved script has repeated spaces")
    if match_policy == "exact" and normalize(text) != text:
        problems.append(
            "exact approved script is not in canonical Persian NFC/Farsi-yeh/keheh form"
        )
    if _SPACE_BEFORE_PUNCT_RE.search(text):
        problems.append("approved script has whitespace before Persian punctuation")
    if _MISSING_ZWNJ_RE.search(text):
        problems.append(
            "approved script contains «می » or «نمی » with a space; use ZWNJ "
            "inside the compound (for example «می‌کند»)"
        )

    for index, char in enumerate(text):
        if char != ZWNJ:
            continue
        if (
            index == 0
            or index == len(text) - 1
            or not text[index - 1].isalpha()
            or not text[index + 1].isalpha()
        ):
            problems.append(
                f"approved script has a malformed ZWNJ at code-point index {index}; "
                "ZWNJ must sit between two letters"
            )
    return problems


def _lexical_key(text: str) -> str:
    return compare_key(to_ascii_digits(normalize(text))).replace(" ", "")


def _script_tokens(script: ApprovedScript) -> list[_Token]:
    tokens = [
        _Token(surface=surface, key=_lexical_key(surface))
        for surface in script.display_text.split(" ")
    ]
    if not tokens or any(not token.surface for token in tokens):
        _fail(["approved script did not yield a non-empty token sequence"])
    return tokens


def _asr_words(words: Iterable[Mapping[str, Any]]) -> list[_AsrWord]:
    parsed: list[_AsrWord] = []
    problems: list[str] = []
    for index, raw in enumerate(words):
        if not isinstance(raw, Mapping):
            problems.append(f"ASR word {index} must be an object")
            continue
        surface = raw.get("word", raw.get("text"))
        if surface is None:
            problems.append(f"ASR word {index} has neither 'word' nor 'text'")
            continue
        if "start" not in raw or "end" not in raw:
            problems.append(f"ASR word {index} is missing start/end")
            continue
        try:
            start = float(raw["start"])
            end = float(raw["end"])
        except (TypeError, ValueError):
            problems.append(f"ASR word {index} has non-numeric start/end")
            continue
        cleaned = normalize(str(surface)).strip()
        if not cleaned:
            continue
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            problems.append(
                f"ASR word {index} has an invalid window {start!r}-{end!r}"
            )
            continue
        if parsed and start < parsed[-1].start:
            problems.append(
                f"ASR word {index} starts before the preceding word; timings are not ordered"
            )
        if parsed and start < parsed[-1].end - TIMING_EPSILON_SECONDS:
            problems.append(
                f"ASR word {index - 1} overlaps word {index} by more than "
                f"{TIMING_EPSILON_SECONDS:.3f}s"
            )
        parsed.append(
            _AsrWord(
                surface=cleaned,
                key=_lexical_key(cleaned),
                start=start,
                end=end,
            )
        )

    if problems:
        _fail(problems)
    if not parsed:
        _fail(["audio.wordTimings contains no usable timed words"])
    return parsed


def _similarity(script: Sequence[_Token], asr: Sequence[_AsrWord]) -> float:
    left = "".join(token.key for token in script)
    right = "".join(word.key for word in asr)
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right, autojunk=False).ratio()


def _align_tokens(script: list[_Token], asr: list[_AsrWord]) -> list[_Match]:
    n, m = len(script), len(asr)
    infinity = float("inf")
    dp = [[infinity] * (m + 1) for _ in range(n + 1)]
    back: list[list[tuple[int, int, str, float] | None]] = [
        [None] * (m + 1) for _ in range(n + 1)
    ]
    dp[0][0] = 0.0

    for i in range(n + 1):
        for j in range(m + 1):
            base = dp[i][j]
            if not math.isfinite(base):
                continue

            if j < m:
                insertion_cost = base + 0.72
                if insertion_cost < dp[i][j + 1]:
                    dp[i][j + 1] = insertion_cost
                    back[i][j + 1] = (i, j, "insert", 0.0)

            for script_count in range(1, MAX_ALIGNMENT_GROUP + 1):
                if i + script_count > n:
                    break
                for asr_count in range(1, MAX_ALIGNMENT_GROUP + 1):
                    if j + asr_count > m:
                        break
                    similarity = _similarity(
                        script[i : i + script_count],
                        asr[j : j + asr_count],
                    )
                    grouping_cost = 0.025 * (script_count + asr_count - 2)
                    shape_cost = 0.035 * abs(script_count - asr_count)
                    candidate = base + (1.0 - similarity) + grouping_cost + shape_cost
                    if candidate < dp[i + script_count][j + asr_count]:
                        dp[i + script_count][j + asr_count] = candidate
                        back[i + script_count][j + asr_count] = (
                            i,
                            j,
                            "match",
                            similarity,
                        )

    if not math.isfinite(dp[n][m]):
        _fail([
            "approved script cannot be aligned to the supplied ASR sequence without "
            "inventing timing for script words absent from the narration"
        ])

    path: list[tuple[str, int, int, int, int, float]] = []
    i, j = n, m
    while i or j:
        step = back[i][j]
        if step is None:
            _fail(["subtitle alignment backtrace is incomplete"])
        previous_i, previous_j, kind, similarity = step
        path.append((kind, previous_i, i, previous_j, j, similarity))
        i, j = previous_i, previous_j
    path.reverse()

    matches: list[_Match] = []
    inserted = 0
    pending_prefix: list[int] = []
    for kind, script_start, script_end, asr_start, asr_end, similarity in path:
        if kind == "insert":
            inserted += asr_end - asr_start
            if matches:
                matches[-1].extended_asr_end = asr_end
            else:
                pending_prefix.extend(range(asr_start, asr_end))
            continue

        match = _Match(
            script_start=script_start,
            script_end=script_end,
            asr_start=asr_start,
            asr_end=asr_end,
            similarity=similarity,
            extended_asr_start=(pending_prefix[0] if pending_prefix else asr_start),
            extended_asr_end=asr_end,
        )
        pending_prefix.clear()
        matches.append(match)

    if pending_prefix:
        _fail(["ASR prefix could not be attached to an aligned script phrase"])
    if not matches:
        _fail(["no script phrase aligned to the narration"])

    problems: list[str] = []
    weighted_similarity = 0.0
    weighted_tokens = 0
    for match in matches:
        token_count = match.script_end - match.script_start
        weighted_similarity += match.similarity * token_count
        weighted_tokens += token_count
        if match.similarity < MIN_GROUP_SIMILARITY:
            script_surface = " ".join(
                token.surface for token in script[match.script_start : match.script_end]
            )
            asr_surface = " ".join(
                word.surface for word in asr[match.asr_start : match.asr_end]
            )
            problems.append(
                f"low-confidence phrase alignment ({match.similarity:.2f}): "
                f"script «{script_surface}» vs ASR «{asr_surface}»"
            )

    overall_similarity = weighted_similarity / max(1, weighted_tokens)
    if overall_similarity < MIN_OVERALL_SIMILARITY:
        problems.append(
            f"overall lexical alignment confidence {overall_similarity:.2f} is below "
            f"the {MIN_OVERALL_SIMILARITY:.2f} floor"
        )
    insertion_fraction = inserted / max(1, len(asr))
    if insertion_fraction > MAX_ASR_INSERTION_FRACTION:
        problems.append(
            f"{inserted}/{len(asr)} ASR words ({insertion_fraction:.1%}) have no "
            "approved-script counterpart"
        )
    if problems:
        _fail(problems)
    return matches


def _timed_script_words(
    script: list[_Token], asr: list[_AsrWord], matches: list[_Match]
) -> list[TimedWord]:
    aligned: list[TimedWord] = []
    for match in matches:
        script_group = script[match.script_start : match.script_end]
        asr_group = asr[match.asr_start : match.asr_end]
        extended_start = (
            match.extended_asr_start
            if match.extended_asr_start is not None
            else match.asr_start
        )
        extended_end = (
            match.extended_asr_end
            if match.extended_asr_end is not None
            else match.asr_end
        )

        if len(script_group) == len(asr_group):
            for offset, (token, source_word) in enumerate(zip(script_group, asr_group)):
                start = source_word.start
                end = source_word.end
                if offset == 0:
                    start = asr[extended_start].start
                if offset == len(script_group) - 1:
                    end = asr[extended_end - 1].end
                aligned.append(TimedWord(text=token.surface, start=start, end=end))
            continue

        span_start = asr[extended_start].start
        span_end = asr[extended_end - 1].end
        weights = [max(1, visible_length(token.surface)) for token in script_group]
        total_weight = sum(weights)
        cursor = span_start
        consumed = 0
        for offset, (token, weight) in enumerate(zip(script_group, weights)):
            consumed += weight
            end = (
                span_end
                if offset == len(script_group) - 1
                else span_start + (span_end - span_start) * consumed / total_weight
            )
            aligned.append(TimedWord(text=token.surface, start=cursor, end=end))
            cursor = end

    if len(aligned) != len(script):
        _fail([
            f"alignment produced timings for {len(aligned)}/{len(script)} approved "
            "script tokens"
        ])
    return aligned


def _normalized_lexical_text(text: str) -> str:
    return " ".join(
        key
        for token in normalize(text).split()
        if (key := _lexical_key(token))
    )


def _audit_aligned_cues(
    cues: list[PersianCue],
    script: ApprovedScript,
    asr: list[_AsrWord],
    *,
    max_visible_chars: int | None = None,
) -> list[str]:
    problems = list(audit_cues(cues))
    if max_visible_chars is not None:
        for cue in cues:
            if visible_length(cue.text) > max_visible_chars:
                problems.append(
                    f"{cue.id}: {visible_length(cue.text)} visible chars exceeds "
                    f"the requested {max_visible_chars}-character display ceiling"
                )
    joined = " ".join(cue.text for cue in cues)

    if script.match_policy == "exact":
        if joined != script.text:
            problems.append(
                "delivered cue text is not byte-for-byte equal to the approved script "
                "under matchPolicy='exact'"
            )
    elif _normalized_lexical_text(joined) != _normalized_lexical_text(script.text):
        problems.append(
            "delivered cue text is not lexically equal to the approved script under "
            "matchPolicy='normalized'"
        )

    for cue in cues:
        if cue.cps > script.max_cps:
            problems.append(
                f"{cue.id}: {cue.cps:.1f} chars/sec exceeds configured "
                f"approvedScript.maxCps={script.max_cps:g}"
            )

    if cues:
        if cues[0].start_seconds > asr[0].start + COVERAGE_EPSILON_SECONDS:
            problems.append(
                f"subtitle coverage starts at {cues[0].start_seconds:.2f}s after "
                f"speech begins at {asr[0].start:.2f}s"
            )
        if cues[-1].end_seconds < asr[-1].end - COVERAGE_EPSILON_SECONDS:
            problems.append(
                f"subtitle coverage ends at {cues[-1].end_seconds:.2f}s before "
                f"speech ends at {asr[-1].end:.2f}s"
            )

    for index, word in enumerate(asr):
        midpoint = (word.start + word.end) / 2.0
        if not any(
            cue.start_seconds - COVERAGE_EPSILON_SECONDS
            <= midpoint
            <= cue.end_seconds + COVERAGE_EPSILON_SECONDS
            for cue in cues
        ):
            problems.append(
                f"ASR timing word {index} «{word.surface}» at {word.start:.2f}-"
                f"{word.end:.2f}s falls in an unexplained subtitle gap"
            )

    return problems


def build_script_aligned_cues(
    approved_script: Mapping[str, Any] | None,
    words: Iterable[Mapping[str, Any]],
    *,
    max_visible_chars: int | None = None,
    id_prefix: str = "cue",
    min_connector_words: int = 0,
) -> list[PersianCue]:
    """Build delivery-safe cues from approved copy plus raw ASR timing words.

    `approved_script` must contain `text`, `sha256`, and `matchPolicy` (`exact` or
    `normalized`). `maxCps` may lower, but never raise, the repository's reading-
    speed ceiling. `max_visible_chars` may additionally tighten grouping for a
    burned display without changing the sidecar policy. The returned cue text comes
    only from the approved script; ASR strings are discarded after timing alignment.

    Raises:
        SubtitleAlignmentError: for any uncertainty or delivery-policy violation.
    """
    script_record = _parse_approved_script(approved_script)
    script_tokens = _script_tokens(script_record)
    asr_words = _asr_words(words)
    matches = _align_tokens(script_tokens, asr_words)
    timed_words = _timed_script_words(script_tokens, asr_words, matches)
    cues = build_cues(
        [
            {"word": word.text, "start": word.start, "end": word.end}
            for word in timed_words
        ],
        persian_digits=False,
        id_prefix=id_prefix,
        max_visible_chars=(
            max_visible_chars if max_visible_chars is not None else 84
        ),
        min_connector_words=min_connector_words,
    )
    if not cues:
        _fail(["alignment produced no subtitle cues"])

    problems = _audit_aligned_cues(
        cues, script_record, asr_words, max_visible_chars=max_visible_chars
    )
    if problems:
        _fail(problems)
    return cues


__all__ = [
    "MATCH_POLICIES",
    "MIN_GROUP_SIMILARITY",
    "MIN_OVERALL_SIMILARITY",
    "MAX_ASR_INSERTION_FRACTION",
    "SubtitleAlignmentError",
    "ApprovedScript",
    "build_script_aligned_cues",
]
