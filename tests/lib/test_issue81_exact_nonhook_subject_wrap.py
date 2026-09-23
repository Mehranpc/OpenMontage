"""Real-browser regression for the Issue 81 Film Type geometry recovery."""
import copy
import os
import unittest

from lib.persian_brand import exact_text_record


@unittest.skipUnless(os.environ.get("OPENMONTAGE_BROWSER_TESTS") == "1", "requires Chromium")
class ExactNonHookSubjectWrap(unittest.TestCase):
    def test_exact_figure_wraps_without_changing_subject_regions_or_copy(self):
        from tests.lib.test_persian_ranked_browser import RankedBrowserContracts
        browser = RankedBrowserContracts()
        props = browser.props()
        props["moments"] = [{
            "id": "sample", "kind": "figure", "startSeconds": 13.6, "endSeconds": 16.65,
            "exactText": exact_text_record("در این مطالعه، ۵۴۳ نفر"),
            "segments": [{"role": "lead", "text": "در این مطالعه،"},
                         {"role": "hero", "text": "۵۴۳ نفر"}],
        }]
        props["shots"] = [
            {"id": "before", "source": "unused.mp4", "startSeconds": 10.4, "endSeconds": 15.6,
             "avoidRegions": [
                 {"x": .37, "y": .24, "w": .32, "h": .27, "priority": "hard"},
                 {"x": .57, "y": .47, "w": .30, "h": .25, "priority": "hard"},
             ]},
            {"id": "after", "source": "unused.mp4", "startSeconds": 15.6, "endSeconds": 20,
             "avoidRegions": [
                 {"x": .26, "y": .27, "w": .24, "h": .22, "priority": "hard"},
                 {"x": .24, "y": .41, "w": .25, "h": .20, "priority": "hard"},
             ]},
        ]
        original = copy.deepcopy(props)
        layout = browser.prepare(props)["filmType"]["moments"]["sample"]
        self.assertEqual(props, original)
        self.assertTrue(layout.get("subjectWrap"))
        self.assertEqual(layout["placement"], "subject-wrap")
        self.assertEqual(" ".join(row["text"] for row in layout["rows"]), "در این مطالعه، ۵۴۳ نفر")
        self.assertEqual(layout["subjectSafety"], "checked-against-supplied-regions")

        without_exact = copy.deepcopy(props)
        del without_exact["moments"][0]["exactText"]
        with self.assertRaisesRegex(ValueError, "no curated adaptive editorial recipe fits"):
            browser.prepare(without_exact)
