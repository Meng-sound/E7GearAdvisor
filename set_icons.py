"""Match all 24 user-labeled set badges without inferring from item artwork."""
import json
from pathlib import Path
from functools import lru_cache
from PIL import Image,ImageOps
ROOT=Path(__file__).parent/'data/set-icons'
ALIASES={'生命值':'生命','守护':'保护','穿透':'贯穿','团结':'夹攻'}
def canonical(name):return ALIASES.get(name,name)
DISPLAY={'生命':'生命值','保护':'守护','贯穿':'穿透'}
def display(name):return DISPLAY.get(name,name)
@lru_cache(maxsize=1)
def bank():
 import numpy as np
 rows=[]
 for record in json.loads((ROOT/'index.json').read_text(encoding='utf8')):
  image=Image.open(ROOT/record['file']).convert('RGB');a=np.asarray(image).astype(float);r,g,b=a[:,:,0],a[:,:,1],a[:,:,2];mask=(r>130)&(g>90)&(r>b*1.08)
  yy,xx=np.where(mask)
  if len(xx):image=image.crop((int(xx.min()),int(yy.min()),int(xx.max())+1,int(yy.max())+1))
  rows.append((record['name'],np.asarray(ImageOps.grayscale(image))))
 return rows
def match_set_badge(region,threshold=.80,margin=.035):
 import cv2,numpy as np
 roi=np.asarray(ImageOps.grayscale(region));scores=[]
 for name,source in bank():
  best=-1
  for fraction in (.70,.78,.86,.94,1.):
   height=max(12,round(roi.shape[0]*fraction));width=round(source.shape[1]*height/source.shape[0])
   if height>roi.shape[0] or width>roi.shape[1]:continue
   sample=cv2.resize(source,(width,height));score=float(cv2.minMaxLoc(cv2.matchTemplate(roi,sample,cv2.TM_CCOEFF_NORMED))[1]);best=max(best,score)
  scores.append((best,name))
 scores.sort(reverse=True);score,name=scores[0]
 return (name if score>=threshold and score-scores[1][0]>=margin else '',score)


def layout_text(reference):
 parts=[display(name) for name in reference.get('sets',[])]
 if reference.get('unknown_sets'):parts.append('套装待识别')
 if reference.get('unmatched_pieces'):parts.append(f"散件×{reference['unmatched_pieces']}")
 if reference.get('unreported_pieces'):parts.append(f"其余{reference['unreported_pieces']}件未标明")
 return ' / '.join(parts) or '未提供套装'
