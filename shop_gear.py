"""Strict tooltip parsing: one main stat plus exactly four distinct substats."""
import re
from core import parse_stat

def parse_tooltip(text):
 lines=[re.sub(r'\s+','',line).replace('％','%').replace('＋','+') for line in text.splitlines() if line.strip()]
 stats=[];header=[]
 for line in lines:
  if '套装' in line or '装备分数' in line:
   if not stats:header.append(line)
   continue
  stat=parse_stat(line)
  if stat:stats.append(stat)
  elif not stats:header.append(line)
 heading='\n'.join(header)
 if '传说' not in heading and '傳說' not in heading:return None
 if not re.search(r'(?<!\d)85(?!\d)',heading):return None
 enhancements=re.findall(r'\+(\d{1,2})(?!\d)',heading)
 if enhancements and any(int(value)!=0 for value in enhancements):return None
 if len(stats)!=5:return None
 subs=stats[1:]
 if len({stat.key for stat in subs})!=4:return None
 return dict(kind='gear',verified=True,level=85,grade='epic',enhance=0,price=1400000,
             subs=[dict(key=stat.key,value=stat.value) for stat in subs])

def read_tooltip(image,ocr):
 import tempfile
 from pathlib import Path
 with tempfile.TemporaryDirectory(prefix='e7-shop-detail-') as directory:
  path=Path(directory)/'detail.png'
  image.crop((round(image.width*.12),round(image.height*.10),round(image.width*.86),round(image.height*.94))).save(path)
  return parse_tooltip(ocr.request(path=str(path)).get('text',''))
