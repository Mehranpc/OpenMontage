from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lib.persian_design import resolve_design

ROOT = Path(__file__).resolve().parents[2]
KAHROBA_SHA256 = "0223838295d7fb72a6dce709d234ef433d7815f66ed83b6959ae2f838f3d6711"
FILM_TYPE_215_SHA256 = "1952d3479b0c9b742255c17587635b2b496c75e773daecd60e6f7b322cb02a5f"


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


def test_issue32_archives_exact_215_profile_before_advancing_default() -> None:
    archived = ROOT / "styles" / "persian-footage" / "film-type-2.15.0.json"
    assert archived.is_file()
    assert hashlib.sha256(archived.read_bytes()).hexdigest() == FILM_TYPE_215_SHA256
    profile = json.loads(archived.read_text(encoding="utf-8"))
    assert profile["profileVersion"] == "2.15.0"
    assert profile["layoutVersion"] == 15
