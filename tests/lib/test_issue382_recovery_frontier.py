"""#382: public exhausted recovery exposes evidence, not speculative footage claims."""
from __future__ import annotations

import json
from datetime import timedelta

import pytest

from lib import persian_asset_workspace as workspace
from lib import persian_video_workflow as workflow
from tests.lib.test_issue224_plan_reconcile import _run_at_acquire
from tests.lib.test_issue331_acquisition_next_step import _spend_both_passes
from tests.lib.test_issue360_preparation_and_stop import _select
from tests.lib.test_issue360_truthful_readiness import BASE, _candidate, _project_bytes


def _exhaust(tmp_path):
    project = _run_at_acquire(tmp_path)
    _spend_both_passes(tmp_path)
    for event in ('event-1', 'event-2'):
        _select(tmp_path, event, _candidate(tmp_path, event, event))
    path = project / workflow.STATE_FILENAME
    state = json.loads(path.read_text())
    state['send_backs'] = state['budgets']['max_send_backs']
    path.write_text(json.dumps(state))
    return project


def _preparation(tmp_path):
    return workflow.workflow_status('run', pipeline_dir=tmp_path, now=BASE)['acquisition']['preparation']


def _row(report, candidate):
    return next(row for row in report['events']['event-0'] if row['candidateId'] == candidate)


@pytest.mark.parametrize('stopped', [False, True])
def test_public_frontier_classifies_evidence_and_preserves_state(tmp_path, stopped):
    project = _exhaust(tmp_path)
    good = _candidate(tmp_path, 'event-0', 'good')
    bad = _candidate(tmp_path, 'event-0', 'bad', shows_subject=False)
    rejected = _candidate(tmp_path, 'event-0', 'rejected')
    workspace.reject_asset_candidate(project, rejected, category='semantic', reason='wrong phone action')
    unreviewed = _candidate(tmp_path, 'event-0', 'unreviewed')
    record = workspace.load_asset_candidate(project, unreviewed)
    record.pop('review'); record.pop('reviewSha256'); record['disposition'] = 'staged'
    workspace._atomic_json(workspace._candidate_path(project, unreviewed), record)
    if stopped:
        with pytest.raises(workflow.PersianVideoWorkflowError, match='wall_budget_exceeded'):
            workflow.enforce_front_door_budget('run', operation='workflow:asset-search',
                                              pipeline_dir=tmp_path, now=BASE + timedelta(days=1))
    before = _project_bytes(project)
    preparation = _preparation(tmp_path)
    report = preparation['recoveryEvidence']
    assert report == _preparation(tmp_path)['recoveryEvidence']
    assert _project_bytes(project) == before
    assert list(report['events']) == ['event-0']
    assert report['complete'] is True
    assert report['readinessInputsSha256'] == preparation['readinessInputsSha256']
    assert _row(report, good)['status'] == 'admissible'
    assert _row(report, bad)['status'] == 'blocked'
    assert _row(report, bad)['codes']
    assert _row(report, rejected)['status'] == 'rejected'
    assert _row(report, rejected)['rejection'] == {'category': 'semantic', 'reason': 'wrong phone action'}
    assert _row(report, unreviewed)['status'] == 'unreviewed'
    assert 'frame_review' not in json.dumps(report)
    if stopped:
        assert preparation['decisionRequired']['kind'] == 'budget_stop'
        assert preparation['legalOperations'] == ['budget-revalidate', 'budget-decision']
    else:
        assert preparation['decisionRequired'] is None
        _select(tmp_path, 'event-0', good, rejected={bad: 'subject missing'})
        assert workflow.load_workflow_state('run', pipeline_dir=tmp_path)['send_backs'] == 2


@pytest.mark.parametrize('damage', ['missing', 'torn', 'identity'])
def test_unknown_evidence_does_not_prove_impossibility_or_authorize_reuse(tmp_path, damage):
    project = _exhaust(tmp_path)
    candidate = _candidate(tmp_path, 'event-0', 'unknown')
    path = workspace._candidate_path(project, candidate)
    if damage == 'missing':
        # A missing selected record must remain a named unknown, not vanish.
        from tests.lib.test_issue360_truthful_readiness import _legacy_select
        _legacy_select(project, 'event-0', candidate)
        path.unlink()
    elif damage == 'torn':
        path.write_text('{')
    else:
        record = workspace.load_asset_candidate(project, candidate)
        record['identity']['sourceWindow']['endSeconds'] = 3.9
        workspace._atomic_json(path, record)
    before = _project_bytes(project)
    preparation = _preparation(tmp_path)
    report = preparation['recoveryEvidence']
    assert report['complete'] is False
    assert preparation['decisionRequired']['kind'] == 'send_back_budget_spent'
    if damage == 'torn':
        assert candidate in report['unreadableRecordIds']
    else:
        assert _row(report, candidate)['status'] == 'unavailable'
    assert _project_bytes(project) == before


@pytest.mark.parametrize('change', ['review', 'rejection', 'plan', 'selection', 'implementation', 'policy'])
def test_frontier_digest_binds_relevant_inputs_but_is_not_mutation_authority(tmp_path, monkeypatch, change):
    project = _exhaust(tmp_path)
    candidate = _candidate(tmp_path, 'event-0', 'candidate')
    first = _preparation(tmp_path)['recoveryEvidence']
    if change in ('review', 'rejection'):
        record = workspace.load_asset_candidate(project, candidate)
        if change == 'review':
            record['review']['shows_subject'] = False
        else:
            record['disposition'] = 'rejected'
            record['rejection'] = {'category': 'editorial', 'reason': 'protected region collision'}
        workspace._atomic_json(workspace._candidate_path(project, candidate), record)
    elif change == 'plan':
        workflow.reconcile_scene_plan('run', [{'visual_event_id': 'event-0', 'set': {'negative_space': 'centre_band'}}],
                                      reason='bound plan amendment', pipeline_dir=tmp_path, now=BASE)
    elif change == 'selection':
        _select(tmp_path, 'event-1', _candidate(tmp_path, 'event-1', 'replacement'),
                replace_existing=True, rejected={workspace._read_selections(project)['event-1']['candidateId']: 'prefer replacement'})
    elif change == 'implementation':
        monkeypatch.setattr(workspace, '_implementation_sha', lambda: 'f' * 40)
    else:
        from lib import persian_assets
        monkeypatch.setattr(persian_assets, 'ASSET_ADMISSION_POLICY_VERSION', '382.test')
    latest = _preparation(tmp_path)['recoveryEvidence']
    assert latest['inputsSha256'] != first['inputsSha256']
    before = _project_bytes(project)
    with pytest.raises(workspace.AssetAdmissionRefused, match='STALE_PREPARATION'):
        workspace.require_current_preparation(project, latest['inputsSha256'])
    assert _project_bytes(project) == before


def test_rejected_and_unreviewed_alone_keep_the_decision(tmp_path):
    project = _exhaust(tmp_path)
    candidate = _candidate(tmp_path, 'event-0', 'rejected')
    workspace.reject_asset_candidate(project, candidate, category='editorial', reason='bad geometry')
    preparation = _preparation(tmp_path)
    assert preparation['recoveryEvidence']['events']['event-0'][0]['status'] == 'rejected'
    assert preparation['decisionRequired'] == {'kind': 'send_back_budget_spent', 'events': ['event-0']}


def test_distinct_windows_are_not_source_blacklisted_and_overlap_still_blocks(tmp_path):
    from copy import deepcopy
    from tests.lib.test_issue224_plan_reconcile import _event, _plan

    project = _exhaust(tmp_path)
    old = workspace._read_selections(project)['event-1']['candidateId']
    selected = _candidate(tmp_path, 'event-1', 'shared-source')
    _select(tmp_path, 'event-1', selected, replace_existing=True, rejected={old: 'prefer shared source'})
    seed = workspace.load_asset_candidate(project, selected)
    event = _event(_plan(tmp_path), 'event-0')
    beat = next(b for b in _plan(tmp_path)['beats'] if any(e['id'] == 'event-0' for e in b['visual_events']))
    candidates = []
    for start in (1.0, 4.5):
        candidate = workspace.stage_asset_candidate(
            project, discovery_id=seed['discoveryId'], visual_event_id='event-0', semantic_beat_id=beat['id'],
            source_in_seconds=start, duration_seconds=4.0, intended_crop={'mode': 'full_frame'},
            candidate_rank=1, query=event['queries'][0], narration_span=event['narration_span'],
        )['candidateId']
        review = deepcopy(seed['review'])
        if event.get('carries_moment'):
            review['frame_review']['placement_space'] = event['negative_space']
        workspace.record_candidate_review(project, candidate, review)
        candidates.append(candidate)
    overlap, distinct = candidates
    report = _preparation(tmp_path)['recoveryEvidence']
    assert 'SOURCE_WINDOW_OVERLAP' in _row(report, overlap)['codes']
    assert _row(report, overlap)['status'] == 'blocked'
    assert _row(report, distinct)['status'] == 'admissible'
    _select(tmp_path, 'event-0', distinct, rejected={overlap: 'source-window overlap'})


def test_pending_pass_has_no_exhaustion_frontier(tmp_path):
    project = _run_at_acquire(tmp_path)
    workflow.bounded_asset_search_request('run', {}, retry_pass=0, pipeline_dir=tmp_path, now=BASE)
    path = project / workflow.STATE_FILENAME
    state = json.loads(path.read_text())
    state['send_backs'] = state['budgets']['max_send_backs']
    path.write_text(json.dumps(state))
    before = _project_bytes(project)
    preparation = _preparation(tmp_path)
    assert preparation['recoveryEvidence'] is None
    assert preparation['decisionRequired'] is None
    assert preparation['legalOperations'] == ['asset-result (reconcile pending pass 0)']
    assert _project_bytes(project) == before


@pytest.mark.parametrize('kind', ['unreviewed', 'malformed_rejection'])
def test_incomplete_or_unreviewed_evidence_never_grants_recovery(tmp_path, monkeypatch, kind):
    from lib import persian_region_commands as regions

    project = _exhaust(tmp_path)
    candidate = _candidate(tmp_path, 'event-0', 'not-approved')
    record = workspace.load_asset_candidate(project, candidate)
    if kind == 'unreviewed':
        record['review'] = None
        record['reviewSha256'] = None
        record['disposition'] = 'staged'
    else:
        record['disposition'] = 'rejected'
        record['rejection'] = {}
    workspace._atomic_json(workspace._candidate_path(project, candidate), record)
    def forbidden(*args, **kwargs):
        pytest.fail('read-only frontier attempted provider/browser work')
    monkeypatch.setattr(workflow, 'bounded_asset_search_request', forbidden)
    monkeypatch.setattr(regions, 'carrier_moment_placement', forbidden)
    before = _project_bytes(project)
    preparation = _preparation(tmp_path)
    report = preparation['recoveryEvidence']
    assert _row(report, candidate)['status'] == ('unreviewed' if kind == 'unreviewed' else 'unavailable')
    assert report['complete'] is (kind == 'unreviewed')
    assert preparation['decisionRequired'] == {'kind': 'send_back_budget_spent', 'events': ['event-0']}
    assert _project_bytes(project) == before
