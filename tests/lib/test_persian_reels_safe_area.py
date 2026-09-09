"""Pinned profile regressions; actual browser bounds also asserted in opt-in suite."""
import json
from pathlib import Path
import unittest
from lib.persian_design import resolve_design, SUPPORTED_FILM_TYPE_27_HASH
ROOT=Path(__file__).resolve().parents[2]
class ReelsSafeAreaContracts(unittest.TestCase):
    def test_default_strong_keeps_soft_field_no_darker_than_baseline(self):
        p=resolve_design({'version':2,'profile':'film-type','seed':'test'})['resolved']
        old=json.loads((ROOT/'styles/persian-footage/film-type-2.7.0.json').read_text())
        self.assertEqual(p['contrast']['defaultStrength'],'strong')
        # Ink/field colours and type scale stay frozen: the look must not drift.
        for key in ('darkField','lightField'):
            self.assertEqual(p['contrast'][key],old['contrast'][key])
        self.assertEqual(p['typography'],old['typography'])
        # The field may only get softer/smaller than the 2.7 baseline, never darker
        # or larger, and it must stay a diffuse ellipse (no plate, no frame grade).
        for key,value in p['contrast']['strengths'].items():
            self.assertLessEqual(value,old['contrast']['strengths'][key])
        field,base=p['contrast']['diffuseField'],old['contrast']['diffuseField']
        self.assertLessEqual(field['radiusScale'],base['radiusScale'])
        self.assertLessEqual(field['minRadiusPx'],base['minRadiusPx'])
        self.assertEqual(field['maxSubjectAlpha'],base['maxSubjectAlpha'])
        self.assertEqual(p['contrast']['footageGrade'],'none')
        # 2.10 scopes the field to each measured row instead of the whole block.
        self.assertTrue(field['perRow'])
        self.assertGreater(field['rowPaddingPx'],0)
    def test_reels_text_and_brand_share_safe_bounds(self):
        p=resolve_design({'version':2,'profile':'film-type','seed':'test'})['resolved']
        text=p['formats']['vertical']['safeArea'];brand=p['watermark']['safeAreas']['vertical']
        for key,value in {'top':.14,'bottom':.35,'left':.08,'right':.16}.items():
            self.assertEqual(text[key],value);self.assertEqual(brand[key],value)
    def test_landscape_geometry_unchanged(self):
        p=resolve_design({'version':2,'profile':'film-type','seed':'test'})['resolved']
        old=json.loads((ROOT/'styles/persian-footage/film-type-2.7.0.json').read_text())
        self.assertEqual(p['formats']['landscape'],old['formats']['landscape'])
        self.assertEqual(p['watermark']['safeAreas']['landscape'],old['watermark']['safeAreas']['landscape'])
    def test_old_pin_keeps_old_safe_area_and_strength(self):
        old=json.loads((ROOT/'styles/persian-footage/film-type-2.7.0.json').read_text())
        pin={'version':2,'profile':'film-type','seed':'test','profileVersion':'2.7.0','resolved':old,'contentHash':SUPPORTED_FILM_TYPE_27_HASH}
        self.assertEqual(resolve_design(pin),pin)
        self.assertEqual(old['formats']['vertical']['safeArea']['bottom'],.2)
        self.assertEqual(old['contrast']['defaultStrength'],'standard')
        self.assertNotIn('perRow',old['contrast']['diffuseField'])

if __name__=='__main__':unittest.main()
