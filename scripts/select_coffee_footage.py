"""Select twelve clips from the pool, one per beat, and normalize them to 1080x1920.

Two things are decided here, and only one of them is a matter of taste.

**Which clip** is a judgement about content, and the evidence available to it is the
Pexels landing-page slug — «close-up-of-an-espresso-machine-pouring-coffee-into-a-ceramic-cup»
is a caption written by a human who saw the clip. It is not a substitute for looking, but
it is what says whether coffee is in frame, and coffee in frame is the failure this
re-run exists to fix. So the choice per beat is written out below with its reason, and
`shows_subject` is derived from the slug rather than asserted.

**Whether the clip can carry type** is measurable, and is measured. The moment band is
the vertical 30-58% of the frame, right-anchored, and this script reports the mean and
the standard deviation of luminance there for every candidate. The scrim guarantees
contrast regardless (it bounds what is behind type at 71.4 of 255), so a bright band is
not a failure — but a *busy* band still reads as noise behind the words, and stddev is
what busy looks like as a number. Where two clips serve a beat equally, the calmer band
wins.

The downscale to 1080x1920 is the caller-side half of the resolution cap. The shared
Pexels adapter takes the largest rendition inside [min_width, 1920] and cannot be
narrowed without affecting `documentary-montage`, so clips arrive at 1440x2560 and are
reduced here, where the target frame is known. Same-frame-rate, same-duration, CRF 20:
the render scales them to 1080 wide anyway, so this discards nothing the viewer sees and
takes ~340MB off a disk with 4.8GiB left.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PROJECT = REPO_ROOT / "projects" / "coffee-hormones-fa"
POOL = PROJECT / "assets" / "video" / "pool"
POOL_RESULT = PROJECT / "assets" / "video" / "pool_result.json"
OUT_DIR = PROJECT / "assets" / "video" / "selected"

#: Where type sits, from `computeMomentZone("vertical")` in tokens.ts. Sampled over the
#: right 62% of the width because moments are right-anchored and the left edge of the
#: frame is behind at most the longest statement line.
BAND_TOP, BAND_BOTTOM = 0.3045, 0.5755
BAND_RIGHT_FRACTION = 0.62

TARGET_WIDTH, TARGET_HEIGHT = 1080, 1920

#: One clip per beat, with the reason it was chosen. `shows_subject` is derived from the
#: slug by `main` and never taken from here — the plan's pre-search guess about what the
#: pool would contain is exactly the thing that needs checking.
SELECTION: list[dict] = [
    {
        "beat_id": "beat-1",
        "clip_id": "pexels_14916793",
        "reason": "اسپرسو در فنجان سرامیکی؛ موضوع در نمای نزدیک و بدون آدم، شروع تمیز",
    },
    {
        "beat_id": "beat-2",
        "clip_id": "pexels_6343677",
        # The study beat, and the one the old run got most wrong: it asked for a
        # laboratory and got one. «فنجان‌ها روی میز کار» is the study as co-presence —
        # the desk is the research, the cups are why we are talking about it. It also has
        # the calmest band of the four candidates (54.8 against 70.9), and the ۲۲۶۴
        # figure lands on this beat, so the band is carrying the largest type in the film.
        "reason": "فنجان‌های قهوه روی میز کار؛ پژوهش به‌عنوان هم‌حضور، نه آزمایشگاه",
    },
    {
        "beat_id": "beat-3",
        "clip_id": "pexels_6389558",
        # The one beat with no coffee, by design: body composition is the claim.
        "reason": "پارو زدن روی دستگاه؛ ترکیب بدنی بدون متر و ترازو",
    },
    {
        "beat_id": "beat-4",
        "clip_id": "pexels_7218891",
        # A deviation, recorded rather than hidden: the plan wanted coffee in frame here
        # and the pool has no gym-and-coffee clip. Of what exists, a woman drinking on a
        # bench is the nearest honest reading of «عضلهٔ بیشتر» after exercise, and its
        # band is the second-calmest available (49.4 against 74.6 for the tumbler shot).
        "reason": "نوشیدن روی نیمکت بعد از تمرین؛ نزدیک‌ترین گزینهٔ موجود، اما بدون قهوهٔ قابل‌تشخیص",
    },
    {
        "beat_id": "beat-5",
        "clip_id": "pexels_7316028",
        # «تقریباً یکسان» as two cups on a tray. A bathroom scale is the stock-library
        # reflex for "weight" and says nothing about a number that stayed the same.
        "reason": "دو فنجان یکسان روی سینی؛ «وزن تقریباً یکسان» به زبان تصویر",
    },
    {
        "beat_id": "beat-6",
        "clip_id": "pexels_6535487",
        # The pivot beat. Stirring is coffee doing something chemical, which is as close
        # to "hormone" as an honest camera gets — and its band is by far the calmest of
        # the six candidates here (30.7 against 70.0), which matters because this is a
        # 3-second beat with a statement on it.
        "reason": "هم‌زدن قهوه با قاشق؛ چرخش شیمیایی به‌جای لولهٔ آزمایش",
    },
    {
        "beat_id": "beat-7",
        "clip_id": "pexels_35332003",
        "reason": "مرد جوان با فنجان قهوه هنگام کار در خانه؛ نمای مردانه بدون فضای پزشکی",
    },
    {
        "beat_id": "beat-8",
        "clip_id": "pexels_6563972",
        "reason": "زن کنار پنجرهٔ شیشه‌ای با فنجان؛ قرینهٔ زنانهٔ بیت قبل با مقیاس نزدیک‌تر",
    },
    {
        "beat_id": "beat-9",
        "clip_id": "pexels_34307143",
        # BCAAs come from protein-rich food, so the honest frame is breakfast.
        "reason": "میز صبحانه با تخم‌مرغ و قهوه؛ آمینواسید از راه غذا، نه پودر پروتئین",
    },
    {
        "beat_id": "beat-10",
        "clip_id": "pexels_36109165",
        # Sugar going into espresso, on the beat that names blood sugar and diabetes. The
        # prescription-pills clip was the first pick and is the trap this pipeline is
        # supposed to refuse: it illustrates the sentence by replacing the subject.
        "reason": "ریختن شکر در اسپرسو؛ قند در قاب، روی جمله‌ای که از قند خون می‌گوید",
    },
    {
        "beat_id": "beat-11",
        "clip_id": "pexels_16565432",
        "reason": "فنجان قهوه و مجله در دست؛ «مطالعهٔ مشاهده‌ای» به‌جای قفسهٔ کتابخانه",
    },
    {
        "beat_id": "beat-12",
        "clip_id": "pexels_7121115",
        # The closing line is «دفعهٔ بعد که قهوه‌تو بو کردی», and this is that. Two
        # coffee-bean clips have far calmer bands (8.0 and 11.8 against 50.6) and were
        # passed over for it: the scrim guarantees the contrast either way, and matching
        # what the narrator is describing is worth more than a quieter background.
        "reason": "بوکردن دانه‌های قهوه؛ همان کاری که جملهٔ آخر از بیننده می‌خواهد",
    },
]

#: Words in a slug that mean coffee is in frame.
_SUBJECT_WORDS = ("coffee", "espresso", "latte", "cappuccino", "mug", "cup", "barista", "cafe")


def _pool() -> dict[str, dict]:
    data = json.loads(POOL_RESULT.read_text(encoding="utf-8"))
    return {clip["clip_id"]: clip for clip in data["result"]["clips"]}


def _beats() -> dict[str, dict]:
    data = json.loads(POOL_RESULT.read_text(encoding="utf-8"))
    return {beat["id"]: beat for beat in data["beats"]}


def _slug(clip: dict) -> str:
    tail = (clip.get("source_url") or "").rstrip("/").rsplit("/", 1)[-1]
    return tail.rsplit("-", 1)[0].replace("-", " ")


#: Mid-frames extracted for clips the pool has no thumbnail for.
FRAME_CACHE = POOL / "band_frames"


def decodable_seconds(path: Path) -> float:
    """Length that actually decodes, from counted packets rather than the header.

    Needed because two pool clips are truncated: their headers claim 17.6s and 26.3s and
    they hold 181 and 314 packets, roughly a third of the frames. They are the files the
    interrupted first run left half-written, and `skip_existing` handed them back —
    its integrity test is `size > 1024`, which a partial download passes. A truncated
    clip is not a cosmetic problem: at 8 decodable seconds behind a 12-second beat the
    render freezes on the last decoded frame, and nothing reports it.
    """
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-count_packets", "-select_streams", "v:0",
            "-show_entries", "stream=nb_read_packets,r_frame_rate",
            "-of", "csv=p=0", str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    rate, packets = probe.stdout.strip().split(",")
    numerator, _, denominator = rate.partition("/")
    fps = float(numerator) / float(denominator or 1)
    return int(packets) / fps if fps else 0.0


def _mid_frame(clip: dict) -> Path:
    """A frame from the middle of this clip's *decodable* span.

    The pool's own thumbnail when it exists. Two clips have none, for the same reason
    they are truncated — `skip_existing` skips thumbnail extraction along with the
    download — so those are extracted here, seeking against decodable length rather than
    the header, which is what made a plain mid-seek write an empty file.
    """
    thumbnail = clip.get("thumbnail")
    if thumbnail and Path(thumbnail).is_file():
        return Path(thumbnail)

    FRAME_CACHE.mkdir(parents=True, exist_ok=True)
    # PNG, not JPEG: the mjpeg encoder refuses these clips' pixel format outright
    # ("Non full-range YUV is non-standard") and writes nothing. PNG is also what the
    # verifier samples, so the two measurements see identical pixels.
    target = FRAME_CACHE / f'{clip["clip_id"]}.png'
    if not target.exists():
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-ss", str(max(0.0, decodable_seconds(Path(clip["path"])) / 2)),
                "-i", clip["path"],
                "-frames:v", "1",
                str(target),
            ],
            check=True,
        )
    return target


def _band_stats(clip: dict) -> tuple[float, float]:
    """Mean and stddev of luminance in the moment band, on 0-255.

    Rec. 601 luma, which is what the eye-weighting in `lib/persian_verify.py` uses for
    the same reason: the green channel dominates perceived brightness, so a plain
    channel average would call a saturated blue band bright.
    """
    with Image.open(_mid_frame(clip)) as image:
        frame = np.asarray(image.convert("RGB"), dtype=np.float64)
    height, width = frame.shape[:2]
    band = frame[
        int(height * BAND_TOP) : int(height * BAND_BOTTOM),
        int(width * (1.0 - BAND_RIGHT_FRACTION)) :,
    ]
    luma = 0.299 * band[..., 0] + 0.587 * band[..., 1] + 0.114 * band[..., 2]
    return float(luma.mean()), float(luma.std())


def _downscale(source: Path, target: Path) -> None:
    """1080x1920, no crop, no re-timing.

    `scale` alone: every pool clip is already 9:16 portrait, so there is no aspect
    correction to make and a crop would silently reframe someone's composition.
    """
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-vf",
            f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}:flags=lanczos",
            "-c:v",
            "libx264",
            "-crf",
            "20",
            "-preset",
            "medium",
            "-pix_fmt",
            "yuv420p",
            "-an",  # Stock clips carry ambience nobody mixed; narration is the audio.
            "-movflags",
            "+faststart",
            str(target),
        ],
        check=True,
    )


def main() -> None:
    pool = _pool()
    beats = _beats()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=== candidates per beat (band mean / stddev, right 62% of 30-58% rows) ===")
    for beat_id in sorted(beats, key=lambda b: int(b.split("-")[1])):
        print(f"\n{beat_id}  {beats[beat_id]['intent_fa']}")
        for clip in pool.values():
            if clip["slot_id"] != beat_id:
                continue
            mean, std = _band_stats(clip)
            chosen = any(s["clip_id"] == clip["clip_id"] for s in SELECTION)
            subject = any(word in _slug(clip) for word in _SUBJECT_WORDS)
            print(
                f'  {"*" if chosen else " "} {clip["clip_id"]:18s} '
                f'{clip["width"]}x{clip["height"]} {clip["duration"]:5.1f}s '
                f"mean {mean:6.1f} std {std:5.1f} "
                f'{"subject" if subject else "no-subject":10s} {_slug(clip)}'
            )

    print("\n=== selected ===")
    manifest: list[dict] = []
    deviations: list[str] = []
    for entry in SELECTION:
        clip = pool[entry["clip_id"]]
        beat = beats[entry["beat_id"]]
        assert clip["slot_id"] == entry["beat_id"], (
            f'{entry["clip_id"]} was found for {clip["slot_id"]}, not {entry["beat_id"]}'
        )

        # Derived, not asserted. The plan's `shows_subject` was a guess about what the
        # search would return; where the two disagree the pool is the fact and the plan
        # is the wish, so the disagreement is reported and the quota is checked against
        # what was actually found.
        shows_subject = any(word in _slug(clip) for word in _SUBJECT_WORDS)
        if shows_subject != beat["shows_subject"]:
            deviations.append(
                f'{entry["beat_id"]}: planned shows_subject={beat["shows_subject"]}, '
                f'got {shows_subject} ({_slug(clip)})'
            )

        # Decodable length must cover the beat, not the header's claim. A clip that runs
        # short either freezes on its last frame or loops, and both read as a mistake.
        usable = decodable_seconds(Path(clip["path"]))
        assert usable >= beat["duration_seconds"], (
            f'{entry["clip_id"]} decodes {usable:.1f}s (header claims '
            f'{clip["duration"]}s) for a {beat["duration_seconds"]}s beat'
        )

        target = OUT_DIR / f'{entry["beat_id"]}_{entry["clip_id"]}.mp4'
        if not target.exists():
            _downscale(Path(clip["path"]), target)

        mean, std = _band_stats(clip)
        manifest.append(
            {
                "beat_id": entry["beat_id"],
                "clip_id": entry["clip_id"],
                "path": str(target.relative_to(REPO_ROOT)),
                "width": TARGET_WIDTH,
                "height": TARGET_HEIGHT,
                "duration_seconds": round(usable, 2),
                "beat_duration_seconds": beat["duration_seconds"],
                "camera": beat["camera"],
                "shot_scale": beat["shot_scale"],
                "environment": beat["environment"],
                "shows_subject": shows_subject,
                "selection_reason": entry["reason"],
                "planned_shows_subject": beat["shows_subject"],
                "provider": clip["source"],
                "original_url": clip["source_url"],
                "license": clip["license"],
                "attribution": f'Video by {clip["creator"]} on Pexels',
                "band_luma_mean": round(mean, 1),
                "band_luma_std": round(std, 1),
            }
        )
        size_mb = target.stat().st_size / 1_048_576
        print(
            f'  {entry["beat_id"]:8s} {entry["clip_id"]:18s} {size_mb:5.1f}MB  '
            f'{"subject" if shows_subject else "no-subject":10s} band {mean:6.1f}/{std:5.1f}'
        )

    if deviations:
        print("\ndeviations from the plan:")
        for line in deviations:
            print(f"  {line}")

    # The anchor quota, enforced rather than printed. A pipeline whose whole failure was
    # footage drifting off-subject cannot treat this as advisory.
    subject_beats = [item for item in manifest if item["shows_subject"]]
    ratio = len(subject_beats) / len(manifest)
    print(
        f"\nanchor quota: first={manifest[0]['shows_subject']} "
        f"last={manifest[-1]['shows_subject']} "
        f"ratio={len(subject_beats)}/{len(manifest)} = {ratio:.0%} (needs >= 40%)"
    )
    assert manifest[0]["shows_subject"], "the first beat must establish the subject"
    assert manifest[-1]["shows_subject"], "the last beat must return to the subject"
    assert ratio >= 0.40, f"only {ratio:.0%} of beats show the subject"

    pairs = [(item["shot_scale"], item["environment"]) for item in manifest]
    repeats = [
        (manifest[i]["beat_id"], manifest[i + 1]["beat_id"])
        for i in range(len(pairs) - 1)
        if pairs[i] == pairs[i + 1]
    ]
    print(f"adjacent scale+environment repeats: {repeats or 'none'}")
    assert not repeats, f"adjacent beats share both shot scale and environment: {repeats}"

    (PROJECT / "assets" / "video" / "selection.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    total = sum(Path(REPO_ROOT / item["path"]).stat().st_size for item in manifest)
    print(f"total selected: {total / 1_048_576:.0f}MB")


if __name__ == "__main__":
    main()
