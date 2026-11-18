"""Equipment-detail parsing shared by the enhancement and inventory screens."""
import re,base64,io
from pathlib import Path
from PIL import Image
from core import Gear,Stat,parse_text,parse_stat,_clean,SETS
from screen_metadata import _number,official_score_lines,_orange
from stat_rows import read_stat_rows
from adaptive_reader import header_metadata
from set_icons import canonical

SET_ALIASES={'夾攻':'夹攻','命中':'命中','貫穿':'贯穿','穿透':'穿透','傷口':'伤口','復仇':'复仇','憤怒':'愤怒','暴擊':'暴击','破滅':'破灭','防禦':'防御','開戰':'开战','追擊':'追击','逆襲':'逆袭','回擊':'回击','弱化':'弱化','全力':'全力'}
SLOT_ALIASES={'鎧甲':'铠甲','盔甲':'铠甲','皮甲':'铠甲','靴子':'鞋子','靴':'鞋子','頭盔':'头盔','項鍊':'项链','項鏈':'项链','項链':'项链','戒指':'戒指','武器':'武器','頭部':'头盔'}

def augment_names(gear,text):
    cleaned=_clean(text)
    # Never discard a new set solely because it was absent from a hardcoded list.
    sets=[name for line in text.splitlines() for name in re.findall(r'([\u4e00-\u9fff]{1,8})套[装裝莊妆]',_clean(line))]
    if sets:
        name=sets[-1]
        name=re.sub(r'^等(?=生命|防御|攻击)','',name)
        name={'生命值':'生命','防御力':'防御','攻击力':'攻击'}.get(name,name)
        gear.set_name=canonical(SET_ALIASES.get(name,name))
        if gear.set_name not in SETS:
            gear.set_name=next((known for known in sorted(SETS,key=len,reverse=True) if gear.set_name.endswith(known)),gear.set_name)
    header='\n'.join(text.splitlines()[:8])
    for alias,slot in SLOT_ALIASES.items():
        if alias in _clean(header):gear.slot=slot;break
    return gear

def color_grade(image,box):
    crop=image.crop(box).convert('RGB');w,h=crop.size;counts={'史诗':0,'英雄':0,'稀有':0}
    for y in range(18,max(19,h-12),2):
      for x in [8,12,16,w-9,w-13,w-17]:
        r,g,b=crop.getpixel((max(0,min(w-1,x)),y))
        if r>65 and r>g*1.55 and r>b*1.7:counts['史诗']+=1
        elif r>45 and b>45 and r>g*1.5 and b>g*1.35:counts['英雄']+=1
        elif b>65 and b>r*1.4 and b>g*1.1:counts['稀有']+=1
    ranked=sorted(counts,key=counts.get,reverse=True)
    return ranked[0] if counts[ranked[0]]>=18 and counts[ranked[0]]>counts[ranked[1]]*1.25 else ''

def detail_grade(image,text):
    header=_clean('\n'.join(text.splitlines()[:3]))
    for words,grade in [(('传说','傳說','史诗','史詩'),'史诗'),(('英雄',),'英雄'),(('稀有',),'稀有')]:
        if any(word in header for word in words):return grade
    # Sample the empty panel backdrop, away from the equipment artwork.
    pixels=list(image.crop((1510,235,1640,282)).convert('RGB').getdata())
    red=sum(r>35 and r>g*1.6 and r>b*1.6 for r,g,b in pixels)
    purple=sum(r>30 and b>25 and r>g*1.5 and b>g*1.4 for r,g,b in pixels)
    blue=sum(b>35 and b>r*1.45 and b>g*1.1 for r,g,b in pixels)
    scores={'史诗':red,'英雄':purple,'稀有':blue};best=max(scores,key=scores.get)
    return best if scores[best]>len(pixels)*.45 else ''

def try_inventory(image,ocr,directory):
    crop=image.crop((1210,220,1780,min(880,image.height)))
    path=Path(directory)/'inventory-right.png';crop.save(path)
    result=ocr.request(path=str(path));text=result['text']
    stats=[parse_stat(line) for line in text.splitlines()];stats=[s for s in stats if s]
    if not re.search(r'套[装裝]',_clean(text)):return None
    gear=augment_names(parse_text(text),text)
    # All stats come only from the right detail panel, never the grid on the left.
    precise=read_stat_rows(crop,result,ocr,directory,body=(240,510))
    if len(precise)>=len(stats):stats=precise
    if len(stats)<2:return None
    gear.main=stats[0];gear.subs=stats[1:5]
    for line in result.get('lines',[]):
        words=line.get('words',[])
        if words and 90<sum(w['y']+w['h']/2 for w in words)/len(words)<150:
            name=_clean(''.join(w['text'] for w in sorted(words,key=lambda w:w['x'])))
            if len(name)>3:gear.name=name;break
    detected=detail_grade(image,text)
    if detected:gear.grade=detected
    anchored=header_metadata(result,crop.width,crop.height)
    level=anchored['level']
    if level is None:level=_number(ocr,image.crop((1264,290,1293,313)),directory,'inventory-level-tight')
    if level is None:level=_number(ocr,image.crop((1255,280,1302,320)),directory,'inventory-level-expanded')
    if level is None or level<50:level=_number(ocr,image.crop((1250,277,1310,322)),directory,'inventory-level-wide')
    if level is not None and 50<=level<=99:gear.level=level
    else:level=None;gear.level=None
    badge=anchored['enhance']
    if badge is None and _orange(image.crop((1330,262,1384,296))):badge=_number(ocr,image.crop((1330,262,1384,296)),directory,'inventory-badge',True)
    if badge is not None and 0<=badge<=15:gear.enhance=badge
    elif level is not None and not _orange(image.crop((1330,262,1384,296))):gear.enhance=0
    gear.screen_score=official_score_lines(text)
    if gear.screen_score is None:
        gear.screen_score=_number(ocr,image.crop((1630,683,1755,737)),directory,'inventory-score')
    gear.warnings=[]
    buffer=io.BytesIO();crop.save(buffer,format='PNG')
    return {'kind':'single','gear':gear,'text':text,'layout':'inventory-right','screen_score':gear.screen_score,'preview_png':base64.b64encode(buffer.getvalue()).decode('ascii')}

def try_floating_detail(image,ocr,directory):
    """Read the equipment modal on a hero page, excluding the dimmed hero stats."""
    if image.width<1700 or image.height<950:return None
    pixels=list(image.crop((710,105,1100,330)).resize((39,23)).convert('RGB').getdata())
    def colored(p):
        r,g,b=p
        return max(p)>25 and ((r>g*1.45 and r>b*1.35) or (r>g*1.45 and b>g*1.3) or (b>r*1.5 and b>g*1.2))
    if sum(colored(p) for p in pixels)<len(pixels)*.65:return None
    modal=image.crop((637,89,1190,942))
    # Translate the complete modal into the shared panel reader's coordinates.
    # Its header/stat/set row geometry matches the inventory detail card.
    translated=Image.new('RGB',(1821,1100),'#07111c');translated.paste(modal,(1210,220))
    result=try_inventory(translated,ocr,directory)
    if result:
        result['layout']='hero-equipment-popup'
        result['source_note']='只读取角色页装备弹窗；不读取背后角色总面板。'
    return result
