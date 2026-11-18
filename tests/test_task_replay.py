import math
import unittest
from task_replay import Config, Session, demo, load_replay


class TaskReplayTests(unittest.TestCase):
    def run_demo(self, mode, **overrides):
        data = demo(mode)
        data['config'].update(overrides)
        config, frames = load_replay(data)
        session = Session(config)
        session.start()
        actions = [session.feed(frame, frame['at']) for frame in frames]
        return session, [a.kind for a in actions if a]

    def test_shop_roundtrip(self):
        session, actions = self.run_demo('shop')
        self.assertEqual(actions, ['open_purchase', 'buy', 'close_receipt', 'open_refresh', 'refresh'])
        self.assertEqual((session.completed, session.gold_used, session.sky_used, session.refreshes), (1, 500, 3, 1))
        self.assertIn('刷新次数上限', session.reason)

    def test_story_roundtrip(self):
        session, actions = self.run_demo('story')
        self.assertEqual(actions, ['enter', 'next_stage', 'enter'])
        self.assertEqual(session.completed, 1)
        self.assertIn('energy_empty', session.reason)

    def test_theater_roundtrip(self):
        session, actions = self.run_demo('theater')
        self.assertEqual(actions, ['watch', 'advance', 'claim', 'next_episode'])
        self.assertEqual(session.completed, 1)
        self.assertIn('ticket_empty', session.reason)

    def test_default_no_purchase(self):
        session, actions = self.run_demo('shop', purchases=False)
        self.assertEqual(actions, [])
        self.assertEqual(session.gold_used, 0)

    def test_budget_too_small(self):
        session, actions = self.run_demo('shop', gold_budget=499)
        self.assertNotIn('buy', actions)
        self.assertEqual(session.gold_used, 0)

    def test_keep_gold(self):
        session, actions = self.run_demo('shop', keep_gold=501)
        self.assertNotIn('buy', actions)

    def test_refresh_budget(self):
        session, actions = self.run_demo('shop', sky_budget=2)
        self.assertNotIn('refresh', actions)
        self.assertEqual(session.sky_used, 0)

    def test_refresh_disabled(self):
        session, actions = self.run_demo('shop', max_refreshes=0)
        self.assertNotIn('open_refresh', actions)

    def test_no_targets_does_not_buy_other_item(self):
        data = demo('shop')
        data['frames'][0]['items'][0]['kind'] = 'other'
        data['config']['max_refreshes'] = 0
        config, frames = load_replay(data)
        session = Session(config)
        session.start()
        self.assertIsNone(session.feed(frames[0], 0))
        self.assertEqual(session.steps, 0)

    def issue_buy(self):
        config, frames = load_replay(demo('shop'))
        session = Session(config)
        session.start()
        session.feed(frames[0], 0)
        session.feed(frames[1], 2)
        return session, frames

    def test_no_refund_ambiguous_purchase(self):
        session, frames = self.issue_buy()
        frames[2].pop('ack')
        self.assertIsNone(session.feed(frames[2], 4))
        self.assertEqual(session.status, 'stopped')
        self.assertEqual(session.gold_used, 500)
        self.assertIsNone(session.feed(frames[2], 5))

    def test_failed_receipt_no_refund(self):
        session, frames = self.issue_buy()
        frames[2]['success'] = False
        session.feed(frames[2], 4)
        self.assertEqual(session.completed, 0)
        self.assertEqual(session.gold_used, 500)

    def test_inconsistent_receipt(self):
        session, frames = self.issue_buy()
        frames[2]['state'] = 'shop_list'
        session.feed(frames[2], 4)
        self.assertIn('画面与动作回执不一致', session.reason)

    def test_duplicate_frame_never_clicks(self):
        session, frames = self.issue_buy()
        for _ in range(5):
            self.assertIsNone(session.feed(frames[1], 3))
        self.assertEqual(session.steps, 2)
        self.assertEqual(session.gold_used, 500)
        self.assertEqual(session.status, 'stopped')

    def test_price_changed(self):
        config, frames = load_replay(demo('shop'))
        session = Session(config)
        session.start()
        session.feed(frames[0], 0)
        frames[1]['price'] = 600
        session.feed(frames[1], 2)
        self.assertIn('价格与列表不一致', session.reason)
        self.assertEqual(session.gold_used, 0)

    def test_missing_balance(self):
        config, frames = load_replay(demo('shop'))
        session = Session(config)
        session.start()
        session.feed(frames[0], 0)
        del frames[1]['gold']
        session.feed(frames[1], 2)
        self.assertIn('金币余额缺失', session.reason)

    def test_missing_button(self):
        session = Session(Config(mode='story'))
        session.start()
        session.feed(dict(mode='story', id='0', state='stage'), 0)
        self.assertEqual(session.status, 'stopped')
        self.assertEqual(session.steps, 0)

    def test_pause_resume_stop(self):
        session = Session(Config(mode='story'))
        session.start()
        session.pause()
        frame = demo('story')['frames'][0]
        self.assertIsNone(session.feed(frame, 0))
        session.resume()
        self.assertEqual(session.feed(frame, 0).kind, 'enter')
        session.stop()
        session.resume()
        self.assertEqual(session.status, 'stopped')
        with self.assertRaises(ValueError):
            session.start()

    def test_limits(self):
        for override, text in [(dict(max_steps=1), '步骤上限'), (dict(max_seconds=1), '时长上限')]:
            with self.subTest(override=override):
                session, actions = self.run_demo('story', **override)
                self.assertEqual(actions, ['enter'])
                self.assertIn(text, session.reason)

    def test_unknown_state_blocks(self):
        for state in ['network_error', 'inventory_full', 'energy_empty', 'defeat', 'ticket_empty',
                      'premium_confirm', 'unknown', 'currency_empty']:
            with self.subTest(state=state):
                session = Session(Config(mode='theater'))
                session.start()
                session.feed(dict(mode='theater', id='a', state=state), 0)
                self.assertEqual(session.status, 'stopped')
                self.assertEqual(session.steps, 0)

    def test_wrong_mode_blocks(self):
        session = Session(Config(mode='theater'))
        session.start()
        session.feed(demo('story')['frames'][0], 0)
        self.assertIn('模式不一致', session.reason)

    def test_confirmation_is_not_entry_point(self):
        config, frames = load_replay(demo('shop'))
        session = Session(config)
        session.start()
        session.feed(frames[4], 0)
        self.assertEqual(session.steps, 0)
        self.assertIn('起始画面', session.reason)

    def test_unexpected_ack(self):
        session = Session(Config(mode='story'))
        session.start()
        frame = demo('story')['frames'][0]
        frame.update(ack='1', success=True)
        session.feed(frame, 0)
        self.assertIn('意外回执', session.reason)

    def test_battle_is_passive(self):
        config, frames = load_replay(demo('story'))
        session = Session(config)
        session.start()
        session.feed(frames[0], 0)
        self.assertIsNone(session.feed(frames[1], 2))
        self.assertIsNone(session.feed(dict(mode='story', state='battle', id='wait'), 3))
        self.assertEqual(session.steps, 1)

    def test_stuck_state(self):
        config, frames = load_replay(demo('story'))
        session = Session(config)
        session.start()
        session.feed(frames[0], 0)
        session.feed(frames[1], 2)
        for i in range(5):
            session.feed(dict(mode='story', id='wait'+str(i), state='battle'), 3+i)
        self.assertIn('状态长时间未变化', session.reason)

    def test_invalid_config(self):
        for overrides in [dict(gold_budget=-1), dict(sky_budget=True), dict(max_steps=0), dict(max_seconds=math.inf),
                          dict(purchases=1), dict(mode='all'), dict(targets=['equipment'])]:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                Config(**overrides)

    def test_invalid_frames_atomic_import(self):
        for mutate in [lambda d: d.update(schema=2), lambda d: d.update(frames=[]),
                       lambda d: d['frames'][1].update(at=-1), lambda d: d['frames'][1].update(at=math.nan),
                       lambda d: d['frames'][1].update(id='0'), lambda d: d['frames'][0].update(buttons='buy'),
                       lambda d: d['frames'][0]['items'][0].update(price=True),
                       lambda d: d['frames'][0]['items'].append(d['frames'][0]['items'][0]),
                       lambda d: d['frames'][1].update(success=1)]:
            data = demo('shop')
            mutate(data)
            with self.subTest(data=data), self.assertRaises(ValueError):
                load_replay(data)

    def test_time_reversal(self):
        session = Session(Config(mode='story'))
        session.start()
        frames = demo('story')['frames']
        session.feed(frames[0], 2)
        session.feed(frames[1], 1)
        self.assertIn('时间必须', session.reason)


if __name__ == '__main__':
    unittest.main()
