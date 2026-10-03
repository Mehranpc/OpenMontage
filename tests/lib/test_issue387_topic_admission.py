"""#387 increment 1: v3 stage-1 footage admission is topic-level, not geometry-coupled."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import persian_asset_workspace as workspace
from lib import persian_pipeline_profile as profile
from lib import persian_video_workflow as workflow
from lib.persian_video_workflow import complete_phase, record_phase_attempt, workflow_status
from tests.contracts.test_phase0_contracts import sample_artifact
from tests.lib.test_issue195_scene_plan_duration_gate import (
    BASE, _advance_to_plan_scenes, _bootstrap, _write_checkpoint,
)
from tests.lib.test_issue213_plan_time_moment_feasibility import _beats
from tests.lib.test_issue35_asset_candidate_workspace import _discovered

V3 = {'pipeline_profile': 'v3_staged'}


def _run(tmp_path: Path, metadata: dict | None) -> Path:
    _bootstrap(tmp_path)
    _advance_to_plan_scenes(tmp_path)
    for stage, artifact in (('idea', 'brief'), ('script', 'script')):
        _write_checkpoint(tmp_path, stage, artifact, sample_artifact(artifact))
    plan = {'version': '2.0', 'format': 'vertical', 'subject': 'phone', 'beats': _beats(*[(5.0, None)] * 12)}
    if metadata is not None:
        plan['metadata'] = metadata
    _write_checkpoint(tmp_path, 'scene_plan', 'scene_plan', plan)
    record_phase_attempt('run', 'plan_scenes_moments', pipeline_dir=tmp_path, now=BASE)
    complete_phase('run', 'plan_scenes_moments', evidence={}, pipeline_dir=tmp_path, now=BASE)
    return tmp_path / 'run'


def _stage(project: Path, source_id: str, index: int = 0) -> str:
    discovery = workspace.record_discovery_pass(
        project, workspace.asset_workspace_status(project)['discoveryPassCount'],
        [_discovered(project, source_id=source_id, name=f'{source_id}.mp4', slot_id=f'event-{index}')],
    )['candidateIds'][0]
    return workspace.stage_asset_candidate(
        project, discovery_id=discovery, visual_event_id=f'event-{index}', semantic_beat_id=f'beat-{index}',
        source_in_seconds=0.0, duration_seconds=5.0, intended_crop={'mode': 'full_frame'},
        candidate_rank=1, query='phone on plain table wide shot', narration_span='span',
    )['candidateId']


def _topic(**overrides) -> dict:
    return {'topic_match': 'on_topic', 'inappropriate': False, 'placeholder_screen': False,
            'technical_usable': True, 'observed': 'A person holds a phone in every frame.', **overrides}


def _v3_review(**topic) -> dict:
    # Deliberately what v2 refuses: no placement_space for a moment carrier, affect
    # mismatch, high staged-stock risk, unsafe crop. v3 stage 1 does not judge these.
    return {
        'frame_review': {'start': True, 'middle': True, 'end': True, 'observed': 'person with phone'},
        'relevance_reason': 'The scene is about a phone; a person with a phone is on topic.',
        'selection_reason': 'Technically usable and on topic.',
        'affect_match': False, 'staged_stock_risk': 'high',
        'geometry_review': {'crop_safe': False, 'observed': 'subject fills the frame'},
        'topic_review': _topic(**topic),
    }


def _review(tmp_path: Path, candidate: str, review: dict) -> dict:
    path = tmp_path / 'run' / f'review-{candidate}.json'
    path.write_text(json.dumps(review))
    return workflow.review_workflow_asset_candidate('run', candidate, path, pipeline_dir=tmp_path)


def _select(tmp_path: Path, candidate: str, event: str = 'event-0'):
    return workflow.select_workflow_asset_candidate(
        'run', event, candidate, rejected_alternatives={}, pipeline_dir=tmp_path)


def test_profile_is_v2_by_default_and_v3_is_opt_in(monkeypatch):
    monkeypatch.delenv(profile.OPT_IN_ENV, raising=False)
    assert profile.plan_profile({}) == 'v2'
    assert profile.plan_profile({'metadata': {'pipeline_profile': 'v2'}}) == 'v2'
    with pytest.raises(profile.PipelineProfileError, match='not enabled'):
        profile.plan_profile({'metadata': V3})
    with pytest.raises(profile.PipelineProfileError, match='must be one of'):
        profile.plan_profile({'metadata': {'pipeline_profile': 'lenient'}})
    monkeypatch.setenv(profile.OPT_IN_ENV, 'v3_staged')
    assert profile.plan_profile({'metadata': V3}) == 'v3_staged'


def test_on_topic_footage_is_admitted_without_geometry_affect_or_staging_gates(tmp_path, monkeypatch):
    monkeypatch.setenv(profile.OPT_IN_ENV, 'v3_staged')
    project = _run(tmp_path, V3)
    candidate = _stage(project, 'person-phone')
    result = _review(tmp_path, candidate, _v3_review())
    assert result['carrierPremeasure'] == {'status': 'not_applicable', 'profile': 'v3_staged'}
    _select(tmp_path, candidate)
    for index in range(1, 12):
        other = _stage(project, f'person-phone-{index}', index)
        _review(tmp_path, other, _v3_review())
        _select(tmp_path, other, f'event-{index}')
    readiness = workflow_status('run', pipeline_dir=tmp_path, now=BASE)['acquisition']['readiness']
    assert readiness['diagnostics'] == {} or all(not rows for rows in readiness['diagnostics'].values())
    assert readiness['disposition'].startswith('ready_for_manifest')
    manifest = workflow.build_workflow_asset_manifest('run', pipeline_dir=tmp_path)
    [row] = [entry for entry in json.loads(Path(manifest['manifestPath']).read_text())['assets']
             if entry.get('visual_event_id') == 'event-0']
    assert row['topic_review']['topic_match'] == 'on_topic'


@pytest.mark.parametrize('topic, code', [
    ({'topic_match': 'off_topic'}, 'TOPIC_OFF'),
    ({'inappropriate': True}, 'CONTENT_INAPPROPRIATE'),
    ({'placeholder_screen': True}, 'PLACEHOLDER_SCREEN'),
    ({'technical_usable': False}, 'TECHNICAL_UNUSABLE'),
])
def test_only_off_topic_inappropriate_placeholder_or_unusable_footage_is_refused(
    tmp_path, monkeypatch, topic, code,
):
    monkeypatch.setenv(profile.OPT_IN_ENV, 'v3_staged')
    project = _run(tmp_path, V3)
    candidate = _stage(project, f'clip-{code.lower()}')
    _review(tmp_path, candidate, _v3_review(**topic))
    with pytest.raises(workspace.AssetAdmissionRefused) as refused:
        _select(tmp_path, candidate)
    assert {item['code'] for item in refused.value.diagnostics} == {code}
    assert workspace._read_selections(project) == {}


def test_v3_review_requires_topic_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv(profile.OPT_IN_ENV, 'v3_staged')
    project = _run(tmp_path, V3)
    candidate = _stage(project, 'no-topic')
    review = _v3_review()
    review.pop('topic_review')
    with pytest.raises(workspace.PersianAssetWorkspaceError, match='topic_review'):
        _review(tmp_path, candidate, review)
    with pytest.raises(workspace.PersianAssetWorkspaceError, match='unknown fields'):
        _review(tmp_path, candidate, {**_v3_review(), 'topic_review': {**_topic(), 'verdict': 'ok'}})
    assert workspace.load_asset_candidate(project, candidate)['reviewSha256'] is None


def test_v3_plan_without_opt_in_never_relaxes_admission(tmp_path, monkeypatch):
    monkeypatch.setenv(profile.OPT_IN_ENV, 'v3_staged')
    project = _run(tmp_path, V3)
    candidate = _stage(project, 'opt-in-gone')
    monkeypatch.delenv(profile.OPT_IN_ENV)
    with pytest.raises((workflow.PersianVideoWorkflowError, workspace.PersianAssetWorkspaceError),
                       match='not enabled'):
        _review(tmp_path, candidate, _v3_review())


def test_v2_plan_keeps_every_geometry_coupled_gate(tmp_path, monkeypatch):
    monkeypatch.setenv(profile.OPT_IN_ENV, 'v3_staged')  # opt-in alone changes nothing
    project = _run(tmp_path, None)
    candidate = _stage(project, 'v2-clip')
    review = _v3_review()
    review.update({'shows_subject': True, 'human_presence': False})
    workspace.record_candidate_review(project, candidate, review)
    with pytest.raises(workspace.AssetAdmissionRefused) as refused:
        _select(tmp_path, candidate)
    codes = {item['code'] for item in refused.value.diagnostics}
    assert {'PLACEMENT_SPACE_MISSING', 'AFFECT_MISMATCH', 'STAGED_RISK_HIGH', 'CROP_UNSAFE'} <= codes
