from lib.persian_retention import audit_persian_retention


def _shot(id, start, end, **extra):
    return {"id": id, "startSeconds": start, "endSeconds": end, **extra}


def _base(**extra):
    data = {
        "durationSeconds": 12.0,
        "shots": [_shot("s1", 0, 2), _shot("s2", 2, 6), _shot("s3", 6, 12)],
        "moments": [{"id": "m1", "startSeconds": 0.5, "endSeconds": 1.5}],
        "typographicBeats": [],
    }
    data.update(extra)
    return data


def test_conforming_timeline_reports_retention_metrics():
    audit = audit_persian_retention(_base())
    assert audit["problems"] == []
    assert audit["first3Seconds"]["eventCount"] >= 2
    assert audit["averageVisualEventSeconds"] == 4.0
    assert audit["longestVisualEvent"] == {"id": "s3", "seconds": 6.0}
    assert audit["weakEmptyIntervals"] == []
    assert audit["cutGrammar"]["nonCutCount"] == 0


def test_first_three_seconds_need_a_second_event_or_pattern_interrupt():
    audit = audit_persian_retention(_base(shots=[_shot("s1", 0, 12)], moments=[]))
    assert any("first 3 seconds" in p for p in audit["problems"])


def test_opening_moment_counts_as_pattern_interrupt():
    audit = audit_persian_retention(_base(shots=[_shot("s1", 0, 12)]))
    assert not any("first 3 seconds" in p for p in audit["problems"])


def test_long_shot_is_reported_as_retention_risk_not_invented_as_absolute_failure():
    audit = audit_persian_retention(_base(shots=[_shot("s1", 0, 12)]))
    assert any("12.00s" in a and "retention risk" in a for a in audit["advisories"])


def test_visual_gap_is_blocking():
    audit = audit_persian_retention(_base(shots=[_shot("s1", 0, 2), _shot("s2", 3, 12)]))
    assert audit["weakEmptyIntervals"] == [{"startSeconds": 2.0, "endSeconds": 3.0}]
    assert any("uncovered" in p for p in audit["problems"])


def test_typographic_plate_can_cover_a_footage_gap():
    audit = audit_persian_retention(_base(
        shots=[_shot("s1", 0, 2), _shot("s2", 4, 12)],
        typographicBeats=[{"id": "t1", "startSeconds": 2, "endSeconds": 4}],
    ))
    assert audit["weakEmptyIntervals"] == []


def test_long_text_only_ending_is_advisory():
    audit = audit_persian_retention(_base(
        shots=[_shot("s1", 0, 9)],
        typographicBeats=[{"id": "end", "startSeconds": 9, "endSeconds": 12}],
    ))
    assert audit["endingTextOnlySeconds"] == 3.0
    assert any("text-only" in a for a in audit["advisories"])


def test_non_cut_transition_is_refused_until_renderer_can_execute_it():
    shots = [_shot("s1", 0, 2), _shot("s2", 2, 12, transitionIn="dissolve")]
    audit = audit_persian_retention(_base(shots=shots))
    assert any("not executable" in p for p in audit["problems"])
