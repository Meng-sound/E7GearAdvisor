"""Live game task decisions and cancellable capture/OCR/background-input loop.

The caller must explicitly start a task. The module never starts at import.
Consumable confirmations require two consistent observations and balance receipts.
"""
from dataclasses import dataclass
import threading
import time


@dataclass(frozen=True)
class Command:
    kind:str
    point:tuple=(.5,.5)
    reason:str=''
    delta:int=0
    gold:int=0
    sky:int=0
    name:str=''


class LivePolicy:
    def __init__(self,config):
        self.config=config;self.pending=None;self.pending_frame=None;self.waits=0
        self.phase='rewind';self.scroll_signature=None;self.same_scroll=0;self.moved_down=False
        self.seen=set();self.intent=None;self.gold_used=0;self.sky_used=0;self.refreshes=0;self.actions=0
        self.checked_gear={}

    def stop(self,reason):return Command('stop',reason=reason)
    def decide(self,obs):
        cfg=self.config
        if obs.scene in {'blocked','unknown_confirm','locked'}:
            return self.stop(obs.reason or '画面未确认')
        if self.pending:
            action=self.pending;before=self.pending_frame;ack=False
            if action.kind in {'buy','buy_ticket'}:
                ack=obs.gold is not None and before.gold is not None and obs.gold==before.gold-action.gold and obs.scene not in {'purchase_confirm','ticket_confirm'}
            elif action.kind=='refresh':
                ack=obs.sky is not None and before.sky is not None and obs.sky==before.sky-action.sky and obs.scene=='shop'
            elif action.kind=='open_purchase':ack=obs.scene=='purchase_confirm'
            elif action.kind=='open_refresh':ack=obs.scene=='refresh_confirm'
            elif action.kind=='scroll':ack=obs.scene=='shop'
            else:ack=obs.signature!=before.signature
            if not ack:
                self.waits+=1
                return self.stop('动作结果未确认；停止，避免重复点击或消费') if self.waits>=4 else Command('wait',reason='等待游戏响应')
            self.pending=None;self.waits=0
            if action.kind=='refresh':
                self.refreshes+=1;self.phase='rewind';self.seen.clear();self.checked_gear.clear();self.moved_down=False;self.same_scroll=0;self.scroll_signature=None
            elif action.kind=='buy':
                self.seen.add((self.intent['name'],self.intent['price']));self.intent=None
            elif action.kind=='scroll':
                unchanged=obs.signature==self.scroll_signature
                self.same_scroll=self.same_scroll+1 if unchanged else 0
                if self.phase=='scan' and not unchanged:self.moved_down=True
                if self.same_scroll>=2:
                    if self.phase=='rewind':self.phase='scan';self.same_scroll=0
                    elif self.moved_down:self.phase='complete'
                    else:return self.stop('滚动未生效或尚未确认列表底部，未刷新')
        if self.actions>=cfg.max_steps:return self.stop('达到动作次数上限')
        if cfg.mode=='shop':return self.shop(obs)
        if cfg.mode=='theater':
            if obs.scene=='use_ticket_confirm':return Command('use_ticket',obs.buttons['confirm'],'使用当前剧场观览券')
            if obs.scene=='theater_reward':return Command('claim_reward',obs.buttons['claim'],'领取已完成剧集奖励')
            if obs.scene=='theater_end':return Command('next_episode',obs.buttons['next_episode'],'前往下一剧集')
            if obs.scene=='theater_clear':return Command('continue',obs.buttons['continue'],'继续剧场结算')
            if obs.scene=='ticket_confirm':
                if obs.price!=500000:return self.stop('观览券价格未确认为50万金币，未购买')
                if obs.gold is None or obs.gold-obs.price<cfg.keep_gold:return self.stop('买票后将低于保留金币，已停止')
                if cfg.gold_budget and self.gold_used+obs.price>cfg.gold_budget:return self.stop('达到金币消费预算')
                return Command('buy_ticket',obs.buttons['confirm'],'购买已核对价格的观览券',gold=obs.price)
            if obs.scene=='theater_home':return Command('enter_theater',obs.buttons['enter'],'进入当前选中的剧场')
            if obs.scene=='theater_episode':return Command('watch',obs.buttons['watch'],'观看当前选中的剧集')
        if cfg.mode=='story':
            for scene,key,kind in [('story_stage','prepare','prepare'),('story_team','start','start_battle'),('story_victory','next','next_stage')]:
                if obs.scene==scene:return Command(kind,obs.buttons[key],'推进：'+scene)
            if obs.scene=='battle':return Command('wait',reason='等待游戏自动战斗；请在游戏中开启AUTO')
        if obs.scene=='skip_confirm':return Command('skip_confirm',obs.buttons['confirm'],'确认跳过剧情')
        if obs.scene=='dialogue':
            key='skip' if 'skip' in obs.buttons else 'advance'
            return Command(key,obs.buttons[key],'推进已识别的剧情界面')
        return Command('wait',reason='等待可识别画面')

    def shop(self,obs):
        cfg=self.config
        if obs.scene not in {'shop','purchase_confirm','refresh_confirm'}:return Command('wait',reason='请打开秘密商店')
        for key,enabled,floor in [('sky',cfg.resource_stop in {'sky','either'},cfg.sky_floor),('gold',cfg.resource_stop in {'gold','either'},cfg.gold_floor)]:
            balance=getattr(obs,key)
            if enabled and balance is None:return self.stop('资源余额未读清：'+key)
            if enabled and balance<=floor:return self.stop('达到资源停止线：'+key)
        if obs.scene=='purchase_confirm':
            if not self.intent:return self.stop('没有匹配的商品选择，未点击购买')
            item=self.intent
            if obs.price!=item['price'] or item['name'] not in ''.join(obs.text.split()):return self.stop('购买弹窗商品或价格不一致')
            floor=max(cfg.keep_gold,cfg.gold_floor if cfg.resource_stop in {'gold','either'} else 0)
            if obs.gold is None or obs.gold-item['price']<floor:return self.stop('金币不足或购买后低于停止线')
            if cfg.gold_budget and self.gold_used+item['price']>cfg.gold_budget:return self.stop('达到金币消费预算')
            return Command('buy',obs.buttons['confirm'],'购买 '+item['name'],gold=item['price'],name=item['name'])
        if obs.scene=='refresh_confirm':
            if self.phase!='complete':return self.stop('没有确认扫完整个列表，禁止刷新')
            floor=cfg.sky_floor if cfg.resource_stop in {'sky','either'} else 0
            if obs.price!=3 or obs.sky is None or obs.sky-3<floor:return self.stop('刷新价格、余额或停止线未通过校验')
            if cfg.sky_budget and self.sky_used+3>cfg.sky_budget:return self.stop('达到天空石消费预算')
            if cfg.max_refreshes and self.refreshes>=cfg.max_refreshes:return self.stop('达到刷新次数上限')
            return Command('refresh',obs.buttons['confirm'],'刷新商店',sky=3)
        if not obs.items:return self.stop('没有完整识别到商品行，不滚动或刷新')
        if self.phase=='rewind':return Command('scroll',(.74,.56),'先滚动到商品列表顶部',delta=720)
        for item in obs.items:
            identity=(item['name'],item['price'])
            if identity in self.seen:continue
            if item['kind']=='gear' and cfg.gear_buy:
                if not any((cfg.gear_gs,cfg.gear_speed,cfg.gear_combo)):continue
                checked=self.checked_gear.get(identity)
                if checked and checked['signature']==obs.signature and checked['point']==item['point']:
                    return Command('open_purchase',item['point'],'红装详情已核验，打开购买确认',name=item['name'])
                point=item.get('inspect_point')
                if not point:return self.stop('发现红装候选，但图标位置未确认，未点击')
                return Command('inspect_gear',point,'长按红装图标，读取两帧详情',name=item['name'])
            if cfg.purchases and item['kind'] in cfg.targets:
                return Command('open_purchase',item['point'],'选择 '+item['name'],name=item['name'])
        if self.phase=='complete':
            point=obs.buttons.get('refresh')
            if not point:return self.stop('立即更新按钮未识别')
            return Command('open_refresh',point,'商品列表已扫描到底，打开刷新确认')
        return Command('scroll',(.74,.56),'向下检查未显示的商品',delta=-120)

    def record_gear(self,command,obs,records):
        from task_replay import eligible_red_gear
        item=next((item for item in obs.items if item['name']==command.name and item.get('inspect_point')==command.point),None)
        if item is None or len(records)!=2 or not records[0] or records[0]!=records[1]:
            raise RuntimeError('红装详情两帧未一致读全，已停止，未购买')
        identity=(item['name'],item['price']);self.actions+=1
        if eligible_red_gear(dict(records[0],price=item['price']),self.config):
            self.checked_gear[identity]=dict(signature=obs.signature,point=item['point'])
            return '红装两帧详情核验通过，符合购买条件'
        self.seen.add(identity);return '红装已核验，不符合所选条件，跳过'

    def dispatched(self,command,obs):
        self.actions+=1;self.pending=command;self.pending_frame=obs;self.waits=0
        self.gold_used+=command.gold;self.sky_used+=command.sky
        if command.kind=='scroll':self.scroll_signature=obs.signature
        if command.kind=='open_purchase':
            self.intent=next(item for item in obs.items if item['name']==command.name and item['point']==command.point)


class LiveRunner:
    def __init__(self,target,config,events,seconds=None,capture=None,ocr=None,inputs=None):
        self.target=target;self.config=config;self.events=events;self.seconds=seconds
        self.cancel=threading.Event();self.paused=threading.Event();self.thread=None;self.status='idle'
        self.gate=threading.Lock()
        self.capture=capture;self.ocr=ocr;self.inputs=inputs
        self.policy=LivePolicy(config);self.last_observation=None
    def emit(self,event,**values):self.events.put(dict(event=event,**values))
    def start(self):
        if self.thread is not None:raise RuntimeError('任务已经启动')
        self.status='running';self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
    def pause(self):
        with self.gate:self.paused.set();self.status='paused'
    def resume(self):self.paused.clear();self.status='running'
    def stop(self):self.cancel.set();self.status='stopping'
    def alive(self):return self.thread is not None and self.thread.is_alive()
    def run(self):
        started=time.monotonic();candidate=None;stable=0;unknown=0;last_change=started;last_sig=None
        try:
            if self.capture is None:
                from stream_capture import StreamCapture
                self.capture=StreamCapture(self.target)
            if self.inputs is None:
                from window_input import WindowInput
                self.inputs=WindowInput(self.target)
            if self.ocr is None:
                from game_task_vision import GameOCR
                self.ocr=GameOCR()
            self.emit('status',text='实机任务已启动；F10紧急停止；后台优先，兼容取图需无遮挡')
            capture_backend=None
            def watchdog():
                while not self.cancel.wait(.05):
                    try:
                        if self.inputs.emergency_pressed():self.cancel.set();self.emit('status',text='F10已停止任务');return
                    except Exception:
                        self.cancel.set();self.emit('status',text='紧急停止键检测失败，已停止任务');return
            threading.Thread(target=watchdog,daemon=True).start()
            while not self.cancel.is_set():
                if time.monotonic()-started>=min(self.config.max_seconds,self.seconds if self.seconds is not None else self.config.max_seconds):
                    self.emit('status',text='达到定时停止时间');break
                if self.paused.is_set():self.cancel.wait(.1);continue
                image=self.capture(self.target)
                backend=getattr(image,'info',{}).get('capture_backend')
                if backend and backend!=capture_backend:
                    capture_backend=backend;self.emit('status',text='当前取图：'+backend)
                obs=self.ocr.read(image,self.config.mode);self.last_observation=obs
                if self.cancel.is_set() or self.paused.is_set():continue
                self.emit('observation',scene=obs.scene,gold=obs.gold,sky=obs.sky,items=len(obs.items))
                if obs.signature!=last_sig:last_sig=obs.signature;last_change=time.monotonic()
                if time.monotonic()-last_change>180:
                    self.emit('status',text='画面长期无变化，已停止');break
                command=self.policy.decide(obs)
                if command.kind=='stop':self.emit('status',text=command.reason);break
                if command.kind=='wait':
                    unknown=unknown+1 if obs.scene=='unknown' else 0
                    if unknown>=5:self.emit('status',text='连续5帧未识别，请查看游戏画面');break
                    candidate=None;stable=0;self.cancel.wait(.5);continue
                unknown=0
                signature=(command.kind,command.name,command.gold,command.sky,command.delta,
                           tuple(round(value,2) for value in command.point),obs.gold,obs.sky)
                stable=stable+1 if signature==candidate else 1;candidate=signature
                required=2 if command.kind in {'buy','buy_ticket','refresh','inspect_gear','open_purchase'} else 1
                if stable<required:self.cancel.wait(.10);continue
                allowed=lambda:not self.cancel.is_set() and not self.paused.is_set()
                with self.gate:
                    if command.kind=='inspect_gear':
                        from shop_gear import read_tooltip
                        frames=self.inputs.inspect_gear(command,image.size,lambda:self.capture(self.target),allowed)
                        if not allowed():continue
                        records=[read_tooltip(frame,self.ocr.local) for frame in frames]
                        note=self.policy.record_gear(command,obs,records)
                        self.emit('status',text=note)
                        candidate=None;stable=0;self.cancel.wait(.4);continue
                    if self.inputs.perform(command,image.size,allowed):
                        self.policy.dispatched(command,obs)
                        self.emit('action',kind=command.kind,text=command.reason,gold=command.gold,sky=command.sky)
                candidate=None;stable=0;self.cancel.wait(.20 if command.kind=='scroll' else .30)
        except Exception as error:self.emit('status',text='任务已停止：'+str(error))
        finally:
            self.cancel.set();self.status='stopped'
            if self.ocr is not None:
                try:self.ocr.close()
                except Exception:pass
            if hasattr(self.capture,'close'):self.capture.close()
            self.emit('done',text='任务已停止',actions=self.policy.actions,gold=self.policy.gold_used,sky=self.policy.sky_used)
