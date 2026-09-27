"""#265: a Mac run starts only on a SHA whose CI rehearsal passed."""
from __future__ import annotations

from scripts.pre_mac import REHEARSAL_CHECK, verdict

SHA = "a" * 40


def _run(status="completed", conclusion="success", at="2026-09-27T22:00:00Z", name=REHEARSAL_CHECK):
    return {"name": name, "status": status, "conclusion": conclusion, "completed_at": at}


def test_passed_rehearsal_on_clean_head_is_clear() -> None:
    assert verdict(SHA, head=SHA, dirty=False, runs=[_run()])[0] is True


def test_refusals_name_the_reason() -> None:
    cases = [
        (dict(head=SHA, dirty=True, runs=[_run()]), "local changes"),
        (dict(head="b" * 40, dirty=False, runs=[_run()]), "not the SHA"),
        (dict(head=SHA, dirty=False, runs=[_run(name="OpenMontage CI (Ubuntu)")]), "no 'P4"),
        (dict(head=SHA, dirty=False, runs=[_run(status="in_progress", conclusion=None, at="")]), "still in_progress"),
        (dict(head=SHA, dirty=False, runs=[_run(conclusion="failure")]), "concluded 'failure'"),
    ]
    for kwargs, expected in cases:
        ok, message = verdict(SHA, **kwargs)
        assert ok is False and expected in message, (kwargs, message)


def test_the_latest_rerun_decides() -> None:
    runs = [_run(conclusion="failure", at="2026-09-27T21:00:00Z"), _run(at="2026-09-27T22:00:00Z")]
    assert verdict(SHA, head=SHA, dirty=False, runs=runs)[0] is True
