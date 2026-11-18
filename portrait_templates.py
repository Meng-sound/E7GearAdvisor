"""Locally registered cropped skin portraits; never upload screenshots."""
import hashlib,re
from pathlib import Path
from PIL import Image,ImageOps
def register(path,hero_id,destination):
 if not re.fullmatch(r'c\d+',hero_id):raise ValueError('英雄ID无效')
 with Image.open(path) as source:
  if not 24<=source.width<=1024 or not 24<=source.height<=1024:raise ValueError('请先裁剪为单个英雄头像（24至1024像素）')
  image=ImageOps.fit(source.convert('RGBA'),(96,96),method=Image.Resampling.LANCZOS)
 digest=hashlib.sha256(image.tobytes()).hexdigest()[:16];folder=Path(destination);folder.mkdir(parents=True,exist_ok=True);target=folder/f'{hero_id}__{digest}.png'
 if not target.exists():
  temporary=target.with_suffix('.tmp');image.save(temporary,format='PNG');temporary.replace(target)
 return target
