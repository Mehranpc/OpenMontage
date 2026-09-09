"""Pinned profile regressions; actual browser bounds also asserted in opt-in suite."""
import json
from pathlib import Path
import unittest
from lib.persian_design import resolve_design, SUPPORTED_FILM_TYPE_27_HASH
ROOT=Path(__file__).resolve().parents[2]
class ReelsSafeAreaContracts(unittest.TestCase):
    def test_default_strong_preserves_diffuse_appearance(self):
        p=resolve_design({'version':2,'profile':'film-type','seed':'test'})['resolved']
        old=json.loads((ROOT/'styles/persian-footage/film-type-2.7.0.json').read_text())
        self.assertEqual(p['contrast']['defaultStrength'],'strong')
        for key in ('diffuseField','darkField','lightField','strengths'):
            self.assertEqual(p['contrast'][key],old['contrast'][key])
        self.assertEqual(p['typography'],old['typography'])
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

if __name__=='__main__':unittest.main()
