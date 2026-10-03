"""#387 increment 2: v3 stage locks and the forward-only state machine."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import persian_asset_workspace as workspace
from lib import persian_pipeline_profile as profile
from lib import persian_stage_locks as locks
from lib import persian_video_workflow as workflow
from lib.checkpoint import CheckpointValidationError, write_checkpoint
from lib.persian_video_workflow import PHASES, PersianVideoWorkflowError, load_workflow_state
from tests.contracts.test_phase0_contracts import sample_artifact
from tests.lib.test_issue387_topic_admission import V3, _run, _stage


@pytest.fixture
def v3(monkeypatch):
    monkeypatch.setenv(profile.OPT_IN_ENV, 'v3_staged')


def test_every_phase_maps_to_a_monotonic_stage():
    stages = [locks.PHASE_STAGE[phase] for phase in PHASES]
    assert stages == sorted(stages)
    assert set(locks.LOCKING_PHASES) == {'plan_scenes_moments', 'acquire_assets'}


def test_v3_plan_completion_locks_narration_and_timing(tmp_path, v3):
    project = _run(tmp_path, V3)
    lock = locks.read_stage_lock(project, 0)
    assert lock['name'] == 'narration_timing'
    assert set(lock['files']) == {'checkpoint_script.json', 'checkpoint_scene_plan.json'}
    assert lock['input_digests'] == {}
    assert len(lock['implementation_sha']) in {7, 40} or lock['implementation_sha'] == 'unknown'
    evidence = load_workflow_state('run', pipeline_dir=tmp_path)['evidence']['plan_scenes_moments']
    assert evidence['stageLock']['content_digest'] == lock['content_digest']
    assert [record['stage'] for record in locks.verify_stage_locks(project)] == [0]


def test_v2_writes_no_lock(tmp_path, monkeypatch):
    monkeypatch.delenv(profile.OPT_IN_ENV, raising=False)
    project = _run(tmp_path, None)
    assert locks.locked_stages(project) == []
    assert not (project / locks.LOCK_DIR).exists()


def test_rewriting_a_locked_checkpoint_is_refused(tmp_path, v3):
    _run(tmp_path, V3)
    with pytest.raises(CheckpointValidationError, match='stage 0 .*locked'):
        write_checkpoint(tmp_path, 'run', 'script', 'completed', {'script': sample_artifact('script')},
                         pipeline_type='persian-footage')


def test_out_of_band_mutation_of_a_locked_file_stops_the_next_phase(tmp_path, v3):
    project = _run(tmp_path, V3)
    path = project / 'checkpoint_scene_plan.json'
    record = json.loads(path.read_text())
    record['artifacts']['scene_plan']['subject'] = 'tampered'
    path.write_text(json.dumps(record))
    workflow.record_phase_attempt('run', 'acquire_assets', pipeline_dir=tmp_path)
    with pytest.raises(PersianVideoWorkflowError, match='locked stage 0 .*mutated'):
        workflow._apply_v3_stage_locks(load_workflow_state('run', pipeline_dir=tmp_path),
                                       'acquire_assets', now=None)


def test_no_automatic_backward_transition_exists_in_v3(tmp_path, v3):
    _run(tmp_path, V3)
    for target in ('plan_scenes_moments', 'align_script_timing', 'prepare_inputs'):
        with pytest.raises(PersianVideoWorkflowError, match='forward-only'):
            workflow.request_send_back('run', target, reason='collision', pipeline_dir=tmp_path,
                                       diagnostic_code='ASSET_SELECTION_HARD_REGION_COLLISION',
                                       affected_shot_ids=['shot-0'])


def test_user_directed_rewind_into_a_locked_stage_is_refused(tmp_path, v3):
    _run(tmp_path, V3)
    with pytest.raises(PersianVideoWorkflowError, match='stage 0 .*locked'):
        workflow.request_send_back('run', 'plan_scenes_moments', reason='human asked',
                                   pipeline_dir=tmp_path, user_directed_revision=True)
    assert locks.verify_stage_locks(tmp_path / 'run')


def test_reconcile_plan_cannot_amend_the_locked_plan(tmp_path, v3):
    _run(tmp_path, V3)
    with pytest.raises(PersianVideoWorkflowError, match='reconcile-plan refused'):
        workflow.reconcile_scene_plan('run', [{'visual_event_id': 'event-0'}], reason='x',
                                      pipeline_dir=tmp_path)


def _lock_footage(project: Path) -> dict:
    (project / 'checkpoint_assets.json').write_text('{"stage": "assets", "status": "completed"}')
    return locks.write_stage_lock(project, 1, ['checkpoint_assets.json'], implementation_sha='abc')


def test_footage_lock_binds_the_timing_lock_and_freezes_the_asset_workspace(tmp_path, v3):
    project = _run(tmp_path, V3)
    candidate = _stage(project, 'person-phone-0')
    lock = _lock_footage(project)
    assert lock['input_digests'] == {'0': locks.read_stage_lock(project, 0)['content_digest']}
    with pytest.raises(workspace.PersianAssetWorkspaceError, match='stage 1 .*footage.* locked'):
        _stage(project, 'person-phone-1', 1)
    with pytest.raises(workspace.PersianAssetWorkspaceError, match='locked'):
        workspace.reject_asset_candidate(project, candidate, category='editorial', reason='late change')
    with pytest.raises(CheckpointValidationError, match='stage 1 .*locked'):
        write_checkpoint(tmp_path, 'run', 'assets', 'in_progress', {}, pipeline_type='persian-footage')


def test_v3_send_back_to_acquire_assets_after_footage_lock_is_refused(tmp_path, v3):
    project = _run(tmp_path, V3)
    _lock_footage(project)
    with pytest.raises(PersianVideoWorkflowError, match='forward-only'):
        workflow.request_send_back('run', 'plan_scenes_moments', reason='text collision',
                                   pipeline_dir=tmp_path)


def test_lock_rules_are_strict(tmp_path):
    project = tmp_path / 'p'
    project.mkdir()
    (project / 'a.json').write_text('{}')
    with pytest.raises(locks.StageLockError, match='before stages 0..0'):
        locks.write_stage_lock(project, 1, ['a.json'], implementation_sha='x')
    first = locks.write_stage_lock(project, 0, ['a.json'], implementation_sha='x')
    assert locks.write_stage_lock(project, 0, ['a.json'], implementation_sha='y') == first
    (project / 'a.json').write_text('{"changed": true}')
    with pytest.raises(locks.StageLockError, match='mutated'):
        locks.verify_stage_locks(project)
    with pytest.raises(locks.StageLockError, match='mutated'):
        locks.write_stage_lock(project, 0, ['a.json'], implementation_sha='x')
    with pytest.raises(locks.StageLockError, match='inside the project'):
        locks._file_digests(project, ['../outside.json'])


def test_acquire_assets_completion_writes_the_footage_lock(tmp_path, v3):
    project = _run(tmp_path, V3)
    (project / 'checkpoint_assets.json').write_text('{"stage": "assets", "status": "completed"}')
    state = load_workflow_state('run', pipeline_dir=tmp_path)
    evidence = workflow._apply_v3_stage_locks(state, 'acquire_assets', now=None)
    assert evidence['stage'] == 1 and evidence['name'] == 'footage'
    assert evidence['input_digests'] == {'0': locks.read_stage_lock(project, 0)['content_digest']}
    assert workflow._apply_v3_stage_locks(state, 'review_subject_regions', now=None) is None
    assert [record['stage'] for record in locks.verify_stage_locks(project)] == [0, 1]
