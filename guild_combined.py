"""Combine online providers without assuming their battle samples are disjoint."""
import concurrent.futures,datetime
from guild_war import count,team_key

def merge_records(defense,records,errors=()):
 defense=team_key(defense);groups={};guides=[];sources=[]
 for provider,record in sorted(records,key=lambda item:item[0]):
  if team_key(record['defense'])!=defense:raise ValueError('综合查询返回了其他防守阵容')
  sources.append({'provider':provider,'source':record.get('source',provider),'complete':record.get('complete',False),'rows':len(record.get('offenses',[])),'guides':len(record.get('guides',[]))})
  for guide in record.get('guides',[]):guides.append({**guide,'source':record.get('source',provider),'source_url':record.get('source_url','')})
  for row in record.get('offenses',[]):
   team=team_key(row['heroes']);counts={key:count(row.get(key,0)) for key in ('wins','losses','draws')};samples=sum(counts.values())
   if count(row['samples'])!=samples:raise ValueError('综合查询的来源场次与胜负不符')
   stats={'provider':provider,'source':record.get('source',provider),'source_url':record.get('source_url',''),'historical':bool(record.get('historical')),**counts,'samples':samples,'report_date':record.get('report_date',''),'first_match':record.get('first_match',''),'last_match':record.get('last_match','')}
   bucket=groups.setdefault(team,{})
   if provider not in bucket or bucket[provider]['samples']<samples:bucket[provider]=stats
 rows=[]
 for team,providers in groups.items():
  stats=sorted(providers.values(),key=lambda row:(-row['samples'],row['historical'],row['provider']))
  chosen=stats[0]
  rows.append({'heroes':list(team),**{key:chosen[key] for key in ('wins','losses','draws','samples')},'source_stats':stats,'display_source':chosen['source'],'historical':chosen['historical']})
 rows.sort(key=lambda row:(-row['samples'],-row['wins'],row['heroes']))
 return {'schema':1,'defense':list(defense),'offenses':rows,'guides':guides,'record_kind':'combined','source':'综合在线查询','sources':sources,'source_errors':list(errors),'complete':not errors and all(row['complete'] for row in sources),'fetched_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'adapter':'combined-online-v1'}

def fetch_combined(defense,fetchers,progress=None):
 records=[];errors=[]
 with concurrent.futures.ThreadPoolExecutor(max_workers=min(5,len(fetchers))) as pool:
  pending={pool.submit(fetch):name for name,fetch in fetchers.items()}
  for future in concurrent.futures.as_completed(pending):
   name=pending[future]
   try:records.append((name,future.result()));message=name+' 查询完成'
   except Exception as error:errors.append({'provider':name,'error':str(error)[:200]});message=name+' 请求失败'
   if progress:progress(message)
 if not records:raise ValueError('所有在线来源请求失败：'+'；'.join(row['provider']+' '+row['error'] for row in errors))
 return merge_records(defense,records,errors)
