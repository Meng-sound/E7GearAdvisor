"""Only explicit, locally sourced loadout metadata. Never defaults to +30."""
import json
import math
import re
from pathlib import Path
from functools import lru_cache
from core import Gear,Stat
from fribbels_gs import item_score
from character_bs import SET_SIZE,SET_ALIASES

ROOT=Path(__file__).parent/'data'

def read_imprint_text(text):
    """Read a complete self-concentration section, excluding team bonuses."""
    text=text.translate(str.maketrans({'傳':'传','裝':'装','擊':'击','傷':'伤','禦':'御','％':'%','＋':'+'}))
    text=text.replace('生命力','生命值').replace('效果抵抗','效果抗性')
    lines=[re.sub(r'[ \t]+','',line) for line in text.splitlines() if line.strip()]
    values=[]
    labels={'攻击力':'atk','生命值':'hp','防御力':'def','速度':'spd','暴击率':'crit','暴击伤害':'cdmg','效果命中':'eff','效果抗性':'res'}
    pattern=r'(攻击力|生命值|防御力|速度|暴击率|暴击伤害|效果命中|效果抗性)\s*\+?\s*(\d+(?:\.\d+)?)\s*(%)?'
    for index,line in enumerate(lines):
        if '刻印集中' not in line:continue
        section=[line.split('刻印集中',1)[1]]
        for following in lines[index+1:index+5]:
            if any(word in following for word in ('刻印释放','刻印效果','阵型','神器','套装','专属装备','刻印集中')):break
            section.append(following)
        # Joining a few adjacent lines handles OCR splitting a label and its value.
        for match in re.finditer(pattern,'\n'.join(section)):
            key=labels[match[1]];value=float(match[2]);percent=bool(match[3])
            if key in {'crit','cdmg','eff','res'} and not percent:continue
            if key=='spd' and percent:continue
            if not 0<=value<=(100 if percent else 10000):continue
            values.append((key,value,percent))
    unique=set(values)
    if len(unique)!=1:return None
    key,value,percent=unique.pop()
    return {'key':key,'value':value,'percent':percent,'scope':'self'}

@lru_cache(maxsize=1)
def artifacts():
    path=ROOT/'artifact-stats.json'
    return json.loads(path.read_text('utf8')).get('artifacts',{}) if path.exists() else {}

def artifact_stats(code,level):
    if type(level) is not int or not 0<=level<=30:raise ValueError('神器强化等级应为0至30')
    record=artifacts().get(code)
    if record is None:raise ValueError('当前资料没有该神器白字，请手动核对')
    # Fribbels artifact.js: base * (1 + 12 * level/30), to tenths.
    return {key:math.floor(record[key]*(1+.4*level)*10+.5)/10 for key in ('atk','hp')}

def artifact_progression(code):
    rows=[];previous=None
    for level in range(31):
        stats=artifact_stats(code,level)
        rows.append(dict(level=level,**stats,delta_atk=round(stats['atk']-previous['atk'],1) if previous else 0,
                         delta_hp=round(stats['hp']-previous['hp'],1) if previous else 0))
        previous=stats
    return rows

def artifact_level_near_name(words,names):
    clean=lambda value:re.sub(r'\s+','',value).casefold()
    anchors=[word for word in words if any(len(name)>=3 and clean(name) in clean(str(word.get('text',''))) for name in names)]
    levels=set()
    for anchor in anchors:
        for word in words:
            cy=word['y']+word.get('h',0)/2;ay=anchor['y']+anchor.get('h',0)/2
            if abs(cy-ay)>max(20,anchor.get('h',20)*1.2):continue
            if word['x']+word.get('w',0)<anchor['x']-80 or word['x']>anchor['x']+anchor.get('w',0)+80:continue
            levels.update(int(v) for v in re.findall(r'\+\s*(\d{1,2})(?!\d)',str(word.get('text',''))) if int(v)<=30)
    return next(iter(levels)) if len(levels)==1 else None

@lru_cache(maxsize=1)
def artifact_icon_bank():
    import numpy as np
    from PIL import Image,ImageOps
    rows=[]
    for path in (ROOT/'artifact-icons').glob('*.png'):
        with Image.open(path) as source:
            image=source.convert('RGB');w,h=image.size
            image=image.crop((round(w*.18),round(h*.18),round(w*.82),round(h*.82)))
            rows.append((path.stem,np.asarray(ImageOps.grayscale(image))))
    return rows

def match_artifact_icon(region,overview=False):
    import cv2,numpy as np
    from PIL import ImageOps
    array=np.asarray(ImageOps.grayscale(region));scores=[]
    for code,source in artifact_icon_bank():
        best=(-1,None)
        for height in (range(60,171,2) if overview else (24,32,40,48,60,76)):
            width=round(source.shape[1]*height/source.shape[0])
            if width>array.shape[1] or height>array.shape[0]:continue
            template=cv2.resize(source,(width,height))
            _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(array,template,cv2.TM_CCOEFF_NORMED))
            if score>best[0]:best=(score,(*point,width,height))
        scores.append((best[0],code,best[1]))
    scores.sort(reverse=True)
    if len(scores)<2 or scores[0][0]<.92 or scores[0][0]-scores[1][0]<.12:return None
    return {'code':scores[0][1],'box':scores[0][2],'confidence':scores[0][0]}

def read_loadout_text(text,hero=None):
    result={'sets':[],'artifact':None,'imprint':None,'warnings':[]}
    text=text.replace('傳說','传说').replace('裝','装').replace('％','%')
    for line in text.splitlines():
        match=re.search(r'([\u4e00-\u9fff]{2,5})套装\s*[（(]?\s*(\d+)\s*/\s*(\d+)',line)
        if match:
            name=SET_ALIASES.get(match[1],match[1]);have=int(match[2]);need=int(match[3])
            if name in SET_SIZE and need==SET_SIZE[name] and have>=need:
                result['sets'].extend([name]*(have//need))
    if sum(SET_SIZE[name] for name in result['sets'])>6:
        result['sets']=[];result['warnings'].append('套装计数冲突，需核对')
    if not result['sets']:result['warnings'].append('未读到明确成套计数，套装待确认')
    catalog=json.loads((ROOT/'artifact-catalog.json').read_text('utf8'))['artifacts']
    candidates=[]
    compact=re.sub(r'\s+','',text).casefold()
    for code,record in catalog.items():
        names=[record.get('name',''),record.get('name_en','')]
        matched=[name for name in names if len(name)>=3 and re.sub(r'\s+','',name).casefold() in compact]
        if matched:candidates.append((max(map(len,matched)),code,matched))
    candidates.sort(reverse=True)
    if candidates and (len(candidates)==1 or candidates[0][0]>candidates[1][0]):
        _,code,names=candidates[0]
        levels=set()
        # Only +N on the same line as the artifact name; equipment +15 is unrelated.
        for line in text.splitlines():
            if any(re.sub(r'\s+','',name).casefold() in re.sub(r'\s+','',line).casefold() for name in names):
                levels.update(int(v) for v in re.findall(r'\+\s*(\d{1,2})(?!\d)',line) if int(v)<=30)
        record=dict(code=code,name=catalog[code]['name'],level=next(iter(levels)) if len(levels)==1 else None)
        if record['level'] is not None:
            try:record.update(artifact_stats(code,record['level']))
            except ValueError as error:result['warnings'].append(str(error))
        else:result['warnings'].append('神器已识别，强化等级未确定')
        result['artifact']=record
    else:result['warnings'].append('神器待确认，未按卸下或+30处理')
    result['imprint']=read_imprint_text(text)
    if result['imprint'] is None:result['warnings'].append('刻印类型或数值未读全，不能仅凭SSS自动扣除')
    return result

def empty_artifact_slot(image):
    """Require a visual match to the empty hexagon, not absence of an icon match."""
    from PIL import Image,ImageOps
    import cv2,numpy as np
    path=ROOT/'artifact-empty-slot.png'
    if not path.is_file():return False
    region=image.crop((1300,170,1480,365)).convert('RGB')
    with Image.open(path) as source:template=source.convert('RGB')
    a=np.asarray(ImageOps.grayscale(region));b=np.asarray(ImageOps.grayscale(template))
    score=float(cv2.matchTemplate(a,b,cv2.TM_CCOEFF_NORMED)[0,0])
    error=float(np.abs(np.asarray(region).astype(float)-np.asarray(template).astype(float)).mean())
    return score>=.94 and error<18

def read_loadout_image(image,ocr,directory,hero=None):
    """Adapt the reader's 1821x1055 title-padded frame to client-only coordinates."""
    from PIL import Image
    if image.size==(1821,1055):
        image=image.crop((0,30,1821,1055)).resize((1920,1080),Image.Resampling.LANCZOS)
    path=Path(directory)/'hero-loadout.png';image.save(path)
    raw=ocr.request(path=str(path));result=read_loadout_text(raw.get('text',''),hero)
    if image.size==(1920,1080):
        strip=image.crop((110,910,540,1080)).resize((860,340));strip_path=Path(directory)/'active-set-names.png';strip.save(strip_path)
        strip_text=ocr.request(path=str(strip_path)).get('text','').replace('生命值','生命').replace('裝','装')
        from set_icons import canonical
        aliases={**{name:name for name in SET_SIZE},**SET_ALIASES,
                 '生命值':'生命','守护':'保护','穿透':'贯穿','团结':'夹攻'}
        pattern='('+'|'.join(re.escape(name) for name in sorted(aliases,key=len,reverse=True))+')套装'
        names=[canonical(aliases[name]) for name in re.findall(pattern,re.sub(r'\s+','',strip_text))]
        if names and sum(SET_SIZE.get(name,7) for name in names)<=6:
            result['sets']=names
            result['warnings']=[w for w in result['warnings'] if '套装' not in w]
    from hero_imprints import read_active_imprint,read_popup_profiles
    words=[word for line in raw.get('lines',[]) for word in line.get('words',[])]
    result['imprint_profiles']=read_popup_profiles(words,image.width,hero)
    region=image.crop((110,330,540,570));region_path=Path(directory)/'hero-imprint.png';region.save(region_path)
    active=read_active_imprint(ocr.request(path=str(region_path)).get('text',''),hero)
    result['imprint_state']=active
    if result['imprint_profiles']:
        result['imprint']=None
        result['imprint_state']={'mode':'unknown','rank':None,'reason':'已读取两种刻印等级表，请核对当前启用类型与等级'}
    elif active['mode']=='locked':
        result['imprint']=None
        result['warnings']=[w for w in result['warnings'] if '刻印' not in w]
    elif active.get('value') and active['mode']=='self':result['imprint']=active['value']
    if empty_artifact_slot(image):
        result['artifact']={'name':'已卸下','code':None,'level':None,'atk':0,'hp':0,'equipped':False}
        result['warnings']=[w for w in result['warnings'] if '神器' not in w]
    if result['artifact'] and result['artifact'].get('equipped') is not False and result['artifact'].get('level') is None:
        record=result['artifact'];level=artifact_level_near_name(words,[record['name'],artifacts().get(record['code'],{}).get('name_en','')])
        if level is not None:
            record['level']=level
            try:record.update(artifact_stats(record['code'],level))
            except ValueError:pass
            result['warnings']=[w for w in result['warnings'] if w!='神器已识别，强化等级未确定']
    if result['artifact'] is None:
        words=[word for line in raw.get('lines',[]) for word in line.get('words',[])]
        anchors=[]  # Character overview has a fixed artifact slot; OCR labels may belong to other UI.
        if len(anchors)<=1:
            if anchors:
                anchor=anchors[0];left=max(0,round(anchor['x']-90));top=max(0,round(anchor['y']-100))
                region=image.crop((left,top,min(image.width,left+300),min(image.height,top+300)))
            else:
                left=round(image.width*.66);top=round(image.height*.14)
                region=image.crop((left,top,round(image.width*.79),round(image.height*.36)))
            match=match_artifact_icon(region,overview=True)
            if match:
                x,y,w,h=match['box'];x+=left;y+=top;levels=set()
                for word in words:
                    cx=word['x']+word['w']/2;cy=word['y']+word['h']/2
                    if x-w*.15<=cx<=x+w*1.15 and y-h*.15<=cy<=y+h*1.15:
                        levels.update(int(v) for v in re.findall(r'\+\s*(\d{1,2})(?!\d)',word.get('text','')) if int(v)<=30)
                code=match['code'];catalog=json.loads((ROOT/'artifact-catalog.json').read_text('utf8'))['artifacts']
                if not levels:
                    badge=image.crop((max(0,round(x+w*.6)),max(0,round(y-h*.2)),min(image.width,round(x+w*1.35)),min(image.height,round(y+h*.4))))
                    badge=badge.resize((badge.width*3,badge.height*3))
                    badge_path=Path(directory)/'artifact-enhancement.png';badge.save(badge_path)
                    badge_text=ocr.request(path=str(badge_path)).get('text','').replace('＋','+')
                    levels.update(int(v) for v in re.findall(r'\+\s*(\d{1,2})(?!\d)',badge_text) if int(v)<=30)
                record={'code':code,'name':catalog.get(code,{}).get('name',code),'level':next(iter(levels)) if len(levels)==1 else None,'icon_confidence':match['confidence']}
                if record['level'] is not None:
                    try:record.update(artifact_stats(code,record['level']))
                    except ValueError as error:result['warnings'].append(str(error))
                result['artifact']=record
                result['warnings']=[w for w in result['warnings'] if '神器待确认' not in w]
                if record['level'] is None:result['warnings'].append('神器图标已识别，强化等级仍待确认')
    from set_icons import match_set_badge
    # Dedicated active-set strip, not the six equipment slots.
    if not result['sets']:
        found=[]
        for x in range(140,465,20):
            region=image.crop((x,935,x+64,1005)).convert('RGB')
            gold=sum(r>145 and g>95 and r>b*1.5 for r,g,b in region.getdata())
            if gold<12:continue
            name,score=match_set_badge(region,threshold=.91,margin=.05)
            name=SET_ALIASES.get(name,name)
            if name in SET_SIZE and (not found or x-found[-1][0]>45):found.append((x,name))
        names=[name for _,name in found]
        if names and sum(SET_SIZE[name] for name in names)<=6:
            result['sets']=names;result['sets_source']='active-strip icons'
            result['warnings']=[warning for warning in result['warnings'] if '成套计数' not in warning]
    return result

TYPES={'Attack':'atk','Health':'hp','Defense':'def','Speed':'spd','AttackPercent':'atk_pct','HealthPercent':'hp_pct',
       'DefensePercent':'def_pct','CriticalHitChancePercent':'crit','CriticalHitDamagePercent':'cdmg',
       'EffectivenessPercent':'eff','EffectResistancePercent':'res'}
SLOTS={'Weapon':'武器','Helmet':'头盔','Armor':'铠甲','Necklace':'项链','Ring':'戒指','Boots':'鞋子'}

def equipped_total(data,hero,panel):
    """Resolve six items bound to this hero in a Fribbels export, not any six items."""
    if not isinstance(data,dict) or not isinstance(data.get('items'),list):raise ValueError('需要含items的Fribbels角色装备导出JSON')
    names={hero['id'],hero['name'],hero.get('name_en',''),*hero.get('aliases',[])}-{''}
    chosen=[row for row in data.get('heroes',[]) if isinstance(row,dict) and (row.get('id')==hero['id'] or row.get('name') in names)]
    if len(chosen)>1:raise ValueError('有多个同名角色，请先消除绑定歧义')
    owner=chosen[0].get('id') if chosen else hero['id']
    if not isinstance(owner,str) or not owner:raise ValueError('角色绑定ID缺失，不能使用未装备物品')
    rows=[row for row in data['items'] if isinstance(row,dict) and row.get('equippedBy')==owner]
    if len(rows)!=6:raise ValueError('没有读到该角色完整绑定的六件装备，不能从面板反推装备总分')
    slots=set();ids=set();score=0;item_scores=[]
    for row in rows:
        slot=SLOTS.get(row.get('gear'))
        if slot is None or slot in slots or not isinstance(row.get('id'),str) or not row['id'] or row['id'] in ids:raise ValueError('装备槽位或ID重复/不完整')
        slots.add(slot);ids.add(row['id']);subs=row.get('substats')
        if not isinstance(subs,list) or len(subs)!=4:raise ValueError('每件装备需要四条完整副属性')
        stats=[]
        for sub in subs:
            if not isinstance(sub,dict) or sub.get('type') not in TYPES:raise ValueError('副属性类型无效')
            value=sub.get('value')
            if type(value) not in (int,float) or not math.isfinite(value) or value<0:raise ValueError('副属性数值无效')
            stats.append(Stat(TYPES[sub['type']],value))
        if len({stat.key for stat in stats})!=4:raise ValueError('副属性重复')
        points=item_score(Gear(subs=stats));score+=points
        item_scores.append({'slot':slot,'score':points})
    if not all(type(panel.get(key)) in (int,float) and math.isfinite(panel[key]) and panel[key]>=0 for key in ('crit','cdmg')):
        raise ValueError('请先读取当前面板暴击率和暴击伤害，用于参考面板同款溢出扣分')
    crit_penalty=max(0,panel['crit']-100)*1.6
    cdmg_penalty=max(0,panel['cdmg']-350)*1.14
    adjusted=math.ceil(score-crit_penalty-cdmg_penalty)
    if adjusted<0:raise ValueError('溢出扣分超过装备总分，当前面板与绑定装备不一致')
    return {'gear_score':adjusted,'uncapped_score':score,'item_scores':item_scores,
            'crit_penalty':crit_penalty,'cdmg_penalty':cdmg_penalty,
            'source':'Fribbels绑定装备；同Hero Library溢出扣分'}
