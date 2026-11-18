import unittest
from fribbels_sync import decode_sets,aggregate,AGGREGATION_VERSION
from set_icons import layout_text
from adaptation_storage import record

class SetLayoutTests(unittest.TestCase):
 def test_new_api_names_resolve_to_complete_sets(self):
  self.assertEqual(decode_sets({'set_speed':'4','set_chase':'2'})[0],('追击','速度'))
  self.assertEqual(decode_sets({'set_speed':'4','set_might':'2'})[0],('全力','速度'))
  self.assertEqual(decode_sets({'set_weak':'4','set_cri':'2'})[0],('弱化','暴击'))
 def test_broken_and_unreported_pieces_are_distinct(self):
  active,loose,unknown,unreported=decode_sets({'set_speed':4,'set_cri':1,'set_max_hp':1})
  self.assertEqual((active,loose,unreported),(('速度',),2,0))
  self.assertIn('散件',layout_text({'sets':active,'unmatched_pieces':loose}))
  self.assertEqual(decode_sets({'set_speed':4})[3],2)
 def test_unknown_set_is_not_treated_as_broken_gear(self):
  active,loose,unknown,missing=decode_sets({'set_speed':4,'set_future':2})
  self.assertEqual(loose,0);self.assertEqual(unknown,(('set_future',2),))
  self.assertIn('待识别',layout_text({'sets':active,'unknown_sets':dict(unknown)}))
 def test_repeated_two_piece_sets_and_six_speed(self):
  self.assertEqual(decode_sets({'set_max_hp':6})[0],('生命','生命','生命'))
  self.assertEqual(decode_sets({'set_speed':6})[:2],(('速度',),2))
 def test_new_set_and_broken_cohorts_are_not_merged(self):
  base={'atk':2000,'hp':22000,'def':1100,'spd':286,'chc':26,'chd':163,'eff':48,'efr':26,'gs':428}
  rows=[{**base,'sets':{'set_speed':4,'set_chase':2}} for _ in range(6)]+[{**base,'sets':{'set_speed':4,'set_cri':1,'set_max_hp':1}} for _ in range(6)]
  data=aggregate('Test',{'data':rows});self.assertEqual(len(data['variants']),2)
  self.assertEqual(data['aggregation_version'],AGGREGATION_VERSION)
  self.assertTrue(any('追击' in v['sets'] for v in data['variants']))
  self.assertTrue(any(v['unmatched_pieces']==2 for v in data['variants']))
  record(data,'Test')
