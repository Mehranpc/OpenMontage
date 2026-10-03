"""Offline joint-coverage experiment over a frozen recovery frontier (#382 increment B).

This module is an *evaluation harness*, not sourcing, selection or mutation authority.
It reads an already-produced ``preparation.recoveryEvidence`` report (or a sanitized
corpus derived from it), never a workspace, provider, browser or media file.

Hypothesis 2 of #382: independently admissible alternates for different unresolved
events can conflict with one another through visible source-window overlap, so an
event-by-event choice may cover fewer events than a jointly compatible one. The
harness measures that mechanically; it never chooses footage, ranks semantics, or
infers meaning from queries, filenames or tags. Shared admission at selection time
remains decisive, and zero known admissible evidence is not proof of impossibility.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence

CORPUS_VERSION = "issue382-joint-coverage-corpus/1.0"
CERTIFICATE_VERSION = "issue382-joint-coverage-certificate/1.0"
DEFAULT_MAX_BRANCHES = 20000
_EPSILON = 1e-6
_STATUSES = ("admissible", "blocked", "rejected", "unreviewed", "unavailable")


class RecoveryExperimentError(ValueError):
    """The input is not a recovery-evidence report or sanitized corpus."""


def _sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _window(identity: object) -> list[float] | None:
    if not isinstance(identity, Mapping):
        return None
    window = identity.get("sourceWindow")
    if not isinstance(window, Mapping):
        return None
    try:
        start = float(window["startSeconds"])
        end = float(window["endSeconds"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (math.isfinite(start) and math.isfinite(end) and start >= 0 and end - start > _EPSILON):
        return None
    return [round(start, 6), round(end, 6)]


def _source_ref(identity: object) -> str | None:
    if not isinstance(identity, Mapping):
        return None
    provider, source_id = identity.get("provider"), identity.get("sourceId")
    if not isinstance(provider, str) or not isinstance(source_id, str) or not provider or not source_id:
        return None
    # Hashed so a published corpus carries identity equality, not provider asset ids.
    return "src-" + _sha256({"provider": provider, "sourceId": source_id})[:16]


def sanitize_recovery_corpus(report: Mapping[str, Any]) -> dict[str, Any]:
    """Project a recoveryEvidence report onto the minimum publishable corpus.

    Keeps candidate status, admission codes, rejection *category*, hashed source
    identity and source window. Drops rejection reason text, review digests, crops and
    every path. Rows whose identity cannot be projected become ``unavailable``.
    """
    if not isinstance(report, Mapping) or not isinstance(report.get("events"), Mapping):
        raise RecoveryExperimentError("recovery evidence report with an events map is required")
    complete = report.get("complete") is True
    events: dict[str, list[dict[str, Any]]] = {}
    for event_id in sorted(str(key) for key in report["events"]):
        rows = report["events"][event_id]
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            raise RecoveryExperimentError(f"{event_id}: candidate rows must be a list")
        projected: list[dict[str, Any]] = []
        for raw in rows:
            if not isinstance(raw, Mapping):
                raise RecoveryExperimentError(f"{event_id}: candidate row must be an object")
            status = str(raw.get("status") or "")
            if status not in _STATUSES:
                status, codes = "unavailable", ["STATUS_UNKNOWN"]
            else:
                codes = sorted({str(code) for code in raw.get("codes") or []})
            row: dict[str, Any] = {
                "ref": "cand-" + _sha256(str(raw.get("candidateId") or ""))[:16],
                "status": status,
                "codes": codes,
                "source": _source_ref(raw.get("identity")),
                "window": _window(raw.get("identity")),
            }
            if status == "rejected":
                rejection = raw.get("rejection") if isinstance(raw.get("rejection"), Mapping) else {}
                row["rejectionCategory"] = str(rejection.get("category") or "") or None
            if status == "admissible" and (row["source"] is None or row["window"] is None):
                row.update(status="unavailable", codes=sorted({*codes, "IDENTITY_UNPROJECTABLE"}))
            if row["status"] == "unavailable":
                complete = False
            projected.append(row)
        projected.sort(key=lambda item: item["ref"])
        events[event_id] = projected
    corpus = {
        "version": CORPUS_VERSION,
        "sourceReportInputsSha256": str(report.get("inputsSha256") or "") or None,
        "complete": complete,
        "events": events,
    }
    return {**corpus, "corpusSha256": _sha256(corpus)}


def _overlap(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    if left["source"] != right["source"]:
        return False
    start = max(left["window"][0], right["window"][0])
    end = min(left["window"][1], right["window"][1])
    return end - start > _EPSILON


def _validated_corpus(corpus: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(corpus, Mapping) or corpus.get("version") != CORPUS_VERSION:
        raise RecoveryExperimentError(f"corpus version {CORPUS_VERSION!r} is required")
    body = {key: value for key, value in corpus.items() if key != "corpusSha256"}
    if corpus.get("corpusSha256") != _sha256(body):
        raise RecoveryExperimentError("corpus digest does not match its content")
    return corpus


def joint_coverage_certificate(
    corpus: Mapping[str, Any], *, max_branches: int = DEFAULT_MAX_BRANCHES,
) -> dict[str, Any]:
    """Mechanical joint-compatibility certificate; never an assignment or selection.

    ``independentCoverage`` counts events with any admissible row. ``sequentialCoverage``
    is the deterministic baseline of choosing per event in event order, first
    compatible row in ref order. ``maxJointCoverage`` is exact unless the bounded
    search is exhausted (then status ``unknown``). Conflicts are reported as pairs.
    """
    corpus = _validated_corpus(corpus)
    if not isinstance(max_branches, int) or max_branches < 1:
        raise RecoveryExperimentError("max_branches must be a positive integer")
    options: dict[str, list[dict[str, Any]]] = {}
    without_admissible: list[str] = []
    for event_id, rows in sorted(corpus["events"].items()):
        admissible = [row for row in rows if row["status"] == "admissible"]
        if admissible:
            options[event_id] = admissible
        else:
            without_admissible.append(event_id)
    events = sorted(options)
    conflicts: list[dict[str, str]] = []
    neighbours: dict[str, set[str]] = {event: set() for event in events}
    for index, left_event in enumerate(events):
        for right_event in events[index + 1:]:
            for left in options[left_event]:
                for right in options[right_event]:
                    if _overlap(left, right):
                        conflicts.append({"leftEvent": left_event, "leftRef": left["ref"],
                                          "rightEvent": right_event, "rightRef": right["ref"]})
                        neighbours[left_event].add(right_event)
                        neighbours[right_event].add(left_event)

    # Deterministic per-event baseline: the order an agent walks events today.
    chosen: list[dict[str, Any]] = []
    for event_id in events:
        pick = next((row for row in options[event_id]
                     if not any(_overlap(row, other) for other in chosen)), None)
        if pick is not None:
            chosen.append(pick)
    sequential = len(chosen)

    # Exact maximum by bounded branch-and-bound over events (skip allowed).
    best = sequential
    branches = 0
    exhausted = False

    def search(position: int, picked: list[dict[str, Any]]) -> None:
        nonlocal best, branches, exhausted
        if exhausted:
            return
        branches += 1
        if branches > max_branches:
            exhausted = True
            return
        if len(picked) + (len(events) - position) <= best:
            return
        if position == len(events):
            best = max(best, len(picked))
            return
        for row in options[events[position]]:
            if not any(_overlap(row, other) for other in picked):
                search(position + 1, [*picked, row])
        search(position + 1, picked)

    search(0, [])
    components: list[list[str]] = []
    seen: set[str] = set()
    for event_id in events:
        if event_id in seen or not neighbours[event_id]:
            continue
        stack, group = [event_id], set()
        while stack:
            current = stack.pop()
            if current in group:
                continue
            group.add(current)
            stack.extend(neighbours[current] - group)
        seen |= group
        components.append(sorted(group))
    if not corpus["complete"] or exhausted:
        status = "unknown"
    elif not events:
        status = "no_known_admissible"
    elif best == len(events):
        status = "jointly_compatible"
    else:
        status = "conflicted"
    certificate = {
        "version": CERTIFICATE_VERSION,
        "corpusSha256": corpus["corpusSha256"],
        "status": status,
        "evidenceComplete": corpus["complete"] is True,
        "searchExhausted": exhausted,
        "eventsTotal": len(corpus["events"]),
        "independentCoverage": len(events),
        "sequentialCoverage": sequential,
        "maxJointCoverage": None if exhausted else best,
        "jointGainOverSequential": None if exhausted else best - sequential,
        "eventsWithoutKnownAdmissible": without_admissible,
        "decideTogether": components,
        "conflicts": conflicts,
        "authority": "diagnostic_only",
    }
    return {**certificate, "certificateSha256": _sha256(certificate)}


__all__ = [
    "CERTIFICATE_VERSION", "CORPUS_VERSION", "RecoveryExperimentError",
    "joint_coverage_certificate", "sanitize_recovery_corpus",
]
