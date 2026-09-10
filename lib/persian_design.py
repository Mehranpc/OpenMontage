"""Versioned Persian design boundary for opt-in V2 rendering."""
from __future__ import annotations
import hashlib, json, math
from pathlib import Path
from typing import Any

PROFILE_PATH = Path(__file__).resolve().parents[1] / "styles" / "persian-footage" / "v2.json"
FILM_TYPE_PROFILE_PATH = PROFILE_PATH.with_name("film-type.json")
SUPPORTED_FILM_TYPE_25_HASH = "ba44a26a97c680a8e714d5578fcab01cb7009a986e4d1361f9ce49dd3aab0261"
SUPPORTED_FILM_TYPE_26_HASH = "1f763aed6dbfa2b61cdc6ce30558f6bc6e5ab318fb88e0125d84b07b0ae28967"
SUPPORTED_FILM_TYPE_27_HASH = "b069a090061c1011d456cc5c63ff6989382f9044fdd38abb7c12db359710cea5"
SUPPORTED_FILM_TYPE_28_HASH = "acfa082438f473f34f595a3a9132e03e26fda7dac0522f9c7ca00267272ac468"
SUPPORTED_FILM_TYPE_29_HASH = "320a67a296d30cf1337b6c121cdd9367dfdc4e28fad1ba6af4f666e1e07551bf"
SUPPORTED_FILM_TYPE_210_HASH = "60ff5e80524aaa3877e8bd94e2bdd8c957c9f367947066ced034cbfb8be678e0"
SUPPORTED_FILM_TYPE_211_HASH = "ee04b0e576891828d754b2dc8bc7139178174251e3755dea4797dd480df4f687"
SUPPORTED_FILM_TYPE_HASH = "3580543858c134902cf1539fccf6d66e31f870d88a0b39a41ed1a28603f7aa5a"
SUPPORTED_FILM_TYPE_MOTION_HASH = "06a6cc6297df4146f9a8fa82af6617cec1e07ff420c72d134fbf878217dca543"
SUPPORTED_FILM_TYPE_REPAIR_HASH = "3ee76f211682537b5b1ac457063a76cd81f1c84dd7fa916fddeef299ff3eecab"
SUPPORTED_FILM_TYPE_POLISH_HASH = "6d71bee9de74a627f393544bbcf9caf37b7349c422397b016f1f10597a1c43c2"
SUPPORTED_FILM_TYPE_LEGACY_HASH = "c56aac71643bdeff4c27b75fa1ef1bb4e2997a3216a886d61dac78c3a021af0c"
SUPPORTED_CONTRAST_STRENGTHS = {"soft", "standard", "strong"}
SUPPORTED_TREATMENTS = {"editorial", "inline-statement"}
SUPPORTED_MOTION = {"soft-reveal", "cut-in"}
SUPPORTED_EMPHASIS = {"none", "inline"}
SUPPORTED_CONTRAST_MODES = {"dark", "light"}
SUPPORTED_PLACEMENTS = {"upper-left", "upper-right", "mid-left", "mid-right", "lower-left", "lower-right", "center", "auto"}


def derive_lockup_size(*, persian_text: str = "طریقت تسلیم", latin_text: str = "Pathway_of_Surrender", font_size_px: float = 36.0, frame_width_px: float = 1080.0, frame_height_px: float = 1920.0, measured_width_px: float | None = None, measured_height_px: float | None = None) -> dict[str, float | bool]:
    """Normalize dimensions from an actual raster/layout measurement.

    Deliberately refuses the old character-count estimate. The compose bridge must
    provide dimensions produced by the loaded Estedad layout pipeline.
    """
    if measured_width_px is None or measured_height_px is None:
        raise ValueError("V2 watermark requires loaded-font raster measurement")
    if measured_width_px <= 0 or measured_height_px <= 0:
        raise ValueError("V2 watermark measurement must be positive")
    return {"w": measured_width_px / frame_width_px, "h": measured_height_px / frame_height_px, "measured": True}


def resolve_watermark_plan(*, duration_seconds: float, format: str, seed: str, text_rects: list[dict[str, float]], safe_area: dict[str, float] | None = None, avoid_regions: list[dict[str, float]] | None = None, motion_policy: dict[str, Any] | None = None, lockup_size: dict[str, float] | None = None) -> list[dict[str, Any]]:
    """Deterministic, conservative Stage-B watermark schedule.

    Empty bounds are explicitly unverified: the plan remains conservative and
    callers must report collision status as ``not_checked``.
    """
    policy = motion_policy or {}
    safe = safe_area or {"top": .08, "bottom": .08, "side": .08}
    # Candidate lockups are sized conservatively and derived from this format's
    # safe area, rather than copying vertical coordinates into landscape.
    # Keep the full bilingual lockup, but make its measured footprint compact enough
    # to coexist with footage-led typography. The planner, not the component, owns
    # this geometry so collision decisions match the render.
    measured_lockup = lockup_size if lockup_size is not None else derive_lockup_size(
        frame_width_px=1920.0 if format == "landscape" else 1080.0,
        frame_height_px=1080.0 if format == "landscape" else 1920.0,
    )
    if not measured_lockup.get("measured"):
        raise ValueError("V2 watermark lockup measurement is missing; plan cannot be trusted")
    w = float(measured_lockup.get("w", 0))
    h = float(measured_lockup.get("h", 0))
    safe_side = float(safe.get("side", .08))
    safe_top = float(safe.get("top", .08))
    safe_bottom = float(safe.get("bottom", .08))
    if w <= 0 or h <= 0 or w > 1 or h > 1:
        raise ValueError("V2 watermark lockup_size must contain positive normalized w/h <= 1")
    if w > 1 - 2 * safe_side or h > 1 - safe_top - safe_bottom:
        raise ValueError("V2 watermark lockup measurement does not fit inside the configured safe area")
    left, right = safe_side, 1 - safe_side - w
    top = safe_top
    bottom = 1 - safe_bottom - h
    mid = max(top, (top + bottom) / 2 - h / 2)
    rects = {"lower-left": {"x": left, "y": bottom, "w": w, "h": h},
             "mid-left": {"x": left, "y": mid, "w": w, "h": h},
             "upper-left": {"x": left, "y": top, "w": w, "h": h},
             "lower-right": {"x": right, "y": bottom, "w": w, "h": h},
             "mid-right": {"x": right, "y": mid, "w": w, "h": h},
             "upper-right": {"x": right, "y": top, "w": w, "h": h}}
    # Try every safe zone. Restricting vertical clips to the left column made a
    # face-safe right column unreachable and falsely reduced an 18s plan to one slot.
    order = ["lower-right", "mid-right", "upper-right", "lower-left", "mid-left", "upper-left"]
    # Seed selects a stable starting candidate, while policy keeps non-top first.
    offset = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16) % len(order)
    candidates = order[offset:] + order[:offset]
    if policy.get("preferNonTopPosition", True):
        candidates.sort(key=lambda s: s.startswith("upper-"))
    forbidden = list(avoid_regions or [])
    def overlaps(a: dict[str, float], b: dict[str, float]) -> bool:
        return not (a["x"] + a["w"] <= b["x"] or b["x"] + b["w"] <= a["x"] or a["y"] + a["h"] <= b["y"] or b["y"] + b["h"] <= a["y"])
    transition_seconds = float(policy.get("transitionSeconds", 0.25))
    def clear(r: dict[str, float], start: float, end: float) -> bool:
        # Validate the full dwell plus both fade envelopes; checking only a
        # sampled frame at .5s/2s misses the real collision at the handoff.
        check_start, check_end = max(0.0, start - transition_seconds), min(duration_seconds, end + transition_seconds)
        for t in text_rects:
            t_start, t_end = float(t.get("startSeconds", 0)), float(t.get("endSeconds", duration_seconds))
            if t_start < check_end and t_end > check_start and overlaps(r, t):
                return False
        for t in forbidden:
            t_start, t_end = float(t.get("startSeconds", 0)), float(t.get("endSeconds", duration_seconds))
            if t_start < end and t_end > start and overlaps(r, t):
                return False
        return True
    max_relocations = max(0, int(policy.get("maxRelocations", 1)))
    min_dwell = float(policy.get("minDwellSeconds", 6))
    requested_count = min(1 + max_relocations, int(duration_seconds // min_dwell))
    count = max(1, requested_count)
    dwell = duration_seconds / count
    # Validate each candidate against its complete proposed dwell. If a candidate
    # fails, reject it and try the next one; never emit an unsafe fallback.
    chosen = []
    for i in range(count):
        start, end = i * dwell, (i + 1) * dwell
        zone = next((s for s in candidates if s not in chosen and clear(rects[s], start, end)), None)
        if zone is None:
            break
        chosen.append(zone)
    if len(chosen) < count:
        count = len(chosen)
        if not count:
            return []
        dwell = duration_seconds / count
        # Revalidate after expansion: a longer dwell can newly intersect text or
        # avoid regions. Keep only the safe prefix and record why slots were hidden.
        while chosen and any(
            not clear(rects[zone], i * dwell, (i + 1) * dwell)
            for i, zone in enumerate(chosen)
        ):
            chosen.pop()
            count = len(chosen)
            if count:
                dwell = duration_seconds / count
    transition = str(policy.get("transition", "relocate-fade"))
    return [{"zone": zone, "startSeconds": i * dwell, "endSeconds": (i + 1) * dwell,
             "rect": rects[zone], "transition": transition if i else "fade-in",
             "reason": "seeded safe candidate; non-top preferred" if zone != "upper-left" else "seeded fallback candidate"}
            for i, zone in enumerate(chosen)]

def canonical_numbers(value):
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Film Type profile contains a non-finite number")
        return int(value) if value.is_integer() else value
    if isinstance(value, list):
        return [canonical_numbers(v) for v in value]
    if isinstance(value, dict):
        return {k: canonical_numbers(v) for k, v in value.items()}
    return value


def resolve_design(raw: Any) -> dict[str, Any] | None:
    """Return a deterministic V2 snapshot; absent design returns None.

    NOTE: None here does NOT mean "render Legacy". Since 2026-09-08 the
    persian-footage compose boundary (PersianCompose._build_props) refuses
    absent/unversioned design outright — Film Type 2.12 is the default path and
    Legacy needs the explicit {"version": 2, "profile": "legacy"} opt-out.
    This library keeps its historical None return so other consumers
    (quiet-editorial resolution, validation) are unaffected.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("Persian design must be an object; only absent design selects Legacy")
    if "version" not in raw:
        if raw.get("profile") == "film-type":
            raise ValueError("Film Type requires explicit design.version=2; no Legacy fallback")
        return None
    version = raw.get("version")
    if version != 2:
        raise ValueError(f"Unsupported Persian design.version={version!r}; only explicit version 2 is supported")
    if raw.get("profile") == "film-type":
        if not isinstance(raw.get("seed"), str) or not raw["seed"].strip():
            raise ValueError("Film Type design.seed is required")
        pinned = any(key in raw for key in ("resolved", "profileVersion", "contentHash"))
        if pinned and not all(key in raw for key in ("resolved", "profileVersion", "contentHash")):
            raise ValueError("Film Type pinned design requires resolved, profileVersion and contentHash together")
        profile = raw["resolved"] if pinned else json.loads(FILM_TYPE_PROFILE_PATH.read_text(encoding="utf-8"))
        if not isinstance(profile, dict) or profile.get("profile") != "film-type":
            raise ValueError("Unsupported Film Type profile snapshot")
        supported = {
            "2.1.0": (1, SUPPORTED_FILM_TYPE_LEGACY_HASH),
            "2.2.0": (2, SUPPORTED_FILM_TYPE_POLISH_HASH),
            "2.3.0": (3, SUPPORTED_FILM_TYPE_REPAIR_HASH),
            "2.4.0": (4, SUPPORTED_FILM_TYPE_MOTION_HASH),
            "2.5.0": (5, SUPPORTED_FILM_TYPE_25_HASH),
            "2.6.0": (6, SUPPORTED_FILM_TYPE_26_HASH),
            "2.7.0": (7, SUPPORTED_FILM_TYPE_27_HASH),
            "2.8.0": (8, SUPPORTED_FILM_TYPE_28_HASH),
            "2.9.0": (9, SUPPORTED_FILM_TYPE_29_HASH),
            "2.10.0": (10, SUPPORTED_FILM_TYPE_210_HASH),
            "2.11.0": (11, SUPPORTED_FILM_TYPE_211_HASH),
            "2.12.0": (12, SUPPORTED_FILM_TYPE_HASH),
        }
        expected = supported.get(profile.get("profileVersion"))
        if expected is None or type(profile.get("layoutVersion")) is not int or profile["layoutVersion"] != expected[0]:
            raise ValueError("Unsupported Film Type profile snapshot")
        # New profile snapshots hash canonical JSON so they can be validated and
        # reused without reopening a mutable registry file on each render.
        profile = canonical_numbers(profile)
        encoded = json.dumps(profile, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        if digest != expected[1]:
            raise ValueError("Unsupported Film Type tokens; a new profile needs explicit versioned renderer support")
        if pinned and (raw["contentHash"] != digest or raw["profileVersion"] != profile["profileVersion"]):
            raise ValueError("Film Type pinned profile hash/version mismatch")
        return {"version": 2, "profile": "film-type", "seed": raw["seed"],
                "profileVersion": profile["profileVersion"], "contentHash": digest,
                "resolved": json.loads(encoded)}
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    profile_hash = hashlib.sha256(PROFILE_PATH.read_bytes()).hexdigest()
    profile_name = raw.get("profile", profile["profile"])
    if profile_name != profile["profile"]:
        raise ValueError(f"Unknown Persian V2 profile {profile_name!r}")
    if not isinstance(raw.get("seed"), str) or not raw["seed"].strip():
        raise ValueError("Persian V2 design.seed is required and must be a non-empty string")
    seed = raw["seed"]
    return {"version": 2, "profile": profile_name, "seed": seed,
            "profileVersion": profile["profileVersion"], "contentHash": profile_hash,
            "resolved": profile}

def validate_presentation(moment: dict[str, Any], index: int, *, profile: str = "quiet-editorial") -> None:
    p = moment.get("presentation") or {}
    if not isinstance(p, dict):
        raise ValueError(f"moment {index}: presentation must be an object")
    if "contrastStrength" in p:
        if profile != "film-type" or p["contrastStrength"] not in SUPPORTED_CONTRAST_STRENGTHS:
            raise ValueError(f"moment {index}: contrastStrength requires film-type and soft, standard or strong")
    treatment = p.get("treatment", "editorial")
    motion = p.get("motion", "soft-reveal")
    emphasis = p.get("emphasis", "none")
    if treatment not in SUPPORTED_TREATMENTS:
        raise ValueError(f"moment {index}: unsupported V2 treatment {treatment!r}; Stage B supports editorial and inline-statement")
    if motion not in SUPPORTED_MOTION:
        raise ValueError(f"moment {index}: unsupported V2 motion {motion!r}")
    if emphasis not in SUPPORTED_EMPHASIS:
        raise ValueError(f"moment {index}: unsupported V2 emphasis {emphasis!r}")
    contrast_mode = p.get("contrastMode", "dark")
    if contrast_mode not in SUPPORTED_CONTRAST_MODES:
        raise ValueError(f"moment {index}: unsupported V2 contrastMode {contrast_mode!r}")
    placement = p.get("placement", "auto")
    if placement not in SUPPORTED_PLACEMENTS:
        raise ValueError(f"moment {index}: unsupported V2 placement {placement!r}")
    if treatment == "inline-statement" and emphasis == "inline":
        heroes = [s for s in moment.get("segments", []) if s.get("role") == "hero"]
        if not heroes:
            raise ValueError(f"moment {index}: inline-statement requires a hero segment")

def prepare_v2(persian: dict[str, Any]) -> dict[str, Any] | None:
    design = resolve_design(persian.get("design"))
    if design is None:
        for i, moment in enumerate(persian.get("moments") or []):
            presentation = moment.get("presentation")
            if isinstance(presentation, dict) and "contrastStrength" in presentation:
                raise ValueError(f"moment {i}: contrastStrength requires explicit film-type design")
        return None
    moments = list(persian.get("moments") or [])
    for i, moment in enumerate(moments):
        if design["profile"] == "film-type" and "presentation" in moment and not isinstance(moment["presentation"], dict):
            raise ValueError(f"moment {i}: Film Type presentation must be an object")
        validate_presentation(moment, i, profile=design["profile"])
    return design
