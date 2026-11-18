import sys,tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from core import Gear,Stat
from advice import evaluate_advice
from vision import ScreenReader,cosine
from fast_vision import ranked
class FastCacheTests(unittest.TestCase):
 def test_cosine_vectorization_preserves_scores(self):
  templates={'a':[[1,2,3],[2,1,3]],'b':[[3,2,1]]};shape=[4,5,6]
  expected=sorted((cosine(shape,v),k) for k,values in templates.items() for v in values)[::-1]
  actual=ranked(shape,templates)
  if actual is None:self.skipTest('NumPy unavailable in optional legacy environment')
  self.assertEqual([x[1] for x in actual],[x[1] for x in expected])
  for a,b in zip(actual,expected):self.assertAlmostEqual(a[0],b[0],places=12)
 def test_exact_frame_reuse_is_independent_and_invalidates_on_change(self):
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/'frame.png';image=Image.new('RGB',(1821,1055),'#050b13');image.save(path)
   reader=ScreenReader(object());gear=Gear(level=85,enhance=0,grade='英雄',subs=[Stat('hp_pct',10)])
   with patch('vision.page_hint',return_value='inventory'),patch('vision.try_inventory',return_value={'kind':'single','gear':gear}) as call:
    first=reader.read({'path':str(path)},mode='single');first['gear'].subs[0].value=999
    second=reader.read({'path':str(path)},mode='single');self.assertTrue(second['cache_hit']);self.assertEqual(second['gear'].subs[0].value,10);self.assertEqual(call.call_count,1)
    image.putpixel((1300,550),(255,255,255));image.save(path);reader.read({'path':str(path)},mode='single');self.assertEqual(call.call_count,2)
 def test_all_blue_equipment_is_discarded(self):
  for level in (75,85,88,90):
   gear=Gear(level=level,enhance=0,grade='稀有',subs=[Stat('spd',30),Stat('hp_pct',80)])
   self.assertEqual(evaluate_advice(gear)['kind'],'discard')
if __name__=='__main__':unittest.main()
