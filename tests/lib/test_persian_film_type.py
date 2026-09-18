"""Focused Film Type regressions; stdlib unittest or pytest, no provider calls.

The mocked bridge/render tests test producer boundaries and cleanup, NOT browser
measurement, actual decoding, TypeScript type safety or production visual approval.
"""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from lib.persian_brand import canonical_watermark
from lib.persian_design import resolve_design, prepare_v2, SUPPORTED_FILM_TYPE_29_HASH, SUPPORTED_FILM_TYPE_28_HASH, SUPPORTED_FILM_TYPE_27_HASH, SUPPORTED_FILM_TYPE_26_HASH, SUPPORTED_FILM_TYPE_25_HASH, SUPPORTED_FILM_TYPE_210_HASH, SUPPORTED_FILM_TYPE_211_HASH, SUPPORTED_FILM_TYPE_212_HASH, SUPPORTED_FILM_TYPE_213_HASH, SUPPORTED_FILM_TYPE_HASH, SUPPORTED_FILM_TYPE_215_HASH, SUPPORTED_FILM_TYPE_216_HASH, SUPPORTED_FILM_TYPE_MOTION_HASH, SUPPORTED_FILM_TYPE_LEGACY_HASH, SUPPORTED_FILM_TYPE_POLISH_HASH, SUPPORTED_FILM_TYPE_REPAIR_HASH
from lib.persian_film_type import prepare_film_type_props
from tools.video.persian_compose import PersianCompose

ROOT=Path(__file__).resolve().parents[2]
class FilmTypeContracts(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.raw={'version':2,'profile':'film-type','seed':'unchanged-project'}
    def tearDown(self):self.temp.cleanup()
    def test_legacy_and_quiet_resolution_unchanged(self):
        self.assertIsNone(resolve_design(None));self.assertIsNone(resolve_design({'seed':'old'}))
        quiet=resolve_design({'version':2,'profile':'quiet-editorial','seed':'x'})
        self.assertEqual(quiet['contentHash'],hashlib.sha256((ROOT/'styles/persian-footage/v2.json').read_bytes()).hexdigest())
    def test_film_type_requires_explicit_version(self):
        with self.assertRaisesRegex(ValueError,'explicit'):resolve_design({'profile':'film-type','seed':'x'})
    def test_known_snapshot_and_pin_roundtrip(self):
        design=resolve_design(self.raw);self.assertEqual(design['contentHash'],SUPPORTED_FILM_TYPE_216_HASH)
        self.assertEqual(resolve_design(design),design)
    def test_pinned_2_1_snapshot_keeps_old_interpretation(self):
        legacy_path=ROOT/'styles/persian-footage/film-type-2.1.0.json'
        profile=json.loads(legacy_path.read_text(encoding='utf-8'))
        pinned={'version':2,'profile':'film-type','seed':'legacy','profileVersion':'2.1.0',
                'contentHash':SUPPORTED_FILM_TYPE_LEGACY_HASH,'resolved':profile}
        resolved=resolve_design(pinned)
        self.assertEqual(resolved['profileVersion'],'2.1.0')
        self.assertEqual(resolved['contentHash'],SUPPORTED_FILM_TYPE_LEGACY_HASH)
        self.assertEqual(resolved['resolved']['layoutVersion'],1)

    def test_pinning_does_not_reopen_mutable_registry(self):
        pinned=resolve_design(self.raw)
        with patch('lib.persian_design.FILM_TYPE_PROFILE_PATH',self.root/'missing.json'):
            self.assertEqual(resolve_design(pinned),pinned)
    def test_partial_pin_refused(self):
        for key,value in [('resolved',{}),('contentHash','0'*64),('profileVersion','2.1.0')]:
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'together'):
                resolve_design({**self.raw,key:value})
    def test_self_hashed_unsupported_tokens_refused(self):
        design=resolve_design(self.raw);design['resolved']['watermark']['maxRelocations']=20
        design['contentHash']=hashlib.sha256(json.dumps(design['resolved'],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        with self.assertRaisesRegex(ValueError,'Unsupported'):resolve_design(design)
    def test_integral_json_floats_use_browser_canonical_hash(self):
        design=resolve_design(self.raw);design['resolved']['watermark']['persianFontPx']=30.0
        self.assertEqual(resolve_design(design)['contentHash'],SUPPORTED_FILM_TYPE_216_HASH)
    def test_nan_profile_refused(self):
        design=resolve_design(self.raw);design['resolved']['motion']['travelPx']=float('nan')
        with self.assertRaisesRegex(ValueError,'non-finite'):resolve_design(design)
    def test_contrast_strength_only_for_film_type(self):
        moment={'presentation':{'contrastStrength':'strong'}}
        self.assertEqual(prepare_v2({'design':self.raw,'moments':[moment]})['profile'],'film-type')
        with self.assertRaisesRegex(ValueError,'contrastStrength'):
            prepare_v2({'design':{**self.raw,'profile':'quiet-editorial'},'moments':[moment]})
    def test_new_contrast_strength_cannot_silently_select_legacy(self):
        with self.assertRaisesRegex(ValueError,'explicit film-type'):
            prepare_v2({'moments':[{'presentation':{'contrastStrength':'strong'}}]})
    def test_invalid_film_presentation_shape_refused(self):
        for value in [[],False,'']:
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'object'):
                prepare_v2({'design':self.raw,'moments':[{'presentation':value}]})
    def _bridge(self,mutate=None,code=0,design=None):
        composer=self.root/'composer';(composer/'scripts').mkdir(parents=True,exist_ok=True)
        (composer/'scripts/prepare-persian-film-type.mjs').write_text('// fake subprocess entry for boundary tests only')
        props={'format':'vertical','durationSeconds':12,'design':design or resolve_design(self.raw),
               'shots':[],'audio':{'narration':'narration.wav','music':'music.wav'},'moments':[{'id':'m','kind':'statement','startSeconds':.2,'endSeconds':3.2,'segments':[{'role':'hero','text':'یک مکس'}]}],
               'watermark':{'persianText':'برند','latinText':'Brand'},'typographicBeats':[],'futureProvenance':{'keep':True}}
        original=copy.deepcopy(props)
        def fake_run(args,**kwargs):
            source=json.loads(Path(args[2]).read_text());source.update(filmType={'version':source['design']['resolved']['layoutVersion'],'inputHash':'measured-test'},watermarkPlanMeasured=True)
            if mutate:mutate(source)
            Path(args[3]).write_text(json.dumps(source,ensure_ascii=False))
            return subprocess.CompletedProcess(args,code,stdout='',stderr='deliberate test refusal' if code else '')
        with patch('lib.persian_film_type.subprocess.run',side_effect=fake_run):
            result=prepare_film_type_props(props,composer)
        self.assertEqual(props,original);return result
    def test_supported_snapshots_and_bridge_versions(self):
        for version,filename,digest in [('2.1.0','film-type-2.1.0.json',SUPPORTED_FILM_TYPE_LEGACY_HASH),
                                        ('2.2.0','film-type-2.2.0.json',SUPPORTED_FILM_TYPE_POLISH_HASH),
                                        ('2.3.0','film-type-2.3.0.json',SUPPORTED_FILM_TYPE_REPAIR_HASH),
                                        ('2.4.0','film-type-2.4.0.json',SUPPORTED_FILM_TYPE_MOTION_HASH),
                                        ('2.5.0','film-type-2.5.0.json',SUPPORTED_FILM_TYPE_25_HASH),
                                        ('2.6.0','film-type-2.6.0.json',SUPPORTED_FILM_TYPE_26_HASH),
                                        ('2.7.0','film-type-2.7.0.json',SUPPORTED_FILM_TYPE_27_HASH),
                                        ('2.8.0','film-type-2.8.0.json',SUPPORTED_FILM_TYPE_28_HASH),
                                        ('2.9.0','film-type-2.9.0.json',SUPPORTED_FILM_TYPE_29_HASH),
                                        ('2.10.0','film-type-2.10.0.json',SUPPORTED_FILM_TYPE_210_HASH),
                                        ('2.11.0','film-type-2.11.0.json',SUPPORTED_FILM_TYPE_211_HASH),
                                        ('2.12.0','film-type-2.12.0.json',SUPPORTED_FILM_TYPE_212_HASH),
                                        ('2.13.0','film-type-2.13.0.json',SUPPORTED_FILM_TYPE_213_HASH),
                                        ('2.14.0','film-type-2.14.0.json',SUPPORTED_FILM_TYPE_HASH),
                                        ('2.15.0','film-type-2.15.0.json',SUPPORTED_FILM_TYPE_215_HASH),
                                        ('2.16.0','film-type.json',SUPPORTED_FILM_TYPE_216_HASH)]:
            with self.subTest(version=version):
                profile=json.loads((ROOT/'styles/persian-footage'/filename).read_text())
                pin={**self.raw,'profileVersion':version,'contentHash':digest,'resolved':profile}
                self.assertEqual(resolve_design(pin),pin)
                self.assertEqual(self._bridge(design=pin)['filmType']['version'],profile['layoutVersion'])
    def test_bridge_refuses_wrong_layout_version(self):
        for wrong in [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,True,False,'16',17,None]:
            with self.subTest(wrong=wrong),self.assertRaisesRegex(ValueError,'provenance'):
                self._bridge(lambda p:p['filmType'].update(version=wrong))
    def test_repair_tokens_restore_scale_and_real_watermark_policy(self):
        p=json.loads((ROOT/'styles/persian-footage/film-type-2.3.0.json').read_text())
        self.assertEqual(p['profileVersion'],'2.3.0')
        self.assertEqual(p['typography']['titleLadderPx'][0],128)
        self.assertEqual(p['typography']['titleTailRatio'],.8)
        self.assertEqual(p['contrast']['plateauStop'],.68)
        self.assertEqual(p['watermark']['safeAreas']['vertical'],{'top':.14,'bottom':.25,'left':.08,'right':.14})
        self.assertTrue(p['watermark']['preferStablePosition'])
        self.assertTrue(p['watermark']['pairWithText'])
        self.assertFalse(any(z.startswith('upper') for z in p['watermark']['allowedZones']))
    def test_motion_profile_preserves_type_and_geometry_tokens(self):
        old=json.loads((ROOT/'styles/persian-footage/film-type-2.3.0.json').read_text())
        new=json.loads((ROOT/'styles/persian-footage/film-type-2.5.0.json').read_text())
        for key in ['typography','layout','formats','palette']:self.assertEqual(old[key],new[key])
        self.assertEqual(new['profileVersion'],'2.5.0');self.assertEqual(new['layoutVersion'],5)
        self.assertEqual(new['motion']['cutInSeconds'],.48)
        self.assertLess(new['contrast']['strengths']['standard'],old['contrast']['strengths']['standard'])
        self.assertFalse(new['watermark']['preferStablePosition'])
    def test_shadow_field_blends_multiply_with_soft_core(self):
        new=resolve_design(self.raw)['resolved']
        field=new['contrast']['compactField']
        self.assertEqual(field['blend'],'multiply')
        self.assertGreaterEqual(field['featherPx'],32)
        self.assertLessEqual(field['featherPx'],160)
        self.assertEqual(field['exponent'],3)
        self.assertLess(field['paddingPx'],28)
        self.assertLessEqual(new['contrast']['strengths']['standard'],.6)
    def test_ranked_tokens_are_registry_default(self):
        new=resolve_design(self.raw)['resolved']
        self.assertEqual(new['profileVersion'],'2.16.0');self.assertEqual(new['layoutVersion'],16)
        self.assertEqual(new['layout']['aestheticPolicy'],'ranked-v1')
        self.assertEqual(new['contrast']['darkField'],'#191919')
        self.assertEqual(new['contrast']['strengths'],{'soft':.24,'standard':.34,'strong':.40})
        self.assertEqual(new['watermark']['introDelaySeconds'],5)
    def test_default_profile_requires_reviews_and_brand_clearance(self):
        new=resolve_design(self.raw)['resolved']
        self.assertTrue(new['layout']['autoRequiresReviewedAvoidRegions'])
        self.assertEqual(new['watermark']['minTextClearancePx'],64)
        self.assertTrue(new['watermark']['suppressWhenNoTextClearance'])
        self.assertEqual(new['watermark']['minCoverageRatio'],.7)
        self.assertEqual(new['watermark']['targetCoverageRatio'],.8)
        self.assertEqual(new['watermark']['longFormThresholdSeconds'],30)
        self.assertEqual(new['watermark']['minLongFormRelocations'],2)
        self.assertEqual(new['formats']['vertical']['safeArea'],{'top':.14,'bottom':.35,'side':.08,'left':.08,'right':.08})
        self.assertEqual(new['watermark']['safeAreas']['vertical'],{'top':.14,'bottom':.35,'left':.08,'right':.16})
    def test_213_only_adds_coverage_policy_to_the_archived_212_profile(self):
        old=json.loads((ROOT/'styles/persian-footage/film-type-2.12.0.json').read_text())
        new=json.loads((ROOT/'styles/persian-footage/film-type-2.13.0.json').read_text())
        self.assertEqual(old['profileVersion'],'2.12.0');self.assertEqual(old['layoutVersion'],12)
        self.assertEqual(new['profileVersion'],'2.13.0');self.assertEqual(new['layoutVersion'],13)
        for key in old:
            if key not in {'profileVersion','layoutVersion','watermark'}:self.assertEqual(new[key],old[key])
        added={'minCoverageRatio','targetCoverageRatio','longFormThresholdSeconds','minLongFormRelocations'}
        self.assertEqual({k:v for k,v in new['watermark'].items() if k not in added},old['watermark'])
        self.assertEqual({k:new['watermark'][k] for k in added},{'minCoverageRatio':.7,'targetCoverageRatio':.8,'longFormThresholdSeconds':30,'minLongFormRelocations':2})

    def test_214_refines_caption_contrast_and_vertical_brand_diversity(self):
        old=json.loads((ROOT/'styles/persian-footage/film-type-2.13.0.json').read_text())
        new=json.loads((ROOT/'styles/persian-footage/film-type-2.14.0.json').read_text())
        self.assertEqual(new['profileVersion'],'2.14.0');self.assertEqual(new['layoutVersion'],14)
        for key in ['typography','formats','palette','motion']:
            self.assertEqual(new[key],old[key])
        self.assertEqual({k:v for k,v in new['layout'].items() if k!='upperCentre'},
                         {k:v for k,v in old['layout'].items() if k!='upperCentre'})
        self.assertEqual(old['layout']['upperCentre'],.32);self.assertEqual(new['layout']['upperCentre'],.26)
        self.assertEqual(new['contrast']['strengths']['strong'],old['contrast']['strengths']['strong'])
        self.assertGreater(new['contrast']['glyphShadow']['nearAlpha'],old['contrast']['glyphShadow']['nearAlpha'])
        added={'minLongFormVerticalBands','verticalDiversityMinDwellSeconds'}
        self.assertEqual({k:v for k,v in new['watermark'].items() if k not in added},old['watermark'])
        self.assertEqual({k:new['watermark'][k] for k in added},
                         {'minLongFormVerticalBands':2,'verticalDiversityMinDwellSeconds':4})
    def test_28_pin_keeps_region_review_requirement(self):
        old=json.loads((ROOT/'styles/persian-footage/film-type-2.8.0.json').read_text())
        pin={**self.raw,'profileVersion':'2.8.0','contentHash':SUPPORTED_FILM_TYPE_28_HASH,'resolved':old}
        self.assertEqual(resolve_design(pin),pin)
        self.assertTrue(old['layout']['autoRequiresReviewedAvoidRegions'])
        self.assertEqual(old['layoutVersion'],8)
    def test_29_only_changes_the_region_gate_tokens(self):
        new=json.loads((ROOT/'styles/persian-footage/film-type-2.9.0.json').read_text())
        old=json.loads((ROOT/'styles/persian-footage/film-type-2.8.0.json').read_text())
        for key in ['typography','formats','palette','contrast','motion','watermark']:
            self.assertEqual(new[key],old[key])
        self.assertEqual({k:v for k,v in new['layout'].items() if k!='autoRequiresReviewedAvoidRegions'},
                         {k:v for k,v in old['layout'].items() if k!='autoRequiresReviewedAvoidRegions'})
    def test_210_only_changes_the_shadow_tokens(self):
        new=json.loads((ROOT/'styles/persian-footage/film-type-2.10.0.json').read_text())
        old=json.loads((ROOT/'styles/persian-footage/film-type-2.9.0.json').read_text())
        # Typography, geometry, timing and brand policy are deliberately untouched.
        for key in ['typography','formats','palette','layout','motion','watermark']:
            self.assertEqual(new[key],old[key])
        # A smaller, per-row field with a softer peak, plus glyph-level separation.
        self.assertLess(new['contrast']['diffuseField']['radiusScale'],old['contrast']['diffuseField']['radiusScale'])
        self.assertTrue(new['contrast']['diffuseField']['perRow'])
        self.assertLess(new['contrast']['strengths']['strong'],old['contrast']['strengths']['strong'])
        shadow=new['contrast']['glyphShadow']
        self.assertGreater(shadow['nearAlpha'],shadow['haloAlpha'])
        self.assertGreater(shadow['haloBlurPx'],shadow['nearBlurPx'])
        self.assertNotIn('glyphShadow',old['contrast'])
        # The glyph shadow is an addition; nothing else in contrast was rewritten.
        for key in ['darkField','lightField','defaultStrength','plateauStop','plateauPaddingPx','footageGrade','compactField']:
            self.assertEqual(new['contrast'][key],old['contrast'][key])
    def test_motion_pin_stays_supported(self):
        p=json.loads((ROOT/'styles/persian-footage/film-type-2.4.0.json').read_text())
        self.assertEqual(p['profileVersion'],'2.4.0');self.assertEqual(p['layoutVersion'],4)
        self.assertEqual(resolve_design({**self.raw,'resolved':p,'profileVersion':'2.4.0','contentHash':SUPPORTED_FILM_TYPE_MOTION_HASH})['resolved'],p)
    def test_all_archived_pins_stay_supported(self):
        for v,h in [('2.1.0',SUPPORTED_FILM_TYPE_LEGACY_HASH),('2.2.0',SUPPORTED_FILM_TYPE_POLISH_HASH),('2.3.0',SUPPORTED_FILM_TYPE_REPAIR_HASH)]:
            p=json.loads((ROOT/f'styles/persian-footage/film-type-{v}.json').read_text())
            self.assertEqual(resolve_design({**self.raw,'resolved':p,'profileVersion':v,'contentHash':h})['resolved'],p)
    def test_new_profile_cannot_claim_old_layout(self):
        p=resolve_design(self.raw);p['resolved']['layoutVersion']=3
        with self.assertRaisesRegex(ValueError,'Unsupported'):resolve_design(p)
    def test_bridge_preserves_audio_text_and_provenance(self):
        result=self._bridge();self.assertEqual(result['audio']['narration'],'narration.wav');self.assertTrue(result['futureProvenance']['keep'])
    def test_bridge_rejects_changed_audio(self):
        with self.assertRaisesRegex(ValueError,'audio'):self._bridge(lambda p:p['audio'].update(narration='changed.wav'))
    def test_bridge_rejects_changed_unknown_provenance(self):
        with self.assertRaisesRegex(ValueError,'futureProvenance'):self._bridge(lambda p:p['futureProvenance'].update(keep=False))
    def test_bridge_rejects_changed_authored_segment(self):
        with self.assertRaisesRegex(ValueError,'authored moment'):self._bridge(lambda p:p['moments'][0]['segments'][0].update(text='دیگر'))
    def test_bridge_failure_does_not_fallback(self):
        with self.assertRaisesRegex(ValueError,'no estimated or Legacy fallback'):self._bridge(code=1)
    def test_bridge_missing_script_fails_loudly(self):
        with self.assertRaisesRegex(ValueError,'missing'):prepare_film_type_props({},self.root)
    def test_empty_schedule_is_opt_in_only(self):
        self.assertEqual(PersianCompose._build_moments({'moments':[]},12,v2=True,measure_layout=False),[])
        with self.assertRaisesRegex(ValueError,'Legacy'):PersianCompose._build_moments({'moments':[]},12)
    def test_film_producer_preserves_reviewed_visual_complexity(self):
        clip=self.root/'clip-busy.mp4';clip.write_bytes(b'fixture-not-decoded')
        persian={'format':'vertical','durationSeconds':12,'design':self.raw,'moments':[],
                 'shots':[{'source':str(clip),'startSeconds':0,'endSeconds':12,'sourceInSeconds':0,
                           'camera':'none','attribution':'fixture','avoidRegions':[],
                           'visualComplexity':'busy'}]}
        with patch('tools.video.persian_compose.prepare_film_type_props',side_effect=lambda p,c:p):
            props,_=PersianCompose()._build_props(persian,self.root/'stage-busy','unit-busy')
        self.assertEqual(props['shots'][0]['visualComplexity'],'busy')

    def test_film_producer_preserves_reviewed_empty_regions(self):
        clip=self.root/'clip.mp4';clip.write_bytes(b'fixture-not-decoded')
        persian={'format':'vertical','durationSeconds':12,'design':self.raw,'moments':[],
                 'shots':[{'id':'s','source':str(clip),'startSeconds':0,'endSeconds':12,'camera':'none','attribution':'Synthetic unit-test fixture','avoidRegions':[]}]}
        with patch('tools.video.persian_compose.prepare_film_type_props',side_effect=lambda p,c:p) as bridge,patch.dict(os.environ,{'PERSIAN_SKIP_OPTIONAL_BRIDGE':'1'}):
            props,_=PersianCompose()._build_props(persian,self.root/'stage','unit-review')
        self.assertEqual(props['shots'][0]['avoidRegions'],[]);bridge.assert_called_once()
        self.assertEqual(props['watermark'],canonical_watermark())
    def _lifecycle(self,keep,success):
        composer=self.root/'runtime';(composer/'node_modules').mkdir(parents=True,exist_ok=True)
        output=self.root/'result.mp4';stages=[]
        props={'format':'vertical','durationSeconds':12,'shots':[{'startSeconds':0,'endSeconds':12}],'moments':[],'typographicBeats':[]}
        def build(p,stage,run):stage.mkdir(parents=True);(stage/'copy.mp4').write_bytes(b'staged-copy');stages.append(stage);return props,[]
        def render(*args,**kwargs):
            if success:output.write_bytes(b'mocked-output-not-decoded')
            return subprocess.CompletedProcess([],0 if success else 1,stdout='',stderr='test failure' if not success else '')
        class QA:
            passed=True;warn_runs=[]
            def to_dict(self):return {'passed':True,'scope':'mocked cleanup test'}
        with patch('tools.video.persian_compose._composer_dir',return_value=composer),patch.object(PersianCompose,'_build_props',side_effect=build),patch.object(PersianCompose,'run_command',side_effect=render),patch('tools.video.persian_compose.audit_render_luminance',return_value=QA()),patch('tools.video.persian_compose.audit_render_motion',return_value=QA()):
            result=PersianCompose().execute({'edit_decisions':{'render_runtime':'remotion','persian':{'format':'vertical'}},'output_path':str(output),'keep_staged_assets':keep})
        self.assertEqual(result.success,success)
        self.assertEqual(stages[0].exists(),keep is True and success)
        if success:
            data=output.with_suffix('.mp4.props.json').read_bytes();digest=output.with_suffix('.mp4.props.sha256').read_text().split()[0]
            self.assertEqual(hashlib.sha256(data).hexdigest(),digest)
            self.assertEqual(json.loads(data),props)
        return result
    def test_successful_review_retains_its_own_staging(self):
        result=self._lifecycle(True,True);self.assertTrue(result.data['staged_assets_retained']);self.assertTrue(Path(result.data['staged_assets_directory']).is_dir())
    def test_default_success_cleans_staging(self):self._lifecycle(False,True)
    def test_failed_review_cleans_even_if_retention_requested(self):self._lifecycle(True,False)
    def test_truthy_string_does_not_activate_retention(self):self._lifecycle('true',True)

if __name__=='__main__':unittest.main(verbosity=2)
