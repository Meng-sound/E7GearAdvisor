"""Offline numerical priors for single-item suitability, not full-build guarantees."""
import json,math,copy,datetime
from pathlib import Path
from functools import lru_cache
from adaptation_storage import overrides
_cache_path=None

def primary_reference(ref):
    """One stable recommendation: median of the largest valid set cohort."""
    variants=[v for v in ref.get('variants',[]) if isinstance(v,dict) and v.get('panel')]
    return max(variants,key=lambda v:v.get('sample_count',0)) if variants else ref if ref.get('panel') else {}
def configure_cache(path):
    global _cache_path
    _cache_path=Path(path);references.cache_clear()

def merge_reference_snapshot(bundled,cached):
    """Select one coherent snapshot; old summaries must not erase shipped scores."""
    def date(record):
        try:
            value=datetime.datetime.fromisoformat(record.get('updated_at','').replace('Z','+00:00'))
            return (value if value.tzinfo else value.replace(tzinfo=datetime.timezone.utc)).timestamp()
        except (ValueError,TypeError,AttributeError):return 0
    def scored(record):
        cohorts=record.get('variants') or [record]
        return all(isinstance(v.get('gear_score'),(int,float)) and not isinstance(v['gear_score'],bool) and math.isfinite(v['gear_score']) for v in cohorts if v.get('panel')) and isinstance(record.get('gear_score'),(int,float))
    if not bundled:return copy.deepcopy(cached)
    if date(bundled)>date(cached) or (date(bundled)==date(cached) and ((scored(bundled) and not scored(cached)) or bundled.get('aggregation_version',0)>cached.get('aggregation_version',0))):
        return copy.deepcopy(bundled)
    return copy.deepcopy(cached)

@lru_cache(maxsize=1)
def references():
    try:data=json.loads((Path(__file__).parent/'data/hero-build-references.json').read_text(encoding='utf8'))
    except (OSError,ValueError):data={'heroes':{}}
    if _cache_path and _cache_path.exists():
        try:
            cache=json.loads(_cache_path.read_text(encoding='utf8'))
            for name,record in cache.get('heroes',{}).items():
                data['heroes'][name]=merge_reference_snapshot(data['heroes'].get(name,{}),record)
            # Enrich older summaries from already-saved public samples; no network/write.
            import gzip,hashlib
            from fribbels_sync import aggregate,AGGREGATION_VERSION
            storage='e7-hero-cache'
            try:
                config=json.loads((_cache_path.parent/'e7-sync-config.json').read_text(encoding='utf8'))
                relative=Path(config.get('storage_dir',storage))
                if not relative.is_absolute() and not relative.drive and not relative.root and '..' not in relative.parts:storage=str(relative)
            except (OSError,ValueError,TypeError):pass
            for name,reference in list(data['heroes'].items()):
                if reference.get('aggregation_version',0)>=AGGREGATION_VERSION and 'gear_score' in reference and all('artifact_rates' in v for v in reference.get('variants',[])):continue
                raw_path=_cache_path.parent/storage/(hashlib.sha256(name.encode('utf8')).hexdigest()[:32]+'.json.gz')
                if not raw_path.is_file():continue
                try:
                    with gzip.open(raw_path,'rt',encoding='utf8') as stream:raw=stream.read(16*1024*1024+1)
                    if len(raw)>16*1024*1024:continue
                    saved=json.loads(raw)
                    if saved.get('hero')!=name:continue
                    enriched=aggregate(name,saved['payload'])
                    for key in ('source','updated_at'):
                        if key in reference:enriched[key]=reference[key]
                    data['heroes'][name]={**reference,**enriched}
                except (OSError,ValueError,KeyError,TypeError):continue
        except (OSError,ValueError):pass
    return data

def panel_weights(panel,base,sets):
    """Estimate stat investment after base, fixed left mains and visible set bonuses.

    Artifact/imprint/passive differences cannot be reconstructed from anonymous
    final panels. These weights indicate affinity, not exact missing stats.
    """
    b={k:float(base.get(k,0)) for k in ('atk','hp','def','spd','crit','cdmg','eff','res')}
    count=lambda name:sets.count(name)
    need={}
    for key,fixed,bonus in [('atk',525,45*count('攻击')),('hp',2835,20*count('生命')-10*count('激流')),('def',310,20*count('防御'))]:
        need[key+'_pct']=max(0,100*(float(panel.get(key,b[key]))-b[key]-fixed)/max(b[key],1)-bonus)
    need['spd']=max(0,float(panel.get('spd',b['spd']))-b['spd']-math.floor(.25*b['spd'])*count('速度')-math.floor(.12*b['spd'])*count('复仇')-math.floor(.15*b['spd'])*count('逆袭'))*2
    need['crit']=max(0,min(100,float(panel.get('crit',b['crit'])))-b['crit']-12*count('暴击'))*1.5
    need['cdmg']=max(0,float(panel.get('cdmg',b['cdmg']))-b['cdmg']-60*count('破灭'))*1.1
    for key,name in [('eff','命中'),('res','抵抗')]:need[key]=max(0,float(panel.get(key,b[key]))-b[key]-20*count(name))
    ceiling=max(need.values(),default=1) or 1
    weights={key:round(value/ceiling,4) for key,value in need.items()}
    for key in ('atk','hp','def'):weights[key]=weights[key+'_pct']
    return weights

def enrich_profiles(heroes,catalog,gear):
    refs=references();custom=overrides();records={**refs.get('heroes',{}),**custom};lookup={h['name_en']:h for h in catalog['heroes']};profiles={h['name']:copy.deepcopy(h) for h in heroes}
    for name,ref in records.items():
        hero=lookup.get(name)
        if not hero:continue
        h=profiles.setdefault(name,{'name':name,'name_zh':hero['name'],'base':hero['base'],'archetype':'面板参考','main':{}})
        if h.get('custom_profile') and name not in custom:continue
        variant=primary_reference(ref) or ref
        if 'weights' in variant:h['weights']={k:variant['weights'].get(k,0) for k in __import__('core').LABELS}
        elif 'panel' in variant:h['weights']=panel_weights(variant['panel'],hero['base'],variant.get('sets',[]))
        if name in custom and 'sets' in ref:h['sets']=ref['sets'];h['_sets_defined']=True
        elif ref.get('set_rates'):h['sets']=[key for key,value in ref['set_rates'].items() if value>=.03]
        elif 'sets' in variant:h['sets']=variant['sets'];h['_sets_defined']=True
        if 'main' in ref:h['main']=ref['main']
        h['_set_basis']='导入适配数据' if name in custom else 'Fribbels成装参考'
        h['_demand_basis']='导入词条需求' if name in custom else 'Fribbels成装参考'
        h['_ref_count']=ref.get('sample_count',0);h['_set_rate']=ref.get('set_rates',{}).get(gear.set_name,0)
        h['_ref_date']=ref.get('updated_at',refs.get('fetched_at',''))[:10]
    return list(profiles.values())
