"""Single-worker public-data cache with durable per-hero commits and TTL checks."""
import copy,datetime,gzip,hashlib,json,math,os,random,time,urllib.request,urllib.error,email.utils
from pathlib import Path
from fribbels_sync import aggregate,save_atomic,NoRedirect,BUILD_URL

DEFAULT_CONFIG=Path(__file__).parent/'data/e7-sync-config.json'

def load_config(path=None):
 data=json.loads(Path(path or DEFAULT_CONFIG).read_text(encoding='utf8'))
 if data.get('endpoint')!=BUILD_URL or data.get('method')!='POST' or data.get('body_format')!='plain_text_hero_name':raise ValueError('同步配置只支持已核对的公开Hero Library接口及纯文本英雄名')
 if data.get('concurrency')!=1:raise ValueError('当前同步器使用单并发')
 for field in ('interval_sec','jitter_sec','timeout_sec','cache_ttl_days','hard_pause_sec'):
  value=data.get(field)
  if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:raise ValueError('同步参数无效：'+field)
 if not 1<=data['timeout_sec']<=180 or not 1<=data['cache_ttl_days']<=3650:raise ValueError('超时或过期天数超出范围')
 for key in ('storage_dir','checkpoint_file','log_file'):
  p=Path(data[key])
  if p.is_absolute() or p.root or p.drive or '..' in p.parts or ':' in str(p):raise ValueError('缓存路径必须位于本地配置目录内')
 if set(data.get('headers',{}))-{'Content-Type','User-Agent'}:raise ValueError('同步请求不接受Cookie、身份信息或附加请求头')
 return data

def utc_text(timestamp):return datetime.datetime.fromtimestamp(timestamp,datetime.timezone.utc).isoformat()
def epoch(value):
 try:
  parsed=datetime.datetime.fromisoformat(str(value).replace('Z','+00:00'))
  return (parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.timezone.utc)).timestamp()
 except (ValueError,TypeError):return 0

class FetchError(Exception):
 def __init__(self,code,message='',retry_after=0):self.code=code;self.retry_after=retry_after;super().__init__(message or ('HTTP '+str(code)))

def fetch_builds(name,conditional,config):
 if not isinstance(name,str) or not 1<=len(name)<=120 or any(ord(c)<32 for c in name):raise ValueError('英雄名无效')
 headers={**config['headers'],**conditional,'Accept':'application/json'}
 request=urllib.request.Request(BUILD_URL,data=name.encode('utf8'),headers=headers,method='POST')
 try:
  with urllib.request.build_opener(NoRedirect()).open(request,timeout=config['timeout_sec']) as response:
   raw=response.read(16*1024*1024+1);result_headers=response.headers
   if len(raw)>16*1024*1024:raise ValueError('英雄样本超过16MB，未覆盖本地数据')
   payload=json.loads(raw)
   if not isinstance(payload,dict) or not isinstance(payload.get('data'),list):raise ValueError('接口未返回有效data数组')
   return {'status':200,'payload':payload,'etag':result_headers.get('ETag',''),'last_modified':result_headers.get('Last-Modified','')}
 except urllib.error.HTTPError as e:
  if e.code==304:return {'status':304}
  retry=e.headers.get('Retry-After','') if e.headers else ''
  try:retry_after=max(0,float(retry))
  except ValueError:
   try:retry_after=max(0,email.utils.parsedate_to_datetime(retry).timestamp()-time.time())
   except (ValueError,TypeError):retry_after=0
  raise FetchError(e.code,retry_after=retry_after) from None

class CacheLock:
 def __init__(self,path):self.path=path;self.file=None
 def __enter__(self):
  self.file=open(self.path,'a+b');self.file.seek(0,2)
  if self.file.tell()==0:self.file.write(b'0');self.file.flush()
  self.file.seek(0)
  try:
   if os.name=='nt':
    import msvcrt
    msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
   else:
    import fcntl
    fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except OSError:self.file.close();raise ValueError('已有同步任务使用此缓存，请先暂停另一个任务') from None
  return self
 def __exit__(self,*_):
  if self.file:self.file.close()

class ResumableSync:
 def __init__(self,user_dir,bundle_path,config=None,fetcher=None,clock=None):
  self.user_dir=Path(user_dir);self.config=load_config(config);self.bundle_path=Path(bundle_path);self.fetcher=fetcher or fetch_builds;self.now=clock or time.time
  self.folder=self.user_dir/self.config['storage_dir'];self.folder.mkdir(parents=True,exist_ok=True)
  self.checkpoint=self.user_dir/self.config['checkpoint_file'];self.log_path=self.user_dir/self.config['log_file'];self.log_path.parent.mkdir(parents=True,exist_ok=True)
  try:self.state=json.loads(self.checkpoint.read_text(encoding='utf8'))
  except (OSError,ValueError):self.state={'schema':1,'heroes':{},'cooldown_until':0}
  if not isinstance(self.state,dict) or not isinstance(self.state.get('heroes'),dict):raise ValueError('断点文件损坏；请保留文件后重新导入缓存')
  try:self.bundle=json.loads(self.bundle_path.read_text(encoding='utf8'))
  except (OSError,ValueError):self.bundle={'schema':1,'source':'Fribbels Hero Library','heroes':{}}
  self.progress=None;self.cancel=None;self.counts={};self.pending=[];self.current='';self.total=0
 def raw_path(self,name):return self.folder/(hashlib.sha256(name.encode('utf8')).hexdigest()[:32]+'.json.gz')
 def persist(self):self.state['updated_at']=utc_text(self.now());save_atomic(self.checkpoint,self.state)
 def log(self,message):
  with self.log_path.open('a',encoding='utf8') as file:file.write(utc_text(self.now())+' '+message+'\n')
 def emit(self,phase,wait_seconds=0):
  if self.progress:self.progress({**self.counts,'phase':phase,'current':self.current,'total':self.total,'remaining':len(self.pending),'wait_seconds':max(0,round(wait_seconds)),'cached':len(self.bundle['heroes'])})
 def wait(self,seconds,phase):
  end=time.monotonic()+seconds;last=-1
  while True:
   remaining=end-time.monotonic()
   if remaining<=0:return True
   if self.cancel and self.cancel.is_set():return False
   whole=round(remaining)
   if whole!=last:self.emit(phase,remaining);last=whole
   if self.cancel:self.cancel.wait(min(.25,remaining))
   else:time.sleep(min(.25,remaining))
 def fresh(self,name):
  record=self.state['heroes'].get(name,{})
  if record.get('status')=='imported':return name in self.bundle['heroes'] and self.now()-epoch(record.get('checked_at'))<self.config['cache_ttl_days']*86400
  if record.get('status') in ('ok','empty') and self.now()-epoch(record.get('checked_at'))<self.config['cache_ttl_days']*86400:
   return record.get('status')=='empty' or self.raw_path(name).exists()
  return False
 def recover(self,name):
  path=self.raw_path(name)
  if not path.exists():return
  try:
   with gzip.open(path,'rt',encoding='utf8') as file:record=json.load(file)
   if record.get('hero')!=name:return
   summary=aggregate(name,record['payload']);self.bundle['heroes'][name]=summary
   self.state['heroes'][name]={k:record.get(k,'') for k in ('checked_at','etag','last_modified','sha256')};self.state['heroes'][name]['status']='ok'
  except (OSError,ValueError,KeyError,TypeError):return
 def commit(self,name,response):
  previous=self.state['heroes'].get(name,{})
  if response['status']==304:
   if not self.raw_path(name).exists():raise ValueError('服务返回未修改，但本地样本文件缺失，未标记完成')
   self.recover(name)
   save_atomic(self.bundle_path,self.bundle)
   previous.update(checked_at=utc_text(self.now()),status='ok');self.state['heroes'][name]=previous;self.counts['unchanged']+=1;return
  payload=response['payload'];encoded=json.dumps(payload['data'],ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf8');digest=hashlib.sha256(encoded).hexdigest();checked=utc_text(self.now())
  meta={'checked_at':checked,'etag':response.get('etag',''),'last_modified':response.get('last_modified',''),'sha256':digest,'status':'ok'}
  if not payload['data']:
   meta['status']='empty';self.state['heroes'][name]=meta;self.counts['empty']+=1;return
  # Validate before replacing either the raw sample or its aggregated view.
  summary=aggregate(name,payload)
  record={'hero':name,'payload':payload,**meta};path=self.raw_path(name);temporary=path.with_suffix('.tmp')
  with gzip.open(temporary,'wt',encoding='utf8') as file:json.dump(record,file,ensure_ascii=False,allow_nan=False)
  temporary.replace(path)
  if previous.get('sha256')==digest and name in self.bundle['heroes']:self.counts['unchanged']+=1
  else:self.counts['saved']+=1
  # Recompute fields even when the server samples have not changed.
  self.bundle['heroes'][name]=summary
  self.bundle['fetched_at']=checked;save_atomic(self.bundle_path,self.bundle);self.state['heroes'][name]=meta
 def run(self,names,progress=None,cancel=None,force=False):
  self.progress=progress;self.cancel=cancel;names=list(dict.fromkeys(names));self.counts={'done':0,'saved':0,'unchanged':0,'failed':0,'empty':0,'skipped':0};self.total=len(names);stopped='';consecutive_403=0;consecutive_errors=0
  with CacheLock(self.folder/'_sync.lock'):
   for name in names:
    if name not in self.state['heroes'] or (self.state['heroes'][name].get('status')=='ok' and name not in self.bundle['heroes']):self.recover(name)
    if name not in self.state['heroes']:
     ref=self.bundle['heroes'].get(name,{})
     if all(key in ref for key in ('panel','sample_count','variants','set_rates','artifact_rates')):
      self.state['heroes'][name]={'status':'imported','checked_at':ref.get('updated_at',self.bundle.get('fetched_at',''))}
   if self.bundle['heroes']:save_atomic(self.bundle_path,self.bundle)
   self.pending=[name for name in names if force or not self.fresh(name)];self.counts['skipped']=len(names)-len(self.pending);self.counts['done']=self.counts['skipped']
   self.state.update(pending=self.pending,phase='running');self.persist();self.emit('准备同步')
   cooldown=max(0,self.state.get('cooldown_until',0)-self.now())
   if cooldown and not self.wait(cooldown,'服务冷却'):stopped='已暂停'
   for name in list(self.pending):
    if stopped or (cancel and cancel.is_set()):stopped=stopped or '已暂停';break
    self.current=name;self.emit('读取英雄样本');attempt_500=0;forbidden_attempt=0;completed=False
    while True:
     if cancel and cancel.is_set():stopped='已暂停';break
     record=self.state['heroes'].get(name,{});conditional={}
     if self.raw_path(name).exists():
      if record.get('etag'):conditional['If-None-Match']=record['etag']
      if record.get('last_modified'):conditional['If-Modified-Since']=record['last_modified']
     try:
      response=self.fetcher(name,conditional,self.config);self.commit(name,response);completed=True;consecutive_errors=0
      if self.config.get('reset_backoff_on_success',True):consecutive_403=0
      self.log('ok '+name);break
     except FetchError as e:
      self.log('HTTP '+str(e.code)+' '+name)
      if e.code==500 and attempt_500<self.config['retry_500']['max_retries']:
       attempt_500+=1
       if not self.wait(max(e.retry_after,self.config['retry_500']['delay_sec']),'服务暂时异常，等待重试'):stopped='已暂停';break
       continue
      if e.code in (403,429):
       consecutive_403+=1;forbidden_attempt+=1
       if consecutive_403>=self.config['max_consecutive_403']:
        delay=max(e.retry_after,self.config['hard_pause_sec']);self.state['cooldown_until']=self.now()+delay;self.state['heroes'][name]={**record,'last_error':'HTTP '+str(e.code)};self.counts['failed']+=1;stopped=f'服务拒绝或限流，已暂停；冷却{delay:g}秒后可继续';break
       delays=self.config['backoff_403_sec'];delay=max(e.retry_after,delays[min(forbidden_attempt-1,len(delays)-1)])
       if not self.wait(delay,'服务拒绝或限流，退避等待'):stopped='已暂停';break
       continue
      self.state['heroes'][name]={**record,'last_error':'HTTP '+str(e.code)};consecutive_errors+=1;self.counts['failed']+=1;break
     except Exception as e:
      message=type(e).__name__+': '+str(e)[:180];self.log('error '+name+' '+message);self.state['heroes'][name]={**record,'last_error':message};consecutive_errors+=1;self.counts['failed']+=1
      if '跳转' in str(e):stopped='数据源跳转，已停止，保留所有已完成数据'
      break
    if completed:self.pending.remove(name);self.counts['done']+=1
    if consecutive_errors>=3:stopped='连续3次连接或数据错误，已暂停，可继续重试'
    self.state.update(pending=self.pending,current=name,phase='paused' if stopped else 'running');self.persist();self.emit(stopped or '已保存断点')
    if stopped:break
    if self.pending and not self.wait(self.config['interval_sec']+random.uniform(0,self.config['jitter_sec']),'低速同步间隔'):stopped='已暂停';break
   self.state.update(pending=self.pending,phase='paused' if self.pending else 'complete');self.persist();self.emit(stopped or ('全部同步完成' if not self.pending else '本轮结束，失败项可继续'))
   return {**self.counts,'total':self.total,'remaining':len(self.pending),'cached':len(self.bundle['heroes']),'stopped':stopped,'completed':not self.pending}
