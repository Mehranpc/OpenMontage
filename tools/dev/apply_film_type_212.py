from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OLD_HASH = "ee04b0e576891828d754b2dc8bc7139178174251e3755dea4797dd480df4f687"
NEW_VERSION = "2.12.0"
NEW_LAYOUT = 12


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one exact match, found {count}: {old[:100]!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def regex_once(path: Path, pattern: str, replacement: str, *, flags: int = 0) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"{path}: expected one regex match, found {count}: {pattern[:100]!r}")
    path.write_text(updated, encoding="utf-8")


def canonical_hash(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


styles = ROOT / "styles" / "persian-footage"
live_path = styles / "film-type.json"
old_profile = json.loads(live_path.read_text(encoding="utf-8"))
if old_profile.get("profileVersion") != "2.11.0" or old_profile.get("layoutVersion") != 11:
    raise RuntimeError("film-type.json is not the expected 2.11 source profile")
if canonical_hash(old_profile) != OLD_HASH:
    raise RuntimeError("the 2.11 profile changed before it could be archived")
archive_path = styles / "film-type-2.11.0.json"
if archive_path.exists():
    raise RuntimeError("film-type-2.11.0.json already exists")
archive_path.write_text(json.dumps(old_profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

profile = copy.deepcopy(old_profile)
profile["profileVersion"] = NEW_VERSION
profile["layoutVersion"] = NEW_LAYOUT
profile["layout"]["autoRequiresReviewedAvoidRegions"] = True
profile["watermark"]["minTextClearancePx"] = 64
profile["watermark"]["suppressWhenNoTextClearance"] = True
live_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
NEW_HASH = canonical_hash(profile)

design_py = ROOT / "lib" / "persian_design.py"
replace_once(
    design_py,
    f'SUPPORTED_FILM_TYPE_210_HASH = "60ff5e80524aaa3877e8bd94e2bdd8c957c9f367947066ced034cbfb8be678e0"\nSUPPORTED_FILM_TYPE_HASH = "{OLD_HASH}"',
    f'SUPPORTED_FILM_TYPE_210_HASH = "60ff5e80524aaa3877e8bd94e2bdd8c957c9f367947066ced034cbfb8be678e0"\nSUPPORTED_FILM_TYPE_211_HASH = "{OLD_HASH}"\nSUPPORTED_FILM_TYPE_HASH = "{NEW_HASH}"',
)
replace_once(
    design_py,
    '            "2.11.0": (11, SUPPORTED_FILM_TYPE_HASH),',
    '            "2.11.0": (11, SUPPORTED_FILM_TYPE_211_HASH),\n            "2.12.0": (12, SUPPORTED_FILM_TYPE_HASH),',
)
replace_once(design_py, "Film Type 2.5 is the default path", "Film Type 2.12 is the default path")

bridge_py = ROOT / "lib" / "persian_film_type.py"
replace_once(
    bridge_py,
    '"2.10.0": 10, "2.11.0": 11}.get(design.get("profileVersion"))',
    '"2.10.0": 10, "2.11.0": 11, "2.12.0": 12}.get(design.get("profileVersion"))',
)

layout = ROOT / "remotion-composer" / "src" / "persian" / "filmType" / "layout.ts"
text = layout.read_text(encoding="utf-8")
old_union = 'profileVersion: "2.1.0" | "2.2.0" | "2.3.0" | "2.4.0" | "2.5.0" | "2.6.0" | "2.7.0" | "2.8.0" | "2.9.0" | "2.10.0" | "2.11.0"; layoutVersion: 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11;'
new_union = 'profileVersion: "2.1.0" | "2.2.0" | "2.3.0" | "2.4.0" | "2.5.0" | "2.6.0" | "2.7.0" | "2.8.0" | "2.9.0" | "2.10.0" | "2.11.0" | "2.12.0"; layoutVersion: 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12;'
if text.count(old_union) != 1:
    raise RuntimeError("layout.ts profile union did not match exactly")
text = text.replace(old_union, new_union)
old_watermark_type = '    targetDwellSeconds?: number; allowedZones?: string[]; preferStablePosition?: boolean; pairWithText?: boolean;\n    glyphShadow?: {color:string;nearOffsetPx:number;nearBlurPx:number;nearAlpha:number;haloBlurPx:number;haloAlpha:number}};'
new_watermark_type = '    targetDwellSeconds?: number; allowedZones?: string[]; preferStablePosition?: boolean; pairWithText?: boolean;\n    minTextClearancePx?: number; suppressWhenNoTextClearance?: boolean;\n    glyphShadow?: {color:string;nearOffsetPx:number;nearBlurPx:number;nearAlpha:number;haloBlurPx:number;haloAlpha:number}};'
if text.count(old_watermark_type) != 1:
    raise RuntimeError("layout.ts watermark type did not match exactly")
text = text.replace(old_watermark_type, new_watermark_type)
old_dispatch = '(p.profileVersion === "2.11.0" && p.layoutVersion === 11))'
new_dispatch = '(p.profileVersion === "2.11.0" && p.layoutVersion === 11) || (p.profileVersion === "2.12.0" && p.layoutVersion === 12))'
if text.count(old_dispatch) != 1:
    raise RuntimeError("layout.ts version/layout dispatch did not match exactly")
text = text.replace(old_dispatch, new_dispatch)
old_review = '(authored === "auto" || (p.profileVersion === "2.6.0" || (p.profileVersion === "2.7.0" || p.profileVersion === "2.8.0")))'
new_review = '(authored === "auto" || p.profileVersion === "2.12.0" || (p.profileVersion === "2.6.0" || (p.profileVersion === "2.7.0" || p.profileVersion === "2.8.0")))'
if text.count(old_review) != 1:
    raise RuntimeError("layout.ts reviewed-region requirement did not match exactly")
text = text.replace(old_review, new_review)
if text.count('if(enforceSubject) for(const region of relevant){') != 1:
    raise RuntimeError("layout.ts field/subject coupling did not match exactly")
text = text.replace('if(enforceSubject) for(const region of relevant){', 'if(enforceSubject && p.profileVersion !== "2.12.0") for(const region of relevant){')

helper_anchor = 'function planWatermark(props: PersianVideoProps, p: FilmProfile, layouts: Record<string,FilmMomentLayout>, lockup: FilmLockup | null, avoid: TimedRect[]): NonNullable<PersianVideoProps["watermarkPlan"]> {'
if text.count(helper_anchor) != 1:
    raise RuntimeError("layout.ts planWatermark anchor did not match")
helper = '''function suppressTextCloseSlots(
  plan: NonNullable<PersianVideoProps["watermarkPlan"]>,
  textRects: TimedRect[], clearancePx: number, dims: {width:number;height:number},
  transitionSeconds: number, minDwellSeconds: number,
): NonNullable<PersianVideoProps["watermarkPlan"]> {
  const result: Array<NonNullable<PersianVideoProps["watermarkPlan"]>[number]> = [];
  for (const slot of plan) {
    let spans: Array<[number,number]> = [[slot.startSeconds,slot.endSeconds]];
    const envelope=expand(slot.rect,clearancePx/dims.width,clearancePx/dims.height);
    const blocked=textRects
      .filter(rect=>intersects(envelope,rect) && rect.startSeconds<slot.endSeconds && rect.endSeconds>slot.startSeconds)
      .map(rect=>[Math.max(slot.startSeconds,rect.startSeconds-transitionSeconds),Math.min(slot.endSeconds,rect.endSeconds+transitionSeconds)] as [number,number])
      .filter(([start,end])=>end>start)
      .sort((a,b)=>a[0]-b[0]);
    for(const [cutStart,cutEnd] of blocked){
      const next: Array<[number,number]> = [];
      for(const [start,end] of spans){
        if(cutEnd<=start||cutStart>=end){next.push([start,end]);continue;}
        if(cutStart>start)next.push([start,Math.min(cutStart,end)]);
        if(cutEnd<end)next.push([Math.max(cutEnd,start),end]);
      }
      spans=next;
    }
    for(const [start,end] of spans){
      if(end-start+1e-8<minDwellSeconds)continue;
      result.push({...slot,startSeconds:start,endSeconds:end,
        transition:start>slot.startSeconds+1e-8?"fade-in":slot.transition,
        reason:"Measured brand-to-moment clearance; brand is explicitly suppressed where no legal separated slot exists"});
    }
  }
  return result;
}

'''
text = text.replace(helper_anchor, helper + helper_anchor)

old_clear_pattern = re.compile(
    r'  const obstacles=\[\.\.\.textRects,\.\.\.subjectAvoid\];\n'
    r'  const blockers:string\[\]=\[\];\n'
    r'  const clear=\(r:Rect,start:number,end:number\)=>\{.*?\n  \};\n',
    re.S,
)
new_clear = '''  const blockers:string[]=[];
  const visualClearancePx=p.profileVersion==="2.12.0"
    ? Math.max(cfg.minTextClearancePx??0,lockup.heightPx)
    : l.collisionMarginPx;
  const noteBlocker=(r:Rect,start:number,end:number,label:string,o:TimedRect)=>{
    const zone=Object.keys(rects).find(z=>rects[z]===r)??"unknown";
    const detail=`${zone} ${start}-${end}s blocked by ${label} (${o.startSeconds}-${o.endSeconds}s)`;
    if(blockers.length<3&&!blockers.includes(detail))blockers.push(detail);
  };
  const clearText=(r:Rect,start:number,end:number,marginPx:number)=>{
    const envelope=expand(r,marginPx/dims.width,marginPx/dims.height);
    const index=textRects.findIndex(o=>o.startSeconds<end&&o.endSeconds>start&&intersects(envelope,o));
    if(index<0)return true;
    noteBlocker(r,start,end,`text ${props.moments[index].id}`,textRects[index]);
    return false;
  };
  const clearSubject=(r:Rect,start:number,end:number)=>{
    const envelope=expand(r,l.collisionMarginPx/dims.width,l.collisionMarginPx/dims.height);
    const index=subjectAvoid.findIndex(o=>o.startSeconds<end&&o.endSeconds>start&&intersects(envelope,o));
    if(index<0)return true;
    noteBlocker(r,start,end,`subject region ${index}`,subjectAvoid[index]);
    return false;
  };
  const hardClear=(r:Rect,start:number,end:number)=>inWatermarkSafe(r,safe)
    && clearText(r,start,end,l.collisionMarginPx) && clearSubject(r,start,end);
  const preferredClear=(r:Rect,start:number,end:number)=>hardClear(r,start,end)
    && clearText(r,start,end,visualClearancePx);
  const clear=p.profileVersion==="2.12.0"?preferredClear:hardClear;
'''
text, count = old_clear_pattern.subn(new_clear, text, count=1)
if count != 1:
    raise RuntimeError(f"layout.ts planner clear block matches: {count}")

old_moving_pattern = re.compile(
    r'  if\(p\.profileVersion === "2\.4\.0".*?\) return planMovingBrand\(props\.durationSeconds,\n'
    r'    props\.shots\.flatMap\(s=>\[s\.startSeconds,s\.endSeconds\]\),\n'
    r'    \[\.\.\.props\.moments\.flatMap\(m=>\[m\.startSeconds,m\.endSeconds\]\),\.\.\.subjectAvoid\.flatMap\(r=>\[r\.startSeconds,r\.endSeconds\]\)\],\n'
    r'    order,rects,clear,cfg,cfg\.introDelaySeconds \?\? 0,\(\)=>blockers\.join\("; "\)\);\n',
    re.S,
)
new_moving = '''  if(p.profileVersion === "2.4.0" || (p.profileVersion === "2.5.0" || (p.profileVersion === "2.6.0" || (p.profileVersion === "2.7.0" || p.profileVersion === "2.8.0" || p.profileVersion === "2.9.0" || p.profileVersion === "2.10.0" || p.profileVersion === "2.11.0" || p.profileVersion === "2.12.0")))) {
    const run=(clearance:(r:Rect,start:number,end:number)=>boolean)=>planMovingBrand(props.durationSeconds,
      props.shots.flatMap(s=>[s.startSeconds,s.endSeconds]),
      [...props.moments.flatMap(m=>[m.startSeconds,m.endSeconds]),...subjectAvoid.flatMap(r=>[r.startSeconds,r.endSeconds])],
      order,rects,clearance,cfg,cfg.introDelaySeconds ?? 0,()=>blockers.join("; "));
    if(p.profileVersion!=="2.12.0")return run(hardClear);
    try{return run(preferredClear);}catch(error){
      if(!(error instanceof Error)||!error.message.startsWith("No safe moving watermark schedule"))throw error;
      if(!cfg.suppressWhenNoTextClearance)throw error;
      const trimmed=suppressTextCloseSlots(run(hardClear),textRects,visualClearancePx,dims,
        cfg.transitionSeconds,cfg.minDwellSeconds);
      if(!trimmed.length)throw new Error("No visible Film Type watermark dwell remains after enforcing measured text clearance; change the edit or explicitly author an empty watermark.");
      return trimmed;
    }
  }
'''
text, count = old_moving_pattern.subn(new_moving, text, count=1)
if count != 1:
    raise RuntimeError(f"layout.ts moving planner call matches: {count}")

lines = []
for line in text.splitlines():
    if 'p.profileVersion === "2.11.0"' in line and 'p.profileVersion === "2.12.0"' not in line:
        if 'p.layoutVersion === 11' not in line and 'subject-region enforcement is OFF' not in line:
            line = line.replace('p.profileVersion === "2.11.0"', '(p.profileVersion === "2.11.0" || p.profileVersion === "2.12.0")')
    if 'profile.profileVersion === "2.11.0"' in line and 'profile.profileVersion === "2.12.0"' not in line:
        if 'subject-region enforcement is OFF' not in line:
            line = line.replace('profile.profileVersion === "2.11.0"', '(profile.profileVersion === "2.11.0" || profile.profileVersion === "2.12.0")')
    if 'design.profileVersion === "2.11.0"' in line and 'design.profileVersion === "2.12.0"' not in line:
        line = line.replace('design.profileVersion === "2.11.0"', '(design.profileVersion === "2.11.0" || design.profileVersion === "2.12.0")')
    if 'version === "2.11.0"' in line and 'version === "2.12.0"' not in line and '.profileVersion' not in line:
        line = line.replace('version === "2.11.0"', '(version === "2.11.0" || version === "2.12.0")')
    lines.append(line)
text = "\n".join(lines) + "\n"

validation_anchor = '  return p;\n}\n\nlet canvas'
validation = '''  if (p.profileVersion === "2.12.0" && (!Number.isFinite(p.watermark.minTextClearancePx) || (p.watermark.minTextClearancePx ?? 0) < 0 || p.watermark.suppressWhenNoTextClearance !== true)) {
    throw new Error("Film Type 2.12 requires explicit measured brand/text clearance and suppression policy tokens.");
  }
  return p;
}

let canvas'''
if text.count(validation_anchor) != 1:
    raise RuntimeError("layout.ts filmProfile return anchor did not match")
text = text.replace(validation_anchor, validation)

hash_anchor = f'    "2.11.0":"{OLD_HASH}",'
if text.count(hash_anchor) != 1:
    raise RuntimeError("layout.ts 2.11 hash entry did not match")
text = text.replace(hash_anchor, hash_anchor + f'\n    "2.12.0":"{NEW_HASH}",')

warning_anchor = '  const watermarkPlan=planWatermark(props,profile,layouts,lockup,avoid);\n'
warning_code = '''  const watermarkPlan=planWatermark(props,profile,layouts,lockup,avoid);
  if(profile.profileVersion==="2.12.0"&&lockup&&watermarkPlan.length){
    const slots=[...watermarkPlan].sort((a,b)=>a.startSeconds-b.startSeconds),gaps:string[]=[];
    let cursor=profile.watermark.introDelaySeconds??0;
    for(const slot of slots){if(slot.startSeconds>cursor+1e-6)gaps.push(`${cursor.toFixed(2)}-${slot.startSeconds.toFixed(2)}s`);cursor=Math.max(cursor,slot.endSeconds);}
    if(cursor<props.durationSeconds-1e-6)gaps.push(`${cursor.toFixed(2)}-${props.durationSeconds.toFixed(2)}s`);
    if(gaps.length)warnings.push(`watermark-suppressed-for-text-clearance: ${gaps.join(", ")}; the brand is intentionally absent rather than grouped with moment text.`);
  }
'''
if text.count(warning_anchor) != 1:
    raise RuntimeError("layout.ts watermark warning anchor did not match")
text = text.replace(warning_anchor, warning_code)
layout.write_text(text, encoding="utf-8")

components = ROOT / "remotion-composer" / "src" / "persian" / "filmType" / "components.tsx"
ctext = components.read_text(encoding="utf-8")
clines = []
for line in ctext.splitlines():
    if 'p.profileVersion === "2.11.0"' in line and 'p.profileVersion === "2.12.0"' not in line:
        line = line.replace('p.profileVersion === "2.11.0"', '(p.profileVersion === "2.11.0" || p.profileVersion === "2.12.0")')
    clines.append(line)
components.write_text("\n".join(clines) + "\n", encoding="utf-8")

film_test = ROOT / "tests" / "lib" / "test_persian_film_type.py"
replace_once(
    film_test,
    'SUPPORTED_FILM_TYPE_25_HASH, SUPPORTED_FILM_TYPE_210_HASH, SUPPORTED_FILM_TYPE_HASH,',
    'SUPPORTED_FILM_TYPE_25_HASH, SUPPORTED_FILM_TYPE_210_HASH, SUPPORTED_FILM_TYPE_211_HASH, SUPPORTED_FILM_TYPE_HASH,',
)
replace_once(
    film_test,
    "('2.10.0','film-type-2.10.0.json',SUPPORTED_FILM_TYPE_210_HASH),\n                                        ('2.11.0','film-type.json',SUPPORTED_FILM_TYPE_HASH)]",
    "('2.10.0','film-type-2.10.0.json',SUPPORTED_FILM_TYPE_210_HASH),\n                                        ('2.11.0','film-type-2.11.0.json',SUPPORTED_FILM_TYPE_211_HASH),\n                                        ('2.12.0','film-type.json',SUPPORTED_FILM_TYPE_HASH)]",
)
replace_once(
    film_test,
    "for wrong in [1,2,3,4,5,6,7,8,9,10,True,False,'11',12,None]:",
    "for wrong in [1,2,3,4,5,6,7,8,9,10,11,True,False,'12',13,None]:",
)
replace_once(
    film_test,
    "self.assertEqual(new['profileVersion'],'2.11.0');self.assertEqual(new['layoutVersion'],11)",
    "self.assertEqual(new['profileVersion'],'2.12.0');self.assertEqual(new['layoutVersion'],12)",
)
replace_once(
    film_test,
    "    def test_default_profile_does_not_require_reviewed_regions(self):\n        new=resolve_design(self.raw)['resolved']\n        self.assertFalse(new['layout']['autoRequiresReviewedAvoidRegions'])\n        # The only hard geometric contract stays: typography inside the Reels safe area.\n        self.assertEqual(new['formats']['vertical']['safeArea'],{'top':.14,'bottom':.35,'side':.08,'left':.08,'right':.16})\n        self.assertEqual(new['watermark']['safeAreas']['vertical'],{'top':.14,'bottom':.35,'left':.08,'right':.16})",
    "    def test_default_profile_requires_reviews_and_brand_clearance(self):\n        new=resolve_design(self.raw)['resolved']\n        self.assertTrue(new['layout']['autoRequiresReviewedAvoidRegions'])\n        self.assertEqual(new['watermark']['minTextClearancePx'],64)\n        self.assertTrue(new['watermark']['suppressWhenNoTextClearance'])\n        self.assertEqual(new['formats']['vertical']['safeArea'],{'top':.14,'bottom':.35,'side':.08,'left':.08,'right':.16})\n        self.assertEqual(new['watermark']['safeAreas']['vertical'],{'top':.14,'bottom':.35,'left':.08,'right':.16})",
)

browser_test = ROOT / "tests" / "lib" / "test_persian_ranked_browser.py"
replace_once(
    browser_test,
    'from lib.persian_design import resolve_design, SUPPORTED_FILM_TYPE_28_HASH',
    'from lib.persian_design import resolve_design, SUPPORTED_FILM_TYPE_28_HASH, SUPPORTED_FILM_TYPE_211_HASH',
)
replace_once(
    browser_test,
    "    def prepare(self, p):\n        return prepare_film_type_props(p, ROOT/'remotion-composer')",
    "    def pinned_211(self):\n        profile=json.loads((ROOT/'styles/persian-footage/film-type-2.11.0.json').read_text(encoding='utf-8'))\n        return {'version':2,'profile':'film-type','seed':'regression','profileVersion':'2.11.0',\n                'contentHash':SUPPORTED_FILM_TYPE_211_HASH,'resolved':profile}\n    def prepare(self, p):\n        return prepare_film_type_props(p, ROOT/'remotion-composer')",
)
regex_once(
    browser_test,
    r'    def test_default_profile_ignores_regions_and_reports_not_checked\(self\):.*?\n    def test_28_pin_still_refuses_missing_reviews_and_obstructed_frames',
    '''    def test_default_profile_requires_review_and_enforces_regions(self):
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
    def test_28_pin_still_refuses_missing_reviews_and_obstructed_frames''',
    flags=re.S,
)
replace_once(
    browser_test,
    "        plain=self.prepare(self.props())['filmType']['moments']['m']['rect']\n        p=self.props();p['shots'][0]['avoidRegions']=[region]",
    "        plain=self.prepare(self.props(design=self.pinned_211()))['filmType']['moments']['m']['rect']\n        p=self.props(design=self.pinned_211());p['shots'][0]['avoidRegions']=[region]",
)
replace_once(
    browser_test,
    "        p=self.props();p['watermark']={'persianText':'برند','latinText':'Brand'}\n        p['moments'][0]['presentation']['placement']='upper-right'",
    "        p=self.props(design=self.pinned_211());p['watermark']={'persianText':'برند','latinText':'Brand'}\n        p['moments'][0]['presentation']['placement']='upper-right'",
)
new_browser_test = '''    def test_212_suppresses_brand_instead_of_grouping_it_with_m5(self):
        p=self.props();p['durationSeconds']=47
        p['shots']=[{'id':'s','source':'unused.mp4','startSeconds':0,'endSeconds':47,
                     'avoidRegions':[{'x':0.05,'y':0.10,'w':0.90,'h':0.20}]}]
        p['moments']=[{'id':'m5','kind':'statement','startSeconds':42.47,'endSeconds':46.97,
                       'presentation':{'placement':'lower-right','motion':'cut-in'},
                       'segments':[{'role':'lead','text':'ولی برای «بودنت»'},
                                   {'role':'hero','text':'هیچ‌وقت عذرخواهی نکن!'}]}]
        p['watermark']={'persianText':'طریقت تسلیم','latinText':'@Pathway_of_Surrender'}
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
'''
replace_once(browser_test, "    def test_stale_layout_refused(self):", new_browser_test + "    def test_stale_layout_refused(self):")

film_md = ROOT / "skills" / "pipelines" / "persian-footage" / "film-type.md"
ft = film_md.read_text(encoding="utf-8")
ft = ft.replace("# Film Type — current default: 2.11.0 / layout 11", "# Film Type — current default: 2.12.0 / layout 12", 1)
ft = ft.replace("docs/persian-film-type-2.11-patch.md", "docs/persian-film-type-2.12-patch.md", 1)
ft = ft.replace("Archived 2.5–2.10 guidance", "Archived 2.5–2.11 guidance", 1)
ft = re.sub(
    r'## What 2\.11 changed.*?(?=## Safe area, contrast, and brand)',
    '''## What 2.12 changed

2.12 turns the two rejected review frames into hard, versioned behaviour:

1. **Every overlapping shot must carry reviewed `avoidRegions`**, including
   `[]` only after a human reviewed the crop and camera move. Both `auto` and
   explicit placement are refused without that evidence.
2. **Reviewed regions reject text placements.** A block that cannot clear the
   supplied subject/action envelope fails and goes back to the edit: shorten the
   copy, reframe, or change the shot. The contrast field remains at full strength;
   regions never weaken it.
3. **Brand/text separation is measured edge-to-edge.** The clearance is
   `max(watermark.minTextClearancePx, measured lockup height)` — 77px for the
   default two-line lockup, instead of the old 12px collision-only margin.
4. **No-slot cases suppress the brand explicitly.** If safe area, reviewed
   regions, and text clearance leave no legal full-dwell slot, the planner removes
   the brand for that interval (including its fade envelope), records a warning,
   and keeps every remaining visible dwell at least 6s. It never groups the brand
   with moment text or parks it on a reviewed subject.

2.11 is archived unchanged at `styles/persian-footage/film-type-2.11.0.json` and
its behaviour remains pinnable. See `docs/persian-film-type-2.12-patch.md`.

## Subject safety: reviewed geometry, never detection

There is still no face/person detector or classifier. The edit supplies normalized
screen-space envelopes after crop and across camera motion. In 2.12 those reviewed
regions are mandatory and binding for both auto and explicit typography placement.
Missing review is a refusal; a blocked wide phrase is an editorial refusal, not an
invitation to weaken the region. `subjectSafety` is
`checked-against-supplied-regions` only after the whole dwell clears them.

When text cannot clear a centre-framed subject, shorten/narrow the display copy,
change the crop or shot, or deliberately pin an older profile for reproduction.
Never remove a truthful region to make a render pass.

''',
    ft,
    count=1,
    flags=re.S,
)
ft = ft.replace(
    "The 2.11 hash is\n`ee04b0e576891828d754b2dc8bc7139178174251e3755dea4797dd480df4f687`.",
    f"The 2.12 hash is\n`{NEW_HASH}`.",
)
ft = ft.replace(
    "Minimum dwell 6s, target 12s, at most 5 relocations, one\nlockup at a time, fade to zero between slots. Movement is not copy protection.",
    "Minimum visible dwell 6s, target 12s, at most 5 relocations, one\nlockup at a time, fade to zero between slots. The brand stays at least one\nmeasured lockup height from moment text; where no legal slot exists it is\nexplicitly suppressed and the warning names the interval. Movement is not copy protection.",
)
film_md.write_text(ft, encoding="utf-8")

for name in ["edit-director.md", "compose-director.md", "executive-producer.md"]:
    path = ROOT / "skills" / "pipelines" / "persian-footage" / name
    content = path.read_text(encoding="utf-8")
    content = content.replace("Film Type 2.11.0 / layout 11 is the default", "Film Type 2.12.0 / layout 12 is the default", 1)
    content = content.replace("docs/persian-film-type-2.11-patch.md", "docs/persian-film-type-2.12-patch.md", 1)
    path.write_text(content, encoding="utf-8")

edit_md = ROOT / "skills" / "pipelines" / "persian-footage" / "edit-director.md"
replace_once(
    edit_md,
    "Neither profile detects subjects, so the shadow or scrim\nhelps legibility without knowing what is behind the text — a moment over a close-up\nface still competes with it for attention, and on Film Type 2.11 subject-region\nenforcement is off, which the run reports as a warning rather than a refusal.",
    "Neither profile detects subjects. Film Type 2.12 instead requires a human-reviewed\n`avoidRegions` array on every overlapping shot (use `[]` only after checking the\nwhole crop/camera move) and rejects any text candidate that intersects it. A wide\nblock over a centre-framed face therefore goes back to the edit for shorter copy, a\nnew crop, or another shot; never weaken the region to make it pass.",
)
replace_once(
    edit_md,
    "What holds in both: the position is computed, never authored for aesthetic reasons.\nExplicit placement without reviewed avoid regions is exactly what the 2.11 warning\nlist flags, and it is not a shortcut around a moment that does not fit.",
    "What holds in both: the position is computed, never authored for aesthetic reasons.\nOn Film Type 2.12 explicit placement is binding but not a review bypass: missing\nreviewed avoid regions is a refusal, and a blocked authored zone is a refusal.",
)

compose_md = ROOT / "skills" / "pipelines" / "persian-footage" / "compose-director.md"
replace_once(
    compose_md,
    "`minDwellSeconds` 6 and `transitionSeconds` 0.3 from `film-type.json`, and it raises\n\"No safe moving watermark schedule\" rather than overlapping type. So on Film Type there\nis no single expected top fraction to pass in — take the slot boundaries from the",
    "`minDwellSeconds` 6 and `transitionSeconds` 0.3 from `film-type.json`. Film Type\n2.12 additionally enforces edge-to-edge brand/text clearance of at least the measured\nlockup height. If no legal slot remains, the brand is explicitly absent for that\ninterval and `filmType.warnings` records it; it is never grouped with the moment.\nThere is no single expected top fraction to pass in — take the slot boundaries from the",
)
replace_once(
    compose_md,
    '| "No safe moving watermark schedule" | Film Type could not place the moving mark clear of every moment rect | An editorial fix: shorten or move a moment, or reduce the stack. Never widen the mark\'s clearance to make it fit |',
    '| "No safe moving watermark schedule" | No hard-safe watermark dwell exists even before the 2.12 suppression policy can preserve a visible slot | Fix the edit, reviewed regions, or brand input; never weaken a truthful region or edit a frozen sidecar |',
)

patch_note = f'''# Film Type 2.12.0 — reviewed subjects and measured brand separation

## Why

Two user-reviewed frames exposed separate missing contracts in 2.11:

- m1 placed a wide block across a face because 2.11 deliberately ignored reviewed
  regions for typography.
- m5 placed the two-line brand only **30.5px edge-to-edge** above the moment. The
  earlier 107px report measured top-to-top and was wrong. The planner's 12px
  collision margin proved non-overlap but did not prevent the two text systems
  from reading as one group.

The test video is not a delivery, so its existing m1 frame is not retroactively
blocked. The pipeline is fixed for every new unpinned run.

## Behaviour

- `profileVersion`: `2.12.0`; `layoutVersion`: `12`
- content hash: `{NEW_HASH}`
- `layout.autoRequiresReviewedAvoidRegions`: `true`
- `watermark.minTextClearancePx`: `64`
- `watermark.suppressWhenNoTextClearance`: `true`

Every shot overlapping a moment must carry reviewed normalized `avoidRegions`.
They reject typography candidates but no longer attenuate the diffuse field. If no
candidate clears the subject/action envelope, preparation fails with an editorial
remedy: shorter copy, another crop, or another shot.

The brand envelope is expanded by
`max(minTextClearancePx, measuredLockup.heightPx)` before it is compared with a
moment. For the default 77px-high lockup, the effective clearance is 77px. The old
12px `collisionMarginPx` remains the hard geometry/subject margin and is not
redefined.

The planner first searches for a full-dwell schedule satisfying the larger visual
clearance. If none exists but a hard-safe schedule does, intervals too close to text
are removed with the fade envelope. Remaining visible fragments shorter than the
6s minimum dwell are removed too. The output warning names every suppression gap.
If no visible dwell remains at all, preparation fails rather than silently deleting
the brand for the whole film.

## Compatibility

2.11 is archived byte-for-behaviour at
`styles/persian-footage/film-type-2.11.0.json` with hash `{OLD_HASH}`. Versions
2.1–2.11 remain pinnable and keep their original placement, subject, and watermark
behaviour. No safe-area, typography, contrast, motion, or shadow token changed.

## Acceptance

Run:

```bash
python -m pytest tests/lib/ -q
cd remotion-composer && npx tsc --noEmit && cd ..
OPENMONTAGE_BROWSER_TESTS=1 python -m unittest tests.lib.test_persian_ranked_browser -q
```

The browser suite includes both rejected geometries: reviewed m1 must refuse its
face collision, and m5 must contain no visible watermark slot inside its moment
unless the expanded measured envelopes clear. A green run is still not visual
approval; re-prepare and review the new stills at phone size.
'''
(ROOT / "docs" / "persian-film-type-2.12-patch.md").write_text(patch_note, encoding="utf-8")

history = ROOT / "skills" / "pipelines" / "persian-footage" / "film-type-history.md"
h = history.read_text(encoding="utf-8")
if "## Film Type 2.11.0 — archived" not in h:
    h += "\n\n## Film Type 2.11.0 — archived\n\n2.11 lowered mid placements, added 20px safe-area padding, strengthened the\nbrand-only shadow, and used reviewed regions to steer the brand while text\nremained unenforced. Reproduce it only with the archived profile and read\n`docs/persian-film-type-2.11-patch.md`; the current contract is 2.12.\n"
history.write_text(h, encoding="utf-8")

print(json.dumps({"profileVersion": NEW_VERSION, "layoutVersion": NEW_LAYOUT, "contentHash": NEW_HASH}, indent=2))
