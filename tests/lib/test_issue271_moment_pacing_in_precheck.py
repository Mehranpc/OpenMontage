"""#271: Film Type reading floors are refused by the cheap edit precheck.

On the first-date run, three hand-set moment ends sat below their Film Type
reading floor. Compose refuses that only inside the browser pass, after spending
a convergence candidate. The same `audit_moments` now runs in the precheck, and
names the end `retime_moments` derives.
"""
from __future__ import annotations

from lib.persian_edit_contract import collect_persian_edit_diagnostics


def _words(text: str, start: float, step: float = 0.35) -> list[dict]:
    rows, t = [], start
    for word in text.split():
        rows.append({"word": word, "start": round(t, 3), "end": round(t + step - 0.05, 3)})
        t += step
    return rows


def _edit(end: float) -> dict:
    return {
        "persian": {
            "design": {"version": 2, "profile": "film-type"},
            "durationSeconds": 20.0,
            "moments": [
                {
                    "id": "m-hook", "kind": "hook", "startSeconds": 0.0, "endSeconds": 4.6,
                    "anchorText": "پیام بدی یا صبر کنی",
                    "segments": [{"role": "hero", "text": "پیام بدی یا صبر کنی؟"}],
                },
                {
                    "id": "m-immediate", "kind": "statement", "startSeconds": 8.0, "endSeconds": end,
                    "anchorText": "پیام فوری علاقه رو واضح‌تر نشون می‌داد",
                    "segments": [
                        {"role": "hero", "text": "پیام فوری"},
                        {"role": "tail", "text": "علاقهٔ واضح‌تر"},
                    ],
                },
            ],
            "audio": {
                "wordTimings": _words("پیام بدی یا صبر کنی", 0.0)
                + _words("پیام فوری علاقه رو واضح‌تر نشون می‌داد", 8.0),
            },
        }
    }


def _pacing(edit):
    return [d for d in collect_persian_edit_diagnostics(edit) if d.code == "moments.pacing"]


def test_a_moment_below_its_reading_floor_is_refused_before_the_browser():
    found = _pacing(_edit(end=10.76))
    assert any(d.message.startswith("m-immediate:") for d in found)


def test_the_refusal_names_the_derived_end():
    found = [d for d in _pacing(_edit(end=10.76)) if d.message.startswith("m-immediate:")]
    assert "retime_moments derives endSeconds=" in found[0].hint


def test_a_moment_timed_at_its_floor_passes():
    assert not [d for d in _pacing(_edit(end=12.0)) if d.message.startswith("m-immediate:")]


def test_non_film_type_edits_are_not_charged():
    edit = _edit(end=10.76)
    edit["persian"]["design"] = {"version": 2, "profile": "classic"}
    assert _pacing(edit) == []
