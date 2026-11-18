"""User-configured vision chat API. Keys are DPAPI protected, never bundled."""
import base64,ctypes,io,json,math,urllib.request,urllib.error
from ctypes import wintypes
from pathlib import Path
from urllib.parse import urlsplit
from PIL import Image
from core import Gear,Stat,LABELS,SLOTS
from set_icons import canonical

class Blob(ctypes.Structure):_fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
def protect(text,decrypt=False):
 raw=base64.b64decode(text) if decrypt else text.encode('utf8');buf=ctypes.create_string_buffer(raw);src=Blob(len(raw),ctypes.cast(buf,ctypes.POINTER(ctypes.c_ubyte)));out=Blob();fn=ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
 if not fn(ctypes.byref(src),None,None,None,None,0,ctypes.byref(out)):raise ctypes.WinError()
 try:
  value=ctypes.string_at(out.data,out.size)
  return value.decode('utf8') if decrypt else base64.b64encode(value).decode('ascii')
 finally:ctypes.windll.kernel32.LocalFree(out.data)

def validate_config(data):
 endpoint=str(data.get('endpoint','')).strip();parsed=urlsplit(endpoint)
 if parsed.scheme!='https' and not (parsed.scheme=='http' and parsed.hostname in ('localhost','127.0.0.1')):raise ValueError('接口应使用HTTPS；本地模型可使用localhost HTTP')
 if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:raise ValueError('接口地址不能包含账号、密钥、查询参数或片段')
 if '/images/' in parsed.path or 'seedream' in str(data.get('model','')).lower():raise ValueError('Seedream／images/generations是生成图片接口，请选择支持图片输入的视觉理解模型及chat/completions接口')
 model=str(data.get('model','')).strip()
 if not model:raise ValueError('请填写支持图片输入的模型名或接入点ID')
 return {**data,'endpoint':endpoint.rstrip('/'),'model':model}

def save_config(path,data):
 clean=validate_config(data);key=clean.pop('api_key','');clean['api_key_protected']=protect(key) if key else '';path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(clean,ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(path)
def load_config(path):
 path=Path(path)
 if not path.exists():return {'endpoint':'https://ark.cn-beijing.volces.com/api/v3/chat/completions','model':'','api_key':''}
 data=json.loads(path.read_text(encoding='utf8'));data['api_key']=protect(data.pop('api_key_protected',''),True) if data.get('api_key_protected') else '';return data

PROMPT='''你是装备截图数据提取器，只返回一个JSON对象，不计算分数，不推荐装备，不补猜被遮挡内容。白色/灰色数值是当前总值，忽略橙色(+数值)、强化跳数(1)、未解锁词条。识别装备图标、品质、部位、套装和等级；不知道就null。字段：scene为single、batch或character。character时另返回hero_name、panel八项当前面板、sets已生效套装名称数组（不要推测未显示套装）。single有gear={name,slot,set_name,level,enhance,grade,main:{key,value},subs:[{key,value}],warnings:[],screen_score}。grade只能史诗、英雄、稀有或空。slot只能武器、头盔、铠甲、项链、戒指、鞋子或空。属性key只能atk_pct,hp_pct,def_pct,atk,hp,def,spd,crit,cdmg,eff,res。百分数以百分数本身填，如11%=11，不填0.11。批量制作页scene=batch，entries=[{gear:同上,box:[左,上,右,下]}]，只读实际存在的卡片。角色总面板scene=character，hero_name填左上角角色名，panel={atk,hp,def,spd,crit,cdmg,eff,res,dual}，只读左侧白色当前总值，不用橙色附加值。无可靠数值用null，绝不臆测神器加成或返回装备总分。'''

class VisionClient:
 def __init__(self,config):self.config=validate_config(config)
 def chat(self,content,max_tokens=6000):
  c=self.config;url=c['endpoint']
  if not url.endswith('/chat/completions'):url+='/chat/completions'
  payload={'model':c['model'],'messages':[{'role':'user','content':content}],'temperature':0,'max_tokens':max_tokens,'stream':False}
  headers={'Content-Type':'application/json'}
  if c.get('api_key'):headers['Authorization']='Bearer '+c['api_key']
  req=urllib.request.Request(url,data=json.dumps(payload,ensure_ascii=False).encode('utf8'),headers=headers,method='POST')
  class NoRedirect(urllib.request.HTTPRedirectHandler):
   def redirect_request(self,*args):raise ValueError('API发生跳转，已停止，密钥不会发送到其他地址')
  try:
   with urllib.request.build_opener(NoRedirect()).open(req,timeout=60) as r:raw=r.read(8*1024*1024+1)
  except urllib.error.HTTPError as e:raise ValueError(f'API返回HTTP {e.code}；请核对模型权限、接口地址和密钥') from None
  if len(raw)>8*1024*1024:raise ValueError('API返回内容过大')
  data=json.loads(raw);value=data.get('choices',[{}])[0].get('message',{}).get('content','')
  if isinstance(value,list):value=''.join(v.get('text','') for v in value if isinstance(v,dict))
  if not isinstance(value,str) or not value.strip():raise ValueError('API没有返回可读取的文本；请确认是视觉理解模型')
  return value
 def test(self):return self.chat('请仅回复OK。',32)
 def read(self,path,mode='single'):
  with Image.open(path) as source:
   image=source.convert('RGB');image.thumbnail((1920,1200));buf=io.BytesIO();image.save(buf,format='PNG')
  text=self.chat([{'type':'text','text':PROMPT+' 重铸预览返回scene=reforge，gear填左列当前装备，reforge_after填右列预览装备（相同结构），不得混用两列。 本次模式：'+mode},{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode('ascii')}}])
  text=text.strip()
  if text.startswith('```'):text=text.split('\n',1)[-1].rsplit('```',1)[0].strip()
  data=json.loads(text)
  if not isinstance(data,dict):raise ValueError('模型结果必须是JSON对象')
  scene=data.get('scene')
  if scene not in ('single','batch','character','reforge'):raise ValueError('视觉模型未返回有效界面类型')
  if mode=='batch' and scene!='batch':raise ValueError('当前未识别到装备制作结果界面')
  if scene=='reforge':
   before=clean_gear(data.get('gear',{}));after=clean_gear(data.get('reforge_after',{}))
   if before.main is None or after.main is None:raise ValueError('重铸前后主属性未读全')
   return {'kind':'single','gear':before,'reforge_after':after.to_dict(),'text':text,'layout':'reforge-preview'}
  if scene=='character':
   panel={}
   for k,v in data.get('panel',{}).items():
    if k not in ('atk','hp','def','spd','crit','cdmg','eff','res','dual'):continue
    if v is not None and (isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=1_000_000):raise ValueError('角色面板数值异常')
    panel[k]=v
   return {'kind':'character','hero_name':str(data.get('hero_name',''))[:100],'panel':panel,'sets':[__import__('set_icons').canonical(s) for s in data.get('sets',[]) if isinstance(s,str)] if isinstance(data.get('sets',[]),list) else [],'text':text,'layout':'vision-character'}
  if scene=='batch':
   entries=[]
   for i,e in enumerate(data.get('entries',[])[:20]):
    gear=clean_gear(e.get('gear',{}));box=e.get('box')
    if not isinstance(box,list) or len(box)!=4 or any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in box):box=[(i%4)*370,(i//4)*170,(i%4)*370+120,(i//4)*170+120]
    entries.append({'gear':gear,'box':box,'screen_score':gear.screen_score})
   if not entries:raise ValueError('视觉模型未可靠读到制作装备，请人工校验')
   return {'kind':'batch','entries':entries,'text':text,'source_note':'视觉模型提取，分数由本地计算；请核对不确定字段。'}
  return {'kind':'single','gear':clean_gear(data.get('gear',{})),'text':text,'layout':'vision-equipment'}

def clean_gear(data):
 if not isinstance(data,dict):raise ValueError('装备字段格式错误')
 def stat(value):
  if not value:return None
  k=value.get('key');v=value.get('value')
  if k not in LABELS or isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<v<=10000:raise ValueError('视觉模型属性名称或数值异常，需人工校验')
  return Stat(k,v)
 grade={'传说':'史诗'}.get(data.get('grade'),data.get('grade')) or ''
 if grade not in ('史诗','英雄','稀有',''):grade=''
 slot=data.get('slot') or '';slot=slot if slot in SLOTS else ''
 def integer(key,lo,hi):
  v=data.get(key)
  return int(v) if isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and int(v)==v and lo<=v<=hi else None
 subs=[stat(v) for v in data.get('subs',[]) if v]
 if len(subs)>4 or len({s.key for s in subs})!=len(subs):raise ValueError('视觉模型副属性数量或重复项异常')
 score=data.get('screen_score');score=score if isinstance(score,(int,float)) and not isinstance(score,bool) and math.isfinite(score) and 0<=score<=999 else None
 return Gear(name=str(data.get('name',''))[:100],slot=slot,set_name=canonical(str(data.get('set_name') or '')),grade=grade,level=integer('level',1,99),enhance=integer('enhance',0,15),main=stat(data.get('main')),subs=subs,warnings=['视觉模型结果，请人工核对不确定字段'],screen_score=score)

def open_config(parent,path,on_save):
 import tkinter as tk,threading
 from tkinter import ttk,messagebox
 win=tk.Toplevel(parent);win.title('视觉模型 API 配置');win.geometry('700x450');win.configure(bg='#171b23');frame=ttk.Frame(win,padding=16);frame.pack(fill='both',expand=True)
 try:data=load_config(path)
 except (OSError,ValueError):data={}
 variables={}
 for key,label in [('endpoint','Chat Completions 接口地址'),('model','支持图片输入的模型名／接入点ID'),('api_key','API Key（仅在本机加密保存）')]:
  ttk.Label(frame,text=label).pack(anchor='w',pady=(8,2));var=tk.StringVar(value=data.get(key,''));variables[key]=var;ttk.Entry(frame,textvariable=var,show='●' if key=='api_key' else '').pack(fill='x')
 ttk.Label(frame,text='选择视觉API引擎后，当前游戏截图会发送到上述服务，可能产生费用。默认仍使用本地OCR。Seedream是图片生成模型；请配置视觉理解模型。模型只提取字段，分数由本地计算，识别不保证比OCR准确。',wraplength=650).pack(anchor='w',pady=12)
 status=tk.StringVar();ttk.Label(frame,textvariable=status,wraplength=650).pack(anchor='w')
 def values():return {k:v.get().strip() for k,v in variables.items()}
 def save():
  try:save_config(path,values());on_save();win.destroy()
  except (ValueError,OSError) as e:messagebox.showerror('未保存',str(e),parent=win)
 def test():
  try:client=VisionClient(values())
  except ValueError as e:status.set(str(e));return
  status.set('测试中，仅发送测试文字，不发送截图…')
  def run():
   try:client.test();message='连接成功；图片识别能力请使用实际截图核验'
   except Exception as e:message=str(e).replace(client.config.get('api_key','') or '\0','[密钥]')[:300]
   try:win.after(0,lambda:status.set(message))
   except RuntimeError:pass
  threading.Thread(target=run,daemon=True).start()
 row=ttk.Frame(frame);row.pack(fill='x',pady=12);ttk.Button(row,text='测试连接',command=test).pack(side='left');ttk.Button(row,text='保存配置',command=save).pack(side='right');return win
