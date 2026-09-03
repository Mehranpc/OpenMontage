"""Re-run the `assets` stage for coffee-hormones-fa with corrected queries.

Kept as a file rather than a heredoc because it is the record of what was searched:
the previous run's failure was invisible precisely because nobody could see the query
list beside the clips it produced.

What changed against the original run, and why:

- `clips_per_query`, not `per_query`. The old call used a key the schema does not
  declare, which is silently ignored, so it downloaded the default 3 per query
  instead of 2 — 36 clips instead of 24.
- `filters.min_width: 1080`, and then a downscale pass at selection. Measured, not
  assumed: `_pick_video_rendition` takes the largest rendition inside
  [min_width, 1920], and 1440 is inside that window, so raising the floor to 1080 does
  not lower the ceiling — clips still arrive at 1440x2560. Pexels does offer an exact
  1080x1920 rendition for these clips (checked against the API: 240/360/540/720/1080/
  1440/2160 are all present), but choosing it requires changing `max_width` in the
  adapter, which `documentary-montage` shares. So the floor stays here for the clips
  that only have small renditions, and `select_coffee_footage.py` downscales the twelve
  it actually keeps. That is the caller-side half of the cap, and it is where a
  per-pipeline resolution preference belongs anyway.
- Two queries per beat, not three. The third was always a paraphrase.
- Every query names coffee unless the beat is genuinely about something else. That is
  the whole repair: the old queries were each a defensible translation of their own
  beat, and together they were a video about a medical check-up.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

# Explicit path: `find_dotenv()` walks up from the *caller's* frame and asserts on it,
# which fails outright when this is run as a script rather than imported.
load_dotenv(REPO_ROOT / ".env")

from tools.video.direct_clip_search import DirectClipSearch  # noqa: E402

PROJECT = REPO_ROOT / "projects" / "coffee-hormones-fa"

#: Beat design. `subject` is coffee, so `shows_subject` says whether coffee is legibly
#: in frame — the anchor quota needs the first beat, the last beat, and at least 40% of
#: footage beats to carry it.
BEATS = [
    {
        "id": "beat-1",
        "intent_fa": "صبح بدون قهوه",
        "duration_seconds": 3.0,
        "camera": "push-in",
        "shows_subject": True,
        "shot_scale": "close up",
        "environment": "kitchen",
        "queries": [
            "close up pouring coffee into cup morning",
            "steam rising from coffee cup kitchen",
        ],
    },
    {
        "id": "beat-2",
        "intent_fa": "پژوهش دانشگاه اولو فنلاند",
        "duration_seconds": 8.0,
        "camera": "pan-right",
        "shows_subject": True,
        "shot_scale": "overhead",
        "environment": "desk",
        # Co-presence, not substitution: the study is a notebook and a pen beside the
        # cup, not a laboratory. `university laboratory researchers team` is what the
        # old run asked for and it is why the video looked like it was about medicine.
        "queries": [
            "overhead coffee cup open notebook pen desk",
            "hands writing notes beside coffee mug desk",
        ],
    },
    {
        "id": "beat-3",
        "intent_fa": "قهوه‌نوش‌ها چربی کمتر دارند",
        "duration_seconds": 6.0,
        "camera": "none",
        "shows_subject": False,
        "shot_scale": "wide",
        "environment": "gym",
        # The one beat with no coffee, deliberately: body composition is what this
        # sentence is about, and a rowing shot says "lean" without a tape measure.
        "queries": [
            "slow motion athlete rowing machine gym",
            "man running treadmill wide shot gym",
        ],
    },
    {
        "id": "beat-4",
        "intent_fa": "و عضلهٔ بیشتر",
        "duration_seconds": 5.0,
        "camera": "push-in",
        "shows_subject": True,
        "shot_scale": "medium",
        "environment": "gym",
        "queries": [
            "athletic man drinking coffee after workout",
            "fit woman holding coffee cup gym morning",
        ],
    },
    {
        "id": "beat-5",
        "intent_fa": "وزن روی ترازو تقریباً یکسان",
        "duration_seconds": 5.0,
        "camera": "pull-out",
        "shows_subject": True,
        "shot_scale": "medium",
        "environment": "cafe",
        # «تقریباً یکسان» as two identical cups rather than a bathroom scale. The scale
        # is the stock-library default for "weight" and says nothing about the claim,
        # which is that the number stayed the same while the body did not.
        "queries": [
            "two identical coffee cups side by side table",
            "barista placing two coffee cups cafe counter",
        ],
    },
    {
        "id": "beat-6",
        "intent_fa": "اما بخش جالب‌تر هورمون است",
        "duration_seconds": 3.0,
        "camera": "none",
        "shows_subject": True,
        "shot_scale": "macro",
        "environment": "kitchen",
        # The pivot beat. Crema swirling is coffee doing something chemical, which is
        # as close to "hormone" as an honest camera gets — and it is not a test tube.
        "queries": [
            "macro crema swirling in black coffee",
            "macro milk swirling into coffee slow motion",
        ],
    },
    {
        "id": "beat-7",
        "intent_fa": "در مردان قند خون متعادل‌تر و تستوسترون آزاد بالاتر",
        "duration_seconds": 7.0,
        "camera": "pan-left",
        "shows_subject": True,
        "shot_scale": "medium",
        "environment": "office",
        "queries": [
            "man drinking coffee at desk morning window",
            "young man holding coffee mug office window light",
        ],
    },
    {
        "id": "beat-8",
        "intent_fa": "در زنان اثر ضعیف‌تر",
        "duration_seconds": 5.0,
        "camera": "push-in",
        "shows_subject": True,
        "shot_scale": "close up",
        "environment": "window",
        "queries": [
            "woman holding coffee cup by window soft light",
            "close up woman sipping coffee morning light",
        ],
    },
    {
        "id": "beat-9",
        "intent_fa": "سطح آمینواسیدهای شاخه‌دار پایین‌تر",
        "duration_seconds": 5.0,
        "camera": "none",
        "shows_subject": True,
        "shot_scale": "overhead",
        "environment": "table",
        # BCAAs come from protein-rich food, so the honest frame is breakfast — with the
        # cup in it. `protein powder scoop` and `amino acids molecular animation` were
        # the old queries and neither is about anything a viewer eats.
        "queries": [
            "overhead breakfast eggs bread coffee cup table",
            "overhead healthy breakfast plate coffee morning",
        ],
    },
    {
        "id": "beat-10",
        "intent_fa": "ارتباط با دیابت و بیماری قلبی",
        "duration_seconds": 6.0,
        "camera": "pull-out",
        "shows_subject": True,
        "shot_scale": "close up",
        "environment": "kitchen table",
        # The script names diabetes, so a glucose monitor is allowed here — paired with
        # the cup in the same frame rather than replacing it. `names_banned_term` records
        # that exemption for `lib.persian_scenes.audit_scene_plan`, which otherwise
        # rejects `blood sugar monitor` outright.
        #
        # The second query used to be `close up hands coffee cup medication pills table`,
        # and the correction is worth keeping visible: that query was written *after* the
        # banned-vocabulary rule was rewritten, by an author who had just read it. The
        # beat felt like the exception the rule allows for. It was not — the script names
        # diabetes, not medication — and the query went in anyway. That is exactly why the
        # rule is now a gate instead of prose. Neither pills clip was ever selected, so the
        # rendered video is unaffected; the plan was wrong, not the footage.
        "names_banned_term": True,
        "queries": [
            "coffee cup beside blood sugar monitor table",
            "close up coffee cup on kitchen table morning light",
        ],
    },
    {
        "id": "beat-11",
        "intent_fa": "مطالعه مشاهده‌ای، نه علت و معلول",
        "duration_seconds": 5.0,
        "camera": "pan-right",
        "shows_subject": True,
        "shot_scale": "medium",
        "environment": "library",
        "queries": [
            "coffee cup beside printed papers reading desk",
            "person reading book with coffee library table",
        ],
    },
    {
        "id": "beat-12",
        "intent_fa": "قهوه هزار ترکیب و پیام هورمونی خاص",
        "duration_seconds": 8.0,
        "camera": "push-in",
        "shows_subject": True,
        "shot_scale": "macro",
        "environment": "studio",
        "queries": [
            "macro roasted coffee beans rotating texture",
            "close up person smelling fresh coffee beans",
        ],
    },
]


def main() -> None:
    queries = [
        {"query": query, "slot_id": beat["id"], "kind": "video"}
        for beat in BEATS
        for query in beat["queries"]
    ]

    tool = DirectClipSearch()
    result = tool.execute(
        {
            "output_dir": str(PROJECT / "assets" / "video" / "pool"),
            "queries": queries,
            "sources": ["pexels"],
            "clips_per_query": 2,
            "filters": {
                "orientation": "portrait",
                # Below the longest beat (8s) on purpose: an 8s floor empties the pool
                # for the nine beats that are shorter. Clips shorter than their own beat
                # are rejected at selection instead, where the beat is known.
                "min_duration": 6,
                "min_width": 1080,
            },
            "extract_thumbnails": True,
            # 31 of 48 clips landed in 900s on this connection, so the first run died
            # mid-download. `skip_existing` (on by default) reuses what is already on
            # disk, so a re-run resumes rather than restarting.
            "timeout_seconds": 2400,
        }
    )

    print("success:", result.success)
    if not result.success:
        print("error:", result.error)
        return

    data = result.data or {}
    print(json.dumps({k: v for k, v in data.items() if k != "clips"}, indent=2)[:1500])

    clips = data.get("clips") or data.get("assets") or []
    print(f"\n{len(clips)} clips")
    for clip in clips:
        slug = (clip.get("source_url") or clip.get("original_url") or "").rstrip("/").rsplit("/", 1)[-1]
        print(
            f'  {clip.get("slot_id", "?"):8s} {clip.get("width")}x{clip.get("height")} '
            f'{clip.get("duration", 0):5.1f}s  {slug}'
        )

    (PROJECT / "assets" / "video" / "pool_result.json").write_text(
        json.dumps({"beats": BEATS, "result": data}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
