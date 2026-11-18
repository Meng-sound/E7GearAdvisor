"""Detect crafted-item cards from neural level-label boxes, not frame colors."""
import re
from statistics import median
from pathlib import Path
from core import _clean
class CraftCards(list):
    def __init__(self,boxes,levels):super().__init__(boxes);self.levels=levels

def locate_crafted_cards(image,ocr,directory):
    title=image.crop((int(image.width*.27),int(image.height*.12),int(image.width*.72),int(image.height*.25)))
    titlepath=Path(directory)/'crafted-items-title.png';title.save(titlepath)
    titletext=_clean(ocr.request(path=str(titlepath),single_line=True,crop_text=True).get('text',''))
    if not any(word in titletext for word in ('制作完毕','製作完畢','制作完成','製作完成')):
        titletext=_clean(ocr.request(path=str(titlepath)).get('text',''))
    if not any(word in titletext for word in ('制作完毕','製作完畢','制作完成','製作完成')):
        raise ValueError('请打开钢铁工坊“制作完毕”界面；装备制作识别只按新制作的+0装备判断。')
    left,top,right,bottom=int(image.width*.065),int(image.height*.27),int(image.width*.96),int(image.height*.79)
    panel=image.crop((left,top,right,bottom));path=Path(directory)/'crafted-items-layout.png';panel.save(path)
    result=ocr.request(path=str(path),yellow_only=True);found=[];level_by_position={}
    for line in result.get('lines',[]):
      for word in line.get('words',[]):
        text=_clean(word['text'])
        if not re.fullmatch(r'\d{2}',text) or int(text) not in {55,57,58,65,70,71,72,75,77,78,80,85,88,90}:continue
        if word.get('confidence',.8)<.7:continue
        x=round(word['x']+left-6);y=round(word['y']+top-6)
        if any(abs(x-b[0])<35 and abs(y-b[1])<35 for b in found):continue
        found.append((x,y,x+120,y+120))
        level_by_position[x,y]=int(text)
    if len(found)<10:
        # Keep the full detector as the fallback for incomplete small batches.
        result=ocr.request(path=str(path))
        for line in result.get('lines',[]):
          for word in line.get('words',[]):
            text=_clean(word['text'])
            if re.fullmatch(r'\d{2}',text) and int(text) in {55,57,58,65,70,71,72,75,77,78,80,85,88,90} and word.get('confidence',.8)>=.7:
                x=round(word['x']+left-6);y=round(word['y']+top-6)
                if not any(abs(x-b[0])<35 and abs(y-b[1])<35 for b in found):found.append((x,y,x+120,y+120));level_by_position[x,y]=int(text)
    groups=[]
    for box in sorted(found,key=lambda b:(b[1],b[0])):
        group=next((g for g in groups if abs(g[0][1]-box[1])<35),None)
        if group is None:groups.append([box])
        else:group.append(box)
    columns=[]
    for box in sorted(found,key=lambda b:b[0]):
        group=next((g for g in columns if abs(g[0][0]-box[0])<35),None)
        if group is None:columns.append([box])
        else:group.append(box)
    x_positions=[round(median(b[0] for b in group)) for group in columns]
    aligned=[]
    for group in groups:
        y=round(median(b[1] for b in group))
        for box in sorted(group,key=lambda b:b[0]):
            x=min(x_positions,key=lambda a:abs(a-box[0]));aligned.append((x,y,x+120,y+120))
    # Align the shared grid with the main-stat glyphs; a 5-pixel OCR box shift
    # must not turn a red card into a missing card or shift all its icon fields.
    from vision import match_icon,ROOT
    import json
    templates=json.loads((ROOT/'data/icon-signatures.json').read_text(encoding='utf-8'))['stats']
    best=None
    for dx in (-2,0,2,4):
      for dy in (-2,0,2,4,6):
        score=sum(match_icon(image.crop((x+140+dx,y+7+dy,x+172+dx,y+37+dy)),templates,threshold=0,margin=0)[1] for x,y,_,_ in aligned)
        candidate=(score,-abs(dx)-abs(dy),dx,dy)
        if best is None or candidate>best:best=candidate
    if best:
        dx,dy=best[2:];aligned=[(x+dx,y+dy,r+dx,b+dy) for x,y,r,b in aligned]
    levels=[level_by_position[min(level_by_position,key=lambda p:(p[0]-b[0])**2+(p[1]-b[1])**2)] for b in aligned]
    return CraftCards(aligned,levels)
