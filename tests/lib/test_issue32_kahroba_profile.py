from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lib.persian_design import resolve_design

ROOT = Path(__file__).resolve().parents[2]
KAHROBA_SHA256 = "0223838295d7fb72a6dce709d234ef433d7815f66ed83b6959ae2f838f3d6711"
FILM_TYPE_215_SHA256 = "810eeccad994366588cd76448d6493a58f1b01cea5692c4f2306b4b5c79c23e7"


def test_issue32_active_profile_is_versioned_kahroba_editorial_system() -> None:
    design = resolve_design({"version": 2, "profile": "film-type", "seed": "issue32"})
    assert design is not None
    profile = design["resolved"]

    assert design["profileVersion"] == "2.16.0"
    assert profile["layoutVersion"] == 16
    editorial = profile["typography"]["editorial"]
    assert editorial["fontFamily"] == "KahrobaEditorial"
    assert editorial["assetPath"] == "fonts/kahroba/Kahroba-BL-LC.woff2"
    assert editorial["assetSha256"] == KAHROBA_SHA256
    assert editorial["weight"] == 900
    assert editorial["supportInk"] == "#FFFFFF"
    assert editorial["semanticAccent"] == "#FFEA00"
    assert editorial["allowedAlignments"] == ["right", "center"]
    assert editorial["maxHookLines"] == 5
    assert editorial["truncate"] is False
    assert "underline" not in editorial["decorativeAccents"]


def test_issue32_archives_exact_215_profile_before_advancing_default() -> None:
    archived = ROOT / "styles" / "persian-footage" / "film-type-2.15.0.json"
    assert archived.is_file()
    assert hashlib.sha256(archived.read_bytes()).hexdigest() == FILM_TYPE_215_SHA256
    profile = json.loads(archived.read_text(encoding="utf-8"))
    assert profile["profileVersion"] == "2.15.0"
    assert profile["layoutVersion"] == 15


def test_issue32_complete_hook_uses_browser_fit_not_legacy_reading_or_char_ceiling() -> None:
    from lib.persian_moments import audit_moments, build_moments

    hook = "بزرگ‌ترین اشتباه دربارهٔ بازی‌های ویدیویی اینه که فکر کنیم فقط وقت تلف کردنه!"
    built = build_moments([{
        "id": "hook-issue32",
        "kind": "hook",
        "purpose": "hook-pattern-interrupt",
        "startSeconds": 0.0,
        "endSeconds": 4.9,
        "segments": [{"role": "hero", "text": hook, "accentWords": ["وقت", "تلف", "کردنه!"]}],
    }])
    audit = audit_moments(
        built,
        duration_seconds=47.4,
        v2=True,
        adaptive_pixel_typography=True,
        simultaneous_hook_typography=True,
    )
    assert audit.problems == []
