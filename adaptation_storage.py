"""Validated local JSON updates for equipment suitability; never change base stats."""
import copy,json,math,shutil
from pathlib import Path
from core import LABELS,SLOTS,SETS
from set_icons import canonical
_overrides={}

def overrides():return copy.deepcopy(_overrides)
def configure(path,catalog=None):
    global _overrides
    _overrides={}
    path=Path(path)
    if not path.exists():_overrides={};return
    payload=read_json(path)
    if catalog is not None:payload=validate_bundle(payload,catalog,allow_empty=True)
    if not isinstance(payload,dict) or payload.get('schema',1)!=1 or not isinstance(payload.get('heroes'),dict):raise ValueError('已保存的适配配置格式异常')
    _overrides={name:{**record(value,name),'hero_id':value.get('hero_id','')} for name,value in payload['heroes'].items()}

def unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('JSON重复字段：'+key)
        result[key]=value
    return result

def read_json(path):
    from local_json import read_json as read_local_json
    return read_local_json(path)

def number(value,label,maximum=1_000_000):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=maximum:raise ValueError(label+'必须是范围内的非负有限数字')
    return value

def stat_map(value,label,keys,maximum=1_000_000,complete=False):
    if not isinstance(value,dict) or not value:raise ValueError(label+'必须是非空对象')
    reverse={v:k for k,v in LABELS.items()};clean={}
    for key,n in value.items():
        key=reverse.get(key,key)
        if key not in keys:raise ValueError(label+'不支持字段：'+str(key))
        if key in clean:raise ValueError(label+'重复属性：'+key)
        clean[key]=number(n,label+'.'+key,maximum)
    if complete and set(clean)!=set(keys):raise ValueError(label+'需完整填写 atk/hp/def/spd/crit/cdmg/eff/res')
    return clean

def clean_sets(value,label):
    if not isinstance(value,list):raise ValueError(label+'必须是套装名称数组')
    result=[]
    for name in value:
        if not isinstance(name,str) or canonical(name) not in SETS:raise ValueError(label+'未知套装：'+str(name))
        result.append(canonical(name))
    return result

def record(value,label,variant=False):
    if not isinstance(value,dict):raise ValueError(label+'必须是对象')
    allowed={'id','hero_id','name','name_en','weights','sets','main','panel','sample_count','set_rates','artifact_rates','variants','source','updated_at','basis','share','note','gear_score','gear_score_samples','aggregation_version','unmatched_pieces','unreported_pieces','unknown_sets'}
    unknown=set(value)-allowed
    if unknown:raise ValueError(label+'未知字段：'+','.join(sorted(unknown)))
    if not any(k in value for k in ('weights','panel','sets','main','variants')):raise ValueError(label+'缺少 weights、panel、sets、main 或 variants')
    result={}
    for key in ('source','updated_at','basis','note','name'):
        if key in value:
            if not isinstance(value[key],str) or len(value[key])>500:raise ValueError(label+'.'+key+'需为不超过500字的文本')
            result[key]=value[key]
    if 'weights' in value:result['weights']=stat_map(value['weights'],label+'.weights',LABELS,10)
    if 'panel' in value:result['panel']=stat_map(value['panel'],label+'.panel',('atk','hp','def','spd','crit','cdmg','eff','res'),complete=True)
    if 'sets' in value:result['sets']=clean_sets(value['sets'],label+'.sets')
    if 'main' in value:
        if not isinstance(value['main'],dict):raise ValueError(label+'.main必须是部位到属性数组的对象')
        result['main']={}
        for slot,keys in value['main'].items():
            if slot not in SLOTS or not isinstance(keys,list) or any(k not in LABELS for k in keys):raise ValueError(label+'.main部位或属性无效')
            result['main'][slot]=list(dict.fromkeys(keys))
    if 'sample_count' in value:
        n=number(value['sample_count'],label+'.sample_count',1_000_000_000)
        if int(n)!=n:raise ValueError(label+'.sample_count必须是整数')
        result['sample_count']=int(n)
    if 'gear_score' in value:result['gear_score']=number(value['gear_score'],label+'.gear_score')
    if 'gear_score_samples' in value:
        n=number(value['gear_score_samples'],label+'.gear_score_samples',1_000_000_000)
        if int(n)!=n:raise ValueError('gear_score_samples 必须是整数')
        result['gear_score_samples']=int(n)
    for field in ('aggregation_version','unmatched_pieces','unreported_pieces'):
        if field in value:
            n=number(value[field],label+'.'+field,100 if field=='aggregation_version' else 6)
            if int(n)!=n:raise ValueError(field+' 必须是整数')
            result[field]=int(n)
    if 'unknown_sets' in value:
        if not isinstance(value['unknown_sets'],dict):raise ValueError('unknown_sets 格式异常')
        result['unknown_sets']={str(k):number(v,'unknown_sets',6) for k,v in value['unknown_sets'].items()}
    if 'share' in value:result['share']=number(value['share'],label+'.share',1)
    if 'set_rates' in value:
        if not isinstance(value['set_rates'],dict):raise ValueError(label+'.set_rates必须是对象')
        result['set_rates']={}
        for name,rate in value['set_rates'].items():
            name=clean_sets([name],label+'.set_rates')[0]
            if name in result['set_rates']:raise ValueError(label+'.set_rates重复套装别名')
            result['set_rates'][name]=number(rate,label+'.set_rates.'+name,1)
    if 'artifact_rates' in value:
        rates=value['artifact_rates']
        if not isinstance(rates,dict) or len(rates)>500:raise ValueError(label+'.artifact_rates格式错误')
        result['artifact_rates']={str(k):number(v,label+'.artifact_rates',1) for k,v in rates.items()}
    if 'variants' in value:
        if variant or not isinstance(value['variants'],list) or not 0<=len(value['variants'])<=50:raise ValueError(label+'.variants需为1至50个配装参考')
        result['variants']=[record(v,label+f'.variants[{i+1}]',True) for i,v in enumerate(value['variants'])]
        if any(not any(k in v for k in ('weights','panel')) for v in result['variants']):raise ValueError(label+'每个配装参考需有 weights 或 panel')
    return result

def validate_bundle(payload,catalog,allow_empty=False):
    if not isinstance(payload,dict) or payload.get('schema',1)!=1:raise ValueError('JSON需为schema=1的对象')
    heroes=payload.get('heroes')
    if not isinstance(heroes,(dict,list)) or not (0 if allow_empty else 1)<=len(heroes)<=2000:raise ValueError('heroes需为非空对象或数组，最多2000名角色')
    byid={h['id']:h for h in catalog['heroes']};names={}
    for h in catalog['heroes']:
        for name in (h['name_en'],h['name']):names.setdefault(name.casefold(),{})[h['id']]=h
    clean={}
    for key,value in (heroes.items() if isinstance(heroes,dict) else [(None,v) for v in heroes]):
        if not isinstance(value,dict):raise ValueError('角色数据必须是对象')
        identity=value.get('hero_id') or value.get('id');name=value.get('name_en') or key or value.get('name')
        hero=byid.get(identity) if identity else None
        if identity and hero is None:raise ValueError('未知角色ID：'+str(identity)+'；请先新增角色基础面板')
        if name:
            matches=names.get(str(name).casefold(),{})
            if len(matches)!=1:raise ValueError('角色名称未知或有歧义：'+str(name)+'；请使用hero_id或准确英文名')
            named=next(iter(matches.values()))
            if hero and hero['id']!=named['id']:raise ValueError('角色ID与名称不一致：'+str(name))
            hero=named
        if hero is None:raise ValueError('角色缺少hero_id或name_en')
        name=hero['name_en']
        if name in clean:raise ValueError('重复角色：'+name)
        clean[name]=record(value,name)
        clean[name]['hero_id']=hero['id']
    return {'schema':1,'source':str(payload.get('source','本地导入'))[:500],'fetched_at':str(payload.get('fetched_at',''))[:50],'heroes':clean}

def import_file(source,destination,catalog):
    incoming=validate_bundle(read_json(source),catalog)
    path=Path(destination);old=validate_bundle(read_json(path),catalog,allow_empty=True) if path.exists() else {'schema':1,'heroes':{}}
    merged={**old,'heroes':{**old['heroes'],**incoming['heroes']}}
    # Bind root provenance to each record before mixing different imports.
    for ref in incoming['heroes'].values():
        ref.setdefault('source',incoming['source']);ref.setdefault('updated_at',incoming['fetched_at'][:10])
    path.parent.mkdir(parents=True,exist_ok=True)
    text=json.dumps(merged,ensure_ascii=False,indent=2,allow_nan=False)
    if path.exists():shutil.copy2(path,path.with_suffix('.previous.json'))
    tmp=path.with_suffix('.tmp');tmp.write_text(text,encoding='utf8');tmp.replace(path);configure(path)
    return len(incoming['heroes'])

def export_bundle(builtin):
    result=copy.deepcopy(builtin);result['schema']=1;result['heroes'].update(overrides());result.pop('unavailable',None)
    return result


def clear_custom(path):
    """Clear imported suitability overrides, preserving a recovery copy."""
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    count=len(_overrides);backup=path.with_suffix('.before-clear.json')
    if path.exists():shutil.copy2(path,backup)
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'schema':1,'heroes':{}},ensure_ascii=False),encoding='utf8')
    temporary.replace(path);configure(path)
    return count,backup if backup.exists() else None
