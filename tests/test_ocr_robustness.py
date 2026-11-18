import unittest,tempfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from core import parse_stat,Gear,Stat
from adaptive_reader import header_metadata
from vision import ScreenReader

class OCRRobustnessTests(unittest.TestCase):
 def test_increment_percent_does_not_change_flat_current_stat(self):
  for line in ['攻击力100+8%','攻击力100(+8%)','生命值1,200+5%']:
   s=parse_stat(line);self.assertIn(s.key,('atk','hp'));self.assertEqual(s.value,1200 if '生命' in line else 100)
 def test_current_percentage_and_prefix_are_preserved(self):
  self.assertEqual(parse_stat('攻击力19%+6%'),Stat('atk_pct',19))
  self.assertEqual(parse_stat('攻击力%19'),Stat('atk_pct',19))
 def test_grouped_numbers_and_malformed_groups(self):
  self.assertEqual(parse_stat('生命值2,835'),Stat('hp',2835))
  self.assertIsNone(parse_stat('生命值12,5'))
 def test_roll_count_is_not_value(self):
  self.assertEqual(parse_stat('生命值(2)17%(+4%)'),Stat('hp_pct',17))
 def test_fragmented_level_and_badge(self):
  def word(t,x,y=12):return {'text':t,'x':x,'y':y,'w':10,'h':20,'confidence':.95}
  result={'lines':[{'words':[word('8',10),word('5',22),word('+',70),word('1',82),word('5',94)]}]}
  r=header_metadata(result,500,600);self.assertEqual(r['level'],85);self.assertEqual(r['enhance'],15)
 def test_separate_rows_and_distant_numbers_are_not_joined(self):
  words=[{'text':'8','x':10,'y':10,'w':10,'h':20},{'text':'5','x':23,'y':45,'w':10,'h':20},{'text':'8','x':60,'y':10,'w':10,'h':20}]
  self.assertIsNone(header_metadata({'lines':[{'words':words}]},500,600)['level'])
 def test_partial_badge_is_replaced_by_complete_group(self):
  words=[{'text':'+1','x':10,'y':10,'w':20,'h':20,'confidence':.95},{'text':'5','x':32,'y':10,'w':10,'h':20,'confidence':.95}]
  self.assertEqual(header_metadata({'lines':[{'words':words}]},500,600)['enhance'],15)
  words[1]['confidence']=.4
  self.assertIsNone(header_metadata({'lines':[{'words':words}]},500,600)['enhance'])
 def test_panel_cache_ignores_unrelated_currency_but_not_equipment(self):
  class OCR:pass
  reader=ScreenReader(OCR());image=Image.new('RGB',(1821,1055),'black')
  def detail(current,*args):return {'kind':'single','layout':'inventory-right','gear':Gear(subs=[Stat('spd',10+current.getpixel((1500,600))[0])])}
  with tempfile.TemporaryDirectory() as folder,patch('vision.normalise',side_effect=lambda x:x.convert('RGB')),patch('vision.page_hint',return_value='inventory'),patch('vision.try_inventory',side_effect=detail) as read:
   path=Path(folder)/'frame.png';image.save(path);first=reader.read({'path':str(path)},mode='single')
   image.putpixel((1000,60),(1,0,0));image.save(path);second=reader.read({'path':str(path)},mode='single')
   self.assertEqual(read.call_count,1);self.assertTrue(second['cache_hit']);self.assertEqual(second['cache_scope'],'equipment-panel')
   image.putpixel((1500,600),(1,0,0));image.save(path);third=reader.read({'path':str(path)},mode='single')
   self.assertEqual(read.call_count,2);self.assertEqual(third['gear'].subs[0].value,11)

if __name__=='__main__':unittest.main()
