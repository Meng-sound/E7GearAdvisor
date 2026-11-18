"""Keep current white/gray totals; orange increments and roll counts are not totals."""
import re,json
from collections import Counter
from pathlib import Path
from PIL import Image,ImageOps,ImageDraw,ImageFont
from core import parse_stat,_clean,Stat

def read_stat_rows(panel,result,ocr,directory,body=(180,490)):
    words=[w for line in result.get('lines',[]) for w in line.get('words',[])]
    rows=[]
    for word in sorted(words,key=lambda w:(w['y']+w['h']/2,w['x'])):
        cy=word['y']+word['h']/2
        if not body[0]<cy<body[1]:continue
        row=next((r for r in rows if abs(r['cy']-cy)<min(r['h'],word['h'])*.5),None)
        if row is None:rows.append({'cy':cy,'h':word['h'],'words':[word]})
        else:row['words'].append(word)
    output=[]
    for index,row in enumerate(sorted(rows,key=lambda r:r['cy'])):
        text=''.join(w['text'] for w in sorted(row['words'],key=lambda w:w['x']))
        if '时获得' in _clean(text) or '時獲得' in _clean(text):continue
        stat=parse_stat(text)
        if stat:output.append(stat);continue
        label=parse_stat(text+'999')
        if not label:continue
        # Windows can omit thin gray '11'. OCR only its row, in numeric English.
        cy=row['cy'];crop=panel.crop((int(panel.width*.50),max(0,int(cy-19)),panel.width-10,min(panel.height,int(cy+21)))).convert('RGB')
        mask=Image.new('L',crop.size)
        mask.putdata([255 if max(p)-min(p)<85 and min(p)>65 else 0 for p in crop.getdata()])
        # Remove thin separator noise, preserve actual digit components.
        px=mask.load();seen=set()
        for y in range(mask.height):
          for x in range(mask.width):
            if not px[x,y] or (x,y) in seen:continue
            stack=[(x,y)];seen.add((x,y));points=[]
            while stack:
                a,b=stack.pop();points.append((a,b))
                for n in ((a-1,b),(a+1,b),(a,b-1),(a,b+1)):
                    if 0<=n[0]<mask.width and 0<=n[1]<mask.height and n not in seen and px[n[0],n[1]]:seen.add(n);stack.append(n)
            if max(b for a,b in points)-min(b for a,b in points)<3:
                for a,b in points:px[a,b]=0
        bounds=mask.getbbox()
        if not bounds:continue
        glyph=mask.crop(bounds)
        from vision import template_number
        templates=json.loads((Path(__file__).parent/'data/icon-signatures.json').read_text(encoding='utf-8'))['digits']
        numeric=template_number(glyph.convert('RGB'),templates)
        percentage=label.key in {'crit','cdmg','eff','res'} or '%' in _clean(text)
        if numeric is None and percentage:
            # A touching '%' can merge with the last digit. Recognize stable
            # numeric prefixes before the percent glyph, rather than orange text.
            votes=Counter()
            for cut in range(max(6,glyph.height//3),max(7,glyph.width-glyph.height//2)):
                trial=template_number(glyph.crop((0,0,cut,glyph.height)).convert('RGB'),templates)
                if trial and not trial[1] and 0<trial[0]<=100:votes[trial[0]]+=1
            if votes:
                number,count=votes.most_common(1)[0]
                if count>=3:numeric=(number,True,str(number))
        if numeric:
            key=label.key.removesuffix('_pct') if label.key in {'atk','hp','def','atk_pct','hp_pct','def_pct'} else label.key
            if key in {'atk','hp','def'} and (percentage or numeric[1]):key+='_pct'
            output.append(Stat(key,numeric[0]));continue
        height=26;glyph=glyph.resize((round(glyph.width*height/glyph.height),height))
        context=Image.new('L',(110+glyph.width,55),0)
        font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',24)
        ImageDraw.Draw(context).text((5,10),'Value',font=font,fill=255);context.paste(glyph,(100,12));mask=context
        path=Path(directory)/f'value-row-{index}.png';mask.save(path)
        raw=_clean(ocr.request(path=str(path),language='en-US').get('text',''))
        raw=re.sub('(?i)^value','',raw).replace('O','0').replace('|','1').replace('Ⅱ','11').replace('l','1').replace('I','1')
        match=re.search(r'([0-9]+(?:\.[0-9]+)?)(%?)$',raw)
        if match:
            key=label.key.removesuffix('_pct') if label.key in {'atk','hp','def','atk_pct','hp_pct','def_pct'} else label.key
            if key in {'atk','hp','def'} and match.group(2):key+='_pct'
            output.append(Stat(key,float(match.group(1))))
    return output

def isolate_game_window(image):
    image=image.convert('RGB');w,h=image.size
    if w/h<1.95:return image
    # Composite screenshots: title-bar seam between game (left) and calculator.
    expected=(h-30)*16/9;candidates=[]
    for x in range(max(20,int(expected-85)),min(w-15,int(expected+85))):
        score=0
        for y in (4,8,12,16,22,24,26,28):
            centre=sum(image.getpixel((x,y)))/3
            left=sum(image.getpixel((x-8,y)))/3;right=sum(image.getpixel((x+8,y)))/3
            if centre<215 and left>220 and right>220:score+=1
        if score>=2:candidates.append((-score,abs(x-expected),x))
    edge=min(candidates)[2] if candidates else int(expected)
    # Match the game client alone to 16:9, not game+tool to one wide image.
    return image.crop((0,0,edge,h))
