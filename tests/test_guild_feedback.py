import unittest
from guild_feedback import defense_issue,empty_feedback
class FeedbackTests(unittest.TestCase):
 def test_duplicate_missing_and_valid_defense_are_distinct(self):
  self.assertIn('重复',defense_issue(['a','a','b'],{'a':'角色甲'}));self.assertIn('角色甲',defense_issue(['a','a','b'],{'a':'角色甲'}));self.assertIn('还缺 2',defense_issue(['a',None,None]));self.assertEqual(defense_issue(['a','b','c']),'')
 def test_unrecorded_is_not_filtered_or_parse_failure(self):
  self.assertIn('尚未收录',empty_feedback({'offenses':[]},5));self.assertIn('未能解析',empty_feedback({'offenses':[],'invalid_rows':2},5))
 def test_filter_causes_are_visible(self):
  record={'offenses':[{'samples':3,'heroes':['a','b','c']}]}
  text=empty_feedback(record,5,['a'],['b'],['c']);self.assertIn('1 组战报',text)
  for cause in ('最少样本','包含英雄','排除英雄','另一场'):self.assertIn(cause,text)
