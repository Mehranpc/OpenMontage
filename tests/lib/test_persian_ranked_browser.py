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
from lib.persian_design import resolve_design, SUPPORTED_FILM_TYPE_28_HASH, SUPPORTED_FILM_TYPE_211_HASH, SUPPORTED_FILM_TYPE_212_HASH, SUPPORTED_FILM_TYPE_HASH
from lib.persian_film_type import FilmTypePreflightError, prepare_film_type_props

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
                'typographicBeats':[], 'captionMode':'sidecar_only', 'captions':[],
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
    def pinned_212(self):
        profile=json.loads((ROOT/'styles/persian-footage/film-type-2.12.0.json').read_text(encoding='utf-8'))
        return {'version':2,'profile':'film-type','seed':'regression','profileVersion':'2.12.0',
                'contentHash':SUPPORTED_FILM_TYPE_212_HASH,'resolved':profile}
    def pinned_214(self):
        profile=json.loads((ROOT/'styles/persian-footage/film-type-2.14.0.json').read_text(encoding='utf-8'))
        return {'version':2,'profile':'film-type','seed':'regression','profileVersion':'2.14.0',
                'contentHash':SUPPORTED_FILM_TYPE_HASH,'resolved':profile}
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
        safe=q['design']['resolved']['formats']['vertical']['safeArea']
        left=safe.get('left',safe['side']);right=safe.get('right',safe['side'])
        self.assertGreaterEqual(rect['x'],left)
        self.assertGreaterEqual(rect['y'],safe['top'])
        self.assertLessEqual(rect['x']+rect['w'],1-right+1e-8)
        self.assertLessEqual(rect['y']+rect['h']+18/1920,1-safe['bottom']+1e-8)
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
    def test_default_216_requires_review_and_moves_typography_off_reviewed_subjects(self):
        p=self.props();p['shots'][0].pop('avoidRegions')
        with self.assertRaisesRegex(ValueError,'review'):self.prepare(p)
        region={'x':0.55,'y':0.45,'w':0.45,'h':0.55}
        p=self.props();p['shots'][0]['avoidRegions']=[region]
        q=self.prepare(p);layout=q['filmType']['moments']['m']
        self.assertEqual(q['shots'][0]['avoidRegions'],[region])
        self.assertEqual(layout['subjectSafety'],'checked-against-supplied-regions')
        self.assertFalse(self._overlaps(layout['rect'],region))
        self.assertFalse(any('2.16' in warning and 'subject-region enforcement is OFF' in warning for warning in q['filmType']['warnings']))
    def test_212_allows_typography_only_moment_without_fake_shot_review(self):
        p=self.props(text='نیاز به توجه')
        p['durationSeconds']=20
        p['captionMode']='sidecar_only'; p['captions']=[]
        p['shots']=[{'id':'s','source':'unused.mp4','startSeconds':0,'endSeconds':14,'avoidRegions':[]}]
        p['moments']=[{'id':'ending','kind':'statement','startSeconds':14,'endSeconds':20,'presentation':{'placement':'auto'},'segments':[{'role':'hero','text':'نیاز به توجه'}]}]
        p['typographicBeats']=[{'id':'end','startSeconds':14,'endSeconds':20}]
        q=self.prepare(p)
        layout=q['filmType']['moments']['ending']
        self.assertEqual(layout['subjectSafety'],'not-checked')
        self.assertTrue(layout['rows'])

    def test_default_216_explicit_placement_refuses_reviewed_face_collision(self):
        p=self.props();p['moments'][0]['presentation']['placement']='upper-right'
        region={'x':0.20,'y':0.14,'w':0.80,'h':0.51}
        p['shots'][0]['avoidRegions']=[region]
        with self.assertRaisesRegex(ValueError,'no curated adaptive editorial recipe fits|blocked by region'):
            self.prepare(p)
    def test_default_216_hook_respects_reviewed_subject_region(self):
        p=self.props();p['durationSeconds']=20
        p['moments']=[{'id':'hook','kind':'hook','purpose':'hook-pattern-interrupt',
                       'startSeconds':0,'endSeconds':4.2,
                       'presentation':{'placement':'auto','motion':'cut-in','treatment':'editorial','recipeId':'editorial-hero-balanced'},
                       'segments':[{'role':'lead','text':'بعد از قرار اول،','semanticRole':'setup'},
                                   {'role':'hero','text':'کی پیام بدی بهتره؟','semanticRole':'subject_hero'}]}]
        region={'x':0.52,'y':0.14,'w':0.48,'h':0.28}
        p['shots'][0]['avoidRegions']=[region]
        q=self.prepare(p);layout=q['filmType']['moments']['hook']
        self.assertEqual(layout['subjectSafety'],'checked-against-supplied-regions')
        self.assertFalse(self._overlaps(layout['rect'],region))

    def test_default_216_soft_region_allows_measured_overlap_when_no_hard_collision(self):
        p=self.props()
        region={'x':0.04,'y':0.10,'w':0.92,'h':0.82,'priority':'soft'}
        p['shots'][0]['avoidRegions']=[region]
        q=self.prepare(p);layout=q['filmType']['moments']['m']
        self.assertEqual(layout['subjectSafety'],'checked-against-supplied-regions')
        self.assertTrue(self._overlaps(layout['rect'],region))
        self.assertTrue(any('soft-subject-overlap' in warning for warning in q['filmType']['warnings']))

    def test_default_216_auto_prefers_soft_clear_candidate_when_available(self):
        p=self.props(text='نیاز به توجه')
        soft={'x':0.48,'y':0.34,'w':0.52,'h':0.35,'priority':'soft'}
        p['shots'][0]['avoidRegions']=[soft]
        q=self.prepare(p);layout=q['filmType']['moments']['m']
        self.assertFalse(self._overlaps(layout['rect'],soft))

    def test_default_216_mixed_timed_regions_never_overlap_hard_region(self):
        p=self.props(text='نیاز به توجه')
        hard={'x':0.48,'y':0.10,'w':0.52,'h':0.28,'priority':'hard','startSeconds':0,'endSeconds':20}
        soft={'x':0.00,'y':0.35,'w':1.00,'h':0.55,'priority':'soft','startSeconds':0,'endSeconds':20}
        p['shots'][0]['avoidRegions']=[hard,soft]
        q=self.prepare(p);layout=q['filmType']['moments']['m']
        self.assertFalse(self._overlaps(layout['rect'],hard))

    def test_default_216_explicit_soft_region_does_not_refuse_layout(self):
        p=self.props(text='نیاز به توجه')
        p['moments'][0]['presentation']['placement']='lower-right'
        p['shots'][0]['avoidRegions']=[{'x':0.35,'y':0.35,'w':0.65,'h':0.60,'priority':'soft'}]
        q=self.prepare(p)
        self.assertEqual(q['filmType']['moments']['m']['placement'],'lower-right')

    def test_default_216_replace_sequence_stacks_alternatives_in_one_measured_slot(self):
        p=self.props();p['moments']=[{'id':'timing-options','kind':'statement',
                       'startSeconds':2,'endSeconds':7,
                       'presentation':{'placement':'auto','motion':'cut-in','sequenceMode':'replace'},
                       'segments':[{'role':'hero','text':'بلافاصله','revealAfterSeconds':0},
                                   {'role':'hero','text':'صبح روز بعد','revealAfterSeconds':1.5},
                                   {'role':'hero','text':'دو روز بعد','revealAfterSeconds':3.1}]}]
        q=self.prepare(p);rows=q['filmType']['moments']['timing-options']['rows']
        self.assertEqual([row['revealAfterSeconds'] for row in rows],[0,1.5,3.1])
        tops={round(row['baselinePx']-row['abovePx'],3) for row in rows}
        self.assertEqual(len(tops),1)
    def test_default_216_accumulate_sequence_keeps_prior_rows_visible_in_stack(self):
        p=self.props();p['moments']=[{'id':'timing-build','kind':'statement',
                       'startSeconds':2,'endSeconds':12,
                       'presentation':{'placement':'auto','motion':'cut-in','sequenceMode':'accumulate'},
                       'segments':[{'role':'hero','text':'بلافاصله','revealAfterSeconds':0},
                                   {'role':'hero','text':'صبح روز بعد','revealAfterSeconds':1.5},
                                   {'role':'hero','text':'دو روز بعد','revealAfterSeconds':3.1}]}]
        q=self.prepare(p);rows=q['filmType']['moments']['timing-build']['rows']
        self.assertEqual([row['revealAfterSeconds'] for row in rows],[0,1.5,3.1])
        tops={round(row['baselinePx']-row['abovePx'],3) for row in rows}
        self.assertEqual(len(tops),3)

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
    def test_212_pin_suppresses_brand_when_subject_regions_leave_no_legal_dwell(self):
        p=self.props(design=self.pinned_212());p['moments']=[]
        p['shots']=[{'id':'s','source':'unused.mp4','startSeconds':0,'endSeconds':20,
                     'avoidRegions':[{'x':0,'y':0,'w':1,'h':1}]}]
        p['watermark']={'persianText':'طریقت تسلیم','latinText':'Pathway_of_Surrender'}
        q=self.prepare(p)
        self.assertEqual(q['watermarkPlan'],[])
        self.assertTrue(any('watermark-suppressed-for-text-clearance' in w for w in q['filmType']['warnings']))

    def test_212_pin_suppresses_brand_instead_of_grouping_it_with_m5(self):
        p=self.props(design=self.pinned_212());p['durationSeconds']=47
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

    def test_214_context_hook_can_use_upper_center_negative_space(self):
        p=self.props(design=self.pinned_214());p['durationSeconds']=20
        p['shots']=[{'id':'s','source':'unused.mp4','startSeconds':0,'endSeconds':20,
                     'avoidRegions':[{'x':0.0,'y':0.36,'w':0.4,'h':0.52},
                                     {'x':0.76,'y':0.4,'w':0.24,'h':0.55}]}]
        p['moments']=[{'id':'hook','kind':'hook','purpose':'hook-pattern-interrupt',
                       'startSeconds':0,'endSeconds':4.15,
                       'presentation':{'placement':'auto','motion':'cut-in','treatment':'editorial'},
                       'segments':[{'role':'lead','text':'برای'},
                                   {'role':'hero','text':'هر کار خوبی'},
                                   {'role':'tail','text':'جایزه می‌دی؟'}]}]
        q=self.prepare(p)
        self.assertEqual(q['filmType']['moments']['hook']['placement'],'upper-center')
        self.assertEqual(q['filmType']['moments']['hook']['fieldPeakAlpha'],.46)

    def test_214_vertical_diversity_may_use_one_shorter_safe_dwell(self):
        p=self.props(design=self.pinned_214());p['durationSeconds']=47;p['moments']=[]
        blocker={'x':0,'y':0.35,'w':1,'h':0.65}
        p['shots']=[{'id':'s','source':'unused.mp4','startSeconds':0,'endSeconds':47,
                     'avoidRegions':[{**blocker,'startSeconds':0,'endSeconds':23},
                                     {**blocker,'startSeconds':28,'endSeconds':47}]}]
        p['watermark']={'persianText':'طریقت تسلیم','latinText':'Pathway_of_Surrender'}
        plan=self.prepare(p)['watermarkPlan']
        bands={slot['zone'].split('-',1)[0] for slot in plan}
        self.assertGreaterEqual(len(bands),2)
        short=[slot for slot in plan if slot['endSeconds']-slot['startSeconds']<6]
        self.assertEqual(len(short),1)
        self.assertGreaterEqual(short[0]['endSeconds']-short[0]['startSeconds'],4)
        self.assertFalse(short[0]['zone'].startswith('upper'))

    def test_rewards_of_slowness_fixture_keeps_coverage_failure_actionable(self):
        fixture = json.loads(
            (ROOT / "tests" / "fixtures" / "persian" / "rewards-of-slowness-watermark-prepass.json")
            .read_text(encoding="utf-8")
        )
        with self.assertRaises(FilmTypePreflightError) as caught:
            self.prepare(fixture)
        error = caught.exception
        self.assertEqual(error.code, "WATERMARK_COVERAGE")
        diagnostics = error.diagnostics
        self.assertAlmostEqual(diagnostics["coverageRatio"], 0.52, places=3)
        self.assertAlmostEqual(diagnostics["coverageFloor"], 0.70, places=3)
        self.assertEqual(
            diagnostics["suppressionGaps"],
            [
                {"startSeconds": 5, "endSeconds": 14.52},
                {"startSeconds": 31.48, "endSeconds": 41.2},
            ],
        )
        self.assertTrue(
            any(
                blocker.get("shotId") == "shot-beat-9-event-1"
                and blocker.get("regionIndex") == 2
                for blocker in diagnostics["topBlockers"]
            )
        )

    def test_214_long_form_brand_meets_coverage_relocation_and_vertical_diversity(self):
        p=self.props(design=self.pinned_214());p['durationSeconds']=47;p['moments']=[]
        p['shots']=[{'id':'s','source':'unused.mp4','startSeconds':0,'endSeconds':47,'avoidRegions':[]}]
        p['watermark']={'persianText':'طریقت تسلیم','latinText':'Pathway_of_Surrender'}
        q=self.prepare(p);plan=q['watermarkPlan']
        coverage=sum(slot['endSeconds']-slot['startSeconds'] for slot in plan)/47
        moves=sum(a['zone']!=b['zone'] for a,b in zip(plan,plan[1:]))
        bands={slot['zone'].split('-',1)[0] for slot in plan}
        self.assertGreaterEqual(coverage,.8)
        self.assertGreaterEqual(moves,2)
        self.assertGreaterEqual(len(bands),2)
        self.assertGreaterEqual(plan[0]['startSeconds'],5)

    def test_214_refuses_an_isolated_eight_second_brand_dwell(self):
        p=self.props(design=self.pinned_214());p['durationSeconds']=47;p['moments']=[]
        p['shots']=[{'id':'s','source':'unused.mp4','startSeconds':0,'endSeconds':47,
                     'avoidRegions':[{'x':0,'y':0,'w':1,'h':1,'startSeconds':0,'endSeconds':10},
                                     {'x':0,'y':0,'w':1,'h':1,'startSeconds':18,'endSeconds':47}]}]
        p['watermark']={'persianText':'طریقت تسلیم','latinText':'Pathway_of_Surrender'}
        with self.assertRaisesRegex(ValueError,'coverage'):self.prepare(p)

    def test_215_adaptive_recipe_is_browser_measured(self):
        text="این عبارت عمداً از سقف قدیمی سی نویسه بلندتر است"
        p=self.props(text=text)
        p["moments"][0]["segments"]=[{"role":"hero","text":text}]
        p["moments"][0]["presentation"]["recipeId"]="editorial-callout-balanced"
        q=self.prepare(p)
        layout=q["filmType"]["moments"]["m"]
        self.assertEqual(layout["recipeId"], "editorial-callout-balanced")
        recipe=q["design"]["resolved"]["typography"]["recipes"]["editorial-callout-balanced"]
        self.assertLessEqual(layout["occupancyRatio"], recipe["occupancyMax"])
        self.assertGreaterEqual(layout["lineBalanceRatio"], 0)

    def test_215_watermark_ignores_subject_regions_and_uses_fixed_anchors(self):
        def prepared(region):
            p=self.props();p["durationSeconds"]=47;p["moments"]=[]
            p["shots"]=[{"id":"s","source":"unused.mp4","startSeconds":0,"endSeconds":47,"avoidRegions":region}]
            p["watermark"]={"persianText":"طریقت تسلیم","latinText":"Pathway_of_Surrender"}
            return self.prepare(p)
        plain=prepared([])
        blocked=prepared([{"x":0,"y":0,"w":1,"h":1}])
        self.assertEqual(blocked["watermarkPlan"], plain["watermarkPlan"])
        approved={"upper-left","upper-right","lower-left","lower-right"}
        self.assertTrue(blocked["watermarkPlan"])
        self.assertTrue(all(slot["zone"] in approved for slot in blocked["watermarkPlan"]))
        diagnostics=blocked["watermarkDiagnostics"]
        self.assertFalse(any(item["blockerType"]=="subject-region" for item in diagnostics["rejectedIntervals"]))

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
