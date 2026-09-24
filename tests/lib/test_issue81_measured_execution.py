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


def test_only_one_media_execution_can_run_or_wait_for_commit(tmp_path: Path):
    import hashlib
    import json
    import os
    import sys
    import time
    from lib import persian_run_kernel as kernel

    _bootstrap(tmp_path)
    _advance_to(tmp_path, 'render_opening_candidate')
    output = tmp_path / 'run' / 'renders' / 'opening-locked.mp4'
    side_effect = tmp_path / 'render-charge-count.txt'
    child = (
        "import hashlib,json,os,time; from pathlib import Path; "
        f"c=Path({str(side_effect)!r}); n=int(c.read_text()) if c.exists() else 0; "
        "c.write_text(str(n+1)); time.sleep(0.35); "
        f"p=Path({str(output)!r}); p.parent.mkdir(parents=True, exist_ok=True); "
        "p.write_bytes(b'one render only'); "
        "Path(os.environ['OPENMONTAGE_DURABLE_RESULT_PATH']).write_text(json.dumps("
        "{'success':True,'data':{'output_path':str(p),"
        "'output_sha256':hashlib.sha256(p.read_bytes()).hexdigest()}}))"
    )
    kernel.start_phase_job(
        'run', job_id='render-owner', phase='render_opening_candidate',
        argv=[sys.executable, '-c', child], idempotence_key='render-owner-v1',
        telemetry_category='browser_render_execution', pipeline_dir=tmp_path,
    )

    with pytest.raises(kernel.PersianRunKernelError, match='media execution.*render-owner|render-owner.*media execution'):
        kernel.start_phase_job(
            'run', job_id='render-duplicate', phase='render_opening_candidate',
            argv=[sys.executable, '-c', child], idempotence_key='render-duplicate-v1',
            telemetry_category='browser_render_execution', pipeline_dir=tmp_path,
        )

    result = None
    for _ in range(100):
        result = kernel.reconcile_phase_job('run', 'render-owner', pipeline_dir=tmp_path)
        if result['executionOutcome'] == 'succeeded':
            break
        time.sleep(0.05)
    assert result and result['executionOutcome'] == 'succeeded'
    assert side_effect.read_text() == '1'

    # A restarted caller with the same logical identity must reconcile the owner,
    # even if it presents a fresh process-local job id.
    replay = kernel.start_phase_job(
        'run', job_id='render-restarted-client', phase='render_opening_candidate',
        argv=[sys.executable, '-c', child], idempotence_key='render-owner-v1',
        telemetry_category='browser_render_execution', pipeline_dir=tmp_path,
    )
    assert replay['jobId'] == 'render-owner'
    assert replay['executionOutcome'] == 'succeeded'
    assert side_effect.read_text() == '1'

    # A finished render is still authoritative until its measured bytes are committed;
    # starting a second render would duplicate expensive work after a caller crash.
    with pytest.raises(kernel.PersianRunKernelError, match='commit.*render-owner|render-owner.*commit'):
        kernel.start_phase_job(
            'run', job_id='render-after-exit', phase='render_opening_candidate',
            argv=[sys.executable, '-c', child], idempotence_key='render-after-exit-v1',
            telemetry_category='browser_render_execution', pipeline_dir=tmp_path,
        )

    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    committed = kernel.commit_phase_job(
        'run', 'render-owner',
        evidence={'output_path': str(output), 'opening_candidate_sha256': digest},
        pipeline_dir=tmp_path,
    )
    assert committed['next_phase'] == 'opening_review'


def test_failed_media_execution_releases_slot_after_reconcile(tmp_path: Path):
    import json
    import os
    import sys
    import time
    from lib import persian_run_kernel as kernel

    _bootstrap(tmp_path)
    _advance_to(tmp_path, 'render_opening_candidate')
    failed_child = (
        "import json,os; from pathlib import Path; "
        "Path(os.environ['OPENMONTAGE_DURABLE_RESULT_PATH']).write_text("
        "json.dumps({'success':False,'error':'renderer failed'}))"
    )
    kernel.start_phase_job(
        'run', job_id='render-failed', phase='render_opening_candidate',
        argv=[sys.executable, '-c', failed_child], idempotence_key='render-failed-v1',
        telemetry_category='browser_render_execution', pipeline_dir=tmp_path,
    )
    failed = None
    for _ in range(100):
        failed = kernel.reconcile_phase_job('run', 'render-failed', pipeline_dir=tmp_path)
        if failed['executionOutcome'] == 'failed':
            break
        time.sleep(0.05)
    assert failed and failed['executionOutcome'] == 'failed'

    replacement = kernel.start_phase_job(
        'run', job_id='render-retry', phase='render_opening_candidate',
        argv=[sys.executable, '-c', failed_child], idempotence_key='render-retry-v1',
        telemetry_category='browser_render_execution', pipeline_dir=tmp_path,
        launch=False,
    )
    assert replacement['jobId'] == 'render-retry'
    assert replacement['phaseAttempt'] == 2
