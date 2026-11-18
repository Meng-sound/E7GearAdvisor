import unittest,sys,re
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Gear,Stat,parse_stat,parse_text,import_heroes
from advice import evaluate_advice
from candidate_panel import candidate_rows
from hero_picker import load_catalog,search_heroes
from quality_profiles import QUALITY_NAMES
import json
ROOT=Path(__file__).resolve().parents[1]
class V08Tests(unittest.TestCase):
 def test_white_current_total_not_orange_increment(self):
  self.assertEqual(parse_stat('效果命中(1)11%(+4%)').value,11)
  self.assertEqual(parse_stat('暴击率(1)9%(+5%)').value,9)
  self.assertIsNone(parse_stat('暴击率(1)(+5%)'))
 def test_unlock_and_score_delta_not_stage(self):
  for text in ['英雄铠甲\n强化+12时获得','装备分数61(+11)']:
   self.assertIsNone(parse_text(text).enhance)
 def test_strict_threshold_no_two_point_tolerance(self):
  g=Gear(slot='武器',grade='史诗',level=85,enhance=9,subs=[Stat('hp_pct',10),Stat('def_pct',10),Stat('eff',10),Stat('res',9)])
  self.assertEqual(evaluate_advice(g)['kind'],'discard')
  g.subs[-1].value=10;self.assertEqual(evaluate_advice(g)['kind'],'enhance')
 def test_only_three_colors(self):
  self.assertTrue(all(name[0] in '红紫蓝' for name in QUALITY_NAMES))
 def test_names_portraits_and_new_aliases(self):
  catalog=load_catalog(ROOT/'data/hero-catalog.json')
  self.assertEqual(search_heroes(catalog['heroes'],'光飞剑')[0]['name_en'],'Monarch of the Sword Iseria')
  self.assertEqual(search_heroes(catalog['heroes'],'大木盾')[0]['name_en'],'Yulha')
  heroes=import_heroes(json.loads((ROOT/'data/heroes.json').read_text(encoding='utf-8')))
  g=Gear(slot='铠甲',level=90,enhance=15,subs=[Stat('hp_pct',25),Stat('spd',11),Stat('eff',15),Stat('res',7)])
  rows=candidate_rows(g,heroes,catalog,{'atk':1200,'hp':5000,'def':600},'role')
  self.assertEqual(len(rows),25)
  self.assertTrue(all(row['hero'] and re.search('[\u4e00-\u9fff]',row['display_name']) for row in rows))
if __name__=='__main__':unittest.main()
