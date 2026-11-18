"""Read E7 Wiki's public contributed guides, without posting feedback."""
import datetime,json,re,urllib.parse,urllib.request
from guild_war import NoRedirect,count,team_key

ORIGIN='https://e7.wiki/gvg-homework'
BASE='https://admin.e7.wiki/api/open/epicseven/'

def read_public_json(url,body=None):
 parsed=urllib.parse.urlsplit(url)
 if parsed.scheme!='https' or parsed.netloc!='admin.e7.wiki' or parsed.query or parsed.path not in ('/api/open/epicseven/hero/card-list','/api/open/epicseven/gvg_homework/page'):raise ValueError('不支持的 E7 Wiki 查询地址')
 request=urllib.request.Request(url,data=json.dumps(body).encode('utf8') if body is not None else None,headers={'Accept':'application/json','Content-Type':'application/json;charset=UTF-8','User-Agent':'E7GearAdvisor public-homework-reader'})
 with urllib.request.build_opener(NoRedirect()).open(request,timeout=25) as response:
  if response.headers.get_content_type()!='application/json':raise ValueError('E7 Wiki 没有返回查询数据')
  raw=response.read(8*1024*1024+1)
 if len(raw)>8*1024*1024:raise ValueError('E7 Wiki 查询响应过大')
 return json.loads(raw)

def unwrap(payload):
 if not isinstance(payload,dict) or payload.get('code') not in (1000,200,201) or 'data' not in payload:raise ValueError('E7 Wiki 查询失败或返回结构变化，不能视为无作业')
 return payload['data']

def text_field(row,key):
 value=row.get(key) or ''
 if not isinstance(value,str) or len(value)>20000:raise ValueError('E7 Wiki 作业文本格式无效')
 return value.replace('\\r\\n','\n').replace('\\n','\n').strip()

def fetch_e7wiki(defense,catalog,reader=read_public_json):
 defense=team_key(defense);known={h['id'] for h in catalog['heroes']}
 heroes=unwrap(reader(BASE+'hero/card-list'))
 if not isinstance(heroes,list) or not heroes or len(heroes)>2000:raise ValueError('E7 Wiki 角色表结构变化')
 by_code={};by_id={}
 for hero in heroes:
  code=hero.get('code');face=hero.get('face_id','')
  match=re.fullmatch(r'(c\d+)(?:_s\d+)?',face) if isinstance(face,str) else None
  if not match or not isinstance(code,str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,120}',code):continue
  hid=match.group(1)
  if hid not in known:continue
  if code in by_code and by_code[code]!=hid:raise ValueError('E7 Wiki 英雄代号映射不一致')
  by_code[code]=hid;by_id.setdefault(hid,set()).add(code)
 if any(len(by_id.get(hid,()))!=1 for hid in defense):raise ValueError('E7 Wiki 缺少该防守英雄的唯一代号，未猜测角色名称')
 codes=[next(iter(by_id[hid])) for hid in defense];guides=[];seen=set();total=None;received=0
 for page in range(1,101):
  payload=unwrap(reader(BASE+'gvg_homework/page',{'page':page,'size':50,'searchType':'defense','keyWord':','.join(codes)}))
  if not isinstance(payload,dict) or not isinstance(payload.get('list'),list) or not isinstance(payload.get('pagination'),dict):raise ValueError('E7 Wiki 作业分页结构变化')
  pagination=payload['pagination'];items=payload['list'];current_total=count(pagination['total'])
  if count(pagination['page'])!=page or count(pagination['size'])!=50 or len(items)>50:raise ValueError('E7 Wiki 作业分页不一致')
  if total is None:total=current_total
  if total!=current_total:raise ValueError('E7 Wiki 查询期间作业发生变化，请重新查询')
  received+=len(items)
  for row in items:
   try:
    target=team_key([by_code[row['defenseHero'+str(i)]] for i in (1,2,3)])
    attack=[by_code[row['offenseHero'+str(i)]] for i in (1,2,3)];team_key(attack)
   except (KeyError,TypeError,ValueError):raise ValueError('E7 Wiki 作业英雄无法完整对应，请更新角色资料') from None
   if target!=defense:raise ValueError('E7 Wiki 返回了其他防守的作业，未作为该队结果显示')
   identity=count(row['id'])
   if identity in seen:raise ValueError('E7 Wiki 作业分页重复，未显示不完整结果')
   seen.add(identity)
   guide={'id':identity,'heroes':attack,'feedback_wins':count(row.get('win',0)),'feedback_losses':count(row.get('lose',0))}
   for key in ('author','scene','equipment','artifact','strategy','note','updateTime','createTime'):guide[key]=text_field(row,key)
   guides.append(guide)
  if received==total:break
  if received>total or len(items)<50:raise ValueError('E7 Wiki 作业分页未完整返回')
 else:raise ValueError('E7 Wiki 作业数量过多，未显示不完整结果')
 return {'schema':1,'defense':list(defense),'offenses':[],'guides':guides,'record_kind':'community_guides','source':'E7·WIKI 在线作业','source_url':ORIGIN,'complete':True,'adapter':'e7wiki-guides-v1','fetched_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
