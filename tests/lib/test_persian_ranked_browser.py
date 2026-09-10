"""Opt-in real Remotion browser tests; no media/provider calls.
Run with OPENMONTAGE_BROWSER_TESTS=1 python -m unittest tests.lib.test_persian_ranked_browser
Requires the composer's installed dependencies and Chromium. A skip is not a pass.
"""
import copy
import json
import os
from pathlib import Path
import unittest
from lib.persian_brand import exact_text_record
from lib.persian_design import resolve_design, SUPPORTED_FILM_TYPE_28_HASH, SUPPORTED_FILM_TYPE_211_HASH
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
    def pinned_211(self):
        profile=json.loads((ROOT/'styles/persian-footage/film-type-2.11.0.json').read_text(encoding='utf-8'))
        return {'version':2,'profile':'film-type','seed':'regression','profileVersion':'2.11.0',
                'contentHash':SUPPORTED_FILM_TYPE_211_HASH,'resolved':profile}
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
    def test_default_profile_requires_review_and_enforces_regions(self):
        p=self.props();p['shots'][0].pop('avoidRegions')
        with self.assertRaisesRegex(ValueError,'review'):self.prepare(p)
        region={'x':0.55,'y':0.45,'w':0.45,'h':0.55}
        p=self.props();p['shots'][0]['avoidRegions']=[region]
        layout=self.prepare(p)['filmType']['moments']['m']
        self.assertEqual(layout['subjectSafety'],'checked-against-supplied-regions')
        self.assertFalse(self._overlaps(layout['rect'],region))
    def test_default_profile_refuses_the_reviewed_m1_face_collision(self):
        p=self.props();p['moments'][0]['presentation']['placement']='upper-right'
        p['shots'][0]['avoidRegions']=[{'x':0.27,'y':0.28,'w':0.39,'h':0.21}]
        with self.assertRaisesRegex(ValueError,'no readable'):self.prepare(p)
    def test_28_pin_still_refuses_missing_reviews_and_obstructed_frames(self):
        p=self.props(design=self.pinned_28());p['shots'][0].pop('avoidRegions')
        p['moments'][0]['presentation']['placement']='upper-right'
        with self.assertRaisesRegex(ValueError,'review'):self.prepare(p)
        p=self.props(design=self.pinned_28());p['shots'][0]['avoidRegions']=[{'x':0,'y':0,'w':1,'h':1}]
        with self.assertRaisesRegex(ValueError,'no readable'):self.prepare(p)
    @staticmethod
    def _overlaps(a,b):
        return a['x']<b['x']+b['w'] and a['x']+a['w']>b['x'] and a['y']<b['y']+b['h'] and a['y']+a['h']>b['y']
    def test_28_pin_moves_text_out_of_a_reviewed_region(self):
        # Where the contract provides enforcement (2.8), a reviewed region moves
        # approved text: the lower-right default no longer fits, so the moment
        # lands upper-right with a rect clear of the region.
        region={'x':0.55,'y':0.45,'w':0.45,'h':0.55}
        p=self.props(design=self.pinned_28());p['shots'][0]['avoidRegions']=[region]
        layout=self.prepare(p)['filmType']['moments']['m']
        self.assertEqual(layout['subjectSafety'],'checked-against-supplied-regions')
        self.assertFalse(self._overlaps(layout['rect'],region))
    def test_211_text_ignores_regions_by_design(self):
        # 2.11 deliberately never moves approved text for a region: the same
        # region that relocates 2.8 text must leave the 2.11 rect bit-identical,
        # with the opt-out still reported as not-checked.
        region={'x':0.55,'y':0.45,'w':0.45,'h':0.55}
        plain=self.prepare(self.props(design=self.pinned_211()))['filmType']['moments']['m']['rect']
        p=self.props(design=self.pinned_211());p['shots'][0]['avoidRegions']=[region]
        layout=self.prepare(p)['filmType']['moments']['m']
        self.assertEqual(layout['subjectSafety'],'not-checked')
        self.assertEqual(layout['rect'],plain)
    def test_211_watermark_prefers_slots_clear_of_reviewed_regions(self):
        # 2.11 consumes reviewed regions as watermark-slot preference: with the
        # text upper-right and the upper band covered for the whole film, every
        # planned slot must avoid the region (and a plan must still exist).
        region={'x':0,'y':0.10,'w':1,'h':0.15}
        p=self.props(design=self.pinned_211());p['watermark']={'persianText':'برند','latinText':'Brand'}
        p['moments'][0]['presentation']['placement']='upper-right'
        p['shots'][0]['avoidRegions']=[region]
        plan=self.prepare(p)['watermarkPlan']
        self.assertTrue(plan)
        for slot in plan:
            with self.subTest(slot=slot['zone']):
                self.assertFalse(self._overlaps(slot['rect'],region))
    def test_212_suppresses_brand_instead_of_grouping_it_with_m5(self):
        p=self.props();p['durationSeconds']=47
        p['shots']=[{'id':'s','source':'unused.mp4','startSeconds':0,'endSeconds':47,
                     'avoidRegions':[{'x':0.05,'y':0.10,'w':0.90,'h':0.20}]}]
        p['moments']=[{'id':'m5','kind':'statement','startSeconds':42.47,'endSeconds':46.97,
                       'presentation':{'placement':'lower-right','motion':'cut-in'},
                       'segments':[{'role':'lead','text':'ولی برای «بودنت»'},
                                   {'role':'hero','text':'هیچ‌وقت عذرخواهی نکن!'}]}]
        p['watermark']={'persianText':'طریقت تسلیم','latinText':'Pathway_of_Surrender'}
        q=self.prepare(p);layout=q['filmType']['moments']['m5'];lockup=q['filmType']['lockup']
        clearance=max(q['design']['resolved']['watermark']['minTextClearancePx'],lockup['heightPx'])
        width,height=FRAME['vertical']
        for slot in q['watermarkPlan']:
            if slot['startSeconds']<46.97 and slot['endSeconds']>42.47:
                expanded={'x':slot['rect']['x']-clearance/width,'y':slot['rect']['y']-clearance/height,
                          'w':slot['rect']['w']+2*clearance/width,'h':slot['rect']['h']+2*clearance/height}
                self.assertFalse(self._overlaps(expanded,layout['rect']))
        self.assertFalse(any(s['startSeconds']<46.97 and s['endSeconds']>42.47 for s in q['watermarkPlan']))
        self.assertTrue(any('watermark-suppressed-for-text-clearance' in w for w in q['filmType']['warnings']))
    def test_strict_rows_preserve_arabic_codepoints_quotes_and_zwnj(self):
        exact="مي‌روم؛ “همین”"
        p=self.props();p['moments']=[{
            'id':'strict','kind':'statement','startSeconds':0,'endSeconds':15,
            'presentation':{'placement':'auto'},
            'segments':[{'role':'hero','text':exact}],
            'exactText':exact_text_record(exact),
        }]
        q=self.prepare(p)
        rows=q['filmType']['moments']['strict']['rows']
        self.assertEqual(' '.join(row['text'] for row in rows),exact)
        self.assertEqual(q['moments'][0]['segments'][0]['text'],exact)
        self.assertEqual(q['moments'][0]['exactText'],exact_text_record(exact))

    def test_strict_digest_is_rechecked_in_the_renderer(self):
        exact="مي‌روم؛ “همین”"
        p=self.props();p['moments']=[{
            'id':'strict','kind':'statement','startSeconds':0,'endSeconds':15,
            'presentation':{'placement':'auto'},
            'segments':[{'role':'hero','text':exact}],
            'exactText':{**exact_text_record(exact),'sha256':'0'*64},
        }]
        with self.assertRaisesRegex(ValueError,'sha256'):self.prepare(p)

    def test_stale_layout_refused(self):
        p=self.prepare(self.props());p['filmType']['inputHash']='stale'
        with self.assertRaisesRegex(ValueError,'stale'):self.prepare(p)

if __name__ == '__main__':
    unittest.main()
