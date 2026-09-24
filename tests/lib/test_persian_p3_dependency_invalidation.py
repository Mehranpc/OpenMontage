from copy import deepcopy

from lib import persian_edit_workspace as workspace


def _edit(music_path: str) -> dict:
    return {
        "version": "2.1",
        "metadata": {"targetPlatform": "instagram_reels"},
        "persian": {
            "format": "vertical",
            "durationSeconds": 12.0,
            "platformTarget": "instagram_reels",
            "shots": [{
                "id": "shot-1",
                "startSeconds": 0.0,
                "endSeconds": 12.0,
                "visualEventId": "event-1",
                "source": "assets/clip.mp4",
                "avoidRegions": [{"x": 0.1, "y": 0.2, "w": 0.4, "h": 0.5}],
            }],
            "moments": [{
                "id": "moment-1",
                "kind": "hook",
                "startSeconds": 0.0,
                "endSeconds": 3.0,
                "segments": [{"role": "hero", "text": "متن ثابت"}],
            }],
            "typographicBeats": [],
            "captions": [],
            "audio": {"narration": "voice.wav", "musicGain": 0.2},
            "musicTrack": {
                "path": music_path,
                "provider": "pixabay",
                "license": {"name": "Pixabay Content License"},
            },
        },
    }


def test_music_only_change_preserves_visual_preflight_dependencies_but_invalidates_audio_review() -> None:
    first = _edit("assets/music/a.mp3")
    second = deepcopy(first)
    second["persian"]["musicTrack"]["path"] = "assets/music/b.mp3"

    before = workspace._dependency_digests(first)
    after = workspace._dependency_digests(second)

    assert before["retention"] == after["retention"]
    assert before["hook"] == after["hook"]
    assert before["browser"] == after["browser"]
    assert before["audio"] != after["audio"]
    assert before["final_review"] != after["final_review"]
