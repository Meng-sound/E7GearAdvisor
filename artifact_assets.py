"""Explicit public-icon update; no account data, credentials or telemetry."""
import io,re,urllib.request
from pathlib import Path
from PIL import Image

HOST='e7gw.xyz'
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args):raise ValueError('图标地址发生跳转，已停止读取')

def update_missing(catalog,bundled,destination,progress=None):
 bundled=Path(bundled);destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
 def valid(path):
  try:
   with Image.open(path) as image:image.verify()
   return True
  except (OSError,ValueError):return False
 todo=[code for code in catalog if re.fullmatch(r'[A-Za-z0-9_]+',code) and not valid(bundled/(code+'.png')) and not valid(destination/(code+'.png'))]
 saved=0;failed=[]
 for index,code in enumerate(todo,1):
  try:
   url='https://'+HOST+'/img/artifacts/'+code+'.png'
   request=urllib.request.Request(url,headers={'User-Agent':'E7GearAdvisor icon-update'})
   with urllib.request.build_opener(NoRedirect()).open(request,timeout=15) as response:raw=response.read(2*1024*1024+1)
   if len(raw)>2*1024*1024:raise ValueError('图片过大')
   with Image.open(io.BytesIO(raw)) as image:
    if image.width>2048 or image.height>2048:raise ValueError('图片尺寸异常')
    image.load();temporary=destination/(code+'.tmp');image.convert('RGBA').save(temporary,format='PNG')
   temporary.replace(destination/(code+'.png'));saved+=1
  except (OSError,ValueError):failed.append(code)
  if progress:progress(index,len(todo),saved,len(failed))
 return saved,failed
