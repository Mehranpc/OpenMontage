from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "persian"
    / "p4_failed_shadow"
    / "issue138-v1.json"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_TRACE32 = re.compile(r"^[0-9a-f]{32}$")
_CASE_IDS = {"F1", "F2", "F3", "F4"}


class FailedShadowFixtureError(ValueError):
    pass


def fixture_digest(payload: Mapping[str, Any]) -> str:
    material = dict(payload)
    material.pop("fixtureDigestSha256", None)
    encoded = json.dumps(
        material, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FailedShadowFixtureError(f"{path} must be an object")
    return value


def _required(obj: Mapping[str, Any], key: str, path: str) -> Any:
    if key not in obj:
        raise FailedShadowFixtureError(f"{path}.{key} is required")
    return obj[key]


def resolve_authority(payload: Mapping[str, Any], reference: str) -> Any:
    if not reference.startswith("authority."):
        raise FailedShadowFixtureError(
            f"authority reference must start with 'authority.': {reference!r}"
        )
    value: Any = payload
    for part in reference.split("."):
        value = _mapping(value, reference)
        if part not in value:
            raise FailedShadowFixtureError(
                f"authority reference does not resolve: {reference!r}"
            )
        value = value[part]
    return value


def _validate_sha_fields(value: Any, path: str = "fixture") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key).lower().endswith("sha256") and not _SHA256.fullmatch(
                str(child)
            ):
                raise FailedShadowFixtureError(
                    f"{child_path} must be a lowercase SHA-256"
                )
            _validate_sha_fields(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_sha_fields(child, f"{path}[{index}]")


def _validate_portable(value: Any, path: str = "fixture") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            _validate_portable(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_portable(child, f"{path}[{index}]")
    elif isinstance(value, str):
        lowered = value.lower()
        if "/users/" in lowered or lowered.startswith("/home/"):
            raise FailedShadowFixtureError(
                f"{path} contains a machine-local absolute path"
            )
        if lowered.endswith((".mp4", ".mov", ".wav", ".mp3")):
            raise FailedShadowFixtureError(
                f"{path} introduces a production-media dependency"
            )


def _validate_window(value: Any, path: str) -> Mapping[str, Any]:
    window = _mapping(value, path)
    start = float(_required(window, "startSeconds", path))
    end = float(_required(window, "endSeconds", path))
    if start < 0 or end <= start:
        raise FailedShadowFixtureError(f"{path} must be a positive source window")
    return window


def _validate_f1(payload: Mapping[str, Any], case: Mapping[str, Any]) -> None:
    data = _mapping(_required(case, "input", "cases.F1"), "cases.F1.input")
    moment = _mapping(_required(data, "moment", "cases.F1.input"), "cases.F1.input.moment")
    if _required(moment, "id", "cases.F1.input.moment") != "moment-2":
        raise FailedShadowFixtureError("cases.F1 must preserve moment-2")
    copy_spec = _mapping(
        _required(moment, "displayCopy", "cases.F1.input.moment"),
        "cases.F1.input.moment.displayCopy",
    )
    if copy_spec.get("mode") not in {"exact", "adaptable"} or not copy_spec.get("text"):
        raise FailedShadowFixtureError("cases.F1 requires authoritative display copy")
    shot = _mapping(_required(data, "shot", "cases.F1.input"), "cases.F1.input.shot")
    regions = resolve_authority(payload, str(_required(shot, "hardRegionAuthority", "cases.F1.input.shot")))
    if not isinstance(regions, list) or not regions:
        raise FailedShadowFixtureError("cases.F1 requires reviewed hard regions")
    if any(_mapping(region, "F1 hard region").get("priority") != "hard" for region in regions):
        raise FailedShadowFixtureError("cases.F1 regions must preserve hard priority")
    expected = _mapping(_required(case, "expected", "cases.F1"), "cases.F1.expected")
    if expected.get("diagnosticCode") != "ASSET_SELECTION_HARD_REGION_COLLISION":
        raise FailedShadowFixtureError("cases.F1 must preserve the blocking diagnostic")
    if expected.get("stage") != "geometric_precheck":
        raise FailedShadowFixtureError("cases.F1 must target the geometric pre-check")
    before = set(expected.get("mustRejectBefore") or [])
    if not {"chromium", "candidate_counter_increment"}.issubset(before):
        raise FailedShadowFixtureError("cases.F1 must reject before browser and candidate count")


def _validate_f2(payload: Mapping[str, Any], case: Mapping[str, Any]) -> None:
    data = _mapping(_required(case, "input", "cases.F2"), "cases.F2.input")
    hook = _mapping(resolve_authority(payload, str(_required(data, "hookAuthority", "cases.F2.input"))), "cases.F2 hook authority")
    if hook.get("mode") != "user_supplied" or hook.get("authoritative") is not True:
        raise FailedShadowFixtureError("cases.F2 must preserve user_supplied hook authority")
    policy = _mapping(resolve_authority(payload, str(_required(data, "policyPin", "cases.F2.input"))), "cases.F2 policy pin")
    if not policy.get("filmTypeProfileVersion"):
        raise FailedShadowFixtureError("cases.F2 requires a pinned Film Type profile")
    observed = _mapping(_required(case, "observed", "cases.F2"), "cases.F2.observed")
    if observed.get("standaloneExtraBlockingCode") != "HOOK_QUALITY_GATE":
        raise FailedShadowFixtureError("cases.F2 must preserve the observed probe divergence")
    expected = _mapping(_required(case, "expected", "cases.F2"), "cases.F2.expected")
    if expected.get("blockingSetParity") is not True or expected.get("readOnly") is not True:
        raise FailedShadowFixtureError("cases.F2 must require read-only blocking-set parity")
    if expected.get("durableSideEffects") is not False:
        raise FailedShadowFixtureError("cases.F2 probe must have zero durable side effects")


def _validate_f3(payload: Mapping[str, Any], case: Mapping[str, Any]) -> None:
    data = _mapping(_required(case, "input", "cases.F3"), "cases.F3.input")
    selected = _mapping(resolve_authority(payload, str(_required(data, "selectedAuthority", "cases.F3.input"))), "cases.F3 selected authority")
    manifest = _mapping(resolve_authority(payload, str(_required(data, "manifestAuthority", "cases.F3.input"))), "cases.F3 manifest authority")
    for key in ("candidateId", "candidateIdentitySha256", "reviewSha256", "sourceId"):
        _required(selected, key, "authority.assetWorkspace.event-2")
        _required(manifest, key, "authority.assetManifest.event-2")
    if any(selected[key] != manifest[key] for key in ("candidateId", "candidateIdentitySha256", "reviewSha256", "sourceId")):
        raise FailedShadowFixtureError("F3 selected workspace and manifest authority must agree")
    selected_window = _validate_window(_required(selected, "reviewedWindow", "authority.assetWorkspace.event-2"), "authority.assetWorkspace.event-2.reviewedWindow")
    manifest_window = _validate_window(_required(manifest, "sourceWindow", "authority.assetManifest.event-2"), "authority.assetManifest.event-2.sourceWindow")
    if dict(selected_window) != dict(manifest_window):
        raise FailedShadowFixtureError("F3 manifest must bind the selected reviewed window")
    attempted = _mapping(_required(data, "attemptedEditIdentity", "cases.F3.input"), "cases.F3.input.attemptedEditIdentity")
    attempted_window = _validate_window(_required(attempted, "sourceWindow", "cases.F3.input.attemptedEditIdentity"), "cases.F3.input.attemptedEditIdentity.sourceWindow")
    if dict(attempted_window) == dict(selected_window):
        raise FailedShadowFixtureError("F3 must preserve the unreviewed-window mismatch")
    if attempted.get("cropTransformIdentity") is None and attempted.get("cropTransformAuthority") != "missing_in_failed_edit_candidate":
        raise FailedShadowFixtureError("F3 missing crop identity must be explicit, never inferred")
    expected = _mapping(_required(case, "expected", "cases.F3"), "cases.F3.expected")
    if expected.get("stage") != "edit-stage" or expected.get("beforeCandidateConsumption") is not True:
        raise FailedShadowFixtureError("F3 must refuse at edit-stage before candidate consumption")
    if expected.get("recoveryRoute") != "send_back:acquire_assets":
        raise FailedShadowFixtureError("F3 must route through bounded acquire_assets send-back")
    if expected.get("diagnosticCode") is None and expected.get("diagnosticCodeAuthority") != "not_defined_by_issue138":
        raise FailedShadowFixtureError("F3 undefined diagnostic code must be modeled explicitly")


def _validate_f4(case: Mapping[str, Any]) -> None:
    data = _mapping(_required(case, "input", "cases.F4"), "cases.F4.input")
    observed = _mapping(_required(case, "observed", "cases.F4"), "cases.F4.observed")
    if float(observed.get("wallSeconds") or 0) <= float(data.get("wallBudgetSeconds") or 0):
        raise FailedShadowFixtureError("F4 must preserve an actual wall-budget overrun")
    if observed.get("budgetStop") is not None:
        raise FailedShadowFixtureError("F4 historical evidence must preserve the missing in-phase stop")
    expected = _mapping(_required(case, "expected", "cases.F4"), "cases.F4.expected")
    if expected.get("status") != "needs_decision" or expected.get("reason") != "wall_budget_exceeded":
        raise FailedShadowFixtureError("F4 must expect the stable budget stop")
    if expected.get("startsNewExpensiveWork") is not False:
        raise FailedShadowFixtureError("F4 must forbid new expensive work after expiry")


def validate_issue138_fixture(payload: Mapping[str, Any]) -> None:
    if payload.get("schemaVersion") != "1.0":
        raise FailedShadowFixtureError("unsupported failed-shadow fixture schema")
    if payload.get("fixtureId") != "issue138-p4-shadow-20260925-v1":
        raise FailedShadowFixtureError("unexpected failed-shadow fixture identity")
    expected_digest = str(_required(payload, "fixtureDigestSha256", "fixture"))
    if not _SHA256.fullmatch(expected_digest) or fixture_digest(payload) != expected_digest:
        raise FailedShadowFixtureError("failed-shadow fixture digest mismatch")
    source = _mapping(_required(payload, "sourceEvidence", "fixture"), "sourceEvidence")
    if source.get("issueNumber") != 138 or source.get("immutableSource") is not True:
        raise FailedShadowFixtureError("sourceEvidence must bind immutable issue #138 evidence")
    if not _SHA40.fullmatch(str(source.get("sourceMainSha") or "")):
        raise FailedShadowFixtureError("sourceEvidence.sourceMainSha must be a commit SHA")
    if not _TRACE32.fullmatch(str(source.get("traceId") or "")):
        raise FailedShadowFixtureError("sourceEvidence.traceId must be the failed-run trace id")
    artifacts = source.get("sourceArtifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise FailedShadowFixtureError("sourceEvidence.sourceArtifacts is required")
    _mapping(_required(payload, "authority", "fixture"), "authority")
    cases = _mapping(_required(payload, "cases", "fixture"), "cases")
    if set(cases) != _CASE_IDS:
        raise FailedShadowFixtureError("fixture must contain exactly F1, F2, F3, and F4")
    _validate_sha_fields(payload)
    _validate_portable(payload)
    _validate_f1(payload, _mapping(cases["F1"], "cases.F1"))
    _validate_f2(payload, _mapping(cases["F2"], "cases.F2"))
    _validate_f3(payload, _mapping(cases["F3"], "cases.F3"))
    _validate_f4(_mapping(cases["F4"], "cases.F4"))


def load_issue138_fixture(path: Path | None = None) -> dict[str, Any]:
    fixture_path = path or FIXTURE_PATH
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FailedShadowFixtureError(
            f"cannot load failed-shadow fixture: {fixture_path}"
        ) from exc
    payload = _mapping(payload, "fixture")
    validate_issue138_fixture(payload)
    return copy.deepcopy(dict(payload))


def fixture_case(payload: Mapping[str, Any], case_id: str) -> dict[str, Any]:
    validate_issue138_fixture(payload)
    if case_id not in _CASE_IDS:
        raise FailedShadowFixtureError(f"unknown failed-shadow case: {case_id!r}")
    return copy.deepcopy(dict(_mapping(payload["cases"][case_id], f"cases.{case_id}")))
