"""Acceptance at the production front door: media cannot bypass execution truth."""
from pathlib import Path

import pytest

from lib import persian_video_workflow as workflow
from tests.lib.test_persian_video_workflow import BASE, _bootstrap, _advance_to


@pytest.mark.parametrize('phase', [
    'render_opening_candidate', 'render_final_candidate', 'master_final_candidate',
])
def test_direct_completion_cannot_certify_unmeasured_media(tmp_path: Path, phase: str):
    _bootstrap(tmp_path)
    # Arrange the phase boundary; execution/commit below is the public seam under test.
    state = _advance_to(tmp_path, 'render_opening_candidate')
    state['next_phase'] = phase
    workflow._write_state(tmp_path / 'run', state)
    workflow.record_phase_attempt('run', phase, pipeline_dir=tmp_path, now=BASE)
    output = tmp_path / 'run' / 'renders' / 'candidate.mp4'
    output.write_bytes(b'unmeasured output')
    with pytest.raises(workflow.PersianVideoWorkflowError, match='run kernel'):
        workflow.complete_phase('run', phase, evidence={'output_path': str(output)},
                                pipeline_dir=tmp_path, now=BASE)
    assert workflow.load_workflow_state('run', pipeline_dir=tmp_path)['next_phase'] == phase


def test_durable_render_commit_binds_measured_output_bytes(tmp_path: Path):
    import json
    import sys
    import time
    from lib import persian_run_kernel as kernel

    _bootstrap(tmp_path)
    _advance_to(tmp_path, 'render_opening_candidate')
    output = tmp_path / 'run' / 'renders' / 'opening-candidate.mp4'
    child = (
        "import hashlib,json,os; from pathlib import Path; "
        f"p=Path({str(output)!r}); p.write_bytes(b'fresh measured video'); "
        "r={'success':True,'data':{'output_path':str(p),"
        "'output_sha256':hashlib.sha256(p.read_bytes()).hexdigest()}}; "
        "Path(os.environ['OPENMONTAGE_DURABLE_RESULT_PATH']).write_text(json.dumps(r))"
    )
    kernel.start_phase_job('run', job_id='measured-opening', phase='render_opening_candidate',
                           argv=[sys.executable, '-c', child], idempotence_key='opening-v1',
                           telemetry_category='browser_render_execution', pipeline_dir=tmp_path)
    for _ in range(100):
        result = kernel.reconcile_phase_job('run', 'measured-opening', pipeline_dir=tmp_path)
        if result['status'] in {'succeeded', 'failed', 'interrupted'}:
            break
        time.sleep(0.05)
    assert result['executionOutcome'] == 'succeeded'
    digest = result['executionEnvelope']['semanticResult']['data']['output_sha256']
    evidence = {'output_path': str(output), 'opening_candidate_sha256': digest}
    committed = kernel.commit_phase_job('run', 'measured-opening', evidence=evidence,
                                        pipeline_dir=tmp_path)
    assert committed['next_phase'] == 'opening_review'
    envelope = kernel.load_execution_envelope('run', 'measured-opening', pipeline_dir=tmp_path)
    assert envelope['workflowTransitionOutcome'] == 'succeeded'
    assert any(span.get('span_id') == 'job:measured-opening' and span.get('finished_at')
               for span in committed['causal_telemetry']['spans'])
    assert kernel.commit_phase_job('run', 'measured-opening', evidence=evidence,
                                   pipeline_dir=tmp_path)['next_phase'] == 'opening_review'


def test_durable_render_refuses_different_output_evidence(tmp_path: Path):
    import sys
    import time
    from lib import persian_run_kernel as kernel

    _bootstrap(tmp_path)
    _advance_to(tmp_path, 'render_opening_candidate')
    output = tmp_path / 'run' / 'renders' / 'opening-candidate.mp4'
    child = (
        "import hashlib,json,os; from pathlib import Path; "
        f"p=Path({str(output)!r}); p.write_bytes(b'fresh measured video'); "
        "Path(os.environ['OPENMONTAGE_DURABLE_RESULT_PATH']).write_text(json.dumps("
        "{'success':True,'data':{'output_path':str(p),"
        "'output_sha256':hashlib.sha256(p.read_bytes()).hexdigest()}}))"
    )
    kernel.start_phase_job('run', job_id='digest-check', phase='render_opening_candidate',
                           argv=[sys.executable, '-c', child], idempotence_key='digest-v1',
                           pipeline_dir=tmp_path)
    for _ in range(100):
        result = kernel.reconcile_phase_job('run', 'digest-check', pipeline_dir=tmp_path)
        if result['status'] in {'succeeded', 'failed', 'interrupted'}:
            break
        time.sleep(0.05)
    with pytest.raises(workflow.PersianVideoWorkflowError, match='sha256'):
        kernel.commit_phase_job('run', 'digest-check', evidence={
            'output_path': str(output), 'opening_candidate_sha256': '0' * 64},
            pipeline_dir=tmp_path)
    assert workflow.load_workflow_state('run', pipeline_dir=tmp_path)['next_phase'] == 'render_opening_candidate'
    assert kernel.load_execution_envelope('run', 'digest-check', pipeline_dir=tmp_path)['executionOutcome'] == 'succeeded'
