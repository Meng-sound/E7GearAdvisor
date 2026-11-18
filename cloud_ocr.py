"""Official cloud OCR transports, normalized word boxes, encrypted credentials."""
import base64,copy,datetime,hashlib,hmac,io,json,math,re,threading,time,uuid,urllib.request,urllib.error
from urllib.parse import urlencode,quote
from pathlib import Path
from collections import OrderedDict
from PIL import Image,ImageOps
from vision_api import protect
from ocr import WindowsOCR,reconstruct_lines

PROVIDERS={'火山引擎 OCR':'volcengine','百度高精度 OCR':'baidu','阿里云 OCR':'aliyun'}
LABELS={v:k for k,v in PROVIDERS.items()}
DEFAULTS={
 'volcengine':{'access_key':'','secret_key':'','session_token':'','region':'cn-north-1'},
 'baidu':{'access_key':'','secret_key':'','mode':'accurate'},
 'aliyun':{'access_key':'','secret_key':'','session_token':'','region':'cn-hangzhou'},
}

class CloudOCRError(ValueError):pass

def validate_config(provider,config,require_keys=True):
 if provider not in DEFAULTS:raise ValueError('未知云OCR服务')
 clean={key:str(config.get(key,value)).strip() for key,value in DEFAULTS[provider].items()}
 if require_keys and (not clean['access_key'] or not clean['secret_key']):raise ValueError('请填写此服务的访问密钥和密钥Secret')
 if any('\n' in value or '\r' in value for value in clean.values()):raise ValueError('配置不能包含换行')
 if provider=='baidu' and clean['mode'] not in ('accurate','accurate_basic'):raise ValueError('百度接口模式无效')
 if provider!='baidu' and not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)+',clean['region']):raise ValueError('区域格式无效')
 return clean

def load_profiles(path):
 defaults=copy.deepcopy(DEFAULTS);path=Path(path)
 if not path.exists():return defaults
 data=json.loads(path.read_text(encoding='utf8'))
 for provider,profile in data.get('providers',{}).items():
  if provider not in defaults:continue
  for key,value in profile.items():
   if key in ('access_key','secret_key','session_token'):defaults[provider][key]=protect(value,True) if value else ''
   elif key in defaults[provider]:defaults[provider][key]=value
 return defaults

def save_profiles(path,profiles):
 result={'schema':1,'providers':{}}
 for provider in DEFAULTS:
  clean=validate_config(provider,profiles.get(provider,{}),require_keys=False)
  for key in ('access_key','secret_key','session_token'):
   if key in clean:clean[key]=protect(clean[key]) if clean[key] else ''
  result['providers'][provider]=clean
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');temporary.replace(path)

def sha(value):return hashlib.sha256(value.encode('utf8') if isinstance(value,str) else value).hexdigest()
def mac(key,value):return hmac.new(key,value.encode('utf8') if isinstance(value,str) else value,hashlib.sha256).digest()

def volc_headers(config,body,stamp=None):
 stamp=stamp or datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
 headers={'Host':'visual.volcengineapi.com','Content-Type':'application/x-www-form-urlencoded','X-Date':stamp,'X-Content-Sha256':sha(body)}
 if config.get('session_token'):headers['X-Security-Token']=config['session_token']
 lower={key.lower():value for key,value in headers.items()};signed=';'.join(sorted(lower));canonical=''.join(key+':'+lower[key]+'\n' for key in sorted(lower));query='Action=OCRNormal&Version=2020-08-26'
 request='\n'.join(('POST','/',query,canonical,signed,sha(body)));scope=stamp[:8]+'/'+config['region']+'/cv/request';to_sign='\n'.join(('HMAC-SHA256',stamp,scope,sha(request)))
 key=config['secret_key'].encode();
 for value in (stamp[:8],config['region'],'cv','request'):key=mac(key,value)
 headers['Authorization']='HMAC-SHA256 Credential='+config['access_key']+'/'+scope+', SignedHeaders='+signed+', Signature='+mac(key,to_sign).hex()
 return headers

def aliyun_headers(config,body,stamp=None,nonce=None):
 stamp=stamp or datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ');host='ocr-api.'+config['region']+'.aliyuncs.com'
 headers={'host':host,'x-acs-action':'RecognizeAdvanced','x-acs-version':'2021-07-07','x-acs-date':stamp,'x-acs-signature-nonce':nonce or str(uuid.uuid4()),'x-acs-content-sha256':sha(body)}
 if config.get('session_token'):headers['x-acs-security-token']=config['session_token']
 signed=';'.join(sorted(headers));canonical=''.join(k+':'+headers[k]+'\n' for k in sorted(headers));request='\n'.join(('POST','/','',canonical,signed,sha(body)));signature=mac(config['secret_key'].encode(),'ACS3-HMAC-SHA256\n'+sha(request)).hex()
 headers['Authorization']='ACS3-HMAC-SHA256 Credential='+config['access_key']+',SignedHeaders='+signed+',Signature='+signature;headers['Content-Type']='application/octet-stream'
 return headers

class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args):raise CloudOCRError('云OCR接口发生跳转，密钥未发送到新地址')

def post_json(url,body,headers):
 request=urllib.request.Request(url,data=body,headers=headers,method='POST')
 try:
  with urllib.request.build_opener(NoRedirect()).open(request,timeout=60) as response:raw=response.read(16*1024*1024+1)
 except urllib.error.HTTPError as e:raise CloudOCRError(f'云OCR请求失败 HTTP {e.code}，请检查密钥、授权、额度和服务区域') from None
 except (urllib.error.URLError,OSError,TimeoutError):raise CloudOCRError('云OCR网络连接失败或超时，请检查网络和接口服务状态') from None
 if len(raw)>16*1024*1024:raise CloudOCRError('云OCR响应过大，未解析')
 try:data=json.loads(raw)
 except (ValueError,UnicodeError):raise CloudOCRError('云OCR响应不是有效JSON') from None
 if not isinstance(data,dict):raise CloudOCRError('云OCR响应格式无效')
 return data

def error_code(value):return str(value)[:80] if re.fullmatch(r'[A-Za-z0-9_.:-]{1,80}',str(value)) else 'Unknown'

class Client:
 def __init__(self,provider,config,transport=None):self.provider=provider;self.config=validate_config(provider,config);self.transport=transport or post_json;self.token='';self.token_until=0
 def recognize(self,image_bytes):
  c=self.config
  if self.provider=='volcengine':
   body=urlencode({'image_base64':base64.b64encode(image_bytes).decode(),'mode':'default','filter_thresh':'0'}).encode();headers=volc_headers(c,body)
   data=self.transport('https://visual.volcengineapi.com/?Action=OCRNormal&Version=2020-08-26',body,headers)
   if data.get('code',data.get('status'))!=10000:raise CloudOCRError('云OCR火山引擎返回错误 '+error_code(data.get('code',data.get('status')))+'，请核对服务权限和额度')
  elif self.provider=='baidu':
   if not self.token or self.token_until<time.time()+60:
    body=urlencode({'grant_type':'client_credentials','client_id':c['access_key'],'client_secret':c['secret_key']}).encode();auth=self.transport('https://aip.baidubce.com/oauth/2.0/token',body,{'Content-Type':'application/x-www-form-urlencoded'})
    if not auth.get('access_token'):raise CloudOCRError('云OCR百度鉴权失败，请核对API Key和Secret Key')
    self.token=auth['access_token'];self.token_until=time.time()+float(auth.get('expires_in',3600))
   body=urlencode({'image':base64.b64encode(image_bytes).decode(),'language_type':'CHN_ENG','detect_direction':'false','probability':'true'}).encode()
   data=self.transport('https://aip.baidubce.com/rest/2.0/ocr/v1/'+c['mode']+'?access_token='+quote(self.token,safe=''),body,{'Content-Type':'application/x-www-form-urlencoded'})
   if 'error_code' in data:
    if data['error_code'] in (110,111):self.token=''
    raise CloudOCRError('云OCR百度返回错误 '+error_code(data['error_code'])+'，请检查密钥、已开通接口和额度')
  else:
   headers=aliyun_headers(c,image_bytes);data=self.transport('https://ocr-api.'+c['region']+'.aliyuncs.com/',image_bytes,headers)
   if data.get('Code') and data['Code'] not in ('Success','OK'):raise CloudOCRError('云OCR阿里云返回错误 '+error_code(data['Code'])+'，请检查权限、区域和额度')
  return normalize(self.provider,data)

def rect(value):
 if isinstance(value,dict):
  x=value.get('left',value.get('x'));y=value.get('top',value.get('y'));w=value.get('width');h=value.get('height')
 elif isinstance(value,list) and len(value)>=4:
  try:
   points=[(p.get('x'),p.get('y')) if isinstance(p,dict) else p[:2] for p in value];xs,ys=zip(*points);x,y,w,h=min(xs),min(ys),max(xs)-min(xs),max(ys)-min(ys)
  except (ValueError,TypeError):return None
 else:return None
 if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in (x,y,w,h)) or w<=0 or h<=0:return None
 return {'x':x,'y':y,'w':w,'h':h}

def normalize(provider,payload):
 rows=[]
 if provider=='volcengine':
  data=payload.get('data') or {};texts=data.get('line_texts',[]);rects=data.get('line_rects',[]);probs=data.get('line_probs',[]);chars=data.get('chars',[])
  for i,text in enumerate(texts):
   bounds=rect(rects[i]) if i<len(rects) else None;words=[]
   if i<len(chars):
    for ch in chars[i]:
     box=rect(ch)
     if box:words.append({**box,'text':str(ch.get('char','')),'confidence':ch.get('score',1)})
   rows.append((str(text),bounds,probs[i] if i<len(probs) else 1,words))
 elif provider=='baidu':
  for item in payload.get('words_result',[]):rows.append((str(item.get('words','')),rect(item.get('location')),item.get('probability',{}).get('average',1),[]))
 else:
  data=payload.get('Data',{})
  if isinstance(data,str):
   try:data=json.loads(data)
   except ValueError:raise CloudOCRError('云OCR阿里云Data字段不是有效JSON') from None
  for item in data.get('prism_wordsInfo',[]):rows.append((str(item.get('word','')),rect(item.get('pos')) or rect(item),item.get('prob',100)/100,[]))
 lines=[];missing=False
 for text,bounds,confidence,words in rows:
  if not isinstance(confidence,(int,float)) or not math.isfinite(confidence):confidence=1
  confidence=max(0,min(1,confidence))
  if not words and bounds:words=[{**bounds,'text':text,'confidence':confidence}]
  if not words:missing=True
  lines.append({'text':text,'words':words,'confidence':confidence})
 result={'ok':True,'lines':lines,'text':reconstruct_lines(lines) if any(l['words'] for l in lines) else '\n'.join(l['text'] for l in lines),'engine':LABELS[provider],'positions_available':not missing}
 return result

class CloudOCR:
 def __init__(self,provider,config,transport=None):
  self.client=Client(provider,config,transport);self.engine_name=LABELS[provider];self.windows=None;self.cache=OrderedDict();self.lock=threading.Lock();self.calls=0;self.frame_calls=0;self.last_call=0
 def begin_frame(self):self.frame_calls=0
 def request(self,**request):
  if request.get('action')=='languages':return {'ok':True,'languages':['zh-Hans-CN','en-US'],'engine':self.engine_name}
  if request.get('capture_only') or request.get('rect'):
   if self.windows is None:self.windows=WindowsOCR()
   return self.windows.request(**request)
  if not request.get('path'):raise CloudOCRError('云OCR缺少截图路径')
  with Image.open(request['path']) as source:picture=source.convert('RGB')
  return self.read_image(picture)
 def read_image(self,picture):
  with self.lock:
   original_size=picture.size;key=(original_size,hashlib.blake2b(picture.tobytes(),digest_size=16).digest())
   if key in self.cache:self.cache.move_to_end(key);return copy.deepcopy(self.cache[key])
   if self.frame_calls>=20:raise CloudOCRError('云OCR本次读图已达到20次请求上限，请切回本地OCR或重新读取')
   if max(picture.size)>=8000:picture=ImageOps.contain(picture,(7900,7900),Image.Resampling.LANCZOS)
   if min(picture.size)<32:
    factor=32/min(picture.size);picture=picture.resize((round(picture.width*factor),round(picture.height*factor)),Image.Resampling.LANCZOS)
   buf=io.BytesIO();picture.save(buf,format='PNG');body=buf.getvalue()
   if len(body)>5*1024*1024:raise CloudOCRError('云OCR截图超过5MB，请缩小截图范围')
   delay=1.05-(time.monotonic()-self.last_call)
   if delay>0:time.sleep(delay)
   self.calls+=1;self.frame_calls+=1;self.last_call=time.monotonic();result=self.client.recognize(body)
   sx=original_size[0]/picture.width;sy=original_size[1]/picture.height
   for line in result['lines']:
    for word in line['words']:word.update(x=word['x']*sx,y=word['y']*sy,w=word['w']*sx,h=word['h']*sy)
   self.cache[key]=copy.deepcopy(result)
   if len(self.cache)>256:self.cache.popitem(last=False)
   return result
 def recognize_tiles(self,tiles):
  if not tiles:return []
  columns=8;cell_w,cell_h=320,120;montage=Image.new('RGB',(min(columns,len(tiles))*cell_w,math.ceil(len(tiles)/columns)*cell_h),'#050b13')
  for i,tile in enumerate(tiles):
   enlarged=tile.convert('RGB');enlarged.thumbnail((288,96),Image.Resampling.LANCZOS);montage.paste(enlarged,((i%columns)*cell_w+16,(i//columns)*cell_h+12))
  result=self.read_image(montage)
  if not result.get('positions_available'):raise CloudOCRError('云OCR所选接口未返回位置，数字批量识别需要百度高精度含位置版')
  grouped={}
  for line in result['lines']:
   for word in line['words']:
    col=int((word['x']+word['w']/2)//cell_w);row=int((word['y']+word['h']/2)//cell_h);index=row*columns+col
    if 0<=index<len(tiles):grouped.setdefault(index,[]).append(word)
  return [(''.join(w['text'] for w in sorted(grouped.get(i,[]),key=lambda w:w['x'])),min((w.get('confidence',1) for w in grouped.get(i,[])),default=0)) for i in range(len(tiles))]
 def close(self):
  if self.windows:self.windows.close()
