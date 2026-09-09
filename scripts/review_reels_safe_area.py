"""Overlay the 2.8 conservative Reels review guide; never modify source media.
Usage: python scripts/review_reels_safe_area.py FRAME.png REVIEW.png
This is a project guide, not a pixel-exact Instagram UI screenshot.
"""
import argparse
from pathlib import Path
from PIL import Image, ImageOps, ImageDraw

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source');parser.add_argument('output');args=parser.parse_args()
    if Path(args.source).resolve()==Path(args.output).resolve():parser.error('Use a separate output path')
    profile=json_profile()
    with Image.open(args.source) as image:base=ImageOps.exif_transpose(image).convert('RGBA')
    w,h=base.size
    if abs(w/h-9/16)>.005:parser.error('Expected upright 9:16 frame')
    left,top,right,bottom=round(w*profile['left']),round(h*profile['top']),round(w*(1-profile['right'])),round(h*(1-profile['bottom']))
    overlay=Image.new('RGBA',base.size);draw=ImageDraw.Draw(overlay)
    for box in [(0,0,w,top),(0,bottom,w,h),(0,top,left,bottom),(right,top,w,bottom)]:draw.rectangle(box,fill=(230,40,40,65))
    draw.rectangle((left,top,right,bottom),outline=(0,230,150,255),width=max(2,w//300))
    draw.text((left+8,top+8),'REELS CONSERVATIVE GUIDE - not actual UI',fill=(0,230,150,255))
    Image.alpha_composite(base,overlay).convert('RGB').save(args.output)

def json_profile():
    import json
    p=Path(__file__).resolve().parents[1]/'styles/persian-footage/film-type.json'
    return json.loads(p.read_text())['formats']['vertical']['safeArea']

if __name__=='__main__':main()
