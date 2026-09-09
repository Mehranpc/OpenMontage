import unittest
import numpy as np
from PIL import Image
from lib.persian_film_verify import normalize_frame, verify_film_frames
from lib.persian_verify import verify_frames

class FilmVerifyContracts(unittest.TestCase):
    def fixture(self):
        raw=np.full((160,90,3),180,dtype=np.uint8)
        bg=np.full_like(raw,40);out=bg.copy();mask=np.zeros((160,90))
        mask[110:120,30:60]=1;out[mask==1]=255
        props={'format':'vertical','design':{'profile':'film-type','resolved':{
            'motion':{'enterSeconds':.56,'cutInSeconds':.48,'exitSeconds':.22},
            'typography':{'ink':'#FFFFFF','darkInk':'#191919'}}},
            'filmType':{'moments':{'m':{'rect':{'x':.2,'y':.6,'w':.6,'h':.2},'contrastMode':'dark'}}},
            'moments':[{'id':'m','startSeconds':0,'endSeconds':5,'segments':[{'text':'متن','role':'hero'}]}]}
        return out,props,{'m':{'background':bg,'footage':raw,'ink_mask':mask,'seconds':2}}
    def test_positive_lower_rect_not_legacy_zone(self):
        a,p,e=self.fixture();q=verify_frames([('m',a)],props=p,evidence=e)
        self.assertTrue(q['passed']);self.assertFalse(q['persian_text_verified'])
    def test_missing_evidence_not_a_pass(self):
        a,p,e=self.fixture();q=verify_frames([('m',a)],props=p)
        self.assertFalse(q['passed']);self.assertTrue(q['not_checked']);self.assertEqual(q['problems'],[])
    def test_absent_text_fails(self):
        a,p,e=self.fixture();q=verify_film_frames([('m',e['m']['background'])],p,e)
        self.assertFalse(q['passed']);self.assertTrue(q['problems'])
    def test_low_contrast_fails(self):
        a,p,e=self.fixture();e['m']['background'][:]=240
        self.assertFalse(verify_film_frames([('m',a)],p,e)['passed'])
    def test_absent_shadow_not_certified(self):
        a,p,e=self.fixture();e['m']['footage']=e['m']['background'].copy()
        q=verify_film_frames([('m',a)],p,e);self.assertFalse(q['passed']);self.assertFalse(q['frames']['m']['shadow_rendered'])
    def test_wrong_geometry_fails(self):
        a,p,e=self.fixture();p['filmType']['moments']['m']['rect']['y']=.1
        self.assertFalse(verify_film_frames([('m',a)],p,e)['passed'])
    def test_raw_rotation_rejected_not_guessed(self):
        a,p,e=self.fixture()
        with self.assertRaisesRegex(ValueError,'orientation'):normalize_frame(np.rot90(a),'vertical')
    def test_exif_orientation_normalized_once(self):
        a,p,e=self.fixture();image=Image.fromarray(np.rot90(a));exif=image.getexif();exif[274]=6
        image.info['exif']=exif.tobytes()
        self.assertEqual(normalize_frame(image,'vertical').shape,a.shape)
    def test_transient_frame_not_certified(self):
        a,p,e=self.fixture();e['m']['seconds']=.1
        self.assertFalse(verify_film_frames([('m',a)],p,e)['passed'])
    def test_empty_input_not_pass(self):
        a,p,e=self.fixture();self.assertFalse(verify_film_frames([],p,e)['passed'])

if __name__=='__main__':unittest.main()
