import unittest,tempfile,copy
from pathlib import Path
import scoring_settings as scoring
from core import Gear,Stat
from picture_algorithm import breakdown

class CustomScoringTests(unittest.TestCase):
 def setUp(self):self.old=scoring.current();self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'score.json'
 def tearDown(self):scoring.save(self.path,self.old);self.tmp.cleanup()
 def test_default_matches_role_score(self):
  gear=Gear(subs=[Stat('atk',100),Stat('hp_pct',7),Stat('crit',5),Stat('cdmg',7),Stat('spd',4)])
  base={'atk':1200,'hp':5000,'def':600};expected=sum(p['score'] for p in breakdown(gear,base));scoring.save(self.path,{**scoring.DEFAULT,'enabled':True})
  self.assertAlmostEqual(sum(p['score'] for p in breakdown(gear,base)),expected)
 def test_custom_formula_uses_gear_and_hero_base(self):
  data=copy.deepcopy(scoring.DEFAULT);data.update(enabled=True);data['formulas']['spd']='value * 3 + base_spd / 100 + enhance / 3';scoring.save(self.path,data)
  gear=Gear(level=85,enhance=6,subs=[Stat('spd',4)]);self.assertEqual(breakdown(gear,{'spd':100},'custom')[0]['score'],15)
 def test_save_load_and_disable(self):
  scoring.save(self.path,{'enabled':True,'name':'追速','formulas':{'spd':'value*4'}});scoring.configure(self.path);self.assertTrue(scoring.enabled());self.assertEqual(scoring.score_stat(Stat('spd',4)),16)
  scoring.save(self.path,scoring.DEFAULT);self.assertFalse(scoring.enabled())
 def test_code_and_excessive_expressions_rejected(self):
  for expression in ['__import__("os").system("cmd")','value.__class__','[value]','value ** 999','1/0','max(1,2,3,4,5,6)','(10**6)**6']:
   with self.subTest(expression=expression),self.assertRaises(ValueError):scoring.validate({'formulas':{'spd':expression}})
 def test_helpers_and_flat_base(self):
  self.assertEqual(scoring.evaluate('round(max(value, 4) * 1.5, 1)',{'value':3}),6)
  self.assertEqual(scoring.score_stat(Stat('atk',100),{'atk':1000}),10)

if __name__=='__main__':unittest.main()
