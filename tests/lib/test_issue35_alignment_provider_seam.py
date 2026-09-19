from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from lib.persian_alignment_provider import (
    AlignmentProviderError,
    build_alignment_provider_plan,
    execute_alignment_with_fallback,
)
from tools.base_tool import ToolResult, ToolStatus


@dataclass
class FakeTool:
    name: str
    provider: str
    status: ToolStatus
    capabilities: list[str]
    input_schema: dict[str, Any]
    lightweight_success: bool = True
    heavy_success: bool = True
    execute_calls: list[dict[str, Any]] | None = None

    def get_status(self) -> ToolStatus:
        return self.status

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        if self.execute_calls is None:
            self.execute_calls = []
        self.execute_calls.append(dict(inputs))
        heavy = inputs.get("model_size") == "large-v3" or "large-v3" in str(inputs.get("model") or "")
        success = self.heavy_success if heavy else self.lightweight_success
        if not success:
            return ToolResult(success=False, error=f"{self.name} semantic failure")
        return ToolResult(
            success=True,
            data={
                "provider": self.provider,
                "word_timestamps": [
                    {"word": "سلام", "start": 0.0, "end": 0.4},
                    {"word": "دنیا", "start": 0.4, "end": 0.9},
                ],
            },
        )


class FakeRegistry:
    def __init__(self, tools: list[FakeTool]):
        self.tools = {tool.name: tool for tool in tools}

    def ensure_discovered(self) -> None:
        pass

    def get(self, name: str):
        return self.tools.get(name)


def _tool(name: str, provider: str, status: ToolStatus = ToolStatus.AVAILABLE, **kwargs) -> FakeTool:
    return FakeTool(
        name=name,
        provider=provider,
        status=status,
        capabilities=kwargs.pop("capabilities", ["transcribe", "word_timestamps"]),
        input_schema=kwargs.pop(
            "input_schema",
            {"type": "object", "required": ["input_path"], "properties": {"input_path": {"type": "string"}}},
        ),
        **kwargs,
    )


def _policy() -> dict[str, Any]:
    return {
        "mode": "timing_oriented",
        "scriptAuthority": "approved_script",
        "primaryModelClass": "smallest_adequate_word_timing",
        "heavyTranscriptionRecoveryOnly": True,
    }


def test_known_unavailable_primary_is_skipped_before_execution_and_mlx_is_selected() -> None:
    primary = _tool("transcriber", "whisperx", ToolStatus.UNAVAILABLE)
    mlx = _tool("mlx_whisper_transcriber", "mlx_whisper")
    registry = FakeRegistry([primary, mlx])

    plan = build_alignment_provider_plan(_policy(), registry=registry)

    assert plan["selectedTool"] == "mlx_whisper_transcriber"
    assert plan["selectedProvider"] == "mlx_whisper"
    assert plan["fallbackReason"] == "primary_unavailable:transcriber"
    assert plan["candidates"][0]["availability"] == "unavailable"
    assert plan["candidates"][1]["availability"] == "available"

    result = execute_alignment_with_fallback(
        plan,
        input_path="narration.wav",
        output_dir="artifacts/transcription",
        language="fa",
        initial_prompt="متن تأییدشده",
        registry=registry,
    )
    assert primary.execute_calls in (None, [])
    assert len(mlx.execute_calls or []) == 1
    assert result["provider_decision"]["selectedTool"] == "mlx_whisper_transcriber"
    assert result["provider_decision"]["heavyRecoveryUsed"] is False


def test_plan_refuses_when_no_policy_valid_provider_is_available() -> None:
    registry = FakeRegistry([
        _tool("transcriber", "whisperx", ToolStatus.UNAVAILABLE),
        _tool("mlx_whisper_transcriber", "mlx_whisper", ToolStatus.UNAVAILABLE),
    ])
    with pytest.raises(AlignmentProviderError, match="no available alignment provider"):
        build_alignment_provider_plan(_policy(), registry=registry)


def test_capability_and_input_shape_are_part_of_fit_evidence() -> None:
    bad_capability = _tool("transcriber", "whisperx", capabilities=["transcribe"])
    bad_input = _tool(
        "mlx_whisper_transcriber",
        "mlx_whisper",
        input_schema={"type": "object", "required": ["audio_url"], "properties": {"audio_url": {"type": "string"}}},
    )
    registry = FakeRegistry([bad_capability, bad_input])
    with pytest.raises(AlignmentProviderError) as exc:
        build_alignment_provider_plan(_policy(), registry=registry)
    text = str(exc.value)
    assert "word_timestamps" in text
    assert "input_path" in text


def test_semantic_failure_falls_to_next_available_provider_before_heavy_recovery() -> None:
    primary = _tool("transcriber", "whisperx", lightweight_success=False, heavy_success=True)
    mlx = _tool("mlx_whisper_transcriber", "mlx_whisper", lightweight_success=True)
    registry = FakeRegistry([primary, mlx])
    plan = build_alignment_provider_plan(_policy(), registry=registry)

    result = execute_alignment_with_fallback(
        plan,
        input_path="narration.wav",
        output_dir="artifacts/transcription",
        language="fa",
        initial_prompt="متن",
        registry=registry,
    )

    decision = result["provider_decision"]
    assert decision["selectedTool"] == "mlx_whisper_transcriber"
    assert decision["fallbackReason"].startswith("semantic_failure:transcriber")
    assert decision["heavyRecoveryUsed"] is False
    assert [item["profile"] for item in decision["attempts"]] == ["lightweight", "lightweight"]
    assert len(primary.execute_calls or []) == 1
    assert len(mlx.execute_calls or []) == 1


def test_heavy_recovery_starts_only_after_all_lightweight_providers_fail() -> None:
    primary = _tool("transcriber", "whisperx", lightweight_success=False, heavy_success=True)
    mlx = _tool("mlx_whisper_transcriber", "mlx_whisper", lightweight_success=False, heavy_success=False)
    registry = FakeRegistry([primary, mlx])
    plan = build_alignment_provider_plan(_policy(), registry=registry)

    result = execute_alignment_with_fallback(
        plan,
        input_path="narration.wav",
        output_dir="artifacts/transcription",
        language="fa",
        registry=registry,
    )

    decision = result["provider_decision"]
    assert decision["selectedTool"] == "transcriber"
    assert decision["heavyRecoveryUsed"] is True
    assert [item["profile"] for item in decision["attempts"]] == [
        "lightweight", "lightweight", "heavy_recovery"
    ]
    assert primary.execute_calls[0]["model_size"] == "base"
    assert primary.execute_calls[1]["model_size"] == "large-v3"


def test_word_timing_validator_can_force_provider_fallback() -> None:
    primary = _tool("transcriber", "whisperx")
    mlx = _tool("mlx_whisper_transcriber", "mlx_whisper")
    registry = FakeRegistry([primary, mlx])
    plan = build_alignment_provider_plan(_policy(), registry=registry)
    calls = 0

    def validate(words: list[dict[str, Any]]) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("timing projection rejected")
        assert words

    result = execute_alignment_with_fallback(
        plan,
        input_path="narration.wav",
        output_dir="artifacts/transcription",
        language="fa",
        registry=registry,
        validate_word_timings=validate,
    )
    decision = result["provider_decision"]
    assert decision["selectedTool"] == "mlx_whisper_transcriber"
    assert "timing_validation_failure:transcriber" in decision["fallbackReason"]
    assert decision["heavyRecoveryUsed"] is False
