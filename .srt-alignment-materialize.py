from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, found {count}: {old[:80]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "tools/video/persian_compose.py",
    "from lib.persian_srt import audit_cues, build_cues, render_srt\n",
    "from lib.persian_srt import render_srt\n"
    "from lib.persian_srt_alignment import (\n"
    "    SubtitleAlignmentError,\n"
    "    build_script_aligned_cues,\n"
    ")\n",
)
replace_once(
    "tools/video/persian_compose.py",
    '    version = "0.2.0"\n',
    '    version = "0.3.0"\n',
)
replace_once(
    "tools/video/persian_compose.py",
    "        return props, attributions\n\n    @staticmethod\n    def _build_moments(\n",
    "        # Subtitle alignment is a pre-render delivery gate. The same helper is\n"
    "        # called again when the SRT is written, but doing it here prevents an\n"
    "        # invalid script/timing pair from consuming a full render first.\n"
    "        self._aligned_subtitle_cues(persian)\n\n"
    "        return props, attributions\n\n    @staticmethod\n    "    def _build_moments(\n",
)
old_subtitle_method = '''    @staticmethod
    def _write_subtitles(
        persian: dict[str, Any], output_path: Path
    ) -> tuple[str | None, list[str]]:
        """Write the narration sidecar `.srt` beside the MP4.

        Returns the path written (or None) and any readability advisories, which are
        surfaced rather than raised: an over-speed caption is a property of the
        narration's delivery, and the honest remedy is a shorter script — not a refused
        render at the last stage before delivery.
        """
        word_timings = (persian.get("audio") or {}).get("wordTimings")
        if not word_timings:
            return None, []

        cues = build_cues(word_timings)
        if not cues:
            return None, []

        srt_path = output_path.with_suffix(".srt")
        # utf-8-sig: several players (and Windows Notepad) mis-detect a BOM-less UTF-8
        # SRT as a legacy single-byte encoding and render Persian as mojibake.
        srt_path.write_text(render_srt(cues), encoding="utf-8-sig")
        return str(srt_path), audit_cues(cues)
'''
new_subtitle_method = '''    @staticmethod
    def _aligned_subtitle_cues(persian: dict[str, Any]) -> list[Any]:
        """Return delivery-safe cues whose text comes only from the approved script.

        Whisper/ASR words remain the timing signal used by moment synchronization,
        but their spelling is never copied into the SRT. Any uncertain alignment,
        malformed approved copy, speech-coverage gap, overlap, or reading-speed
        violation is a hard delivery failure.
        """
        audio = persian.get("audio") or {}
        word_timings = audio.get("wordTimings")
        if not word_timings:
            if audio.get("narration"):
                raise ValueError(
                    "narrated Persian delivery requires audio.wordTimings so the "
                    "approved script can be aligned to the spoken audio"
                )
            return []

        try:
            return build_script_aligned_cues(
                audio.get("approvedScript"),
                word_timings,
            )
        except SubtitleAlignmentError as exc:
            raise ValueError(
                "the Persian sidecar SRT is not provably aligned, so delivery is "
                f"refused rather than shipping ASR copy or a timing gap: {exc}"
            ) from exc

    @staticmethod
    def _write_subtitles(
        persian: dict[str, Any], output_path: Path
    ) -> tuple[str | None, list[str]]:
        """Write the validated, approved-script-aligned `.srt` beside the MP4."""
        cues = PersianCompose._aligned_subtitle_cues(persian)
        if not cues:
            return None, []

        srt_path = output_path.with_suffix(".srt")
        # utf-8-sig: several players (and Windows Notepad) mis-detect a BOM-less UTF-8
        # SRT as a legacy single-byte encoding and render Persian as mojibake.
        srt_path.write_text(render_srt(cues), encoding="utf-8-sig")
        # Alignment, lexical equality, coverage, overlap, and reading speed are gates
        # in build_script_aligned_cues. A written sidecar therefore has no suppressed
        # advisory: a non-empty problem list would have blocked the render preflight.
        return str(srt_path), []
'''
replace_once(
    "tools/video/persian_compose.py",
    old_subtitle_method,
    new_subtitle_method,
)

schema_path = ROOT / "schemas/artifacts/edit_decisions.schema.json"
schema = json.loads(schema_path.read_text(encoding="utf-8"))
audio_schema = schema["properties"]["persian"]["properties"]["audio"]
audio_properties = audio_schema["properties"]
if "approvedScript" in audio_properties:
    raise RuntimeError("edit_decisions schema already contains approvedScript")
approved_schema = {
    "type": "object",
    "description": (
        "Authoritative Persian narration copy for the sidecar SRT. ASR words provide "
        "timing only and are never delivered as subtitle text."
    ),
    "required": ["text", "sha256", "matchPolicy"],
    "properties": {
        "text": {
            "type": "string",
            "minLength": 1,
            "description": "Approved narration sections joined with one ASCII space.",
        },
        "sha256": {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
            "description": "SHA-256 of the exact UTF-8 bytes in text.",
        },
        "matchPolicy": {
            "type": "string",
            "enum": ["exact", "normalized"],
            "description": (
                "exact preserves approved bytes; normalized permits only the documented "
                "Persian letter/digit canonicalization while retaining approved wording."
            ),
        },
        "maxCps": {
            "type": "number",
            "exclusiveMinimum": 0,
            "maximum": 21,
            "default": 21,
            "description": "Configured reading-speed ceiling; may not exceed 21 visible chars/sec.",
        },
    },
    "additionalProperties": False,
}
ordered = {}
for key, value in audio_properties.items():
    if key == "wordTimings":
        ordered["approvedScript"] = approved_schema
        value["description"] = (
            "Raw ASR narration words used only as a timing signal. persian_compose "
            "aligns approvedScript text to these windows and never copies ASR spelling "
            "into the delivered SRT. Omitted only in silent mode."
        )
    ordered[key] = value
audio_schema["properties"] = ordered
schema_path.write_text(
    json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)

replace_once(
    "pipeline_defs/persian-footage.yaml",
    "a sidecar SRT built from narration word timings,",
    "a sidecar SRT whose approved-script copy is aligned to narration word timings,",
)
replace_once(
    "pipeline_defs/persian-footage.yaml",
    "      The user supplies (or records) Persian narration audio. Word-level timings\n"
    "      are transcribed from that audio, become a sidecar SRT beside the MP4, and\n"
    "      ANCHOR the moments: each moment names its words and its timing is re-derived\n",
    "      The user supplies (or records) Persian narration audio. Raw ASR word timings\n"
    "      are transcribed from that audio and remain timing evidence only; approved\n"
    "      script copy becomes the sidecar SRT and ANCHORS the moments. Each moment\n"
    "      names its words and its timing is re-derived\n",
)
replace_once(
    "pipeline_defs/persian-footage.yaml",
    '      - "In narrated mode: audio.wordTimings is present so persian_compose writes the sidecar SRT"',
    '      - "In narrated mode: audio.wordTimings supplies raw timing and audio.approvedScript supplies hash-bound delivery copy; persian_compose refuses an uncertain alignment"',
)
replace_once(
    "pipeline_defs/persian-footage.yaml",
    '      - "In narrated mode: the sidecar SRT exists beside the MP4, and its readability advisories are reported rather than suppressed. An over-speed subtitle is a property of how fast the narrator spoke; the honest remedy is a shorter script, not a blocked delivery."',
    '      - "In narrated mode: the sidecar SRT exists beside the MP4 only after approved-script lexical equality, cue ordering, non-overlap, speech coverage, Persian spacing/ZWNJ, and configured reading-speed gates pass; any failure blocks delivery."',
)
replace_once(
    "pipeline_defs/persian-footage.yaml",
    '      - "In narrated mode: render_report.subtitle_path points at an existing SRT"',
    '      - "In narrated mode: render_report.subtitle_path points at an existing approved-script-aligned SRT"',
)

replace_once(
    "skills/pipelines/persian-footage/edit-director.md",
    "Pass `audio.wordTimings` and the file appears beside the MP4. You do not build cues\n"
    "by hand and you do not put them in the props; `persian_compose` refuses a `cues` key\n"
    "outright.\n",
    "Pass raw ASR timing words in `audio.wordTimings` and the authoritative narration\n"
    "copy in `audio.approvedScript = {text, sha256, matchPolicy, maxCps}`. Build `text`\n"
    "from the approved script sections with one ASCII space between tokens and hash its\n"
    "exact UTF-8 bytes. `matchPolicy: exact` preserves those bytes; `normalized` permits\n"
    "only the repository's documented Persian letter/digit canonicalization. The\n"
    "aligner discards ASR spelling after timing alignment. You do not build cues by hand\n"
    "and you do not put them in the props; `persian_compose` refuses a `cues` key outright.\n",
)
replace_once(
    "skills/pipelines/persian-footage/edit-director.md",
    "Test coverage: cue construction is\n"
    "covered by `TestCueConstruction` in `tests/lib/test_persian_gates.py:93+`, but\n"
    "`_write_subtitles` itself and the compose-level `cues` refusal have **no test** —\n"
    "treat both as unguarded when editing that code.\n",
    "Test coverage: legacy cue grouping remains covered by `TestCueConstruction` in\n"
    "`tests/lib/test_persian_gates.py`; script authority, the raw-Whisper regression,\n"
    "the 5.18-second speech-gap regression, and compose integration are covered by\n"
    "`tests/lib/test_persian_srt_alignment.py`.\n",
)
replace_once(
    "skills/pipelines/persian-footage/edit-director.md",
    "`wordTimings` drives two things now — the sidecar `.srt` **and** the sync audit /\n"
    "`retime_moments`. In narrated mode it is required, not optional. Omit it only in\n"
    "silent mode, where there is no voice to anchor to and no subtitle file to write.\n",
    "`wordTimings` drives moment sync and supplies the SRT clock; `approvedScript` owns\n"
    "every delivered subtitle character. Both are required in narrated mode. Omit both\n"
    "only in silent mode, where there is no voice to anchor and no subtitle to write.\n",
)
replace_once(
    "skills/pipelines/persian-footage/edit-director.md",
    '      "wordTimings": [ { "word": "قهوه", "start": 0.2, "end": 0.6 } ],\n',
    '      "approvedScript": { "text": "…", "sha256": "<sha256-of-exact-utf8>", "matchPolicy": "exact", "maxCps": 21 },\n'
    '      "wordTimings": [ { "word": "قهوه", "start": 0.2, "end": 0.6 } ],\n',
)
replace_once(
    "skills/pipelines/persian-footage/edit-director.md",
    "- Narrated mode: `music` + audited `musicTrack` (or an explicit `omitMusicReason`);\n"
    "  `wordTimings` present for the `.srt` and the sync audit.\n",
    "- Narrated mode: `music` + audited `musicTrack` (or an explicit `omitMusicReason`);\n"
    "  raw `wordTimings` present for timing/sync and hash-bound `approvedScript` present\n"
    "  for exact or normalized SRT delivery copy.\n",
)

replace_once(
    "skills/pipelines/persian-footage/compose-director.md",
    "It also writes a sidecar `.srt` beside the MP4 when `audio.wordTimings` is present, and\n"
    "returns its path plus any readability advisories. Those are advisories on purpose: an\n"
    "over-speed subtitle is a property of how fast the narrator spoke, and the honest remedy\n"
    "is a shorter script, not a blocked delivery.\n",
    "It writes a sidecar `.srt` only when raw `audio.wordTimings` can be confidently\n"
    "aligned to the hash-bound `audio.approvedScript`. The script owns every delivered\n"
    "character; ASR owns timing only. Lexical mismatch, malformed spacing/ZWNJ, overlap,\n"
    "uncovered speech, or a cue above `approvedScript.maxCps` blocks delivery before render.\n"
    "The honest remedy for over-speed narration is a shorter approved script or a slower\n"
    "recording — never suppressing the gate or copying Whisper wording.\n",
)

for temporary in (
    ".srt-alignment-materialize.py",
    ".srt-alignment-materialize-request",
    ".github/workflows/materialize-srt-alignment.yml",
):
    (ROOT / temporary).unlink(missing_ok=True)
