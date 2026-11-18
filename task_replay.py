"""Deterministic task policies and replay. This module never captures or clicks.

Frames are reviewed semantic observations, NOT raw game OCR. A pending action
must be acknowledged by a different frame before another action can be emitted.
Resource costs are reserved when issued; an ambiguous outcome never refunds or
retries a purchase. Native recognition and input adapters are not implemented.
"""
from dataclasses import dataclass, field
import math

MODES = {'shop': '刷商店', 'story': '自动推图', 'theater': '月光剧场'}
STATES = {
    'shop': {'shop_list', 'purchase_confirm', 'refresh_confirm', 'receipt'},
    'story': {'stage', 'battle', 'victory'},
    'theater': {'episode', 'dialogue', 'reward', 'episode_end'},
}
BLOCKED = {'network_error', 'inventory_full', 'energy_empty', 'defeat',
           'ticket_empty', 'premium_confirm', 'unknown', 'currency_empty'}


def integer(value, name, maximum=10**12):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(name + ' 必须为范围内的非负整数')
    return value


@dataclass(frozen=True)
class Config:
    mode: str = 'shop'
    gold_budget: int = 0
    sky_budget: int = 0
    keep_gold: int = 0
    max_refreshes: int = 0
    max_steps: int = 100
    max_seconds: int = 600
    purchases: bool = False
    targets: tuple = ('covenant', 'mystic')
    stuck_frames: int = 5
    resource_stop: str = 'none'
    sky_floor: int = 0
    gold_floor: int = 0
    gear_buy: bool = False
    gear_gs: bool = False
    gear_speed: bool = False
    gear_combo: bool = False

    def __post_init__(self):
        if self.mode not in MODES:
            raise ValueError('未知任务模式')
        for name in ('gold_budget', 'sky_budget', 'keep_gold', 'max_refreshes',
                     'max_steps', 'max_seconds', 'stuck_frames', 'sky_floor', 'gold_floor'):
            integer(getattr(self, name), name)
        if not self.max_steps or not self.max_seconds or not self.stuck_frames:
            raise ValueError('步骤、时长与卡住次数上限必须大于0')
        if any(type(getattr(self, key)) is not bool for key in ('purchases','gear_buy','gear_gs','gear_speed','gear_combo')):
            raise ValueError('购买开关必须为布尔值')
        if self.resource_stop not in {'none','sky','gold','either'}:
            raise ValueError('停止条件无效')
        if not isinstance(self.targets, (tuple, list)) or not set(self.targets) <= {'covenant', 'mystic', 'friendship'}:
            raise ValueError('不支持的商品目标')


@dataclass(frozen=True)
class Action:
    id: str
    kind: str
    target: str = ''
    gold: int = 0
    sky: int = 0


def eligible_red_gear(item, config):
    """Reviewed 85 epic +0 only. Conditions are OR; unknown fields never buy."""
    if not config.gear_buy or item.get('kind') != 'gear' or item.get('verified') is not True:
        return False
    if type(item.get('level')) is not int or type(item.get('enhance')) is not int or item.get('level') != 85 or item.get('grade') != 'epic' or item.get('enhance') != 0 or item.get('price') != 1400000:
        return False
    from core import Gear, Stat
    from fribbels_gs import COEFFICIENTS, raw_score
    subs=item.get('subs')
    if not isinstance(subs,list) or len(subs)!=4 or any(not isinstance(row,dict) for row in subs):
        return False
    keys=[row.get('key') for row in subs]
    if any(not isinstance(key,str) or key not in COEFFICIENTS for key in keys) or len(set(keys))!=4:
        return False
    if any(type(row.get('value')) not in (int,float) or not math.isfinite(row['value']) or row['value']<0 for row in subs):
        return False
    values={row['key']:row['value'] for row in subs}
    score=raw_score(Gear(subs=[Stat(row['key'],row['value']) for row in subs]))
    return ((config.gear_gs and score>=27) or
            (config.gear_speed and values.get('spd',0)>=3) or
            (config.gear_combo and {'crit','cdmg','spd'}<=set(keys)))


def validate_frame(frame, mode):
    if not isinstance(frame, dict) or frame.get('mode') != mode:
        raise ValueError('帧模式不一致')
    for name in ('id', 'state'):
        if not isinstance(frame.get(name), str) or not 0 < len(frame[name]) <= 120:
            raise ValueError('帧缺少有效的 ' + name)
    if frame['state'] not in STATES[mode] | BLOCKED:
        raise ValueError('未知状态')
    for name in ('gold', 'sky', 'refresh_cost', 'price'):
        if name in frame:
            integer(frame[name], name)
    if 'ack' in frame and (not isinstance(frame['ack'], str) or len(frame['ack']) > 120):
        raise ValueError('回执格式错误')
    if 'success' in frame and type(frame['success']) is not bool:
        raise ValueError('回执结果必须为布尔值')
    buttons = frame.get('buttons', [])
    if not isinstance(buttons, list) or len(buttons) > 30 or any(not isinstance(b, str) or len(b) > 120 for b in buttons):
        raise ValueError('按钮列表格式错误')
    items = frame.get('items', [])
    if not isinstance(items, list) or len(items) > 30:
        raise ValueError('商品列表格式错误')
    seen = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not 0 < len(item['id']) <= 80 or item['id'] in seen:
            raise ValueError('商品ID缺失或重复')
        seen.add(item['id'])
        if item.get('kind') not in {'covenant', 'mystic', 'friendship', 'other', 'gear'}:
            raise ValueError('未知商品类型')
        integer(item.get('price'), '商品价格')
        if item['price'] <= 0:
            raise ValueError('商品价格必须大于0')
    return frame


@dataclass
class Session:
    config: Config
    status: str = 'idle'
    reason: str = '尚未开始'
    gold_used: int = 0
    sky_used: int = 0
    refreshes: int = 0
    steps: int = 0
    completed: int = 0
    pending: Action | None = None
    intent: dict | None = None
    log: list = field(default_factory=list)
    seen: set = field(default_factory=set)
    purchased: set = field(default_factory=set)
    expected: str | None = None
    last_state: str = ''
    repeats: int = 0
    elapsed: float = 0

    def start(self):
        if self.status != 'idle':
            raise ValueError('请新建任务；停止的任务不能自动恢复')
        self.status = 'running'
        self.reason = '回放运行中（不会点击游戏）'

    def pause(self):
        if self.status == 'running':
            self.status = 'paused'
            self.reason = '手动暂停'

    def resume(self):
        if self.status == 'paused':
            self.status = 'running'
            self.reason = '回放继续'

    def stop(self, reason='手动停止'):
        self.status = 'stopped'
        self.reason = reason
        self.log.append({'event': 'stop', 'reason': reason})

    def _issue(self, kind, target='', gold=0, sky=0):
        self.steps += 1
        action = Action(str(self.steps), kind, target, gold, sky)
        self.gold_used += gold
        self.sky_used += sky
        self.pending = action
        self.log.append({'event': 'action', **action.__dict__})
        return action

    def _button(self, frame, name, target='', gold=0, sky=0):
        if name not in frame.get('buttons', []):
            self.stop('所需按钮缺失或未确认：' + name)
            return None
        return self._issue(name, target, gold, sky)

    def feed(self, frame, elapsed):
        if self.status != 'running':
            return None
        try:
            validate_frame(frame, self.config.mode)
            if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < self.elapsed:
                raise ValueError('时间必须单调递增且有限')
        except (TypeError, ValueError) as error:
            self.stop('无效回放：' + str(error))
            return None
        self.elapsed = elapsed
        if elapsed >= self.config.max_seconds:
            self.stop('达到时长上限')
            return None
        state = frame['state']
        if state in BLOCKED:
            self.stop('停止状态：' + state)
            return None
        # A repeated capture can never acknowledge or click a second time.
        if frame['id'] in self.seen:
            self.repeats += 1
            if self.repeats >= self.config.stuck_frames:
                self.stop('重复画面，等待人工检查')
            return None
        self.seen.add(frame['id'])
        if self.steps == 0 and state != {'shop': 'shop_list', 'story': 'stage', 'theater': 'episode'}[self.config.mode]:
            self.stop('请从任务起始画面开始')
            return None
        self.repeats = self.repeats + 1 if state == self.last_state else 0
        self.last_state = state
        if self.repeats >= self.config.stuck_frames:
            self.stop('状态长时间未变化')
            return None
        if not self.pending and 'ack' in frame:
            self.stop('没有待确认动作，收到意外回执')
            return None
        if self.pending:
            action = self.pending
            if frame.get('ack') != action.id:
                self.stop('动作结果未确认，禁止重试')
                return None
            if frame.get('success') is not True:
                self.stop('动作失败或结果不明，保留已预留预算')
                return None
            self.pending = None
            self.log.append({'event': 'ack', 'id': action.id})
            if action.kind == 'buy':
                self.purchased.add(action.target)
                self.completed += 1
                self.expected = 'receipt'
            elif action.kind == 'refresh':
                self.refreshes += 1
                self.purchased.clear()
                self.expected = 'shop_list'
            elif action.kind == 'open_purchase':
                self.expected = 'purchase_confirm'
            elif action.kind == 'open_refresh':
                self.expected = 'refresh_confirm'
            elif action.kind == 'enter':
                self.expected = 'battle'
            elif action.kind == 'next_stage':
                self.expected = 'stage'
                self.completed += 1
            elif action.kind == 'watch':
                self.expected = 'dialogue'
            elif action.kind == 'claim':
                self.expected = 'episode_end'
                self.completed += 1
            elif action.kind == 'next_episode':
                self.expected = 'episode'
            elif action.kind == 'close_receipt':
                self.expected = 'shop_list'
            elif action.kind == 'advance' and state not in {'dialogue', 'reward'}:
                self.stop('剧情推进后的画面不属于对话或奖励')
                return None
        if self.expected and state != self.expected:
            self.stop('画面与动作回执不一致：需要 ' + self.expected)
            return None
        self.expected = None
        if self.steps >= self.config.max_steps:
            self.stop('达到步骤上限')
            return None
        if self.config.mode == 'shop':
            return self._shop(frame)
        if self.config.mode == 'story':
            if state == 'stage':
                return self._button(frame, 'enter')
            if state == 'victory':
                return self._button(frame, 'next_stage')
            # battle is deliberately passive; no manual combat macros.
            return None
        if state == 'episode':
            return self._button(frame, 'watch')
        if state == 'dialogue':
            return self._button(frame, 'advance')
        if state == 'reward':
            return self._button(frame, 'claim')
        if state == 'episode_end':
            return self._button(frame, 'next_episode')

    def _shop(self, frame):
        state = frame['state']
        if state == 'receipt':
            return self._button(frame, 'close_receipt')
        for currency, enabled, floor in [
            ('sky',self.config.resource_stop in {'sky','either'},self.config.sky_floor),
            ('gold',self.config.resource_stop in {'gold','either'},self.config.gold_floor)]:
            if enabled and currency not in frame:
                self.stop('停止线所需余额未识别：'+currency)
                return None
            if enabled and frame[currency]<=floor:
                self.stop('达到资源停止线：'+currency)
                return None
        if state == 'shop_list':
            for item in frame.get('items', []):
                if (item['kind'] not in self.config.targets and not eligible_red_gear(item,self.config)) or item['id'] in self.purchased:
                    continue
                if not (self.config.gear_buy if item['kind']=='gear' else self.config.purchases):
                    self.stop('发现目标商品；购买开关关闭')
                    return None
                self.intent = dict(item)
                return self._button(frame, 'open_purchase', item['id'])
            if self.refreshes >= self.config.max_refreshes:
                self.stop('达到刷新次数上限')
                return None
            self.intent = None
            return self._button(frame, 'open_refresh')
        if state == 'purchase_confirm':
            item = self.intent
            if not item or frame.get('item_id') != item['id'] or frame.get('price') != item['price']:
                self.stop('商品或价格与列表不一致')
                return None
            enabled=self.config.gear_buy if item['kind']=='gear' else self.config.purchases
            if not enabled or item['price'] + self.gold_used > self.config.gold_budget:
                self.stop('购买关闭或金币预算不足')
                return None
            if 'gold' not in frame or frame['gold'] - item['price'] < self.config.keep_gold:
                self.stop('金币余额缺失或低于保留值')
                return None
            if self.config.resource_stop in {'gold','either'} and frame['gold']-item['price']<self.config.gold_floor:
                self.stop('购买后金币将低于停止线')
                return None
            return self._button(frame, 'buy', item['id'], gold=item['price'])
        if state == 'refresh_confirm':
            cost = frame.get('refresh_cost')
            if not cost or self.refreshes >= self.config.max_refreshes or self.sky_used + cost > self.config.sky_budget:
                self.stop('刷新价格缺失、次数已满或天空石预算不足')
                return None
            if 'sky' not in frame or frame['sky'] < cost:
                self.stop('天空石余额缺失或不足')
                return None
            if self.config.resource_stop in {'sky','either'} and frame['sky']-cost<self.config.sky_floor:
                self.stop('刷新后天空石将低于停止线')
                return None
            return self._button(frame, 'refresh', sky=cost)


def load_replay(data):
    if not isinstance(data, dict) or data.get('schema') != 1 or not isinstance(data.get('frames'), list):
        raise ValueError('需要 schema=1 的任务回放文件')
    config = Config(**data.get('config', {}))
    if not 1 <= len(data['frames']) <= 10000:
        raise ValueError('回放需要1至10000帧')
    seen = set()
    previous = 0
    for frame in data['frames']:
        validate_frame(frame, config.mode)
        at = frame.get('at')
        if type(at) not in (int, float) or not math.isfinite(at) or at < previous:
            raise ValueError('回放时间必须有序且有限')
        if frame['id'] in seen:
            raise ValueError('回放帧ID不能重复')
        seen.add(frame['id'])
        previous = at
    return config, data['frames']


def demo(mode):
    """Synthetic examples only: never presented as captured game evidence."""
    if mode == 'shop':
        config = dict(mode=mode, purchases=True, gold_budget=1000, sky_budget=3, max_refreshes=1)
        rows = [
            dict(state='shop_list', items=[dict(id='slot1', kind='mystic', price=500)], buttons=['open_purchase']),
            dict(state='purchase_confirm', ack='1', success=True, item_id='slot1', price=500, gold=1000, buttons=['buy']),
            dict(state='receipt', ack='2', success=True, buttons=['close_receipt']),
            dict(state='shop_list', ack='3', success=True, items=[], buttons=['open_refresh']),
            dict(state='refresh_confirm', ack='4', success=True, refresh_cost=3, sky=30, buttons=['refresh']),
            dict(state='shop_list', ack='5', success=True, items=[], buttons=['open_refresh']),
        ]
        # Synthetic balances support stop-line testing; these are not live prices.
        for row in rows:
            row.setdefault('gold',1000)
            row.setdefault('sky',30)
    elif mode == 'story':
        config = dict(mode=mode)
        rows = [dict(state='stage', buttons=['enter']), dict(state='battle', ack='1', success=True),
                dict(state='victory', buttons=['next_stage']), dict(state='stage', ack='2', success=True, buttons=['enter']),
                dict(state='energy_empty')]
    elif mode == 'theater':
        config = dict(mode=mode)
        rows = [dict(state='episode', buttons=['watch']), dict(state='dialogue', ack='1', success=True, buttons=['advance']),
                dict(state='reward', ack='2', success=True, buttons=['claim']),
                dict(state='episode_end', ack='3', success=True, buttons=['next_episode']), dict(state='ticket_empty')]
    else:
        raise ValueError('未知模式')
    return dict(schema=1, synthetic=True, config=config,
                frames=[dict(mode=mode, id=str(i), at=i * 2, **row) for i, row in enumerate(rows)])
