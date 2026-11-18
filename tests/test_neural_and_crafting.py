import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Gear,Stat
from adaptive_reader import header_metadata
from craft_window import crafted_decision
BASE={'atk':1200,'hp':5000,'def':600}
class NeuralCraftTests(unittest.TestCase):
 def test_header_reads_full_level_and_plus_badge(self):
  words=[{'text':'85','x':50,'y':60,'w':35,'h':25,'confidence':.93},{'text':'+15','x':125,'y':45,'w':45,'h':25,'confidence':.99}]
  result=header_metadata({'lines':[{'words':words}]},570,660)
  self.assertEqual((result['level'],result['enhance']),(85,15))
 def test_single_clipped_digit_not_a_level(self):
  result=header_metadata({'lines':[{'words':[{'text':'8','x':50,'y':60,'w':15,'h':25}]}]},570,660)
  self.assertIsNone(result['level'])
 def test_typed_percent_is_required_in_crafted_score(self):
  gear=Gear(level=85,enhance=0,grade='英雄',subs=[Stat('atk_pct',19),Stat('crit',4),Stat('cdmg',4)])
  self.assertEqual(crafted_decision(gear,BASE)['category'],'keep')
  gear.subs[0]=Stat('atk',19)
  self.assertEqual(crafted_decision(gear,BASE)['category'],'discard')
 def test_blue_two_substats_complete_and_speed_exception(self):
  gear=Gear(level=85,enhance=0,grade='稀有',subs=[Stat('res',6),Stat('atk_pct',7)])
  self.assertEqual(crafted_decision(gear,BASE)['category'],'discard')
  gear.subs=[Stat('spd',3),Stat('res',6)]
  self.assertEqual(crafted_decision(gear,BASE)['category'],'discard')
 def test_missing_attribute_type_is_not_complete(self):
  gear=Gear(level=85,enhance=0,grade='英雄',subs=[Stat('spd',4),Stat('eff',5)])
  self.assertEqual(crafted_decision(gear,BASE)['category'],'review')
if __name__=='__main__':unittest.main()
