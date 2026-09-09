"""Opt-in real Remotion browser tests; no media/provider calls.
Run with OPENMONTAGE_BROWSER_TESTS=1 python -m unittest tests.lib.test_persian_ranked_browser
Requires the composer's installed dependencies and Chromium. A skip is not a pass.
"""
import copy
import json
import os
from pathlib import Path
import unittest
from lib.persian_design import resolve_design, SUPPORTED_FILM_TYPE_28_HASH
from lib.persian_film_type import prepare_film_type_props

ROOT = Path(__file__).resolve().parents[2]
FRAME = {'vertical': (1080, 1920), 'landscape': (1920, 1080)}

@unittest.skipUnless(os.environ.get('OPENMONTAGE_BROWSER_TESTS') == '1', 'opt-in real browser suite')
class RankedBrowserContracts(unittest.TestCase):
    def props(self, text='«ببخشید» گفتن‌های همیشگی‌ت', format='vertical', design=None):
        # Same complete shape persian_compose sends, including the beats key: the
        # prepass guard refuses any key the composition would have to default.
        return {'format':format, 'durationSeconds':20,
                'design':design or resolve_design({'version':2,'profile':'film-type','seed':'regression'}),
                'watermark':{'persianText':'','latinText':''},
                'typographicBeats':[],
                'shots':[{'id':'s','source':'unused.mp4','startSeconds':0,'endSeconds':20,'avoidRegions':[]}],
                'moments':[{'id':'m','kind':'statement','startSeconds':0,'endSeconds':15,
                            'presentation':{'placement':'auto'},
                            'segments':[{'role':'lead','text':'شاید باورت نشه اما این'},
                                        {'role':'hero','text':text},
                                        {'role':'tail','text':'ربطی به ادب نداره!'}]}]}
    def pinned_28(self):
        profile=json.loads((ROOT/'styles/persian-footage/film-type-2.8.0.json').read_text(encoding='utf-8'))
        return {'version':2,'profile':'film-type','seed':'regression','profileVersion':'2.8.0',
                'contentHash':SUPPORTED_FILM_TYPE_28_HASH,'resolved':profile}
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
    def test_per_row_field_is_smaller_than_the_block_field_and_frame_bounded(self):
        for fmt in ['vertical','landscape']:
            with self.subTest(format=fmt):
                q=self.prepare(self.props(format=fmt))
                layout=q['filmType']['moments']['m']
                field=q['design']['resolved']['contrast']['diffuseField']
                width,height=FRAME[fmt]
                self.assertTrue(field['perRow'])
                self.assertGreater(field['rowPaddingPx'],0)
                pad=field['rowPaddingPx']
                # 2.9 sized one ellipse from the whole block; 2.10 must never draw
                # a row field larger than that, and the painted radius is clamped
                # to the frame so the shadow cannot leave the video.
                block=max(field['minRadiusPx'],layout['widthPx']*1.15)
                for row in layout['rows']:
                    self.assertGreater(row['widthPx'],0)
                    self.assertGreater(row['baselinePx'],0)
                    raw=max(field['minRadiusPx'],(row['widthPx']+2*pad)*field['radiusScale'])
                    self.assertLessEqual(raw,block+1e-8)
                    self.assertLessEqual(min(raw,width/2),width/2+1e-8)
                self.assertLessEqual(layout['heightPx'],height)
    def test_formats_and_phrase_variants(self):
        for fmt in ['vertical','landscape']:
            for text in ['یه سپره','بی‌آزار و دوست‌داشتنی','قبل از شروع کار','هیچ‌وقت عذرخواهی نکن!']:
                with self.subTest(format=fmt,text=text):
                    q=self.prepare(self.props(text,fmt))
                    self.assertTrue(q['filmType']['moments']['m']['rows'])
    def test_default_profile_ignores_regions_and_reports_not_checked(self):
        # 2.9 turned subject-region enforcement OFF on purpose: the only hard
        # geometric contract left is the platform safe area. The opt-out must be
        # visible in the output, never silently claimed as verified.
        for label,mutate in [('missing reviews',lambda p:p['shots'][0].pop('avoidRegions')),
                             ('full-frame review',lambda p:p['shots'][0].update(avoidRegions=[{'x':0,'y':0,'w':1,'h':1}]))]:
            with self.subTest(case=label):
                p=self.props();mutate(p)
                layout=self.prepare(p)['filmType']['moments']['m']
                self.assertEqual(layout['subjectSafety'],'not-checked')
                rect=layout['rect']
                self.assertGreaterEqual(rect['x'],.08)
                self.assertGreaterEqual(rect['y'],.14)
                self.assertLessEqual(rect['y']+rect['h']+18/1920,.65+1e-8)
    def test_28_pin_still_refuses_missing_reviews_and_obstructed_frames(self):
        p=self.props(design=self.pinned_28());p['shots'][0].pop('avoidRegions')
        p['moments'][0]['presentation']['placement']='upper-right'
        with self.assertRaisesRegex(ValueError,'review'):self.prepare(p)
        p=self.props(design=self.pinned_28());p['shots'][0]['avoidRegions']=[{'x':0,'y':0,'w':1,'h':1}]
        with self.assertRaisesRegex(ValueError,'no readable'):self.prepare(p)
    def test_stale_layout_refused(self):
        p=self.prepare(self.props());p['filmType']['inputHash']='stale'
        with self.assertRaisesRegex(ValueError,'stale'):self.prepare(p)

if __name__ == '__main__':
    unittest.main()
