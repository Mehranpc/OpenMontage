"""Every supported profile version must be handled everywhere it is dispatched.

2.9 was registered as a supported profile, archived, hashed and tested --
and still painted wrongly, because its version string was missing from the
version lists in ``components.tsx``. The comparison chains there are a series
of explicit equality checks, so an unlisted version does not fail loudly: it
falls through to the pre-2.4 painter, which sizes its field from a different
rule and draws a wash far outside the frame.

No token test can catch that. Comparing 2.10's tokens to 2.9's tokens says
nothing about whether any code branch reads them. So these tests read the
TypeScript sources as text and assert presence, which is exactly the property
that was violated.

Text matching is deliberately crude. It cannot prove a branch is *correct*;
it only proves the version was not forgotten. That is the failure that
actually happened, twice.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STYLES = ROOT / "styles" / "persian-footage"
FILM_TYPE_DIR = ROOT / "remotion-composer" / "src" / "persian" / "filmType"
LAYOUT_TS = FILM_TYPE_DIR / "layout.ts"
COMPONENTS_TSX = FILM_TYPE_DIR / "components.tsx"

#: Versions from 2.4.0 on are painted by an explicitly versioned branch in
#: components.tsx. 2.1-2.3 intentionally share the original painter and are
#: therefore not required to appear there.
EXPLICIT_PAINT_FROM = (2, 4, 0)

_VERSION_IN_FILENAME = re.compile(r"^film-type-(\d+\.\d+\.\d+)\.json$")
_PROFILE_VERSION_UNION = re.compile(
    r"profileVersion:\s*((?:\"\d+\.\d+\.\d+\"\s*\|\s*)*\"\d+\.\d+\.\d+\")"
)
_QUOTED_VERSION = re.compile(r"\"(\d+\.\d+\.\d+)\"")


def parse(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def registered_versions() -> dict[str, Path]:
    """Every profile snapshot the repository ships, by version.

    The default profile is whatever ``film-type.json`` currently declares, so
    this stays correct across a version bump without being edited.
    """
    found: dict[str, Path] = {}
    for path in sorted(STYLES.glob("film-type*.json")):
        match = _VERSION_IN_FILENAME.match(path.name)
        if match:
            found[match.group(1)] = path
            continue
        if path.name == "film-type.json":
            profile = json.loads(path.read_text(encoding="utf-8"))
            found[profile["profileVersion"]] = path
    return found


class FilmTypeVersionCoverage(unittest.TestCase):
    def setUp(self) -> None:
        self.versions = registered_versions()
        self.layout = LAYOUT_TS.read_text(encoding="utf-8")
        self.components = COMPONENTS_TSX.read_text(encoding="utf-8")
        self.assertTrue(self.versions, "no Film Type profile snapshots were found")

    def test_every_snapshot_declares_the_version_in_its_filename(self) -> None:
        for version, path in self.versions.items():
            with self.subTest(version=version):
                profile = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(profile["profileVersion"], version)
                self.assertEqual(profile["profile"], "film-type")
                self.assertIsInstance(profile["layoutVersion"], int)

    def test_layout_versions_are_dense_and_unique(self) -> None:
        """layoutVersion must be a 1..N sequence with no gaps or duplicates.

        The bridge validates ``layoutVersion`` against a hard-coded map, so a
        skipped or reused number silently accepts the wrong snapshot.
        """
        layout_versions = sorted(
            json.loads(path.read_text(encoding="utf-8"))["layoutVersion"]
            for path in self.versions.values()
        )
        self.assertEqual(
            layout_versions,
            list(range(1, len(layout_versions) + 1)),
            "layoutVersion values must be a dense 1..N sequence",
        )

    def test_typescript_union_lists_every_registered_version(self) -> None:
        union = _PROFILE_VERSION_UNION.search(self.layout)
        self.assertIsNotNone(union, "could not find the profileVersion union in layout.ts")
        declared = set(_QUOTED_VERSION.findall(union.group(1)))
        self.assertEqual(
            declared,
            set(self.versions),
            "the profileVersion union in layout.ts must match the shipped snapshots",
        )

    def test_layout_dispatches_every_registered_version(self) -> None:
        for version in self.versions:
            with self.subTest(version=version):
                self.assertIn(
                    f'"{version}"',
                    self.layout,
                    f"layout.ts never mentions {version}; it cannot be dispatched",
                )

    def test_layout_pins_a_hash_for_every_registered_version(self) -> None:
        """prepareFilmTypeProps refuses any version absent from its hash map."""
        for version in self.versions:
            with self.subTest(version=version):
                self.assertRegex(
                    self.layout,
                    rf'"{re.escape(version)}"\s*:\s*"[0-9a-f]64"',
                    f"layout.ts has no expectedHash entry for {version}",
                )

    def test_components_paint_every_explicitly_painted_version(self) -> None:
        """The exact omission that made 2.9 fall through to the old painter."""
        for version in self.versions:
            if parse(version) < EXPLICIT_PAINT_FROM:
                continue
            with self.subTest(version=version):
                self.assertIn(
                    f'"{version}"',
                    self.components,
                    f"components.tsx never mentions {version}, so it would fall "
                    "through to the pre-2.4 painter",
                )

    def test_newest_version_is_the_default_profile(self) -> None:
        """The unpinned default must be the highest registered version.

        A bump that archives the old profile but forgets to replace
        ``film-type.json`` would otherwise ship the previous look silently.
        """
        newest = max(self.versions, key=parse)
        default = json.loads((STYLES / "film-type.json").read_text(encoding="utf-8"))
        self.assertEqual(default["profileVersion"], newest)


if __name__ == "__main__":
    unittest.main(verbosity=2)
