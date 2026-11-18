"""Match visible equipment artwork and set badges against labeled local samples."""
import json
from pathlib import Path
from PIL import Image,ImageOps
ROOT=Path(__file__).parent/'data/equipment-icons'
_bank=None
def feature(image):
    import numpy as np
    a=np.asarray(ImageOps.grayscale(image.resize((80,80),Image.Resampling.LANCZOS)),dtype=float)
    mask=np.zeros((80,80),dtype=bool);mask[17:55,9:69]=True;mask[45:55,9:29]=False
    v=a[mask];v=v-v.mean();return v/max(float(np.linalg.norm(v)),1e-9)
def load_bank():
    global _bank
    if _bank is None:
        import numpy as np
        rows=json.loads((ROOT/'index.json').read_text(encoding='utf-8'))
        _bank=(rows,np.asarray([feature(Image.open(ROOT/r['file']).convert('RGB')) for r in rows]))
    return _bank
def selected_slot(image):
    if image.width/image.height<1.6:return ''
    from core import SLOTS
    import numpy as np
    counts=[]
    for fraction in (.743,.788,.832,.876,.920,.964):
        cx=int(image.width*fraction);cy=int(image.height*.244);a=np.asarray(image.crop((cx-30,cy-24,cx+30,cy+27))).astype(int);r,g,b=a[:,:,0],a[:,:,1],a[:,:,2]
        counts.append(int(((b>110)&(g>55)&(b>r*1.5)&(g>r*1.2)).sum()))
    order=sorted(range(6),key=lambda i:counts[i],reverse=True)
    return SLOTS[order[0]] if counts[order[0]]>100 and counts[order[0]]>counts[order[1]]*1.8 else ''
def read_equipment_icon(image,result,level_y):
    import numpy as np,cv2
    rows,_=load_bank();words=[w for line in result.get('lines',[]) for w in line.get('words',[])]
    anchors=[w for w in words if w['text'].strip()=='85' and 100<w['y']<level_y-100 and w.get('confidence',1)>.7]
    if anchors:
        word=anchors[0];ax=word['x']-10;ay=word['y']-10;guess=max(110,min(250,word['h']*5.8))
    elif image.width/image.height>1.6:ax=image.width*.36;ay=image.height*.365;guess=image.width*.079
    else:ax=image.width*.44;ay=image.height*.197;guess=image.width*.128
    left=max(0,int(ax-24));top=max(0,int(ay-24));right=min(image.width,int(ax+guess*1.45));bottom=min(image.height,int(ay+guess*1.45))
    target=np.asarray(ImageOps.grayscale(image.crop((left,top,right,bottom))))
    confirmed=selected_slot(image);best=(-1,0,0,0,120)
    scales=np.linspace(max(90,guess*.66),min(290,guess*1.45),20)
    patches=[]
    for record in rows:
        with Image.open(ROOT/record['file']) as source:patches.append(np.asarray(ImageOps.grayscale(source.crop((22,22,85,82)))))
    def trial(index,side):
        patch=cv2.resize(patches[index],(round(63*side/120),round(60*side/120)))
        if patch.shape[0]>=target.shape[0] or patch.shape[1]>=target.shape[1]:return (-1,index,0,0,side)
        scores=cv2.matchTemplate(target,patch,cv2.TM_CCOEFF_NORMED);_,score,_,location=cv2.minMaxLoc(scores)
        return (score,index,left+location[0]-round(22*side/120),top+location[1]-round(22*side/120),side)
    for index,record in enumerate(rows):
        if confirmed and record['slot']!=confirmed:continue
        for side in scales:
            found=trial(index,float(side))
            if found[0]>best[0]:best=found
    for side in np.linspace(max(80,best[4]-10),best[4]+10,21):
        found=trial(best[1],float(side))
        if found[0]>best[0]:best=found
    score,index,x,y,side=best;record=rows[index];x,y,side=round(x),round(y),round(side)
    slot=confirmed or (record['slot'] if score>=.86 else '')
    name=record['name'] if score>=.94 else ''
    from panel_reader import color_grade
    grade=color_grade(image,(x,y,x+side,y+side))
    set_scores={}
    region=image.crop((round(x+side*.58),round(y+side*.52),round(x+side*1.12),round(y+side*1.10)))
    roi=np.asarray(ImageOps.grayscale(region))
    for sample in rows:
        if not sample.get('set'):continue
        with Image.open(ROOT/sample['file']) as item:badge=np.asarray(ImageOps.grayscale(item.crop((79,73,122,119))))
        for ratio in (.88,.94,1,1.06,1.12):
            template=cv2.resize(badge,(round(43*side/120*ratio),round(46*side/120*ratio)))
            if template.shape[0]>roi.shape[0] or template.shape[1]>roi.shape[1]:continue
            value=float(cv2.minMaxLoc(cv2.matchTemplate(roi,template,cv2.TM_CCOEFF_NORMED))[1])
            set_scores[sample['set']]=max(set_scores.get(sample['set'],-1),value)
    ranked=sorted(set_scores.items(),key=lambda r:r[1],reverse=True)
    setname=ranked[0][0] if ranked and ranked[0][1]>=.86 and (len(ranked)==1 or ranked[0][1]-ranked[1][1]>=.04) else ''
    from set_icons import match_set_badge
    full_name,full_score=match_set_badge(region)
    if full_name:setname=full_name
    return {'slot':slot,'name':name,'grade':grade,'set_name':setname,'appearance_score':score,'set_score':ranked[0][1] if ranked else 0,'box':[x,y,x+side,y+side]}
