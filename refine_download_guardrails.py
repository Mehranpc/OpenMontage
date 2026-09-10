from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if text.count(old) != 1:
        raise RuntimeError(f"expected exactly one match in {path}, got {text.count(old)}")
    p.write_text(text.replace(old, new))


replace_once(
    "tools/video/direct_clip_search.py",
    '_DEFAULT_MAX_CANDIDATES_TOTAL = 24\n',
    '_DEFAULT_MAX_CANDIDATES_TOTAL = 24\n_FFPROBE_VALIDATION_TIMEOUT_SECONDS = 15.0\n',
)

replace_once(
    "tools/video/direct_clip_search.py",
    '''def _probe_media(path: Path, *, timeout_seconds: float) -> dict[str, float | int]:
    timeout = min(15.0, max(0.1, timeout_seconds))
    cmd = [
''',
    '''def _probe_media(path: Path, *, timeout_seconds: float) -> dict[str, float | int]:
    remaining = max(0.1, float(timeout_seconds))
    timeout = min(_FFPROBE_VALIDATION_TIMEOUT_SECONDS, remaining)
    cmd = [
''',
)

replace_once(
    "tools/video/direct_clip_search.py",
    '''    except subprocess.TimeoutExpired as exc:
        raise _DeadlineExceeded("ffprobe exceeded the remaining deadline") from exc
    except FileNotFoundError as exc:
''',
    '''    except subprocess.TimeoutExpired as exc:
        if remaining <= _FFPROBE_VALIDATION_TIMEOUT_SECONDS:
            raise _DeadlineExceeded("ffprobe exceeded the remaining deadline") from exc
        raise _MediaValidationError(
            "ffprobe exceeded the 15-second media-validation timeout"
        ) from exc
    except FileNotFoundError as exc:
''',
)

replace_once(
    "tests/tools/test_direct_clip_search_limits.py",
    '''        source_url=f"{{https://example.test/{source_id}}}",
        download_url=f"{{https://cdn.example.test/{source_id}}}.mp4",
''',
    '''        source_url=f"{{https://example.test/{source_id}}}",
        download_url=f"{{https://cdn.example.test/{source_id}}}.mp4",
''',
)

insert_before = '''def test_nasa_probe_prefers_bounded_rendition():
'''
new_tests = '''def test_invalid_reused_file_is_deleted(monkeypatch, tmp_path):
    source = _Source({"one": [_candidate("one")]})
    _install_source(monkeypatch, source)
    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()
    reused = clips_dir / "pexels_one.mp4"
    reused.write_bytes(b"x" * 2048)
    monkeypatch.setattr(
        module,
        "_probe_media",
        lambda *_a, **_k: {"width": 1920, "height": 1080, "duration": 8.0},
    )

    result = DirectClipSearch().execute(_inputs(tmp_path, ["one"]))

    assert result.success is True
    assert result.data["clips_reused"] == 0
    assert result.data["errors"][0]["phase"] == "validation"
    assert not reused.exists()


def test_ffprobe_local_timeout_rejects_candidate_without_claiming_global_timeout(
    monkeypatch,
):
    def raise_timeout(*_args, **kwargs):
        raise module.subprocess.TimeoutExpired("ffprobe", kwargs["timeout"])

    monkeypatch.setattr(module.subprocess, "run", raise_timeout)
    with pytest.raises(module._MediaValidationError, match="media-validation timeout"):
        module._probe_media(Path("candidate.mp4"), timeout_seconds=30)


def test_ffprobe_timeout_at_deadline_is_global_timeout(monkeypatch):
    def raise_timeout(*_args, **kwargs):
        raise module.subprocess.TimeoutExpired("ffprobe", kwargs["timeout"])

    monkeypatch.setattr(module.subprocess, "run", raise_timeout)
    with pytest.raises(module._DeadlineExceeded, match="remaining deadline"):
        module._probe_media(Path("candidate.mp4"), timeout_seconds=5)


'''
replace_once(
    "tests/tools/test_direct_clip_search_limits.py",
    insert_before,
    new_tests + insert_before,
)

replace_once(
    "skills/pipelines/persian-footage/asset-director.md",
    '''beats, using their already-authored alternate query and the remaining shared byte and
candidate budget. Do not widen providers, add generic queries, or start a third pass.
''',
    '''beats, using their already-authored alternate query. Subtract the first call's
`bytes_downloaded` and `candidates_considered` from the original ceilings and pass those
smaller remaining values into the retry call; never reset either budget. Do not widen
providers, add generic queries, or start a third pass.
''',
)
