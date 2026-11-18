"""Read isolated score/level/badges; never flatten numeric lines together."""
from pathlib import Path
import re
from PIL import Image,ImageOps,ImageDraw,ImageFont
from core import _clean
from functools import lru_cache

@lru_cache(maxsize=1)
def digit_templates():
    import json
    return json.loads((Path(__file__).parent/'data/icon-signatures.json').read_text(encoding='utf8'))['digits']

def official_score_lines(text):
    for line in text.splitlines():
        m=re.fullmatch(r'装备分数(\d{1,3})(?:\([+]\d+\))?',_clean(line))
        if m:return int(m.group(1))
    return None

def _mask(crop,white=False,score=False):
    mask=Image.new('L',crop.size)
    mask.putdata([255 if (min(p)>175 and max(p)-min(p)<70 if white else p[0]>150 and p[1]>(140 if score else 120) and (not score or p[0]<p[1]*1.5) and p[2]<180) else 0 for p in crop.convert('RGB').getdata()])
    mask=ImageOps.expand(mask,8,fill=0)
    return mask.resize((mask.width*4,mask.height*4),Image.Resampling.LANCZOS)

def _number(ocr,crop,directory,name,white=False):
    from vision import template_number
    path=Path(directory)/(name+'.png');_mask(crop,white,score=name=='official-score').save(path)
    text=_clean(ocr.request(path=str(path),language='en-US' if white or name=='official-score' else 'zh-Hans-CN').get('text',''))
    m=re.fullmatch(r'[+十]?(\d{1,3})',text)
    if not m and white:
        # Resampled white text can disappear under the strict color mask.
        crop=ImageOps.expand(crop.convert('RGB'),8,fill='#07111c')
        crop=crop.resize((crop.width*4,crop.height*4),Image.Resampling.LANCZOS)
        path=Path(directory)/(name+'-raw.png');crop.save(path)
        text=_clean(ocr.request(path=str(path),language='en-US').get('text',''))
        m=re.fullmatch(r'[+十]?(\d{1,3})',text)
    if not m:
        glyph=_mask(crop,white,score=name in {'official-score','inventory-score'})
        bounds=glyph.getbbox()
        if bounds:
            glyph=glyph.crop(bounds);height=32;glyph=glyph.resize((max(1,round(glyph.width*height/glyph.height)),height))
            canvas=Image.new('L',(110+glyph.width,60),0)
            ImageDraw.Draw(canvas).text((5,12),'Value',font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',24),fill=255);canvas.paste(glyph,(100,12))
            path=Path(directory)/(name+'-context.png');canvas.save(path)
            raw=_clean(ocr.request(path=str(path),language='en-US').get('text',''));raw=re.sub(r'(?i)^value','',raw)
            m=re.fullmatch(r'[+十]?(\d{1,3})',raw)
    if not m:
        value=template_number(crop,digit_templates(),yellow=not white)
        if value and not value[1] and 0<=value[0]<=999:return int(value[0])
    return int(m.group(1)) if m else None

def _orange(crop):
    pixels=list(crop.convert('RGB').getdata())
    orange=sum(r>180 and 90<g<215 and b<130 and r>g*1.15 for r,g,b in pixels)>70
    upper=list(crop.crop((0,0,crop.width,max(1,int(crop.height*.55)))).convert('RGB').getdata())
    red=sum(r>155 and r>g*1.75 and r>b*1.7 and g<110 for r,g,b in upper)>max(70,len(upper)*.15)
    return orange or red

def read_metadata(image,ocr,directory,text='',known=None):
    known=known or {};levels=[known['level']] if known.get('level') is not None else [];badges=[known['enhance']] if known.get('enhance') is not None else [];badge_present=bool(badges);warnings=[]
    for name,box in [('level-left',(57,165,98,197)),('level-centre',(825,330,870,365))]:
        if known.get('level') is not None:break
        n=_number(ocr,image.crop(box),directory,name)
        if n in {55,58,65,70,71,72,75,77,78,80,85,88,90}:levels.append(n)
    for name,box in [('badge-centre',(899,302,972,350)),('badge-left',(128,143,199,190))]:
        if known.get('enhance') is not None:break
        crop=image.crop(box)
        if _orange(crop):
            badge_present=True
            n=_number(ocr,crop,directory,name,True)
            if n is not None and 0<n<=15:badges.append(n)
    level=levels[0] if levels and len(set(levels))==1 else None
    enhance=badges[0] if badges and len(set(badges))==1 else None
    if not badge_present and level is not None:enhance=0
    if enhance is None:warnings.append('强化角标未读清或两处不一致，请手动确认；不再默认+0。')
    if level is None:warnings.append('装备等级未读清，请手动确认。')
    line_score=official_score_lines(text)
    score=line_score if line_score is not None else _number(ocr,image.crop((320,595,520,642)),directory,'official-score')
    if score is None:score=line_score
    elif line_score is not None and score!=line_score:
        warnings.append('官方分的两次识别不一致，请手动核对。');score=None
    if score is None:warnings.append('官方分未读清；不影响民间分计算。')
    return {'level':level,'enhance':enhance,'screen_score':score,'warnings':warnings}
