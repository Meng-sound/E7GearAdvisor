"""Lossless-input text crop cache; changed amounts always go through recognition."""
import copy,hashlib
from collections import OrderedDict

class ExactCropCache:
 def __init__(self,recognizer,limit=512):
  self.recognizer=recognizer;self.limit=limit;self.cache=OrderedDict();self.hits=0;self.misses=0
 def __getattr__(self,name):return getattr(self.recognizer,name)
 def __call__(self,images,return_word_box=False):
  if hasattr(images,'ndim'):images=[images]
  results=[None]*len(images);missing=[];positions=[];keys=[]
  for index,image in enumerate(images):
   key=(image.shape,str(image.dtype),bool(return_word_box),hashlib.blake2b(image.tobytes(),digest_size=16).digest())
   if key in self.cache:
    self.hits+=1;self.cache.move_to_end(key);results[index]=copy.deepcopy(self.cache[key])
   else:self.misses+=1;missing.append(image);positions.append(index);keys.append(key)
  elapsed=0
  if missing:
   recognized,elapsed=self.recognizer(missing,return_word_box)
   for index,key,value in zip(positions,keys,recognized):
    self.cache[key]=copy.deepcopy(value);results[index]=value
   while len(self.cache)>self.limit:self.cache.popitem(last=False)
  return results,elapsed

class FrameCache:
 """Cache identical OCR inputs; ignore only the shop portrait between inputs."""
 def __init__(self,ocr,epoch=lambda:0,ignore_portrait=False,limit=8):
  self.ocr=ocr;self.read=ocr.read;self.epoch=epoch;self.ignore_portrait=ignore_portrait;self.limit=limit
  self.cache=OrderedDict();self.shop=False;self.hits=0;self.misses=0
 def __call__(self,image,*args,**kwargs):
  masked=self.ignore_portrait and self.shop and image.shape[:2]==(1023,1819)
  if masked:
   sample=image.copy();sample[184:818,:618]=0
  else:sample=image
  key=(self.epoch(),image.shape,str(image.dtype),masked,args,tuple(sorted(kwargs.items())),hashlib.blake2b(sample.tobytes(),digest_size=16).digest())
  if key in self.cache:
   self.hits+=1;self.cache.move_to_end(key);result,dim=self.cache[key]
   self.ocr.last_dim_items=copy.deepcopy(dim);return copy.deepcopy(result)
  self.misses+=1;result=self.read(image,*args,**kwargs);dim=getattr(self.ocr,'last_dim_items',[])
  if image.shape[:2]==(1023,1819):self.shop=any('秘密商店' in ''.join(item.text.split()) for item in result+dim)
  self.cache[key]=(copy.deepcopy(result),copy.deepcopy(dim))
  if not masked and self.ignore_portrait and self.shop and image.shape[:2]==(1023,1819):
   sample=image.copy();sample[184:818,:618]=0
   alias=list(key);alias[3]=True;alias[-1]=hashlib.blake2b(sample.tobytes(),digest_size=16).digest()
   self.cache[tuple(alias)]=self.cache[key]
  while len(self.cache)>self.limit:self.cache.popitem(last=False)
  return result

def enable(ocr,epoch=None,ignore_portrait=False):
 if not isinstance(ocr._engine.text_rec,ExactCropCache):ocr._engine.text_rec=ExactCropCache(ocr._engine.text_rec)
 if epoch is not None and not isinstance(ocr.read,FrameCache):ocr.read=FrameCache(ocr,epoch,ignore_portrait)
 return ocr
