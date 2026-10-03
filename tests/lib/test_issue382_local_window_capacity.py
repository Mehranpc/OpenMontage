"""#382 H1: unexamined time in known sources is visible evidence, never authority."""
from __future__ import annotations

import json

from lib import persian_asset_workspace as workspace
from lib import persian_video_workflow as workflow
from tests.lib.test_issue224_plan_reconcile import _run_at_acquire
from tests.lib.test_issue360_truthful_readiness import _candidate, _project_bytes
from tests.lib.test_issue382_recovery_frontier import _exhaust, _preparation


def _restage(project, candidate_id, start, *, event=None):
    record = workspace.load_asset_candidate(project, candidate_id)
    context = record['context']
    return workspace.stage_asset_candidate(
        project, discovery_id=record['discoveryId'],
        visual_event_id=event or context['visualEventId'], semantic_beat_id=context['semanticBeatId'],
        source_in_seconds=start, duration_seconds=4.0, intended_crop=record['identity']['intendedCrop'],
        candidate_rank=2, query=context['query'], narration_span=context['narrationSpan'],
    )['candidateId']


def _capacity(tmp_path, source_id):
    report = _preparation(tmp_path)['recoveryEvidence']
    return report, next(item for item in report['localWindowCapacity']['event-0']
                        if item['sourceId'] == source_id)


def test_opening_window_capacity_is_reported_read_only_without_changing_status(tmp_path):
    project = _exhaust(tmp_path)
    rejected = _candidate(tmp_path, 'event-0', 'opening')
    workspace.reject_asset_candidate(project, rejected, category='semantic', reason='wrong action')
    record = workspace.load_asset_candidate(project, rejected)
    duration = float(record['source']['durationSeconds'])
    before = _project_bytes(project)
    report, item = _capacity(tmp_path, record['identity']['sourceId'])
    assert _project_bytes(project) == before
    assert report == _preparation(tmp_path)['recoveryEvidence']
    assert item['openingWindowOnly'] is True
    assert item['knownWindows'] == [[0.0, 4.0]]
    assert item['unexploredSpans'] == [[4.0, round(duration, 6)]]
    assert item['unexploredSeconds'] == round(duration - 4.0, 6)
    assert item['distinctWindowsFitting'] == int((duration - 4.0) // 4.0)
    # Capacity is not admissible evidence: the event still needs a decision.
    preparation = _preparation(tmp_path)
    assert preparation['decisionRequired'] == {'kind': 'send_back_budget_spent', 'events': ['event-0']}
    rows = report['events']['event-0']
    assert [row['status'] for row in rows] == ['rejected']


def test_known_windows_from_any_event_count_as_examined(tmp_path):
    project = _exhaust(tmp_path)
    first = _candidate(tmp_path, 'event-0', 'shared')
    workspace.reject_asset_candidate(project, first, category='semantic', reason='subject absent')
    _restage(project, first, 6.0)                 # unreviewed later window, same event
    _restage(project, first, 12.0 - 4.0, event='event-1')  # window bound to another event
    record = workspace.load_asset_candidate(project, first)
    duration = round(float(record['source']['durationSeconds']), 6)
    report, item = _capacity(tmp_path, 'shared')
    assert item['openingWindowOnly'] is False
    assert item['knownWindows'] == [[0.0, 4.0], [6.0, 10.0], [8.0, 12.0]]
    expected = [[4.0, 6.0]] + ([[12.0, duration]] if duration > 12.0 else [])
    assert item['unexploredSpans'] == expected
    statuses = sorted(row['status'] for row in report['events']['event-0'])
    assert statuses == ['rejected', 'unreviewed']


def test_unknown_duration_never_invents_capacity_and_changes_the_digest(tmp_path):
    project = _exhaust(tmp_path)
    rejected = _candidate(tmp_path, 'event-0', 'unknown-duration')
    workspace.reject_asset_candidate(project, rejected, category='technical', reason='soft focus')
    first = _preparation(tmp_path)['recoveryEvidence']
    record = workspace.load_asset_candidate(project, rejected)
    record['source']['durationSeconds'] = None
    workspace._atomic_json(workspace._candidate_path(project, rejected), record)
    report, item = _capacity(tmp_path, 'unknown-duration')
    assert item['sourceDurationSeconds'] is None
    assert item['unexploredSpans'] is None and item['distinctWindowsFitting'] is None
    assert report['inputsSha256'] != first['inputsSha256']


def test_staging_reports_whether_the_source_window_was_declared(tmp_path):
    project = _run_at_acquire(tmp_path)
    seed = _candidate(tmp_path, 'event-0', 'declared')
    record = workspace.load_asset_candidate(project, seed)
    payload = {
        'discovery_id': record['discoveryId'], 'visual_event_id': 'event-0',
        'semantic_beat_id': record['context']['semanticBeatId'], 'duration_seconds': 4.0,
        'intended_crop': record['identity']['intendedCrop'], 'candidate_rank': 2,
        'query': record['context']['query'], 'narration_span': record['context']['narrationSpan'],
    }
    implicit = project / 'stage-implicit.json'
    implicit.write_text(json.dumps({**payload, 'intended_crop': {'mode': 'cover'}}))
    result = workflow.stage_workflow_asset_candidate('run', implicit, pipeline_dir=tmp_path)
    assert result['sourceWindowDeclared'] is False
    assert '0.0s' in result['sourceWindowWarning']
    explicit = project / 'stage-explicit.json'
    explicit.write_text(json.dumps({**payload, 'source_in_seconds': 5.0}))
    result = workflow.stage_workflow_asset_candidate('run', explicit, pipeline_dir=tmp_path)
    assert result['sourceWindowDeclared'] is True and 'sourceWindowWarning' not in result
    staged = workspace.load_asset_candidate(project, result['candidateId'])
    assert staged['identity']['sourceWindow'] == {'startSeconds': 5.0, 'endSeconds': 9.0}
