"""Version-aware Film Type QA. No Legacy plateau or accent assumptions.
Evidence must be synchronized captures from the SAME frame/render:
background = footage + shadow, no text; footage = without text/shadow;
ink_mask = independently rendered text alpha, 0..1. Never estimate masks by
thresholding bright footage. This checks sampled pixels, not Persian spelling.
"""
from pathlib import Path
import numpy as np
from PIL import Image, ImageOps


def normalize_frame(frame, fmt):
    if isinstance(frame, (str, Path)):
        with Image.open(frame) as image:
            array = np.asarray(ImageOps.exif_transpose(image).convert('RGB')).copy()
    elif isinstance(frame, Image.Image):
        array = np.asarray(ImageOps.exif_transpose(frame).convert('RGB'))
    else:
        array = np.asarray(frame)
    if array.ndim != 3 or array.shape[2] != 3 or not np.isfinite(array).all():
        raise ValueError('Expected finite RGB image')
    h,w = array.shape[:2]
    ratio = 9/16 if fmt == 'vertical' else 16/9
    if abs(w/h-ratio) > .005:
        raise ValueError('Frame orientation/aspect does not match composition; normalize extraction metadata, do not guess rotation')
    if array.min()<0 or array.max()>255:
        raise ValueError('RGB must be in 0..255')
    return array.astype(float)


def luminance(rgb):
    x=rgb/255
    linear=np.where(x<=.04045,x/12.92,((x+.055)/1.055)**2.4)
    return linear @ np.array([.2126,.7152,.0722])


def verify_film_frames(frames, props, evidence=None):
    measurements={};problems=[];unchecked=[];evidence=evidence or {}
    if props.get('design',{}).get('profile') != 'film-type':
        raise ValueError('Film verifier requires resolved film-type props')
    fmt=props['format'];layouts=props.get('filmType',{}).get('moments',{})
    for label,frame in frames:
        result={'status':'not_checked','glyph_order':'not_checked'};measurements[label]=result
        try:
            a=normalize_frame(frame,fmt);h,w=a.shape[:2]
            layout=layouts.get(label)
            if not layout: raise ValueError('No measured moment rect for label')
            rect=layout['rect'];x,y,rw,rh=[float(rect[k]) for k in ('x','y','w','h')]
            if not np.isfinite([x,y,rw,rh]).all() or min(x,y)<0 or min(rw,rh)<=0 or x+rw>1.00001 or y+rh>1.00001:
                raise ValueError('Invalid measured rect')
            result['rect']=rect
            e=evidence.get(label,{})
            if not all(k in e for k in ('background','footage','ink_mask','seconds')):
                unchecked.append(f'{label}: synchronized background, footage, ink_mask and seconds required; no Legacy ceiling applied')
                continue
            moment=next(m for m in props['moments'] if m['id']==label)
            t=float(e['seconds']);motion=props['design']['resolved']['motion']
            latest=max(s.get('revealAfterSeconds',0) for s in moment['segments'])
            if not moment['startSeconds']+latest+max(motion['enterSeconds'],motion['cutInSeconds'])+.2 <= t <= moment['endSeconds']-motion['exitSeconds']:
                unchecked.append(f'{label}: sample is not a stable fully-revealed frame');continue
            bg=normalize_frame(e['background'],fmt);raw=normalize_frame(e['footage'],fmt)
            mask=np.asarray(e['ink_mask'],dtype=float)
            if bg.shape!=a.shape or raw.shape!=a.shape or mask.shape!=(h,w) or not np.isfinite(mask).all() or mask.min()<0 or mask.max()>1:
                raise ValueError('Evidence shape/range mismatch')
            ink=mask>.95
            if ink.sum()<8: raise ValueError('Missing independent opaque glyph mask')
            box=np.zeros((h,w),bool);box[max(0,int(y*h)-2):min(h,int(np.ceil((y+rh)*h))+2),max(0,int(x*w)-2):min(w,int(np.ceil((x+rw)*w))+2)]=True
            if np.any(ink & ~box): raise ValueError('Glyph mask outside measured rect')
            foreground=luminance(a)[ink];back=luminance(bg)[ink]
            ratios=(np.maximum(foreground,back)+.05)/(np.minimum(foreground,back)+.05)
            contrast=float(np.quantile(ratios,.05));result['contrast_p05']=round(contrast,3)
            # Support text needs 4.5:1; using that threshold for all ink is conservative.
            result['contrast_passed']=contrast>=4.5
            if contrast<4.5: problems.append(f'{label}: measured contrast below 4.5:1')
            field=box & ~ink
            change=np.abs(bg-raw).max(axis=2)
            rendered=bool(np.any(change[field]>2))
            result['shadow_rendered']=rendered
            if not rendered:
                unchecked.append(f'{label}: shadow effect not detectable; dark footage or absent shadow require a diagnostic mask')
            # Composite agreement catches absent/wrong text without inferring ink from footage.
            color=props['design']['resolved']['typography']['ink' if layout['contrastMode']=='dark' else 'darkInk']
            rgb=np.array([int(color[i:i+2],16) for i in (1,3,5)])
            agreement=float(np.quantile(np.abs(a[ink]-rgb).max(axis=1),.95))
            result['ink_error_p95']=round(agreement,3)
            if agreement>28: problems.append(f'{label}: rendered ink differs from independently expected ink')
            result['status']='pass' if contrast>=4.5 and agreement<=28 and rendered else 'fail' if contrast<4.5 or agreement>28 else 'not_checked'
        except (ValueError,KeyError,StopIteration,TypeError) as exc:
            result['status']='fail';problems.append(f'{label}: {exc}')
    if not frames: unchecked.append('No sampled frames')
    return {'frames':measurements,'problems':problems,'not_checked':unchecked,
            'passed':bool(frames) and not problems and not unchecked,
            'persian_text_verified':False,
            'scope':'sampled stable-frame contrast/composite checks only; glyph order, full timeline and visual approval are not certified'}
