# Replay fixture: first-date-message-timing on f418063

Source: the 2026-09-28 Mac acceptance run on f418063, exported read-only by Mehran for #264. The run exposed #305, #206, #308, #310, #313 and #315.

- `export/`: the run's `persian-video-workflow.json`, `.telemetry/` (703 command events, argv, JSON input snapshots), and `inputs/approved_script.txt`. The local home directory is replaced by `/Users/operator`; replay remaps the project root from `read_allowlist.project_root`.
- `export/inputs/narration.mp3` and `providers/narration.mp3`: **synthetic** pink noise at the original duration (62.51s). Replay maps the recorded narration sha256 onto this file's.
- `providers/recorded/`: the run's own provider recordings: search cache (27 queries), transcriber output, committed word timings.
- `providers/clips/`: **synthetic** flat-colour clips for the 27 sources the run downloaded or rejected, at each one's recorded width, height, exact frame rate (NTSC rates as 24000/1001) and duration, built by `scripts/make_replay_fixture.py`. A clip the run's download validation rejected keeps its probed width, so it is rejected again.
- `providers/music-bed.mp3`: **synthetic** tone.

None of the run's footage, narration, music or frames are in this directory.

`tests/rehearsal/test_real_run_replay.py` replays commands 0-239: 0-238 reproduce the recorded exit codes, and 239 (the edit staged without the opening shot's semantic fields) is now refused before a candidate is spent (#305). Reverting #305 fails the test.
