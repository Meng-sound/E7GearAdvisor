"""Public-data synchronization only. No telemetry, cookies or player uploads."""
import json,urllib.request,urllib.error,statistics,collections,datetime,hashlib,math
from urllib.parse import urlsplit,parse_qs
from pathlib import Path
BASE_URL='https://e7-optimizer-game-data.s3-accelerate.amazonaws.com/herodata.json'
BUILD_URL='https://krivpfvxi0.execute-api.us-west-2.amazonaws.com/dev/getBuilds'
ALLOWED={'e7-optimizer-game-data.s3-accelerate.amazonaws.com','krivpfvxi0.execute-api.us-west-2.amazonaws.com','raw.githubusercontent.com'}
FOUR={'set_att','set_counter','set_cri_dmg','set_rage','set_revenge','set_scar','set_speed','set_vampire','set_shield','set_revenant','set_riposte','set_opener','set_warfare','set_weakening'}
SETS={'set_acc':'命中','set_att':'攻击','set_coop':'夹攻','set_counter':'反击','set_cri_dmg':'破灭','set_cri':'暴击','set_def':'防御','set_immune':'免疫','set_max_hp':'生命','set_penetrate':'贯穿','set_rage':'愤怒','set_res':'抵抗','set_revenge':'复仇','set_scar':'伤口','set_speed':'速度','set_vampire':'吸血','set_shield':'保护','set_torrent':'激流','set_revenant':'逆袭','set_riposte':'回击','set_opener':'开战','set_warfare':'开战','set_pursuit':'追击','set_weakening':'弱化','set_fervor':'全力'}
SETS.update({'set_weak':'弱化','set_chase':'追击','set_might':'全力'})
FOUR.add('set_weak')
AGGREGATION_VERSION=4
FIELDS={'atk':'atk','hp':'hp','def':'def','spd':'spd','chc':'crit','chd':'cdmg','eff':'eff','efr':'res'}
def hero_from_url(url):
 p=urlsplit(url.strip())
 if p.scheme!='https' or p.hostname!='fribbels.github.io' or p.path!='/e7/hero-library.html' or p.username or p.password or p.port:raise ValueError('请粘贴Fribbels Hero Library的英雄链接')
 values=parse_qs(p.query).get('hero',[])
 if len(values)!=1 or not 1<=len(values[0])<=120 or any(ord(c)<32 for c in values[0]):raise ValueError('链接缺少有效的hero参数')
 return values[0]

class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args):raise ValueError('数据源发生跳转，已停止同步；不会改用不明遥测地址')
def fetch_json(url,body=None):
 p=urlsplit(url)
 if p.scheme!='https' or p.hostname not in ALLOWED or p.username or p.password:raise ValueError('不支持的数据源地址')
 headers={'Accept':'application/json','User-Agent':'E7GearAdvisor local-data-sync'}
 if body is not None:headers.update({'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','Origin':'https://fribbels.github.io','Referer':'https://fribbels.github.io/'})
 request=urllib.request.Request(url,data=body,headers=headers,method='POST' if body is not None else 'GET')
 with urllib.request.build_opener(NoRedirect()).open(request,timeout=25) as response:raw=response.read(16*1024*1024+1)
 if len(raw)>16*1024*1024:raise ValueError('数据源返回过大')
 return json.loads(raw)
def save_atomic(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8');tmp.replace(path)
def decode_sets(raw):
 if not isinstance(raw,dict):raise ValueError('套装数据格式异常')
 known={};unknown={};total=0
 for code,value in raw.items():
  if isinstance(value,bool):raise ValueError('套装件数无效')
  count=int(value)
  if (isinstance(value,float) and value!=count) or not 0<=count<=6:raise ValueError('套装件数无效')
  total+=count
  if code not in SETS:
   if count:unknown[str(code)]=count
   continue
  name=SETS[code];previous,needed=known.get(name,(0,4 if code in FOUR else 2));known[name]=(previous+count,needed)
 if total>6:raise ValueError('套装件数超过六件')
 active=tuple(sorted(name for name,(count,needed) in known.items() for _ in range(count//needed)))
 loose=sum(count%needed for count,needed in known.values())
 return active,loose,tuple(sorted(unknown.items())),6-total

def aggregate(name,payload):
 rows=[];layouts={}
 for r in payload.get('data',[]):
  if not isinstance(r,dict) or any(not isinstance(r.get(k),(int,float)) or isinstance(r[k],bool) or not 0<=r[k]<=1_000_000 for k in FIELDS):continue
  if r.get('unitName',name)!=name:continue
  try:layouts[id(r)]=decode_sets(r.get('sets',{}))
  except (ValueError,TypeError):continue
  rows.append(r)
 if not rows:raise ValueError('该英雄暂未返回有效配装样本')
 def summary(items,sets=None,layout=None):
  result={'sample_count':len(items),'panel':{out:statistics.median(r[key] for r in items) for key,out in FIELDS.items()},'sets':list(sets or ())}
  scores=[math.ceil(r['gs']-max(0,r['chc']-100)*1.6-max(0,r['chd']-350)*1.14) for r in items if isinstance(r.get('gs'),(int,float)) and not isinstance(r['gs'],bool) and math.isfinite(r['gs']) and 0<=r['gs']<=1_000_000]
  scores=[score for score in scores if score>=0]
  if scores:result.update(gear_score=statistics.median(scores),gear_score_samples=len(scores))
  artifacts=collections.Counter(str(r['artifactCode']) for r in items if r.get('artifactCode'))
  result['artifact_rates']={k:round(v/len(items),5) for k,v in artifacts.most_common(8)}
  if layout is not None:
   result.update(unmatched_pieces=layout[1],unknown_sets=dict(layout[2]),unreported_pieces=layout[3])
  return result
 groups=collections.defaultdict(list);counts=collections.Counter();artifacts=collections.Counter()
 for r in rows:
  layout=layouts[id(r)];combo=layout[0]
  groups[layout].append(r);counts.update(set(combo))
  if r.get('artifactCode'):artifacts[str(r['artifactCode'])]+=1
 result=summary(rows);result['set_rates']={k:round(v/len(rows),5) for k,v in counts.items()};result['artifact_rates']={k:round(v/len(rows),5) for k,v in artifacts.most_common(8)}
 result['variants']=[{**summary(v,layout[0],layout),'share':round(len(v)/len(rows),5)} for layout,v in sorted(groups.items(),key=lambda p:len(p[1]),reverse=True) if len(v)>=max(5,len(rows)*.02)][:8]
 result['aggregation_version']=AGGREGATION_VERSION
 result['updated_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();result['source']='Fribbels Hero Library';return result
def fetch_reference(name):return aggregate(name,fetch_json(BUILD_URL,name.encode('utf8')))
def to_catalog_record(name,raw,cn_names=None):
 values=raw.get('calculatedStatus',{}).get('lv60SixStarFullyAwakened',{});code=raw.get('code','')
 if not code or not code.replace('_','').isalnum():raise ValueError('新英雄ID无效')
 mapping={'atk':'atk','hp':'hp','def':'def','spd':'spd','chc':'crit','chd':'cdmg','eff':'eff','efr':'res','dac':'dual'};base={}
 for source,target in mapping.items():
  v=values.get(source)
  if not isinstance(v,(int,float)) or isinstance(v,bool) or v<0:raise ValueError(name+'基础面板不完整')
  base[target]=round(v*100,5) if target in ('crit','cdmg','eff','res','dual') else v
 if min(base[k] for k in ('atk','hp','def','spd'))<=0:raise ValueError('基础面板存在零值')
 translated=(cn_names or {}).get(name,name)
 return {'id':code,'name':translated,'name_en':name,'base':base,'portrait':'diche-icon.png','element':raw.get('attribute',''),'role':raw.get('role',''),'stars':raw.get('rarity',5),'aliases':[],'archetype':'攻击暴击输出'}
def refresh_base_cache(path):
 data=fetch_json(BASE_URL)
 if not isinstance(data,dict) or not data:raise ValueError('角色数据格式异常')
 for name,record in data.items():
  if not isinstance(record,dict):raise ValueError('角色数据格式异常，未覆盖已有缓存')
  to_catalog_record(name,record)
 save_atomic(path,data);return data
def sync_references(names,path,progress=None,cancel=None,missing_only=True):
 path=Path(path)
 try:data=json.loads(path.read_text(encoding='utf8'))
 except (OSError,ValueError):data={'schema':1,'source':'https://fribbels.github.io/e7/hero-library.html','heroes':{}}
 todo=[n for n in names if not missing_only or n not in data['heroes']];success=0;errors={};failures=0;stopped=''
 for i,name in enumerate(todo):
  if cancel and cancel.is_set():break
  try:
   data['heroes'][name]=fetch_reference(name);success+=1;failures=0;data['fetched_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();save_atomic(path,data)
  except Exception as exc:
   errors[name]=type(exc).__name__+': '+str(exc)[:180];failures+=1
   if isinstance(exc,urllib.error.HTTPError) and exc.code in (401,403,429):stopped='数据源拒绝或限流，已暂停；保留已完成数据'
   elif isinstance(exc,ValueError) and '跳转' in str(exc):stopped=str(exc)
   elif failures>=3:stopped='连续3次失败，已暂停；请稍后继续'
  if progress:progress(i+1,len(todo),name,success,len(errors))
  if stopped:break
 return {'saved':success,'errors':errors,'completed':not errors and len(todo)==success,'total':len(data['heroes']),'stopped':stopped}
