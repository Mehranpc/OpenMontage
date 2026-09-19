"""Capability-level alignment provider selection and bounded fallback.

Provider availability is probed before execution. Approved-script production keeps
copy authority outside ASR: providers supply timing evidence only, lightweight
providers are exhausted before any heavy transcription recovery is attempted, and
all selection/fallback reasons are returned as durable JSON-safe evidence.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Mapping, Sequence

from tools.base_tool import ToolStatus
from tools.tool_registry import registry as default_registry

ALIGNMENT_PROVIDER_DECISION_VERSION = "1.0"
_REQUIRED_CAPABILITY = "word_timestamps"

_PROVIDER_PROFILES: tuple[dict[str, Any], ...] = (
    {
        "tool": "transcriber",
        "lightweightArgs": {"model_size": "base"},
        "heavyArgs": {"model_size": "large-v3"},
        "fitClass": "local_word_timing",
    },
    {
        "tool": "mlx_whisper_transcriber",
        "lightweightArgs": {"model": "mlx-community/whisper-small-mlx"},
        "heavyArgs": {"model": "mlx-community/whisper-large-v3-mlx"},
        "fitClass": "apple_silicon_word_timing",
    },
    {
        "tool": "azure_stt",
        "lightweightArgs": {},
        "heavyArgs": None,
        "fitClass": "cloud_word_timing",
    },
)


class AlignmentProviderError(RuntimeError):
    """Raised when no policy-valid alignment provider can satisfy the request."""


def _status_value(value: object) -> str:
    if isinstance(value, ToolStatus):
        return value.value
    return str(value or "unknown").strip().lower()


def _runtime_value(tool: object) -> str | None:
    raw = getattr(tool, "runtime", None)
    if raw is None:
        return None
    return str(getattr(raw, "value", raw))


def _candidate(profile: Mapping[str, Any], *, registry) -> dict[str, Any]:
    name = str(profile["tool"])
    tool = registry.get(name)
    if tool is None:
        return {
            "tool": name,
            "provider": None,
            "availability": "missing",
            "fit": False,
            "fitClass": profile["fitClass"],
            "requiredCapability": _REQUIRED_CAPABILITY,
            "supportsInputPath": False,
            "rejectionReasons": ["tool_not_registered"],
            "lightweightArgs": dict(profile.get("lightweightArgs") or {}),
            "heavyArgs": deepcopy(profile.get("heavyArgs")),
        }

    status = _status_value(tool.get_status())
    capabilities = [str(item) for item in list(getattr(tool, "capabilities", []) or [])]
    schema = getattr(tool, "input_schema", {})
    properties = schema.get("properties") if isinstance(schema, Mapping) else {}
    supports_input_path = isinstance(properties, Mapping) and "input_path" in properties
    reasons: list[str] = []
    if status != ToolStatus.AVAILABLE.value:
        reasons.append(f"provider_{status}")
    if _REQUIRED_CAPABILITY not in capabilities:
        reasons.append(f"missing_capability:{_REQUIRED_CAPABILITY}")
    if not supports_input_path:
        reasons.append("unsupported_input:input_path")
    return {
        "tool": name,
        "provider": str(getattr(tool, "provider", "") or "") or None,
        "availability": status,
        "fit": not reasons,
        "fitClass": profile["fitClass"],
        "requiredCapability": _REQUIRED_CAPABILITY,
        "supportsInputPath": supports_input_path,
        "runtime": _runtime_value(tool),
        "capabilities": capabilities,
        "rejectionReasons": reasons,
        "lightweightArgs": dict(profile.get("lightweightArgs") or {}),
        "heavyArgs": deepcopy(profile.get("heavyArgs")),
    }


def build_alignment_provider_plan(
    policy: Mapping[str, Any], *, registry=default_registry
) -> dict[str, Any]:
    """Return one deterministic provider plan after live capability/status probing."""
    ensure = getattr(registry, "ensure_discovered", None)
    if callable(ensure):
        ensure()
    mode = str(policy.get("mode") or "").strip()
    authority = str(policy.get("scriptAuthority") or "").strip()
    if mode not in {"timing_oriented", "transcription_oriented"}:
        raise AlignmentProviderError(f"unsupported alignment mode: {mode or '<empty>'}")

    candidates = [_candidate(profile, registry=registry) for profile in _PROVIDER_PROFILES]
    selected = next((item for item in candidates if item["fit"]), None)
    if selected is None:
        diagnostics = "; ".join(
            f"{item['tool']}=[{', '.join(item['rejectionReasons']) or 'not-fit'}]"
            for item in candidates
        )
        raise AlignmentProviderError(
            "no available alignment provider satisfies word_timestamps + input_path: " + diagnostics
        )

    first = candidates[0]
    fallback_reason = None
    if selected["tool"] != first["tool"]:
        if first["availability"] != ToolStatus.AVAILABLE.value:
            fallback_reason = f"primary_unavailable:{first['tool']}"
        else:
            fallback_reason = f"primary_incompatible:{first['tool']}"

    return {
        "version": ALIGNMENT_PROVIDER_DECISION_VERSION,
        "capability": _REQUIRED_CAPABILITY,
        "mode": mode,
        "scriptAuthority": authority,
        "primaryProfile": "lightweight" if mode == "timing_oriented" else "transcription_primary",
        "heavyRecoveryAllowed": bool(policy.get("heavyTranscriptionRecoveryOnly")),
        "selectionPolicy": "first_available_policy_valid_provider",
        "selectedTool": selected["tool"],
        "selectedProvider": selected["provider"],
        "fallbackReason": fallback_reason,
        "candidates": candidates,
    }


def _inputs_for_candidate(
    candidate: Mapping[str, Any],
    *,
    profile: str,
    input_path: str,
    output_dir: str,
    language: str | None,
    initial_prompt: str | None,
) -> dict[str, Any]:
    if profile in {"heavy_recovery", "transcription_primary"} and candidate.get("heavyArgs") is not None:
        args_key = "heavyArgs"
    else:
        args_key = "lightweightArgs"
    model_args = candidate.get(args_key)
    if model_args is None:
        raise AlignmentProviderError(
            f"{candidate.get('tool')} does not expose a {profile} profile"
        )
    inputs: dict[str, Any] = {
        "input_path": str(input_path),
        "output_dir": str(output_dir),
    }
    if language:
        inputs["language"] = language
    if initial_prompt:
        inputs["initial_prompt"] = initial_prompt
    inputs.update(dict(model_args))
    return inputs


def _attempt_failure(
    *,
    candidate: Mapping[str, Any],
    profile: str,
    kind: str,
    error: str,
    model: str | None = None,
    duration_seconds: float | None = None,
    invoked: bool,
) -> dict[str, Any]:
    return {
        "tool": candidate["tool"],
        "provider": candidate.get("provider"),
        "profile": profile,
        "model": model or "provider-default",
        "durationSeconds": round(max(0.0, float(duration_seconds or 0.0)), 3),
        "invoked": bool(invoked),
        "semanticSuccess": False,
        "failureKind": kind,
        "error": str(error),
    }


def _success_decision(
    plan: Mapping[str, Any],
    *,
    candidate: Mapping[str, Any],
    attempts: Sequence[Mapping[str, Any]],
    heavy_used: bool,
    fallback_history: Sequence[str],
) -> dict[str, Any]:
    fallback_reason = fallback_history[-1] if fallback_history else plan.get("fallbackReason")
    history: list[str] = []
    if plan.get("fallbackReason"):
        history.append(str(plan["fallbackReason"]))
    history.extend(str(item) for item in fallback_history)
    final_attempt = dict(attempts[-1]) if attempts else {}
    execution_seconds = sum(
        float(item.get("durationSeconds") or 0.0)
        for item in attempts
        if isinstance(item, Mapping) and item.get("invoked") is True
    )
    return {
        **{key: deepcopy(value) for key, value in plan.items() if key not in {"selectedTool", "selectedProvider", "fallbackReason"}},
        "selectedTool": candidate["tool"],
        "selectedProvider": candidate.get("provider"),
        "selectedModel": str(final_attempt.get("model") or "provider-default"),
        "semanticOutcome": "succeeded",
        "executionDurationSeconds": round(execution_seconds, 3),
        "fallbackReason": fallback_reason,
        "fallbackHistory": history,
        "recoveryReason": "lightweight_providers_exhausted" if heavy_used else None,
        "heavyRecoveryUsed": heavy_used,
        "attempts": [dict(item) for item in attempts],
    }


def execute_alignment_with_fallback(
    plan: Mapping[str, Any],
    *,
    input_path: str,
    output_dir: str,
    language: str | None = None,
    initial_prompt: str | None = None,
    registry=default_registry,
    validate_word_timings: Callable[[list[dict[str, Any]]], None] | None = None,
) -> dict[str, Any]:
    """Execute only pre-probed providers, exhausting lightweight paths before heavy recovery."""
    if str(plan.get("version") or "") != ALIGNMENT_PROVIDER_DECISION_VERSION:
        raise AlignmentProviderError("alignment provider plan version is unsupported")
    ensure = getattr(registry, "ensure_discovered", None)
    if callable(ensure):
        ensure()
    candidates = [
        dict(item)
        for item in list(plan.get("candidates") or [])
        if isinstance(item, Mapping)
        and item.get("fit") is True
        and str(item.get("availability") or "") == ToolStatus.AVAILABLE.value
    ]
    if not candidates:
        raise AlignmentProviderError("alignment provider plan has no executable available candidates")

    attempts: list[dict[str, Any]] = []
    fallback_history: list[str] = []

    def attempt(candidate: Mapping[str, Any], profile: str) -> dict[str, Any] | None:
        tool = registry.get(str(candidate["tool"]))
        if tool is None:
            error = "tool disappeared after provider planning"
            attempts.append(_attempt_failure(
                candidate=candidate, profile=profile, kind="provider_missing", error=error,
                invoked=False,
            ))
            fallback_history.append(f"provider_missing:{candidate['tool']}")
            return None
        # Recheck status immediately before execution: a dependency can disappear
        # between planning and invocation. A known-unavailable provider is skipped.
        status = _status_value(tool.get_status())
        if status != ToolStatus.AVAILABLE.value:
            attempts.append(_attempt_failure(
                candidate=candidate, profile=profile, kind="provider_unavailable", error=status,
                invoked=False,
            ))
            fallback_history.append(f"provider_unavailable:{candidate['tool']}")
            return None
        inputs = _inputs_for_candidate(
            candidate,
            profile=profile,
            input_path=input_path,
            output_dir=output_dir,
            language=language,
            initial_prompt=initial_prompt,
        )
        model = str(inputs.get("model") or inputs.get("model_size") or "provider-default")
        result = tool.execute(inputs)
        duration = result.duration_seconds if isinstance(result.duration_seconds, (int, float)) else 0.0
        if not result.success:
            error = str(result.error or "semantic tool failure")
            attempts.append(_attempt_failure(
                candidate=candidate, profile=profile, kind="semantic_failure", error=error,
                model=model, duration_seconds=duration, invoked=True,
            ))
            fallback_history.append(f"semantic_failure:{candidate['tool']}:{error}")
            return None
        data = dict(result.data or {})
        words = list(data.get("word_timestamps") or [])
        if not words:
            error = "provider returned no word_timestamps"
            attempts.append(_attempt_failure(
                candidate=candidate, profile=profile, kind="semantic_failure", error=error,
                model=model, duration_seconds=duration, invoked=True,
            ))
            fallback_history.append(f"semantic_failure:{candidate['tool']}:{error}")
            return None
        if validate_word_timings is not None:
            try:
                validate_word_timings(words)
            except Exception as exc:  # validation is caller-owned policy evidence
                error = str(exc)
                attempts.append(_attempt_failure(
                    candidate=candidate, profile=profile, kind="timing_validation_failure", error=error,
                    model=model, duration_seconds=duration, invoked=True,
                ))
                fallback_history.append(f"timing_validation_failure:{candidate['tool']}:{error}")
                return None
        attempts.append({
            "tool": candidate["tool"],
            "provider": candidate.get("provider"),
            "profile": profile,
            "model": model,
            "durationSeconds": round(max(0.0, float(duration or 0.0)), 3),
            "invoked": True,
            "semanticSuccess": True,
        })
        decision = _success_decision(
            plan,
            candidate=candidate,
            attempts=attempts,
            heavy_used=profile == "heavy_recovery",
            fallback_history=fallback_history,
        )
        data["provider_decision"] = decision
        data["alignment_mode"] = plan.get("mode")
        data["heavy_recovery_used"] = profile == "heavy_recovery"
        return data

    primary_profile = str(plan.get("primaryProfile") or "lightweight")
    if primary_profile not in {"lightweight", "transcription_primary"}:
        raise AlignmentProviderError(f"unsupported primary alignment profile: {primary_profile}")
    for candidate in candidates:
        data = attempt(candidate, primary_profile)
        if data is not None:
            return data

    if bool(plan.get("heavyRecoveryAllowed")):
        for candidate in candidates:
            if candidate.get("heavyArgs") is None:
                continue
            data = attempt(candidate, "heavy_recovery")
            if data is not None:
                return data

    summary = "; ".join(
        f"{item['tool']}:{item['profile']}:{item.get('failureKind')}:{item.get('error')}"
        for item in attempts
    )
    raise AlignmentProviderError("alignment providers exhausted without valid word timing evidence: " + summary)


def validate_alignment_provider_decision(
    decision: Mapping[str, Any], policy: Mapping[str, Any]
) -> None:
    """Validate persisted selection/fallback evidence without reprobeing providers."""
    if not isinstance(decision, Mapping):
        raise AlignmentProviderError("alignment provider decision must be an object")
    if str(decision.get("version") or "") != ALIGNMENT_PROVIDER_DECISION_VERSION:
        raise AlignmentProviderError("alignment provider decision version is unsupported")
    if str(decision.get("capability") or "") != _REQUIRED_CAPABILITY:
        raise AlignmentProviderError("alignment provider decision must certify word_timestamps capability")
    expected_mode = str(policy.get("mode") or "")
    if str(decision.get("mode") or "") != expected_mode:
        raise AlignmentProviderError("alignment provider decision mode does not match workflow policy")
    expected_authority = str(policy.get("scriptAuthority") or "")
    if str(decision.get("scriptAuthority") or "") != expected_authority:
        raise AlignmentProviderError("alignment provider decision script authority does not match workflow policy")

    candidates_raw = decision.get("candidates")
    if not isinstance(candidates_raw, list) or not candidates_raw:
        raise AlignmentProviderError("alignment provider decision requires candidate availability evidence")
    candidates: dict[str, Mapping[str, Any]] = {}
    for item in candidates_raw:
        if not isinstance(item, Mapping):
            raise AlignmentProviderError("alignment provider candidates must be objects")
        name = str(item.get("tool") or "")
        if not name or name in candidates:
            raise AlignmentProviderError("alignment provider candidates require unique tool names")
        candidates[name] = item

    selected_tool = str(decision.get("selectedTool") or "")
    selected_provider = str(decision.get("selectedProvider") or "")
    selected = candidates.get(selected_tool)
    if selected is None or not selected_provider:
        raise AlignmentProviderError("alignment provider decision requires a selected provider/tool")
    if selected_provider != str(selected.get("provider") or ""):
        raise AlignmentProviderError("selected provider must match the selected candidate provider")
    if selected.get("fit") is not True or str(selected.get("availability") or "") != ToolStatus.AVAILABLE.value:
        raise AlignmentProviderError("selected alignment provider was not policy-valid and available at planning time")
    if selected.get("supportsInputPath") is not True or str(selected.get("requiredCapability") or "") != _REQUIRED_CAPABILITY:
        raise AlignmentProviderError("selected alignment provider lacks required input_path/word_timestamps fit evidence")

    if str(decision.get("semanticOutcome") or "") != "succeeded":
        raise AlignmentProviderError("alignment provider decision semantic outcome must be succeeded")
    selected_model = str(decision.get("selectedModel") or "").strip()
    if not selected_model:
        raise AlignmentProviderError("alignment provider decision requires selected model evidence")
    execution_duration = decision.get("executionDurationSeconds")
    if not isinstance(execution_duration, (int, float)) or isinstance(execution_duration, bool) or execution_duration < 0:
        raise AlignmentProviderError("alignment provider decision requires non-negative execution timing")
    attempts = decision.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        raise AlignmentProviderError("alignment provider decision requires execution attempts")
    heavy_used = decision.get("heavyRecoveryUsed")
    if not isinstance(heavy_used, bool):
        raise AlignmentProviderError("alignment provider decision heavyRecoveryUsed must be boolean")
    policy_heavy_allowed = bool(policy.get("heavyTranscriptionRecoveryOnly"))
    if heavy_used and not policy_heavy_allowed:
        raise AlignmentProviderError("heavy recovery is forbidden by the current alignment policy")
    if heavy_used and str(decision.get("recoveryReason") or "") != "lightweight_providers_exhausted":
        raise AlignmentProviderError("heavy recovery requires persisted lightweight exhaustion reason")

    for raw in attempts:
        if not isinstance(raw, Mapping):
            raise AlignmentProviderError("alignment provider attempts must be objects")
        name = str(raw.get("tool") or "")
        candidate = candidates.get(name)
        if candidate is None:
            raise AlignmentProviderError(f"alignment attempt references unknown provider tool: {name}")
        if candidate.get("fit") is not True or str(candidate.get("availability") or "") != ToolStatus.AVAILABLE.value:
            raise AlignmentProviderError(
                f"alignment attempt executed provider {name!r} that was unavailable or not policy-valid"
            )
        duration = raw.get("durationSeconds")
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration < 0:
            raise AlignmentProviderError("alignment provider attempt requires non-negative durationSeconds")
        if not str(raw.get("model") or "").strip():
            raise AlignmentProviderError("alignment provider attempt requires model evidence")
        if not isinstance(raw.get("invoked"), bool):
            raise AlignmentProviderError("alignment provider attempt requires invoked boolean")
        profile = str(raw.get("profile") or "")
        if profile not in {"lightweight", "transcription_primary", "heavy_recovery"}:
            raise AlignmentProviderError(f"alignment attempt has unsupported profile: {profile}")
        if profile == "heavy_recovery" and not policy_heavy_allowed:
            raise AlignmentProviderError("heavy recovery attempt is forbidden by the current alignment policy")

    final = attempts[-1]
    if final.get("semanticSuccess") is not True:
        raise AlignmentProviderError("final alignment provider attempt must be semantically successful")
    if str(final.get("tool") or "") != selected_tool:
        raise AlignmentProviderError("selected alignment tool must match the successful final attempt")
    if str(final.get("model") or "") != selected_model:
        raise AlignmentProviderError("selected model must match the successful final attempt")
    expected_duration = round(
        sum(
            float(item.get("durationSeconds") or 0.0)
            for item in attempts
            if isinstance(item, Mapping) and item.get("invoked") is True
        ),
        3,
    )
    if abs(float(execution_duration) - expected_duration) > 1e-6:
        raise AlignmentProviderError(
            "alignment execution duration must equal the sum of invoked provider attempts"
        )
    final_profile = str(final.get("profile") or "")
    if heavy_used != (final_profile == "heavy_recovery"):
        raise AlignmentProviderError("heavyRecoveryUsed does not match the successful execution profile")

    fallback_needed = (
        selected_tool != str(candidates_raw[0].get("tool") or "")
        or any(item.get("semanticSuccess") is not True for item in attempts[:-1] if isinstance(item, Mapping))
    )
    if fallback_needed and not str(decision.get("fallbackReason") or "").strip():
        raise AlignmentProviderError("alignment provider fallback reason must be persisted")


__all__ = [
    "ALIGNMENT_PROVIDER_DECISION_VERSION",
    "AlignmentProviderError",
    "build_alignment_provider_plan",
    "execute_alignment_with_fallback",
    "validate_alignment_provider_decision",
]
