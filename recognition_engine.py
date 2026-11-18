"""Full-frame vision API route; never send every OCR tile to a cloud model."""
import tempfile,hashlib,copy
from pathlib import Path
from collections import OrderedDict
from PIL import Image
from ocr import WindowsOCR
from vision_api import VisionClient,load_config

class VisionScreenReader:
 def __init__(self,path):
  self.client=VisionClient(load_config(path));self.ocr=None;self.frames=OrderedDict()
 def read(self,request,mode='single',slot='',on_captured=None):
  with tempfile.TemporaryDirectory(prefix='e7-api-') as td:
   source=request.get('path')
   if not source:
    if self.ocr is None:self.ocr=WindowsOCR()
    source=str(Path(td)/'game.png');self.ocr.request(rect=request['rect'],save_to=source,capture_only=True)
    if on_captured:on_captured()
   with Image.open(source) as img:key=(mode,img.size,hashlib.blake2b(img.convert('RGB').tobytes(),digest_size=16).digest())
   if key in self.frames:
    value=copy.deepcopy(self.frames[key]);value['cache_hit']=True;return value
   value=self.client.read(source,mode)
   self.frames[key]=copy.deepcopy(value)
   if len(self.frames)>6:self.frames.popitem(last=False)
   return value
 def close(self):
  if self.ocr:self.ocr.close()
