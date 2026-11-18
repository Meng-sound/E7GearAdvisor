import unittest
from core import Gear,Stat,SLOTS
from fribbels_gs import item_score,raw_score,total_score
class GSTests(unittest.TestCase):
 def test_upstream_coefficients_and_no_main_stat(self):
  gear=Gear(main=Stat('atk',525),subs=[Stat('atk',39),Stat('hp',174),Stat('def',31),Stat('cdmg',7)])
  self.assertAlmostEqual(raw_score(gear),3.46+3.09+4.99+8);self.assertEqual(item_score(gear),20)
 def test_java_rounding_is_per_item_before_sum(self):
  gears={slot:Gear(subs=[Stat('atk_pct',10.5)]) for slot in SLOTS}
  self.assertEqual(total_score(gears),66)
  with self.assertRaises(ValueError):total_score({})
 def test_invalid_stat_values_rejected(self):
  for v in [float('nan'),float('inf'),-1,True]:
   with self.assertRaises(ValueError):item_score(Gear(subs=[Stat('spd',v)]))
