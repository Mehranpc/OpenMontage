"""Version-aware Film Type QA. No Legacy plateau or accent assumptions.
Evidence must be synchronized captures from the SAME frame/render:
background = footage + shadow, no text; footage = without text/shadow;
ink_mask = independently rendered text alpha, 0..1. Never estimate masks by
thresholding bright footage. Row glyph order is compared with an independently
shaped reference of the same text (#228); spelling itself is not certified.
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


_REPO = Path(__file__).resolve().parents[1]
_FONTS = _REPO / "remotion-composer" / "public" / "fonts"
_ESTEDAD = {500: "estedad/Estedad-Medium.ttf", 700: "estedad/Estedad-Bold.ttf", 900: "estedad/Estedad-Black.ttf"}
_KAHROBA = "kahroba/Kahroba-EB-LC.woff2"
GLYPH_ORDER_MIN_CORRELATION = 0.8
GLYPH_ORDER_MIN_MARGIN = 0.15


def _row_font(row, scale):
    from PIL import ImageFont
    family = str(row.get("family") or "")
    rel = _KAHROBA if "kahroba" in family.lower() else _ESTEDAD.get(int(row.get("weight") or 700), _ESTEDAD[700])
    path = _FONTS / rel
    if not path.is_file():
        return None
    return ImageFont.truetype(str(path), max(8, round(float(row["fontSizePx"]) * scale)),
                              layout_engine=ImageFont.Layout.RAQM)


def _profile(mask):
    cols = mask.sum(axis=0).astype(float)
    nz = np.nonzero(cols > 0)[0]
    if nz.size < 4:
        return None
    return cols[nz[0]:nz[-1] + 1]


def _correlate(a, b):
    n = max(len(a), len(b))
    xa = np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a)
    xb = np.interp(np.linspace(0, len(b) - 1, n), np.arange(len(b)), b)
    xa, xb = xa - xa.mean(), xb - xb.mean()
    denominator = float(np.linalg.norm(xa) * np.linalg.norm(xb))
    return float(xa @ xb / denominator) if denominator > 0 else 0.0


def glyph_order_check(frame, background, layout, props, *, align="right"):
    """Compare each painted row against an independently shaped reference of its text (#228).

    Film Type paints every role in plain ink, so the Legacy colour-keyed tools cannot see
    word or letter order. Here the painted ink is isolated by difference from the
    synchronized no-text background, each row's band is cut at its measured position, and
    the column-ink profile is correlated with the same text shaped right-to-left by HarfBuzz
    (Pillow + raqm) in the same font file and size. A row passes when it matches its
    reference strongly and clearly better than the mirrored reference, which is what a
    reversed or scrambled row looks like. Rows whose font file is not installed are
    reported as not checked, never passed.
    """
    from PIL import Image, ImageDraw

    h, w = frame.shape[:2]
    dims = (1080, 1920) if props["format"] == "vertical" else (1920, 1080)
    scale = w / dims[0]
    # Ink is what the glyphs ADD: white/yellow over a darkened field. The glyph shadow
    # only darkens, so a signed difference keeps it out of the profile.
    ink = (np.asarray(frame, dtype=float) - np.asarray(background, dtype=float)).max(axis=2) > 40
    pad = float(props["design"]["resolved"]["layout"].get("inkPaddingPx", 12))
    rect = layout["rect"]
    left, top = rect["x"] * w, rect["y"] * h
    width_px = float(layout["widthPx"]) * scale
    anchor = width_px / 2 if align == "center" else width_px - pad * scale
    rows = []
    for index, row in enumerate(layout.get("rows") or []):
        if row.get("role") == "brand" or not str(row.get("text") or "").strip():
            continue
        font = _row_font(row, scale)
        if font is None:
            rows.append({"row": index, "status": "not_checked", "reason": "font file not installed"})
            continue
        row_w = float(row["widthPx"]) * scale
        right = left + anchor + float(row.get("offsetXPx") or 0) * scale + (row_w / 2 if align == "center" else 0)
        x0, x1 = int(max(0, right - row_w - 4)), int(min(w, right + 4))
        base = top + float(row["baselinePx"]) * scale
        y0 = int(max(0, base - float(row["abovePx"]) * scale - 2))
        y1 = int(min(h, base + float(row["belowPx"]) * scale + 2))
        painted = _profile(ink[y0:y1, x0:x1])
        canvas = Image.new("L", (int(row_w * 1.5) + 40, int((y1 - y0) * 2) + 40), 0)
        ImageDraw.Draw(canvas).text((20, 20), str(row["text"]), font=font, fill=255,
                                    direction=str(row.get("direction") or "rtl"), language="fa")
        reference = _profile(np.asarray(canvas) > 127)
        if painted is None or reference is None:
            rows.append({"row": index, "status": "fail", "reason": "no painted ink in the row band"})
            continue
        forward, mirrored = _correlate(painted, reference), _correlate(painted, reference[::-1])
        ok = forward >= GLYPH_ORDER_MIN_CORRELATION and forward - mirrored >= GLYPH_ORDER_MIN_MARGIN
        rows.append({"row": index, "status": "pass" if ok else "fail",
                     "correlation": round(forward, 3), "mirrored": round(mirrored, 3)})
    statuses = {row["status"] for row in rows}
    status = "fail" if "fail" in statuses else "not_checked" if (not rows or "not_checked" in statuses) else "pass"
    return {"status": status, "rows": rows}


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
            if layout.get('rows'):
                placement=str(layout.get('placement') or '')
                align='center' if placement=='center' or placement.endswith('-center') else 'right'
                order=glyph_order_check(a,bg,layout,props,align=align)
                result['glyph_order']=order['status'];result['glyph_order_rows']=order['rows']
                if order['status']=='fail': problems.append(f'{label}: painted row order does not match its shaped reference')
                elif order['status']=='not_checked': unchecked.append(f'{label}: glyph order not checked (font file missing)')
        except (ValueError,KeyError,StopIteration,TypeError) as exc:
            result['status']='fail';problems.append(f'{label}: {exc}')
    if not frames: unchecked.append('No sampled frames')
    order_verified=bool(frames) and all(m.get('glyph_order')=='pass' for m in measurements.values())
    return {'frames':measurements,'problems':problems,'not_checked':unchecked,
            'passed':bool(frames) and not problems and not unchecked,
            # Approval-level text verification stays a human decision; glyph order is
            # reported separately so it can never be mistaken for approval.
            'persian_text_verified':False,
            'glyph_order_verified':order_verified and not problems,
            'scope':('sampled stable-frame contrast/composite checks plus per-row glyph order against a '
                     'HarfBuzz-shaped reference; full timeline and visual approval are not certified')}
