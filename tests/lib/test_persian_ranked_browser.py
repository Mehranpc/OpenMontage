"""Opt-in real Remotion browser tests; no media/provider calls.
Run with OPENMONTAGE_BROWSER_TESTS=1 python -m unittest tests.lib.test_persian_ranked_browser
Requires the composer's installed dependencies and Chromium. A skip is not a pass.
"""
import copy
import os
from pathlib import Path
import unittest
from lib.persian_design import resolve_design
from lib.persian_film_type import prepare_film_type_props

ROOT = Path(__file__).resolve().parents[2]

@unittest.skipUnless(os.environ.get('OPENMONTAGE_BROWSER_TESTS') == '1', 'opt-in real browser suite')
class RankedBrowserContracts(unittest.TestCase):
    def props(self, text='«ببخشید» گفتن‌های همیشگی‌ت', format='vertical'):
        # Same complete shape persian_compose sends, including the beats key: the
        # prepass guard refuses any key the composition would have to default.
        return {'format':format, 'durationSeconds':20,
                'design':resolve_design({'version':2,'profile':'film-type','seed':'regression'}),
                'watermark':{'persianText':'','latinText':''},
                'typographicBeats':[],
                'shots':[{'id':'s','source':'unused.mp4','startSeconds':0,'endSeconds':20,'avoidRegions':[]}],
                'moments':[{'id':'m','kind':'statement','startSeconds':0,'endSeconds':15,
                            'presentation':{'placement':'auto'},
                            'segments':[{'role':'lead','text':'شاید باورت نشه اما این'},
                                        {'role':'hero','text':text},
                                        {'role':'tail','text':'ربطی به ادب نداره!'}]}]}
    def prepare(self, p):
        return prepare_film_type_props(p, ROOT/'remotion-composer')
    def test_ranked_long_copy_preserves_content_and_frozen_geometry(self):
        p=self.props(); before=copy.deepcopy(p)
        q=self.prepare(p)
        self.assertEqual(p,before)
        self.assertEqual(q['moments'][0]['segments'],p['moments'][0]['segments'])
        rows=q['filmType']['moments']['m']['rows']
        self.assertLessEqual(len([r for r in rows if r['role']=='hero']),2)
        self.assertEqual(self.prepare(q)['filmType'],q['filmType'])
        rect=q['filmType']['moments']['m']['rect']
        self.assertGreaterEqual(rect['x'],.08)
        self.assertGreaterEqual(rect['y'],.14)
        self.assertLessEqual(rect['x']+rect['w'],.84+1e-8)
        self.assertLessEqual(rect['y']+rect['h']+18/1920,.65+1e-8)
        self.assertEqual(q['filmType']['moments']['m']['strength'],'strong')
    def test_incomplete_props_are_refused_not_silently_completed(self):
        p=self.props();p.pop('typographicBeats')
        with self.assertRaisesRegex(ValueError,'unexpectedly changed typographicBeats'):self.prepare(p)
    def test_field_is_per_row_and_bounded_by_the_frame(self):
        q=self.prepare(self.props())
        layout=q['filmType']['moments']['m']
        field=q['design']['resolved']['contrast']['diffuseField']
        self.assertTrue(field['perRow'])
        # Every row carries the geometry the per-row field is drawn from, and no
        # row's field can be wider than the frame it sits in.
        for row in layout['rows']:
            self.assertGreater(row['widthPx'],0)
            self.assertLessEqual(max(field['minRadiusPx'],row['widthPx']*field['radiusScale']),1080/2+1e-8)
            self.assertGreater(row['baselinePx'],0)
    def test_formats_and_phrase_variants(self):
        for fmt in ['vertical','landscape']:
            for text in ['یه سپره','بی‌آزار و دوست‌داشتنی','قبل از شروع کار','هیچ‌وقت عذرخواهی نکن!']:
                with self.subTest(format=fmt,text=text):
                    q=self.prepare(self.props(text,fmt))
                    self.assertTrue(q['filmType']['moments']['m']['rows'])
    def test_missing_reviews_refused_even_for_explicit_placement(self):
        p=self.props();p['shots'][0].pop('avoidRegions');p['moments'][0]['presentation']['placement']='upper-right'
        with self.assertRaisesRegex(ValueError,'review'):self.prepare(p)
    def test_obstructed_frame_refused(self):
        p=self.props();p['shots'][0]['avoidRegions']=[{'x':0,'y':0,'w':1,'h':1}]
        with self.assertRaisesRegex(ValueError,'no readable'):self.prepare(p)
    def test_stale_layout_refused(self):
        p=self.prepare(self.props());p['filmType']['inputHash']='stale'
        with self.assertRaisesRegex(ValueError,'stale'):self.prepare(p)

if __name__ == '__main__':
    unittest.main()
