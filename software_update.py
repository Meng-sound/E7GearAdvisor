"""Opt-in GitHub Release checks; downloads never overwrite or silently run the app."""
import hashlib,json,re,urllib.error,urllib.parse,urllib.request
from pathlib import Path
from app_version import VERSION

ALLOWED_HOSTS={'api.github.com','github.com','release-assets.githubusercontent.com','objects.githubusercontent.com','github-releases.githubusercontent.com'}
ASSET_NAMES=('E7GearAdvisor-Windows.zip','E7GearAdvisor.exe','装备强化计算器.exe')
DEFAULT_REPOSITORY='Meng-sound/E7GearAdvisor'

def repository(value):
 value=value.strip().rstrip('/')
 if value.startswith('https://github.com/'):value=value[len('https://github.com/'):].removesuffix('.git')
 if not re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+',value) or value.endswith('/.'):raise ValueError('请填写 owner/repo 或 GitHub 仓库主页链接')
 return value

def version_key(value):
 match=re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)(?:[-.]?(alpha|beta|rc)[.-]?(\d+))?(?:\+[A-Za-z0-9.-]+)?',value.strip(),re.I)
 if not match:raise ValueError('版本号应为 v1.0.0 或 v1.0.0-rc.2')
 major,minor,patch,stage,number=match.groups()
 return (int(major),int(minor),int(patch),{'alpha':0,'beta':1,'rc':2,None:3}[stage.lower() if stage else None],int(number or 0))

def safe_url(url):
 parsed=urllib.parse.urlsplit(url)
 if parsed.scheme!='https' or parsed.hostname not in ALLOWED_HOSTS or parsed.username or parsed.password:raise ValueError('更新地址不是允许的 GitHub HTTPS 地址')
 return url

class ReleaseRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  safe_url(newurl);return super().redirect_request(req,fp,code,msg,headers,newurl)

def open_url(url):
 return urllib.request.build_opener(ReleaseRedirect()).open(urllib.request.Request(safe_url(url),headers={'User-Agent':'E7GearAdvisor/'+VERSION,'Accept':'application/vnd.github+json' if urllib.parse.urlsplit(url).hostname=='api.github.com' else 'application/octet-stream'}),timeout=25)

def read_bytes(url,limit=2*1024*1024):
 with open_url(url) as response:data=response.read(limit+1)
 if len(data)>limit:raise ValueError('更新说明返回内容过大')
 return data

def check_release(repo,current=VERSION,reader=read_bytes):
 repo=repository(repo)
 try:data=json.loads(reader('https://api.github.com/repos/'+repo+'/releases/latest'))
 except urllib.error.HTTPError as error:
  if error.code==404:raise ValueError('尚无公开正式版本，请在 GitHub 创建 Release 并上传完整 Windows ZIP；预发布版本不会推送。') from error
  raise
 if not isinstance(data,dict) or data.get('draft'):raise ValueError('没有可用的公开 Release')
 tag=data.get('tag_name','');newer=version_key(tag)>version_key(current)
 page=data.get('html_url','')
 if not page.startswith('https://github.com/'+repo+'/releases/'):raise ValueError('Release 页面与配置的仓库不一致')
 assets=data.get('assets',[]);selected=None
 for name in ASSET_NAMES:
  selected=next((a for a in assets if a.get('name')==name),None)
  if selected:break
 if selected:
  selected=dict(selected);url=selected.get('browser_download_url','')
  if not url.startswith('https://github.com/'+repo+'/releases/download/'):raise ValueError('下载文件不属于配置的仓库')
  safe_url(url)
  if not isinstance(selected.get('size'),int) or not 0<selected['size']<=512*1024*1024:raise ValueError('更新文件大小无效或超过512MB')
 checksum=next((a for a in assets if a.get('name')=='SHA256SUMS.txt'),None)
 return {'tag':tag,'newer':newer,'notes':str(data.get('body') or '作者未填写更新说明')[:20000],'page':page,'asset':selected,'assets':assets,'checksum':checksum,'repo':repo}

def expected_hash(release,reader=read_bytes):
 asset=release['asset'];digest=asset.get('digest','')
 if isinstance(digest,str) and re.fullmatch(r'sha256:[0-9a-fA-F]{64}',digest):return digest.split(':')[1].lower()
 checksum=release.get('checksum')
 if checksum:
  url=checksum.get('browser_download_url','')
  if not url.startswith('https://github.com/'+release['repo']+'/releases/download/'):raise ValueError('校验文件不属于配置的仓库')
  for line in reader(url,256*1024).decode('utf8-sig').splitlines():
   match=re.fullmatch(r'([0-9a-fA-F]{64})\s+\*?(.+)',line.strip())
   if match and match[2]==asset['name']:return match[1].lower()
 raise ValueError('Release 缺少该文件的 SHA256 校验信息；请作者上传 SHA256SUMS.txt，可先打开发布页面手动下载。')

def download_release(release,directory,progress=lambda *_:None,opener=open_url,hash_reader=read_bytes):
 asset=release.get('asset')
 if not asset:raise ValueError('Release 未提供此软件的 Windows EXE 或 ZIP 文件')
 checksum=expected_hash(release,hash_reader);folder=Path(directory)/re.sub(r'[^A-Za-z0-9_.-]','_',release['tag']);folder.mkdir(parents=True,exist_ok=True)
 target=folder/asset['name'];partial=target.with_suffix(target.suffix+'.part');size=0;digest=hashlib.sha256()
 try:
  with opener(asset['browser_download_url']) as response,partial.open('wb') as output:
   while block:=response.read(256*1024):
    size+=len(block)
    if size>asset['size']:raise ValueError('更新文件大小与 Release 不符')
    output.write(block);digest.update(block);progress(size,asset['size'])
  if size!=asset['size'] or digest.hexdigest()!=checksum:raise ValueError('更新文件校验失败，已丢弃下载内容')
  with partial.open('rb') as stream:magic=stream.read(4)
  if asset['name'].endswith('.exe') and not magic.startswith(b'MZ'):raise ValueError('下载内容不是有效的 EXE')
  if asset['name'].endswith('.zip') and not magic.startswith(b'PK'):raise ValueError('下载内容不是有效的 ZIP')
  partial.replace(target);return target
 except Exception:
  partial.unlink(missing_ok=True);raise
