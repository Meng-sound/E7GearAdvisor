"""Locate header fields using text boxes, rather than a fixed tiny digit crop."""
import re
from core import _clean
def header_metadata(result,panel_width,panel_height):
    words=[w for line in result.get('lines',[]) for w in line.get('words',[])]
    header=[w for w in words if w['x']<=panel_width*.42 and w['y']<=min(180,panel_height*.3)]
    fragments=sorted((w for w in header if re.fullmatch(r'[+\d]{1,3}',_clean(w['text']))),key=lambda w:w['x'])
    joined=[];superseded=set()
    for start,first in enumerate(fragments):
        group=[first];text=_clean(first['text'])
        for word in fragments[start+1:]:
            previous=group[-1];gap=word['x']-(previous['x']+previous['w']);height=min(w['h'] for w in group+[word])
            if gap<0 or gap>max(3,height*.35):break
            if abs(word['y']+word['h']/2-(first['y']+first['h']/2))>height*.55:continue
            if len(text+_clean(word['text']))>3:break
            text+=_clean(word['text']);group.append(word)
        if len(group)>1 and re.fullmatch(r'(?:[5-9]\d|\+(?:1[0-5]|[0-9]))',text):
            last=group[-1];joined.append({'text':text,'x':first['x'],'y':min(w['y'] for w in group),'w':last['x']+last['w']-first['x'],'h':max(w['y']+w['h'] for w in group)-min(w['y'] for w in group),'confidence':min(w.get('confidence',.8) for w in group)})
            superseded.update(id(w) for w in group)
    words=[w for w in words if id(w) not in superseded]+joined
    levels=[];badges=[]
    for word in words:
        if word['x']>panel_width*.42 or word['y']>min(180,panel_height*.3):continue
        text=_clean(word['text']);confidence=word.get('confidence',.8)
        if confidence<.7:continue
        if re.fullmatch(r'\+\d{1,2}',text):
            value=int(text[1:])
            if 0<value<=15:badges.append((confidence,value,word))
        elif re.fullmatch(r'\d{2}',text):
            value=int(text)
            if 50<=value<=99:levels.append((confidence,value,word))
    def winner(options):
        options=sorted(options,key=lambda x:(-x[0],x[2]['x']))
        if not options:return None
        if len({x[1] for x in options})>1 and options[0][0]-options[1][0]<.1:return None
        return options[0][1]
    return {'level':winner(levels),'enhance':winner(badges),'level_box':levels[0][2] if levels else None}
