"""Read EP7's public matchup search, respecting its persistent guest quota."""
import datetime,json,urllib.error,urllib.parse,urllib.request,uuid
from pathlib import Path
from guild_war import NoRedirect,count,team_key,validate_bundle

ORIGIN='https://ep7guild-war.vercel.app'
ENDPOINT='https://ep7guildwar.duckdns.org/api/v1/matchups'

def client_key(user_dir):
 path=Path(user_dir)/'ep7-public-client-id.txt'
 try:
  value=path.read_text('ascii').strip();uuid.UUID(value);return value
 except FileNotFoundError:
  value=str(uuid.uuid4())
  try:
   with path.open('x',encoding='ascii') as output:output.write(value)
  except FileExistsError:return client_key(user_dir)
  return value
 except (ValueError,UnicodeError):raise ValueError('EP7 查询身份文件无效，请保留文件并检查；未自动更换查询身份') from None

def read_public_json(url,headers):
 parsed=urllib.parse.urlsplit(url)
 if parsed.scheme!='https' or parsed.netloc!='ep7guildwar.duckdns.org' or parsed.path!='/api/v1/matchups':raise ValueError('不支持的 EP7 查询地址')
 request=urllib.request.Request(url,headers={'Accept':'application/json','User-Agent':'E7GearAdvisor public-matchup-reader',**headers})
 try:
  with urllib.request.build_opener(NoRedirect()).open(request,timeout=25) as response:
   if response.headers.get_content_type()!='application/json':raise ValueError('EP7 没有返回战报数据')
   raw=response.read(8*1024*1024+1)
 except urllib.error.HTTPError as error:
  if error.code==429:raise ValueError('EP7 查询额度已用完，请按网站规则稍后查询；未自动重试或更换身份') from None
  if error.code in (401,403):raise ValueError('EP7 当前需要登录或访问授权，请到来源网站查看') from None
  raise
 if len(raw)>8*1024*1024:raise ValueError('EP7 战报响应过大')
 return json.loads(raw)

def fetch_ep7(defense,catalog,identity,reader=read_public_json):
 defense=team_key(defense);known={h['id'] for h in catalog['heroes']};rows=[];seen={};dates=[];expected_total=None;raw_count=0
 if not set(defense)<=known:raise ValueError('防守英雄资料不完整')
 for page in range(100):
  params=[('defenseHeroIds',hid) for hid in defense]+[('sort','TOTAL_MATCHES'),('minMatches','1'),('page',str(page)),('size','30')]
  payload=reader(ENDPOINT+'?'+urllib.parse.urlencode(params),{'X-EP7-Client-Key':identity})
  if not isinstance(payload,dict) or not isinstance(payload.get('content'),list) or not isinstance(payload.get('last'),bool):raise ValueError('EP7 战报结构未识别，不能视作无战报')
  items=payload['content'];total=count(payload['totalElements'])
  if count(payload['number'])!=page or count(payload['numberOfElements'])!=len(items) or len(items)>30:raise ValueError('EP7 战报分页不一致')
  if expected_total is None:expected_total=total
  if total!=expected_total:raise ValueError('EP7 查询期间战报发生变化，请重新查询')
  raw_count+=len(items)
  for item in items:
   if team_key(item['defenseHeroes'])!=defense:continue
   heroes=team_key(item['attackHeroes'])
   if not set(heroes)<=known:raise ValueError('EP7 战报包含尚未收录的英雄，请更新英雄资料')
   counts={key:count(item.get(key,0)) for key in ('wins','losses','draws')}
   if sum(counts.values())!=count(item['totalMatches']):raise ValueError('EP7 总场次与胜负不一致')
   if heroes in seen:raise ValueError('EP7 返回重复进攻组合，未重复累加统计，请重新查询')
   seen[heroes]=True;rows.append({'heroes':list(heroes),**counts})
   # This is an aggregate update timestamp, not a battle timestamp.
   stamp=item.get('updatedAt','')
   try:dates.append(datetime.datetime.fromisoformat(stamp).date().isoformat())
   except (TypeError,ValueError):pass
  if payload['last']:
   if raw_count!=expected_total:raise ValueError('EP7 战报分页未完整返回')
   break
  if not items:raise ValueError('EP7 战报分页提前中断')
 else:raise ValueError('EP7 战报分页过多，未显示不完整统计')
 result=validate_bundle({'defense':list(defense),'offenses':rows})[0]
 return {**result,'source':'EP7 公开战报','source_url':ORIGIN+'/en/meta','complete':True,'adapter':'ep7-matchups-v1','raw_rows':raw_count,'report_date':max(dates) if dates else '未提供','date_kind':'统计快照','fetched_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
