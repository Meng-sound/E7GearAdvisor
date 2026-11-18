"""Read hero names and white panel totals; never infer artifact contributions."""
import re
from pathlib import Path
from PIL import Image,ImageOps
from core import parse_stat

def find_hero(text,catalog):
 text=re.sub(r'\s+','',text).casefold().replace('梦里娜','萝里娜');matches=[]
 for h in catalog['heroes']:
  for name in (h['name'],h['name_en'],*h.get('aliases',[])):
   key=re.sub(r'\s+','',name).casefold()
   if len(key)>=2 and key in text:matches.append((len(key),h))
 return max(matches,key=lambda x:x[0])[1] if matches else None

def read_name(image,ocr,directory,catalog):
 path=Path(directory)/'hero-name.png';image.crop((140,175,510,270)).save(path)
 text=ocr.request(path=str(path)).get('text','');hero=find_hero(text,catalog)
 if hero is None:
  image.crop((140,175,510,270)).resize((1110,285),Image.Resampling.LANCZOS).save(path)
  enlarged=ocr.request(path=str(path)).get('text','');hero=find_hero(enlarged,catalog);text+='\n'+enlarged
 return hero,text

def try_character(image,ocr,directory,catalog):
 hero,name_text=read_name(image,ocr,directory,catalog)
 if hero is None:return None
 crop=image.crop((140,610,505,930)).convert('RGB')
 # Gold/orange addends are excluded before text recognition.
 grey=Image.new('L',crop.size);grey.putdata([255 if min(p)>135 and max(p)-min(p)<65 else 0 for p in crop.getdata()]);path=Path(directory)/'hero-white-totals.png';grey.save(path)
 result=ocr.request(path=str(path));panel={}
 for line in result.get('text','').splitlines():
  line=line.replace('防往力','防御力').replace('防卸力','防御力')
  if '击率' in line or '擊率' in line:line=re.sub(r'^.*?[击擊]率','暴击率',line)
  if '击伤害' in line or '擊傷害' in line:line=re.sub(r'^.*?[击擊][伤傷]害','暴击伤害',line)
  stat=parse_stat(line)
  if stat:
   key=stat.key.removesuffix('_pct')
   if key in ('atk','hp','def','spd','crit','cdmg','eff','res','dual') and stat.value>=0:panel[key]=stat.value
 if not all(k in panel for k in ('atk','hp','def','spd')):return None
 from character_loadout import read_loadout_image
 try:loadout=read_loadout_image(image,ocr,directory,hero)
 except (OSError,ValueError,RuntimeError):loadout={'sets':[],'artifact':None,'imprint':None,'warnings':['套装、神器和刻印读取未完成，请核对']}
 return {'kind':'character','hero_name':hero['name'],'hero_id':hero['id'],'panel':panel,'loadout':loadout,'text':name_text+'\n'+result.get('text',''),'layout':'hero-panel','notice':'已读取角色面板与加成候选，请核对未确定项。'}

def read_character_request(image,ocr,directory,catalog,selected_id=None):
 """A dedicated read path accepts imprint detail tables without erasing totals."""
 path=Path(directory)/'character-full.png';image.save(path)
 raw=ocr.request(path=str(path));text=raw.get('text','')
 if '刻印记忆效果' in re.sub(r'\s+','',text) or ('开放型刻印' in text and '自身刻印' in text):
  hero,_=read_name(image,ocr,directory,catalog)
  hero=hero or next((h for h in catalog['heroes'] if h['id']==selected_id),None)
  if hero is None:raise ValueError('请先选择此刻印详情对应的角色')
  from hero_imprints import read_popup_profiles
  words=[word for line in raw.get('lines',[]) for word in line.get('words',[])]
  records=read_popup_profiles(words,image.width,hero)
  if not records:raise ValueError('刻印等级表未读全，请保持详情窗口完整显示')
  return {'kind':'character_metadata','hero_id':hero['id'],'hero_name':hero['name'],'imprint_profiles':records,'text':text}
 value=try_character(image,ocr,directory,catalog)
 if value is None:raise ValueError('未读到完整角色面板，请打开角色详情或刻印详情')
 return value
