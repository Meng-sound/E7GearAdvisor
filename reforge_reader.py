"""Read both real columns of the reforge preview; orange is the after column here."""
import re,base64,io
from pathlib import Path
from PIL import Image,ImageOps
from core import Gear,Stat,parse_stat,_clean
from screen_metadata import _number

def rows_from_result(result):
    rows=[]
    for word in sorted((w for line in result.get('lines',[]) for w in line.get('words',[])),key=lambda w:(w['y']+w['h']/2,w['x'])):
        cy=word['y']+word['h']/2
        row=next((r for r in rows if abs(r['cy']-cy)<min(r['h'],word['h'])*.55),None)
        if row:row['words'].append(word)
        else:rows.append({'cy':cy,'h':word['h'],'words':[word]})
    for row in rows:row['words'].sort(key=lambda w:w['x']);row['text']=''.join(w['text'] for w in row['words'])
    return sorted(rows,key=lambda r:r['cy'])

def try_reforge(image,ocr,directory):
    # Inventory and enhancement panels never contain a paired item-level row.
    width=int(image.width*.68) if image.width/image.height>1.6 else image.width
    panel=image.crop((0,0,width,image.height))
    path=Path(directory)/'reforge-preview.png';panel.save(path)
    result=ocr.request(path=str(path));rows=rows_from_result(result)
    levelrow=next((r for r in rows if any(x in _clean(r['text']) for x in ['道具等级','道具等級'])),None)
    if levelrow is None:return None
    numbers=[w for w in levelrow['words'] if re.fullmatch(r'\d{2}',_clean(w['text']))]
    if len(numbers)!=2:
        # OCR may omit a short white '85'. Anchor both columns using main totals.
        anchor=next((r for r in rows if r['cy']>levelrow['cy'] and parse_stat(r['text'])),None)
        paired=[w for w in anchor['words'] if re.fullmatch(r'\d{2,4}',_clean(w['text']))] if anchor else []
        if len(paired)!=2:return None
        numbers=[]
        for col,word in enumerate(paired):
            right=word['x']+word['w'];cy=levelrow['cy'];box=(int(right-105),int(cy-levelrow['h']),int(right+18),int(cy+levelrow['h']))
            existing=next((w for w in levelrow['words'] if re.fullmatch(r'\d{2}',_clean(w['text'])) and abs(w['x']+w['w']-right)<65),None)
            value=int(_clean(existing['text'])) if existing else _number(ocr,panel.crop(box),directory,f'reforge-level-{col}',white=col==0)
            if value is None:return None
            numbers.append({**word,'text':str(value)})
    levels=[int(_clean(w['text'])) for w in numbers]
    if levels!=[85,90]:return None
    centres=[w['x']+w['w']/2 for w in numbers];middle=sum(centres)/2
    # Numeric columns share right-aligned centres; roll counts sit far to the left.
    left_edge=centres[0]-max(90,(centres[1]-centres[0])*.7)
    before=[];after=[];official=[None,None]
    for i,row in enumerate(rows):
        if row['cy']<=levelrow['cy']:continue
        label=''.join(w['text'] for w in row['words'] if w['x']<left_edge)
        key=parse_stat(label+'999')
        score=any(x in _clean(label) for x in ['装备分数','裝備分數'])
        if not key and not score:continue
        values=[]
        for col,(x0,x1) in enumerate([(left_edge,middle),(middle,panel.width)]):
            text=_clean(''.join(w['text'] for w in row['words'] if x0<=w['x']+w['w']/2<x1))
            text=text.replace('>','').replace('›','').replace('→','')
            match=re.fullmatch(r'[^\d]*([0-9]{1,4})(%?)[^\d]*',text)
            if not match:
                cy=row['cy'];right=numbers[col]['x']+numbers[col]['w'];tile=panel.crop((int(right-150),int(cy-row['h']*.8),int(right+18),int(cy+row['h']*.8)))
                if score:
                    n=_number(ocr,tile,directory,f'reforge-score-{col}')
                    if n is not None:values.append((float(n),False));continue
                tile=ImageOps.expand(tile,10);tile=tile.resize((tile.width*3,tile.height*3))
                valuepath=Path(directory)/f'reforge-value-{i}-{col}.png';tile.save(valuepath)
                text=_clean(ocr.request(path=str(valuepath),language='en-US').get('text',''))
                match=re.fullmatch(r'[^\d]*([0-9]{1,4})(%?)[^\d]*',text)
            if not match:
                if score:values.append((None,False));continue
                return None
            values.append((float(match.group(1)),bool(match.group(2))))
        if score:official=[v[0] for v in values];continue
        for output,value in zip((before,after),values):
            statkey=key.key.removesuffix('_pct')
            if statkey in {'atk','hp','def'} and value[1]:statkey+='_pct'
            output.append(Stat(statkey,value[0]))
    if len(before)!=5 or len(after)!=5:return None
    first=Gear(level=85,enhance=15,main=before[0],subs=before[1:],screen_score=official[0])
    second=Gear(level=90,enhance=15,main=after[0],subs=after[1:],screen_score=official[1])
    from equipment_icons import read_equipment_icon
    details=read_equipment_icon(image,result,levelrow['cy'])
    for gear in (first,second):
        for key in ('slot','name','grade','set_name'):setattr(gear,key,details[key])
    buffer=io.BytesIO();panel.save(buffer,format='PNG')
    return {'kind':'single','layout':'reforge-preview','gear':first,'reforge_after':second.to_dict(),'text':result['text'],'icon_details':details,'preview_png':base64.b64encode(buffer.getvalue()).decode('ascii')}
