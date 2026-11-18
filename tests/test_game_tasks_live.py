import queue
import unittest
from unittest.mock import patch
from core import Gear,Stat
from game_task_vision import Word,Observation,observe
from game_tasks import LivePolicy,Command,LiveRunner
from task_replay import Config
from window_input import WindowInput,packed_point
from picture_algorithm import breakdown


class LiveVisionTests(unittest.TestCase):
    def test_supplied_shop_geometry_and_balances(self):
        words=[Word('秘密商店',.05,.02,.10),Word('2,461,440',.59,.03,.07),Word('3,221',.70,.03,.04),
               Word('龙兽皮甲',.54,.36,.10),Word('23,000',.90,.33,.05),Word('购买',.92,.40,.04),
               Word('立即更新',.19,.90,.10)]
        result=observe(words,'shop')
        self.assertEqual((result.scene,result.gold,result.sky),('shop',2461440,3221))
        self.assertEqual(result.items[0]['price'],23000)
        self.assertEqual(result.items[0]['kind'],'other')
        self.assertIn('refresh',result.buttons)
    def test_clipped_buy_button_excluded(self):
        result=observe([Word('秘密商店',.05,.02),Word('购买',.92,.96)],'shop')
        self.assertFalse(result.items)
    def test_theater_selected_locked_episode_stops(self):
        result=observe([Word('月光剧场',.05,.02),Word('进行观览',.58,.89),Word('6天后可观看',.75,.94)],'theater')
        self.assertEqual(result.scene,'locked')
    def test_theater_home(self):
        result=observe([Word('月光剧场',.05,.02),Word('入场',.84,.88)],'theater')
        self.assertEqual(result.scene,'theater_home')
    def test_story_stage(self):
        result=observe([Word('Episode 1',.05,.02),Word('准备战斗',.82,.89)],'story')
        self.assertEqual(result.scene,'story_stage')
    def test_generic_confirm_never_authorized(self):
        result=observe([Word('确定',.60,.65),Word('取消',.30,.65)],'theater')
        self.assertEqual(result.scene,'unknown_confirm')
    def test_low_confidence_button_not_accepted(self):
        result=observe([Word('Episode 1',.05,.02),Word('准备战斗',.82,.89,confidence=.5)],'story')
        self.assertNotIn('prepare',result.buttons)
    def test_ticket_confirmation_price_is_scoped(self):
        result=observe([Word('购买观览券',.4,.3),Word('500,000',.50,.42),Word('确定',.6,.65),Word('取消',.3,.65),Word('2,461,440',.59,.03,.07)],'theater')
        self.assertEqual((result.scene,result.price,result.gold),('ticket_confirm',500000,2461440))


class LivePolicyTests(unittest.TestCase):
    def shop(self,**changes):
        values=dict(mode='shop',resource_stop='sky',sky_floor=2000,purchases=True)
        values.update(changes)
        return LivePolicy(Config(**values))
    def observation(self,signature='top',**changes):
        item=dict(name='誓约书签',kind='covenant',price=184000,point=(.9,.3))
        values=dict(scene='shop',gold=2461440,sky=3221,signature=signature,items=[item],buttons={'refresh':(.2,.9)})
        values.update(changes);return Observation(**values)
    def test_first_action_rewinds_not_refreshes(self):
        self.assertEqual(self.shop().decide(self.observation()).delta,720)
    def test_scan_never_refreshes_before_bottom(self):
        policy=self.shop(purchases=False);policy.phase='scan'
        action=policy.decide(self.observation());self.assertEqual((action.kind,action.delta),('scroll',-120))
    def test_ignored_wheel_does_not_refresh(self):
        policy=self.shop(purchases=False);policy.phase='scan';obs=self.observation()
        for _ in range(3):
            action=policy.decide(obs)
            if action.kind=='stop':break
            policy.dispatched(action,obs)
        self.assertEqual(action.kind,'stop');self.assertEqual(policy.refreshes,0)
    def test_proven_movement_and_bottom_allows_refresh(self):
        policy=self.shop(purchases=False);policy.phase='scan'
        first=self.observation();action=policy.decide(first);policy.dispatched(action,first)
        bottom=self.observation('bottom')
        for _ in range(4):
            action=policy.decide(bottom)
            if action.kind=='open_refresh':break
            policy.dispatched(action,bottom)
        self.assertEqual(action.kind,'open_refresh')
    def test_full_purchase_receipt_no_repeat(self):
        policy=self.shop();policy.phase='scan';obs=self.observation()
        action=policy.decide(obs);self.assertEqual(action.kind,'open_purchase');policy.dispatched(action,obs)
        modal=self.observation(scene='purchase_confirm',signature='modal',price=184000,text='购买 誓约书签 184,000',buttons={'confirm':(.6,.6)})
        action=policy.decide(modal);self.assertEqual(action.kind,'buy');policy.dispatched(action,modal)
        ack=self.observation('after',gold=2461440-184000)
        action=policy.decide(ack);self.assertEqual(action.kind,'scroll');self.assertEqual(policy.gold_used,184000)
    def test_unknown_receipt_no_retry(self):
        policy=self.shop();policy.phase='scan';obs=self.observation()
        policy.dispatched(Command('buy',gold=184000),obs)
        for _ in range(4):action=policy.decide(obs)
        self.assertEqual(action.kind,'stop');self.assertEqual(policy.gold_used,184000)
    def test_price_mismatch_never_buy(self):
        policy=self.shop();policy.phase='scan';obs=self.observation();policy.dispatched(policy.decide(obs),obs)
        action=policy.decide(self.observation(scene='purchase_confirm',price=1,text='誓约书签',buttons={'confirm':(.6,.6)}))
        self.assertEqual(action.kind,'stop')
    def test_ticket_purchase_keeps_reserve(self):
        policy=LivePolicy(Config(mode='theater',keep_gold=1000000))
        obs=Observation(scene='ticket_confirm',gold=1500000,price=500000,buttons={'confirm':(.6,.6)})
        self.assertEqual(policy.decide(obs).kind,'buy_ticket')
        obs.gold=1499999;self.assertEqual(policy.decide(obs).kind,'stop')
        obs.gold=2000000;obs.price=499999;self.assertEqual(policy.decide(obs).kind,'stop')
    def test_locked_theater_no_ticket_click(self):
        policy=LivePolicy(Config(mode='theater'))
        self.assertEqual(policy.decide(Observation(scene='locked',reason='尚未开放')).kind,'stop')
    def test_refresh_requires_complete_scan(self):
        policy=self.shop()
        self.assertEqual(policy.decide(self.observation(scene='refresh_confirm',price=3,buttons={'confirm':(.6,.6)})).kind,'stop')


class BackgroundInputTests(unittest.TestCase):
    def test_permission_error_distinguishes_elevated_game(self):
        from process_permissions import input_permission_error
        with patch('process_permissions.integrity_level',side_effect=[8192,12288]):
            self.assertIn('更高权限',input_permission_error({'pid':456}))
        with patch('process_permissions.integrity_level',side_effect=[12288,12288]):
            self.assertIsNone(input_permission_error({'pid':456}))
    def test_cancel_before_input(self):
        backend=WindowInput.__new__(WindowInput)
        self.assertFalse(backend.perform(Command('prepare'),(1600,900),lambda:False))
    def test_click_posts_only_to_bound_window(self):
        backend=WindowInput.__new__(WindowInput);backend.check=lambda size:123
        backend.emergency_pressed=lambda:False
        messages=[];backend.send=lambda *args:messages.append(args)
        with patch('window_input.time.sleep'):
            self.assertTrue(backend.perform(Command('prepare',(.5,.5)),(1600,900),lambda:True))
        self.assertEqual([message[1] for message in messages],[0x200,0x201,0x202])
        self.assertTrue(all(message[0]==123 for message in messages))
        self.assertEqual(messages[1][-1],packed_point(800,450))
    def test_coordinates_reject_outside(self):
        backend=WindowInput.__new__(WindowInput)
        with self.assertRaises(ValueError):backend.perform(Command('prepare',(2,.5)),(1600,900),lambda:True)


class ScoreDifferenceTests(unittest.TestCase):
    def test_percent_only_modes_correctly_equal(self):
        gear=Gear(subs=[Stat('atk_pct',8),Stat('crit',5),Stat('spd',4)])
        self.assertEqual(sum(row['score'] for row in breakdown(gear,score_mode='gs')),sum(row['score'] for row in breakdown(gear,score_mode='role')))
    def test_flat_stat_modes_differ_and_role_uses_selected_base(self):
        gear=Gear(subs=[Stat('atk',100)])
        gs=breakdown(gear,score_mode='gs')[0]['score']
        role=breakdown(gear,{'atk':1000,'hp':5000,'def':500},'role')[0]['score']
        self.assertAlmostEqual(gs,100*3.46/39);self.assertEqual(role,10);self.assertNotEqual(gs,role)


class RunnerTests(unittest.TestCase):
    def test_capture_ocr_dispatch_pipeline_and_cleanup(self):
        from types import SimpleNamespace
        class OCR:
            closed=False
            def read(self,image,mode):return Observation(scene='story_stage',buttons={'prepare':(.8,.9)},signature='stage')
            def close(self):self.closed=True
        class Inputs:
            calls=0
            def emergency_pressed(self):return False
            def perform(self,command,size,allowed):
                assert allowed() and command.kind=='prepare' and size==(1600,900)
                self.calls+=1;runner.cancel.set();return True
        ocr=OCR();inputs=Inputs();events=queue.Queue()
        runner=LiveRunner({},Config(mode='story'),events,capture=lambda target:SimpleNamespace(size=(1600,900)),ocr=ocr,inputs=inputs)
        runner.run()
        self.assertEqual(inputs.calls,1);self.assertTrue(ocr.closed);self.assertEqual(runner.status,'stopped')
        kinds=[]
        while not events.empty():kinds.append(events.get()['event'])
        self.assertIn('action',kinds);self.assertEqual(kinds[-1],'done')
    def test_cancelled_runner_never_inputs(self):
        class OCR:
            def close(self):pass
        class Inputs:
            def emergency_pressed(self):return False
            def perform(self,*args):raise AssertionError('must not input')
        runner=LiveRunner({},Config(mode='story'),queue.Queue(),capture=lambda target:None,ocr=OCR(),inputs=Inputs())
        runner.cancel.set();runner.run();self.assertEqual(runner.policy.actions,0)


if __name__=='__main__':unittest.main()
