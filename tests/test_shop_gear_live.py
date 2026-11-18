import unittest
from game_task_vision import Observation,Word,observe
from game_tasks import LivePolicy
from task_replay import Config
from shop_gear import parse_tooltip

DETAIL='传说\n85 速度套装\n+0 武器\n攻击力100\n攻击力8%\n生命值7%\n暴击率4%\n速度3'
class GearFlowTests(unittest.TestCase):
 def setup_flow(self):
  policy=LivePolicy(Config(mode='shop',gear_buy=True,gear_speed=True,keep_gold=1000000));policy.phase='scan'
  item=dict(name='圣者之剑',kind='gear',price=1400000,point=(.9,.4),inspect_point=(.52,.35))
  obs=Observation(scene='shop',signature='same-list',gold=3000000,sky=3000,items=[item])
  return policy,obs
 def test_tooltip_requires_quality_level_four_subs_and_zero_enhancement(self):
  self.assertTrue(parse_tooltip(DETAIL)['verified'])
  for text in (DETAIL.replace('传说','英雄'),DETAIL.replace('85','70'),DETAIL.replace('+0','+3'),DETAIL.replace('\n速度3','')):
   self.assertIsNone(parse_tooltip(text))
 def test_complete_inspect_purchase_receipt_flow(self):
  p,obs=self.setup_flow();command=p.decide(obs);self.assertEqual(command.kind,'inspect_gear')
  record=parse_tooltip(DETAIL);p.record_gear(command,obs,[record,record])
  command=p.decide(obs);self.assertEqual(command.kind,'open_purchase');p.dispatched(command,obs)
  modal=Observation(scene='purchase_confirm',signature='confirmation',gold=3000000,price=1400000,text='购买 圣者之剑',buttons={'confirm':(.6,.6)})
  command=p.decide(modal);self.assertEqual(command.kind,'buy');p.dispatched(command,modal)
  obs.gold=1600000
  self.assertNotEqual(p.decide(obs).kind,'buy');self.assertEqual(p.gold_used,1400000)
 def test_unknown_or_disagreeing_detail_never_authorizes(self):
  p,obs=self.setup_flow();command=p.decide(obs);record=parse_tooltip(DETAIL)
  with self.assertRaises(RuntimeError):p.record_gear(command,obs,[record,None])
  self.assertFalse(p.checked_gear)
 def test_changed_shop_reinspects_and_rejected_gear_is_skipped(self):
  p,obs=self.setup_flow();record=parse_tooltip(DETAIL)
  p.record_gear(p.decide(obs),obs,[record,record]);obs.signature='scrolled'
  self.assertEqual(p.decide(obs).kind,'inspect_gear')
  record['subs'][-1]['value']=2;p.record_gear(p.decide(obs),obs,[record,record])
  self.assertEqual(p.decide(obs).kind,'scroll')
 def test_minimum_balance_and_price_still_apply_to_gear(self):
  p,obs=self.setup_flow();record=parse_tooltip(DETAIL);p.record_gear(p.decide(obs),obs,[record,record]);p.dispatched(p.decide(obs),obs)
  modal=Observation(scene='purchase_confirm',gold=2000000,price=1400000,text='购买 圣者之剑',buttons={'confirm':(.6,.6)})
  self.assertEqual(p.decide(modal).kind,'stop')
 def test_ticket_use_and_reward(self):
  result=observe([Word('使用剧场门票',.4,.3),Word('确定',.6,.65),Word('取消',.3,.65)],'theater')
  self.assertEqual(LivePolicy(Config(mode='theater')).decide(result).kind,'use_ticket')
  result=observe([Word('领取观览奖励',.55,.75)],'theater')
  self.assertEqual(LivePolicy(Config(mode='theater')).decide(result).kind,'claim_reward')
