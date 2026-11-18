import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Gear,Stat
from advice import evaluate_advice
from recognition_check import recognition_notice
class CurrentRules(unittest.TestCase):
 def gear(self,score=25,speed=0):
  return Gear(slot='项链',set_name='速度',grade='英雄',level=85,enhance=0,main=Stat('hp_pct',12),subs=[Stat('hp_pct',score-speed*2),Stat('spd',speed)] if speed else [Stat('hp_pct',score)])
 def test_new_unenhanced_gate(self):
  for slot in ('武器','头盔','铠甲','项链','戒指','鞋子'):
   for grade in ('英雄','史诗'):
    right=slot in ('项链','戒指','鞋子');gate=(18 if right else 20)+(2 if grade=='史诗' else 0)
    for score,expected in [(gate,'enhance'),(gate-.001,'discard')]:
     g=self.gear();g.slot=slot;g.grade=grade
     n=4 if grade=='史诗' else 3;g.subs=[Stat(k,v) for k,v in zip(('hp_pct','def_pct','eff','res'),[score-(n-1),*([1]*(n-1))])]
     r=evaluate_advice(g);self.assertEqual(r['kind'],expected,(slot,grade,score,r));self.assertEqual(r['threshold'],gate)
     self.assertIn('右三件' if right else '左三件',r['threshold_text']);self.assertIn('红装' if grade=='史诗' else '紫装',r['threshold_text'])
 def test_initial_purple_speed_retention(self):
  for speed,expected in [(2,'discard'),(3,'enhance'),(4,'enhance')]:
   g=self.gear(15,speed);g.slot='武器';r=evaluate_advice(g);self.assertEqual(r['kind'] if r['kind']!='backup' else 'discard',expected)
  g=self.gear(15,4);self.assertEqual(evaluate_advice(g)['kind'],'enhance')
 def test_right_fixed_main_blocks_high_score_speed_and_confirmation(self):
  for slot in ('项链','戒指','鞋子'):
   for key in ('atk','hp','def'):
    g=self.gear(80,20);g.slot=slot;g.main=Stat(key,100)
    for confirmed in (False,True):
     r=evaluate_advice(g,fixed_main_confirmed=confirmed);self.assertEqual(r['kind'],'discard');self.assertIn('右三件',r['threshold_text']);self.assertTrue(r['blocked_fixed_main'])
 def test_no_plus_three_conditional_node(self):
  g=self.gear();g.enhance=None;g.subs=[Stat('hp_pct',8),Stat('def_pct',5),Stat('eff',5)]
  r=evaluate_advice(g);self.assertNotIn('+3','\n'.join(r.get('case_details',[])))
 def test_official_score_is_optional(self):
  g=self.gear();g.subs=[Stat('atk',31),Stat('cdmg',4),Stat('hp',172)];g.screen_score=None
  self.assertEqual(recognition_notice(g),'')
  g.level=None;self.assertIn('装备等级',recognition_notice(g));self.assertNotIn('官方',recognition_notice(g))
 def test_missing_metadata_explains_left_right_levels_and_all_stages(self):
  g=Gear(subs=[Stat('hp_pct',11),Stat('spd',3),Stat('crit',9),Stat('cdmg',14)])
  r=evaluate_advice(g);text='\n'.join(r['case_details']);self.assertAlmostEqual(r['score'],47.4)
  for value in ('85级','88级','左三件','右三件','+9','+12','门槛40','门槛46'):self.assertIn(value,text)
if __name__=='__main__':unittest.main()
