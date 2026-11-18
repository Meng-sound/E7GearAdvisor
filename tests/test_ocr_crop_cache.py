import unittest
from ocr_crop_cache import ExactCropCache,FrameCache
from types import SimpleNamespace

class Crop:
 shape=(1,1,3);dtype='uint8'
 def __init__(self,value):self.value=value
 def tobytes(self):return bytes([self.value])

class CacheTests(unittest.TestCase):
 def recognizer(self,images,return_word_box=False):
  self.calls+=1;return [[str(image.value),1.] for image in images],.5
 def setUp(self):self.calls=0;self.cache=ExactCropCache(self.recognizer,limit=2)
 def test_exact_pixels_only_and_changed_price_recognized_again(self):
  first,_=self.cache([Crop(3)]);second,elapsed=self.cache([Crop(3)])
  self.assertEqual(first,second);self.assertEqual(self.calls,1);self.assertEqual(elapsed,0)
  result,_=self.cache([Crop(4)]);self.assertEqual(result[0][0],'4');self.assertEqual(self.calls,2)
 def test_cached_result_cannot_be_mutated_by_caller(self):
  result,_=self.cache([Crop(3)]);result[0][0]='wrong'
  result,_=self.cache([Crop(3)]);self.assertEqual(result[0][0],'3')
 def test_lru_is_bounded_and_word_box_mode_is_separate(self):
  self.cache([Crop(1)]);self.cache([Crop(2)]);self.cache([Crop(3)])
  self.assertEqual(len(self.cache.cache),2)
  self.cache([Crop(3)],True);self.assertEqual(self.calls,4)

class FrameCacheTests(unittest.TestCase):
 def test_input_or_pixel_change_always_triggers_fresh_read(self):
  count=[];epoch=[0]
  def read(image,*args,**kwargs):count.append(image.value);return [SimpleNamespace(text=str(image.value))]
  ocr=SimpleNamespace(read=read,last_dim_items=[SimpleNamespace(text='dim')]);cache=FrameCache(ocr,epoch=lambda:epoch[0])
  cache(Crop(3));cache(Crop(3));self.assertEqual(count,[3])
  epoch[0]+=1;cache(Crop(3));self.assertEqual(count,[3,3])
  cache(Crop(4));self.assertEqual(count,[3,3,4])
 def test_thresholds_and_dim_metadata_are_preserved(self):
  calls=[]
  def read(image,*args,**kwargs):calls.append(kwargs);return [SimpleNamespace(text='price')]
  ocr=SimpleNamespace(read=read,last_dim_items=[SimpleNamespace(text='dim')]);cache=FrameCache(ocr)
  result=cache(Crop(3),min_score=.55);result[0].text='changed';ocr.last_dim_items=[]
  result=cache(Crop(3),min_score=.55)
  self.assertEqual(result[0].text,'price');self.assertEqual(ocr.last_dim_items[0].text,'dim')
  cache(Crop(3),min_score=.45);self.assertEqual(len(calls),2)
