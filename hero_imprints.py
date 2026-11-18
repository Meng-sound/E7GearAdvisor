"""Two distinct imprint profiles per hero, with explicit active-state evidence."""
import json,re,os
from functools import lru_cache
from pathlib import Path

ROOT=Path(__file__).parent/'data'
MODES={'team':'开放型刻印','self':'自身刻印','locked':'锁定 / 未刻印','unknown':'待确认'}
RANKS=('D','C','B','A','S','SS','SSS')

@lru_cache(maxsize=1)
def catalog():return json.loads((ROOT/'hero-imprints.json').read_text('utf8'))['heroes']

def profiles(hero):
    if not hero:return {}
    record=dict(catalog().get(hero['id'],{}))
    home=Path(os.environ.get('E7_ADVISOR_HOME',str(Path(__file__).parent/'userdata')))
    try:record.update(json.loads((home/'hero-imprints.json').read_text('utf8')).get(hero['id'],{}))
    except (OSError,ValueError,TypeError):pass
    return record

def imprint_value(hero,mode,rank):
    if mode=='locked':return None
    record=profiles(hero).get(mode)
    if not record or rank not in record.get('grades',{}):return None
    return dict(key=record['key'],value=record['grades'][rank],percent=record['percent'],scope='self' if mode=='self' else 'team',rank=rank,source=record['source'])

def read_active_imprint(text,hero):
    """Call only on the hero's small imprint region, never on the rank-table popup."""
    compact=re.sub(r'\s+','',text).replace('開放','开放').replace('鎖定','锁定').replace('擊','击').replace('傷','伤').replace('禦','御')
    if '刻印记忆效果' in compact or ('开放型刻印' in compact and '自身刻印' in compact):
        return {'mode':'unknown','rank':None,'reason':'刻印等级表不能证明当前启用类型'}
    if '锁定' in compact:return {'mode':'locked','rank':None,'reason':'刻印锁定，当前不计入加成'}
    ranks=set(re.findall(r'(?<![A-Z])(SSS|SS|S|A|B|C|D)(?![A-Z])',text.upper()))
    rank=next(iter(ranks)) if len(ranks)==1 else None
    mode='self' if any(x in compact for x in ('自身刻印','刻印集中')) else 'team' if any(x in compact for x in ('开放型刻印','刻印释放')) else 'unknown'
    # A visible stat label can distinguish the two fixed per-hero types.
    if mode=='unknown':
        labels={'atk':'攻击力','hp':'生命值','def':'防御力','spd':'速度','crit':'暴击率','cdmg':'暴击伤害','eff':'效果命中','res':'效果抗性','dual':'夹攻率'}
        matches=[key for key in ('team','self') if profiles(hero).get(key,{}).get('key') in labels and labels[profiles(hero)[key]['key']] in compact]
        if len(matches)==1:mode=matches[0]
    result={'mode':mode,'rank':rank,'reason':'已读取当前刻印' if mode!='unknown' and rank else '当前刻印类型或等级待确认'}
    value=imprint_value(hero,mode,rank)
    if value:result['value']=value
    return result

def read_popup_profiles(words,width,hero):
    """Read each visible column independently. This learns a table, not activation."""
    text=''.join(str(w.get('text','')) for w in words)
    if '刻印' not in text or not any(label in text for label in ('自身刻印','刻印集中')):return {}
    from character_loadout import read_imprint_text
    found={}
    for mode,left,right in (('team',width*.2,width*.5),('self',width*.5,width*.8)):
        selected=[w for w in words if left<=w['x']+w.get('w',0)/2<=right]
        lines={}
        for word in sorted(selected,key=lambda w:w['y']):
            cy=word['y']+word.get('h',0)/2
            row=next((y for y in lines if abs(y-cy)<=max(10,word.get('h',20)*.6)),None)
            lines.setdefault(cy if row is None else row,[]).append(word)
        grades={};stat=None
        for line in lines.values():
            value=' '.join(str(w['text']) for w in sorted(line,key=lambda w:w['x']))
            rank=re.search(r'(?<![A-Z])(SSS|SS|S|A|B|C|D)(?![A-Z])',value.upper())
            parsed=read_imprint_text('刻印集中\n'+value)
            if rank and parsed:
                if stat and (stat['key'],stat['percent'])!=(parsed['key'],parsed['percent']):return {}
                stat=parsed;grades[rank[1]]=parsed['value']
        if stat and len(grades)>=2:found[mode]={'key':stat['key'],'percent':stat['percent'],'grades':grades,'source':'本机游戏刻印详情OCR（请核对）'}
    return found

def save_profiles(path,hero,records):
    """Save only this hero's explicitly read tables; preserve other heroes."""
    path=Path(path)
    data=json.loads(path.read_text('utf8')) if path.exists() else {}
    data.setdefault(hero['id'],{}).update(records)
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),'utf8');temporary.replace(path)
