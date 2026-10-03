"""#382 increment B: offline joint-coverage harness is diagnostic, never selection.

Synthetic rows here verify harness mechanics only; they are not decision evidence.
"""
from __future__ import annotations

import json

import pytest

from lib import persian_recovery_experiment as experiment
from scripts import recovery_joint_coverage as cli
from tests.lib.test_issue360_truthful_readiness import _candidate, _project_bytes
from tests.lib.test_issue382_recovery_frontier import _exhaust, _preparation


def _row(candidate_id, status='admissible', source='s1', start=0.0, end=4.0, **extra):
    identity = {'provider': 'pexels', 'sourceId': source,
                'sourceWindow': {'startSeconds': start, 'endSeconds': end},
                'intendedCrop': {'mode': 'private-crop-mode', 'x': 0.1}}
    return {'candidateId': candidate_id, 'status': status, 'codes': [],
            'reviewSha256': 'r' * 64, 'identity': identity, **extra}


def _report(events, complete=True):
    return {'version': '1.0', 'complete': complete, 'events': events,
            'inputsSha256': 'f' * 64, 'readinessInputsSha256': 'e' * 64}


def _ref(candidate_id):
    return experiment.sanitize_recovery_corpus(_report({'e': [_row(candidate_id)]}))['events']['e'][0]['ref']


def _certificate(events, **kwargs):
    return experiment.joint_coverage_certificate(experiment.sanitize_recovery_corpus(_report(events)), **kwargs)


def test_corpus_keeps_identity_equality_but_drops_private_detail():
    rejected = _row('asset-r', 'rejected', rejection={'category': 'semantic', 'reason': 'private note'})
    corpus = experiment.sanitize_recovery_corpus(_report({'ev-2': [rejected], 'ev-1': [_row('asset-a')]}))
    text = json.dumps(corpus)
    for secret in ('private note', 'pexels', 'asset-a', 'private-crop-mode', 'r' * 64):
        assert secret not in text
    assert list(corpus['events']) == ['ev-1', 'ev-2']
    assert corpus['events']['ev-2'][0]['rejectionCategory'] == 'semantic'
    assert corpus['events']['ev-1'][0]['source'] == corpus['events']['ev-2'][0]['source']
    assert corpus == experiment.sanitize_recovery_corpus(_report({'ev-1': [_row('asset-a')], 'ev-2': [rejected]}))
    tampered = {**corpus, 'complete': False}
    with pytest.raises(experiment.RecoveryExperimentError, match='digest'):
        experiment.joint_coverage_certificate(tampered)


def test_sequential_choice_can_lose_coverage_that_joint_certificate_reports():
    first, second = sorted(['asset-x', 'asset-y'], key=_ref)
    # ev-a's first-in-order option shares source s1 with ev-b's only option.
    certificate = _certificate({
        'ev-a': [_row(first, source='s1', start=0, end=5), _row(second, source='s2')],
        'ev-b': [_row('asset-z', source='s1', start=2, end=6)],
    })
    assert certificate['status'] == 'jointly_compatible'
    assert (certificate['independentCoverage'], certificate['sequentialCoverage'],
            certificate['maxJointCoverage'], certificate['jointGainOverSequential']) == (2, 1, 2, 1)
    assert certificate['decideTogether'] == [['ev-a', 'ev-b']]
    assert len(certificate['conflicts']) == 1
    assert certificate['authority'] == 'diagnostic_only'
    assert 'assignment' not in certificate and 'selection' not in json.dumps(certificate)


def test_true_conflict_is_reported_without_choosing_a_winner():
    certificate = _certificate({'ev-a': [_row('asset-a', start=0, end=5)],
                                'ev-b': [_row('asset-b', start=4, end=8)]})
    assert certificate['status'] == 'conflicted'
    assert certificate['maxJointCoverage'] == 1 and certificate['jointGainOverSequential'] == 0


def test_same_source_distinct_window_is_not_a_source_blacklist():
    certificate = _certificate({'ev-a': [_row('asset-a', start=0, end=4)],
                                'ev-b': [_row('asset-b', start=4, end=8)],
                                'ev-c': [_row('asset-c', 'rejected', start=0, end=8,
                                              rejection={'category': 'semantic', 'reason': 'x'})]})
    # Compatibility covers events with admissible evidence; ev-c stays visibly uncovered.
    assert certificate['status'] == 'jointly_compatible'
    assert certificate['conflicts'] == [] and certificate['maxJointCoverage'] == 2
    assert certificate['eventsWithoutKnownAdmissible'] == ['ev-c']


def test_negative_controls_never_turn_absence_into_success_or_impossibility():
    none = _certificate({'ev-a': [_row('asset-a', 'blocked'), _row('asset-u', 'unreviewed')]})
    assert none['status'] == 'no_known_admissible' and none['maxJointCoverage'] == 0
    corpus = experiment.sanitize_recovery_corpus(_report({'ev-a': [_row('asset-a')]}, complete=False))
    assert experiment.joint_coverage_certificate(corpus)['status'] == 'unknown'
    broken = _row('asset-b')
    broken['identity'].pop('sourceWindow')
    corpus = experiment.sanitize_recovery_corpus(_report({'ev-a': [broken]}))
    assert corpus['complete'] is False
    assert corpus['events']['ev-a'][0]['status'] == 'unavailable'
    assert experiment.joint_coverage_certificate(corpus)['status'] == 'unknown'


def test_bounded_search_reports_unknown_instead_of_guessing():
    events = {f'ev-{index}': [_row(f'asset-{index}-{option}', source=f's{option}', start=index, end=index + 30)
                              for option in range(3)] for index in range(8)}
    certificate = _certificate(events, max_branches=5)
    assert certificate['status'] == 'unknown' and certificate['searchExhausted'] is True
    assert certificate['maxJointCoverage'] is None and certificate['jointGainOverSequential'] is None
    with pytest.raises(experiment.RecoveryExperimentError):
        _certificate(events, max_branches=0)


def test_real_public_frontier_round_trips_read_only(tmp_path, capsys):
    project = _exhaust(tmp_path)
    good = _candidate(tmp_path, 'event-0', 'good')
    before = _project_bytes(project)
    preparation = _preparation(tmp_path)
    corpus = experiment.sanitize_recovery_corpus(preparation['recoveryEvidence'])
    assert corpus['sourceReportInputsSha256'] == preparation['recoveryEvidence']['inputsSha256']
    assert good not in json.dumps(corpus)
    certificate = experiment.joint_coverage_certificate(corpus)
    assert certificate['status'] == 'jointly_compatible' and certificate['maxJointCoverage'] == 1
    status_file = tmp_path / 'status.json'
    status_file.write_text(json.dumps({'acquisition': {'preparation': preparation}}))
    assert cli.main([str(status_file)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['certificate'] == certificate
    assert _project_bytes(project) == before
    missing = tmp_path / 'none.json'
    missing.write_text(json.dumps({'acquisition': {'preparation': {'recoveryEvidence': None}}}))
    assert cli.main([str(missing)]) == 2
