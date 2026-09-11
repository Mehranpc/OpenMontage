from scripts import persian_reels_local_e2e as harness


def test_local_e2e_contract_fixture_is_hermetic_and_never_production_certified(tmp_path):
    result = harness.validate_contract_fixture(tmp_path)

    assert result["production_certified"] is False
    assert result["scene_audit"]["problems"] == []
    assert result["scene_audit"]["uses_visual_events"] is True
    assert result["scene_audit"]["visual_events"] == 4
    assert result["projection_problems"] == []
    assert result["retention_audit"]["problems"] == []
    assert any(
        "outside the Persian production allowlist" in problem
        for problem in result["synthetic_provider_problems"]
    )
