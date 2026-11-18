"""Public GW statistics. Never upload images, account IDs, or battle logs."""
import collections,datetime,hashlib,itertools,json,re,time,urllib.parse,urllib.request
from pathlib import Path

ROOT=Path(__file__).parent
ARK_SOURCE=json.loads((ROOT/'data/guild-war-source.json').read_text('utf8'))
FRIBBELS_URL='https://z4tfy2r5kc.execute-api.us-west-2.amazonaws.com/dev/getDef'

def team_key(heroes):
 if len(heroes)!=3 or len(set(heroes))!=3 or any(not isinstance(h,str) or not h.strip() or len(h)>120 for h in heroes):raise ValueError('请选择三个不同的防守英雄')
 return tuple(sorted(heroes))

def count(value):
 if isinstance(value,bool) or not isinstance(value,(int,float)) or int(value)!=value or not 0<=value<=1_000_000_000:raise ValueError('胜败次数格式无效')
 return int(value)

def normalize_rows(rows,defense,catalog,source='Ark Guild War Tracker'):
 byname={h['name_en']:h['id'] for h in catalog['heroes']};byid={h['id']:h['id'] for h in catalog['heroes']};lookup={**byname,**byid}
 target=team_key(defense);groups=collections.defaultdict(lambda:{'wins':0,'losses':0,'draws':0});dates=[];seen=set();invalid=0
 for row in rows:
  try:
   defend=team_key([lookup[row['defense_hero'+str(i)]] for i in (1,2,3)])
   if defend!=target:continue
   attack=team_key([lookup[row['offense_hero'+str(i)]] for i in (1,2,3)])
   outcome=row['outcome']
   if outcome not in ('win','loss','draw'):raise ValueError('Unknown result')
   # Source outcome is the DEFENSE perspective, verified in the site source.
   field={'win':'losses','loss':'wins','draw':'draws'}[outcome]
   # API paging uses stable row IDs; imported rows without IDs remain separate.
   identity=row.get('id')
   if identity is not None:
    if identity in seen:continue
    seen.add(identity)
   groups[attack][field]+=1
   if isinstance(row.get('match_timestamp'),str):dates.append(row['match_timestamp'])
  except (ValueError,TypeError,KeyError):invalid+=1
 offenses=[{'heroes':list(team),**value,'samples':sum(value.values())} for team,value in groups.items()]
 offenses.sort(key=lambda r:(-r['samples'],-r['wins'],r['heroes']))
 return {'schema':1,'defense':list(target),'offenses':offenses,'source':source,'source_url':ARK_SOURCE['origin'],'first_match':min(dates) if dates else '', 'last_match':max(dates) if dates else '', 'invalid_rows':invalid,'fetched_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}

def validate_bundle(data):
 if not isinstance(data,dict):raise ValueError('战报 JSON 必须是对象')
 records=data.get('defenses',[data] if 'defense' in data else [])
 if not isinstance(records,list) or len(records)>10000:raise ValueError('战报数据格式异常')
 result=[]
 for record in records:
  defense=list(team_key(record['defense']));offenses=[]
  for row in record.get('offenses',[]):
   counts={k:count(row.get(k,0)) for k in ('wins','losses','draws')}
   offenses.append({'heroes':list(team_key(row['heroes'])),**counts,'samples':sum(counts.values())})
  cards=record.get('community_solutions',[])
  if not isinstance(cards,list) or len(cards)>1000:raise ValueError('社区配装列表无效或过多')
  clean_cards=[]
  for card in cards:
   if not isinstance(card,dict):raise ValueError('社区配装格式无效')
   heroes=list(team_key(card['heroes']));url=card.get('source_url','')
   if not isinstance(url,str) or not re.fullmatch(r'https://e7gw\.xyz/builds/\d+',url):raise ValueError('社区配装原文地址必须来自E7GW')
   members=card.get('members',[])
   if not isinstance(members,list) or len(members)>3:raise ValueError('社区配装成员无效')
   for member in members:
    if not isinstance(member,dict) or member.get('hero_id') not in heroes:raise ValueError('社区配装英雄不匹配')
    for field in ('name','position','stats_text','artifact_name','artifact_code','imprint','exclusive'):
     if not isinstance(member.get(field,''),str) or len(member.get(field,''))>1500:raise ValueError('社区配装字段过长或无效')
    sets=member.get('sets',[])
    if not isinstance(sets,list) or len(sets)>6 or any(not isinstance(v,str) or len(v)>80 for v in sets):raise ValueError('社区配装套装字段无效')
    if member.get('artifact_level') is not None and not 0<=count(member['artifact_level'])<=30:raise ValueError('神器等级无效')
   for field in ('notes','defense_text'):
    if not isinstance(card.get(field,''),str) or len(card.get(field,''))>10000:raise ValueError('社区说明字段过长或无效')
   clean_cards.append({**card,'heroes':heroes})
  result.append({**record,'defense':defense,'offenses':offenses,'community_solutions':clean_cards})
 return result

class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args):raise ValueError('团战数据源发生跳转，已停止读取')

def read_json(url,headers=None,body=None):
 parsed=urllib.parse.urlsplit(url)
 if parsed.scheme!='https' or parsed.hostname not in {'sdjhjdsdjrjrfktrtsch.supabase.co','z4tfy2r5kc.execute-api.us-west-2.amazonaws.com'}:raise ValueError('不支持的团战数据源')
 request=urllib.request.Request(url,data=body,headers={'Accept':'application/json',**(headers or {})},method='POST' if body is not None else 'GET')
 with urllib.request.build_opener(NoRedirect()).open(request,timeout=25) as response:raw=response.read(8*1024*1024+1)
 if len(raw)>8*1024*1024:raise ValueError('战报返回内容过大')
 return json.loads(raw)

def fetch_ark(defense,catalog,progress=None,reader=read_json):
 defense=team_key(defense);byid={h['id']:h for h in catalog['heroes']}
 names=[byid[h]['name_en'] for h in defense]
 quoted='('+','.join('"'+name.replace('\\','\\\\').replace('"','\\"')+'"' for name in names)+')'
 config=ARK_SOURCE;key=config['public_anon_key'];headers={'apikey':key,'Authorization':'Bearer '+key,'User-Agent':'E7GearAdvisor public-GW-read'}
 rows=[];offset=0;page_size=1000
 while True:
  params={'select':'id,defense_hero1,defense_hero2,defense_hero3,offense_hero1,offense_hero2,offense_hero3,outcome,match_timestamp','order':'id.asc','limit':str(page_size),'offset':str(offset)}
  for i in (1,2,3):params['defense_hero'+str(i)]='in.'+quoted
  part=reader(config['endpoint']+'?'+urllib.parse.urlencode(params),headers)
  if not isinstance(part,list):raise ValueError('团战接口没有返回战报列表')
  rows.extend(part)
  if progress:progress(len(rows))
  if len(part)<page_size:break
  offset+=page_size
  if offset>=100000:raise ValueError('战报超过十万条，未显示不完整统计；请缩小时间范围')
  time.sleep(.15)
 result=normalize_rows(rows,defense,catalog)
 result.update(complete=True,raw_rows=len(rows),matched_samples=sum(r['samples'] for r in result['offenses']))
 return result

def fetch_fribbels(defense,reader=read_json):
 defense=team_key(defense);data=reader(FRIBBELS_URL,{'Content-Type':'text/plain','User-Agent':'E7GearAdvisor public-GW-read'},','.join(defense).encode('ascii'))
 if not isinstance(data,dict) or 'data' not in data or (data['data'] is not None and not isinstance(data['data'],dict)):raise ValueError('Fribbels 团战接口未返回有效统计')
 rows=[]
 for heroes,result in (data['data'] or {}).items():
  rows.append({'heroes':list(team_key(heroes.split(','))),'wins':count(result['w']),'losses':count(result['l'])})
 result=validate_bundle({'defense':list(defense),'offenses':rows})[0]
 return {**result,'source':'Fribbels GW 历史数据（已停止更新）','source_url':'https://fribbels.github.io/e7/gw-meta.html','historical':True,'complete':True,'fetched_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}

def fribbels_team_url(defense,catalog):
 byid={h['id']:h['name_en'] for h in catalog['heroes']}
 return 'https://fribbels.github.io/e7/gw-meta.html?'+urllib.parse.urlencode({'def':','.join(byid[h] for h in team_key(defense))})

class GWStore:
 def __init__(self,user_dir):self.folder=Path(user_dir)/'guild-war-cache';self.folder.mkdir(parents=True,exist_ok=True)
 def path(self,defense,provider):return self.folder/(hashlib.sha256((provider+':'+','.join(team_key(defense))).encode('utf8')).hexdigest()[:32]+'.json')
 def load(self,defense,provider):
  try:return validate_bundle(json.loads(self.path(defense,provider).read_text('utf8')))[0]
  except (OSError,ValueError,KeyError,TypeError):return None
 def save(self,data,provider):
  clean=validate_bundle(data)[0];path=self.path(clean['defense'],provider);tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(clean,ensure_ascii=False,indent=2),'utf8');tmp.replace(path)
