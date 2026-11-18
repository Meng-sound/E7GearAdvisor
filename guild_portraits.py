"""Local portrait matching for the enemy half of a visible GW preparation screen."""
from pathlib import Path
from PIL import Image,ImageOps
import sys

def dependencies():
 neural=str(Path(__file__).parent/'neural')
 if neural not in sys.path:sys.path.insert(0,neural)
 import cv2,numpy as np
 return cv2,np

class PortraitMatcher:
 def __init__(self,catalog,data_dir,extra_dir=None):
  self.cv2,self.np=dependencies();self.heroes=[];features=[];self.root=Path(data_dir)
  for hero in catalog['heroes']:
   paths=[self.root/hero.get('portrait',''),*sorted((self.root/'hero-skins').glob(hero['id']+'_s*_s.png'))]
   if extra_dir:paths.extend([*sorted(Path(extra_dir).glob(hero['id']+'__*.png')),*sorted(Path(extra_dir).glob(hero['id']+'_s*_s.png'))])
   for path in paths:
    if not path.is_file() or path.name=='diche-icon.png':continue
    try:
     with Image.open(path) as image:feature=self.feature(image)
    except (OSError,ValueError):continue
    self.heroes.append(hero);features.append(feature)
  if not features:raise ValueError('没有可用的英雄头像模板，请先更新英雄资料')
  self.bank=self.np.stack(features)
 def feature(self,image):
  np=self.np;cv2=self.cv2
  rgba=ImageOps.fit(image.convert('RGBA'),(48,48),method=Image.Resampling.LANCZOS)
  background=Image.new('RGBA',(48,48),(32,38,48,255));background.alpha_composite(rgba)
  a=np.asarray(background.convert('RGB')).astype('float32');a=cv2.GaussianBlur(a,(3,3),0)
  yy,xx=np.mgrid[:48,:48];mask=((xx-23.5)**2+(yy-22.5)**2)<(17.8**2)
  vector=a[mask].ravel();vector-=vector.mean();norm=np.linalg.norm(vector)
  return vector/max(float(norm),1e-6)
 def match(self,image):
  scores=self.np.einsum('ij,j->i',self.bank,self.feature(image));order=self.np.argsort(scores)[::-1]
  candidates=[];seen=set()
  for i in order:
   hero=self.heroes[int(i)]
   if hero['id'] in seen:continue
   seen.add(hero['id']);candidates.append({'id':hero['id'],'name':hero['name'],'score':round(float(scores[i]),4)})
   if len(candidates)==3:break
  best=candidates[0];margin=best['score']-candidates[1]['score'] if len(candidates)>1 else 1
  return {'hero_id':best['id'] if best['score']>=.76 and margin>=.045 else None,'score':best['score'],'margin':round(margin,4),'candidates':candidates}
 def recognize(self,image):
  primary=self._recognize_scaled(image,min(1,1280/image.width))
  if not primary['needs_confirmation'] or image.width>=1280:return primary
  # A small compressed frame may miss circles at its native resolution.
  # Retry at the working resolution only when the first pass is incomplete;
  # never replace an already complete team with a different resampled match.
  alternate=self._recognize_scaled(image,1280/image.width)
  return alternate if sum(map(len,alternate['rounds']))>sum(map(len,primary['rounds'])) else primary
 def _recognize_scaled(self,image,scale):
  cv2,np=self.cv2,self.np
  rgb=image.convert('RGB');rgb=rgb.resize((round(rgb.width*scale),round(rgb.height*scale)),Image.Resampling.LANCZOS)
  a=np.asarray(rgb);h,w=a.shape[:2];gray=cv2.cvtColor(a,cv2.COLOR_RGB2GRAY);gray=cv2.GaussianBlur(gray,(5,5),0)
  circles=cv2.HoughCircles(gray,cv2.HOUGH_GRADIENT,dp=1.25,minDist=max(25,int(h*.065)),param1=110,param2=26,minRadius=max(15,int(h*.032)),maxRadius=max(20,int(h*.085)))
  detections=[]
  for x,y,r in circles[0] if circles is not None else []:
   # The enemy formation starts near the middle of the screen. The rightmost
   # quarter is the hero roster, not the enemy team. Searching farther right
   # both loses the enemy's left slot and admits roster/background circles.
   if not (.44*w<x<.76*w and .09*h<y<.82*h):continue
   best=None
   for fraction in (.88,1.,1.12):
    radius=r*fraction;box=(int(x-radius),int(y-radius),int(x+radius),int(y+radius))
    if min(box[:2])<0 or box[2]>w or box[3]>h:continue
    candidate=self.match(rgb.crop(box))
    if best is None or candidate['score']>best['score']:best={**candidate,'box':tuple(round(v/scale) for v in box),'center':(float(x),float(y)),'radius':float(r)}
   # Class/level badges and stars distort the detected circle. Register its
   # crop locally at several scales; retain the normal identity threshold.
   if best and best['score']>=.54:
    original=best['box'];width=(original[2]-original[0])*scale;height=(original[3]-original[1])*scale
    for offsets in ((-.12,-.06,0,.06,.12),(-.28,-.14,0,.14,.28)):
     if offsets[0]==-.28 and best['hero_id']:break
     for fraction in (.9,1.,1.1):
      for horizontal in offsets:
       for vertical in offsets:
        dx=r*horizontal;dy=r*vertical
        box=(round(x+dx-width*fraction/2),round(y+dy-height*fraction/2),round(x+dx+width*fraction/2),round(y+dy+height*fraction/2))
        if min(box[:2])<0 or box[2]>w or box[3]>h:continue
        candidate=self.match(rgb.crop(box))
        if candidate['score']>best['score']:best={**candidate,'box':tuple(round(v/scale) for v in box),'center':(float(x),float(y)),'radius':float(r)}
    # Unmatched background circles must not move the boundary between rounds
    # or displace an actual portrait when selecting a three-hero team.
    if best['hero_id']:detections.append(best)
  detections.sort(key=lambda x:x['score'],reverse=True);selected=[]
  for item in detections:
   x,y=item['center']
   if any((x-other['center'][0])**2+(y-other['center'][1])**2<(.85*(item['radius']+other['radius']))**2 for other in selected):continue
   selected.append(item)
  selected=sorted(selected[:10],key=lambda x:x['center'][1]);rounds=[[],[]]
  if len(selected)>=4:
   gaps=[selected[i+1]['center'][1]-selected[i]['center'][1] for i in range(len(selected)-1)];cut=max(range(len(gaps)),key=gaps.__getitem__)+1
   if gaps[cut-1]>=h*.12:groups=[selected[:cut],selected[cut:]]
   else:groups=[selected,[]] if np.median([x['center'][1] for x in selected])<h*.45 else [[],selected]
  else:groups=[selected,[]] if not selected or np.median([x['center'][1] for x in selected])<h*.45 else [[],selected]
  for index,group in enumerate(groups):
   best=sorted(group,key=lambda x:x['score'],reverse=True)[:3];rounds[index]=sorted(best,key=lambda x:x['center'][0])
  return {'rounds':rounds,'detected':len(selected),'needs_confirmation':any(len(row)!=3 or any(not x['hero_id'] for x in row) for row in rounds)}
