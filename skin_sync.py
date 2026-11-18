"""Incremental official-repository portrait sync; no scripts or player data.

Each verified image is committed independently. Existing content hashes are
the checkpoint, so restart skips files already downloaded successfully.
"""
import hashlib,io,json,re,urllib.request,urllib.error
from pathlib import Path
from PIL import Image
REPO='fribbels/Fribbels-Epic-7-Optimizer'
TREE_URL='https://api.github.com/repos/'+REPO+'/git/trees/main?recursive=1'
PREFIX='data/cachedimages/'
def blob_sha(raw):return hashlib.sha1(b'blob '+str(len(raw)).encode('ascii')+b'\0'+raw).hexdigest()
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args):raise ValueError('皮肤源发生跳转，已停止更新')
def read_public(url,limit):
 if url!=TREE_URL and not re.fullmatch(r'https://raw\.githubusercontent\.com/fribbels/Fribbels-Epic-7-Optimizer/[a-f0-9]{40}/data/cachedimages/c\d+_s\d+_s\.png',url):raise ValueError('不支持的皮肤资源地址')
 request=urllib.request.Request(url,headers={'User-Agent':'E7GearAdvisor public-skin-update','Accept':'application/vnd.github+json' if url==TREE_URL else 'image/png'})
 with urllib.request.build_opener(NoRedirect()).open(request,timeout=20) as response:raw=response.read(limit+1)
 if len(raw)>limit:raise ValueError('皮肤源返回内容过大')
 return raw
def manifest(payload,catalog):
 if not isinstance(payload,dict) or payload.get('truncated') is not False or not re.fullmatch(r'[a-f0-9]{40}',str(payload.get('sha',''))):raise ValueError('官方皮肤目录不完整，未更新')
 tree=payload.get('tree')
 if not isinstance(tree,list) or len(tree)>50000:raise ValueError('官方皮肤目录格式无效')
 known={h['id'] for h in catalog['heroes']};result=[];seen=set()
 for row in tree:
  path=row.get('path','') if isinstance(row,dict) else ''
  match=re.fullmatch(re.escape(PREFIX)+r'(c\d+)_s\d+_s\.png',path)
  if not match or match.group(1) not in known:continue
  if row.get('type')!='blob' or not re.fullmatch(r'[a-f0-9]{40}',str(row.get('sha',''))) or isinstance(row.get('size'),bool) or not isinstance(row.get('size'),int) or not 1<=row['size']<=1024*1024:raise ValueError('皮肤资源元数据无效')
  if path in seen:raise ValueError('皮肤目录重复')
  seen.add(path);result.append(row)
 return payload['sha'],result
def update(catalog,bundled,destination,progress=None,cancel=None,reader=read_public):
 revision,rows=manifest(json.loads(reader(TREE_URL,8*1024*1024)),catalog);folder=Path(destination);folder.mkdir(parents=True,exist_ok=True);saved=skipped=0
 def same(path,sha):
  try:return path.stat().st_size<=1024*1024 and blob_sha(path.read_bytes())==sha
  except OSError:return False
 for index,row in enumerate(rows,1):
  if cancel is not None and cancel.is_set():return {'saved':saved,'skipped':skipped,'total':len(rows),'cancelled':True}
  name=Path(row['path']).name;target=folder/name
  if same(target,row['sha']) or same(Path(bundled)/name,row['sha']):skipped+=1
  else:
   raw=reader('https://raw.githubusercontent.com/'+REPO+'/'+revision+'/'+row['path'],1024*1024)
   if len(raw)!=row['size'] or blob_sha(raw)!=row['sha']:raise ValueError('皮肤文件校验失败，已保存的文件可在下次继续：'+name)
   with Image.open(io.BytesIO(raw)) as image:
    if image.format!='PNG' or not 24<=image.width<=512 or not 24<=image.height<=512:raise ValueError('皮肤图片格式或尺寸异常')
    image.verify()
   temporary=target.with_suffix('.tmp');temporary.write_bytes(raw);temporary.replace(target);saved+=1
  if progress:progress(index,len(rows),saved,skipped)
 return {'saved':saved,'skipped':skipped,'total':len(rows),'cancelled':False}
