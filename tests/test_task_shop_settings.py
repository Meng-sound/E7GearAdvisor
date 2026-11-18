import copy
import unittest
from task_replay import Config,Session,eligible_red_gear,demo


class ShopSettingsTests(unittest.TestCase):
    def frame(self,**overrides):
        result=demo('shop')['frames'][0]
        result.update(overrides)
        return result

    def session(self,**kwargs):
        config=dict(mode='shop',purchases=True,gold_budget=5000000,sky_budget=100,max_refreshes=10)
        config.update(kwargs)
        session=Session(Config(**config));session.start()
        return session

    def gear(self,**overrides):
        value=dict(id='red1',kind='gear',price=1400000,verified=True,level=85,grade='epic',enhance=0,
                   subs=[dict(key='spd',value=3),dict(key='crit',value=3),dict(key='cdmg',value=4),dict(key='hp_pct',value=4)])
        value.update(overrides)
        return value

    def test_sky_stop_at_or_below(self):
        for sky in (1999,2000):
            session=self.session(resource_stop='sky',sky_floor=2000)
            self.assertIsNone(session.feed(self.frame(sky=sky),0))
            self.assertIn('停止线',session.reason)

    def test_gold_stop_ignores_sky(self):
        session=self.session(resource_stop='gold',gold_floor=1000,sky_floor=2000)
        self.assertIsNotNone(session.feed(self.frame(gold=1001,sky=0),0))

    def test_either_currency_stops(self):
        for gold,sky in [(1000,2001),(1001,2000)]:
            session=self.session(resource_stop='either',gold_floor=1000,sky_floor=2000)
            self.assertIsNone(session.feed(self.frame(gold=gold,sky=sky),0))

    def test_missing_required_balance_stops(self):
        session=self.session(resource_stop='sky',sky_floor=1)
        frame=self.frame();del frame['sky']
        self.assertIsNone(session.feed(frame,0));self.assertIn('未识别',session.reason)

    def test_projected_purchase_cannot_cross_gold_line(self):
        session=self.session(resource_stop='gold',gold_floor=900)
        session.feed(self.frame(gold=1000),0)
        frame=demo('shop')['frames'][1]
        self.assertIsNone(session.feed(frame,2))
        self.assertEqual(session.gold_used,0)
        self.assertIn('购买后金币',session.reason)

    def test_projected_refresh_cannot_cross_sky_line(self):
        session=self.session(resource_stop='sky',sky_floor=29)
        session.feed(self.frame(items=[],buttons=['open_refresh']),0)
        frame=dict(mode='shop',id='new',state='refresh_confirm',ack='1',success=True,refresh_cost=3,sky=30,buttons=['refresh'])
        self.assertIsNone(session.feed(frame,2));self.assertEqual(session.sky_used,0)

    def test_invalid_stop_config(self):
        for values in [dict(resource_stop='both'),dict(sky_floor=True),dict(gold_floor=-1),dict(gear_gs=1)]:
            with self.subTest(values=values),self.assertRaises(ValueError):Config(**values)

    def test_gear_defaults_do_not_buy(self):
        self.assertFalse(eligible_red_gear(self.gear(),Config()))
        self.assertFalse(eligible_red_gear(self.gear(),Config(gear_buy=True)))

    def test_speed_rule(self):
        config=Config(gear_buy=True,gear_speed=True)
        self.assertTrue(eligible_red_gear(self.gear(),config))
        item=self.gear();item['subs'][0]['value']=2
        self.assertFalse(eligible_red_gear(item,config))

    def test_combo_rule(self):
        config=Config(gear_buy=True,gear_combo=True)
        self.assertTrue(eligible_red_gear(self.gear(),config))
        item=self.gear();item['subs'][1]['key']='eff'
        self.assertFalse(eligible_red_gear(item,config))

    def test_gs_uses_fribbels_raw_threshold(self):
        config=Config(gear_buy=True,gear_gs=True)
        item=self.gear(subs=[dict(key='atk_pct',value=8),dict(key='hp_pct',value=8),dict(key='def_pct',value=5),dict(key='spd',value=3)])
        self.assertTrue(eligible_red_gear(item,config))
        item['subs'][2]['value']=4.9
        self.assertFalse(eligible_red_gear(item,config))

    def test_rules_are_or(self):
        self.assertTrue(eligible_red_gear(self.gear(),Config(gear_buy=True,gear_gs=True,gear_speed=True)))

    def test_uncertain_or_wrong_gear_never_buy(self):
        config=Config(gear_buy=True,gear_speed=True)
        for changes in [dict(price=1399999),dict(grade='heroic'),dict(level=90),dict(enhance=3),dict(enhance=False),dict(verified=False),dict(subs=[]),dict(subs=[dict(key='spd',value=3)]*4)]:
            with self.subTest(changes=changes):self.assertFalse(eligible_red_gear(self.gear(**changes),config))

    def test_red_gear_independent_of_bookmark_switch(self):
        session=self.session(purchases=False,gear_buy=True,gear_speed=True)
        item=self.gear()
        action=session.feed(self.frame(items=[item],gold=3000000),0)
        self.assertEqual(action.kind,'open_purchase')
        action=session.feed(dict(mode='shop',id='next',state='purchase_confirm',ack='1',success=True,item_id='red1',price=1400000,gold=3000000,buttons=['buy']),2)
        self.assertEqual(action.kind,'buy');self.assertEqual(action.gold,1400000)


if __name__=='__main__':unittest.main()
