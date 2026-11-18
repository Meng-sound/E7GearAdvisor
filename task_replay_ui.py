"""Visible offline replay workbench. No game input or background worker."""
import json
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from dataclasses import asdict
from local_json import read_json
from task_replay import Config, Session, MODES, demo, load_replay
from ui_theme import BG, CARD, TEXT, MUTED, GOLD


class TaskReplayWindow(tk.Toplevel):
    def __init__(self, app, mode='shop'):
        super().__init__(app)
        self.title('自动任务 · E7Pilot 源码流程')
        self.geometry(f'620x{min(490, self.winfo_screenheight()-85)}')
        self.minsize(560, 430)
        self.configure(bg=BG)
        self.session = None
        self.frames = []
        self.index = 0
        self.job = None
        self.capture_job = None
        self.capture_results = queue.Queue()
        self.capture_busy = False
        self.synthetic = False
        self.mode = tk.StringVar(value=MODES[mode])
        self.note = tk.StringVar(value='三个任务使用E7Pilot源码流程 · 后台输入，不抢鼠标 · F10停止。')
        self.capture_mode=tk.StringVar(value='自动兼容')
        self.live_runner=None;self.live_events=queue.Queue();self.live_poll_job=None
        self.summary = tk.StringVar(value='等待测试')
        self.values = {key: tk.StringVar(value=str(value)) for key, value in
                       dict(gold_budget=0, sky_budget=0, keep_gold=0, max_refreshes=0,
                            max_steps=100, max_seconds=600, sky_floor=2000, gold_floor=1000000).items()}
        self.resource_stop=tk.StringVar(value='sky')
        self.gear_buy=tk.BooleanVar(value=False)
        self.gear_rules={key:tk.BooleanVar(value=False) for key in ('gear_gs','gear_speed','gear_combo')}
        self.timed_stop=tk.BooleanVar(value=False)
        self.minutes=tk.StringVar(value='120')
        self.settings_file=getattr(app,'user_dir',None)
        self.settings_file=self.settings_file/'task-settings.json' if self.settings_file is not None else None
        self.saved_modes={}
        if self.settings_file is not None and self.settings_file.exists():
            try:
                saved=read_json(self.settings_file)
                if isinstance(saved,dict) and saved.get('schema')==1 and isinstance(saved.get('modes'),dict):
                    self.saved_modes=saved['modes']
            except (OSError,ValueError,TypeError):
                self.note.set('已忽略无效任务设置；本次使用默认值。')
        self.purchases = tk.BooleanVar(value=False)
        self.targets = {key: tk.BooleanVar(value=key in ('covenant', 'mystic')) for key in ('covenant', 'mystic', 'friendship')}
        self.config_widgets = []
        self.running_locked=False
        head = ttk.Frame(self, padding=12)
        head.pack(fill='x')
        self.heading=ttk.Label(head, text=MODES[mode], font=('Microsoft YaHei UI', 15, 'bold'))
        self.heading.pack(side='left')
        tools=ttk.Menubutton(head,text='测试工具 ▾',style='Compact.TButton')
        self.tools_menu=tk.Menu(tools,tearoff=False)
        for label,command in [('载入示例',self.example),('导入回放 JSON',self.import_file),('单步',self.step),('回放运行（不操作游戏）',self.start_replay),
                              ('导出示例',self.export_example),('导出日志',self.export_log),
                              ('取图兼容检测',self.test_capture),('高级测试设置',self.advanced_settings)]:
            self.tools_menu.add_command(label=label,command=command)
            if label=='取图兼容检测':self.tools_menu.entryconfigure('end',foreground='#4b73ff',font=('Microsoft YaHei UI',10,'bold'))
        tools.configure(menu=self.tools_menu)
        tools.pack(side='right',padx=(8,0))
        selector = ttk.Combobox(head, textvariable=self.mode, values=list(MODES.values()), state='readonly', width=12)
        selector.pack(side='right')
        self.config_widgets.append(selector)
        self.mode_selector=selector
        selector.bind('<<ComboboxSelected>>', lambda _: self.reset())
        capture_row=ttk.Frame(self,padding=(12,0));capture_row.pack(fill='x')
        ttk.Label(capture_row,text='取图方式').pack(side='left',padx=(0,7))
        capture_selector=ttk.Combobox(capture_row,textvariable=self.capture_mode,values=['自动兼容','仅后台取图','无遮挡窗口'],state='readonly',width=15,style='Compact.TCombobox')
        capture_selector.pack(side='left');self.config_widgets.append(capture_selector)
        ttk.Label(capture_row,text='后台支持遮挡；兼容取图需无遮挡',font=('Microsoft YaHei UI',8)).pack(side='left',padx=8)
        ttk.Label(self, text='实机测试版：开始后会操作游戏；F10紧急停止。',
                  foreground=GOLD, wraplength=530).pack(fill='x', padx=12, pady=(0, 5))
        self.mode_form=ttk.Frame(self,padding=(12,6))
        self.mode_form.pack(fill='x')
        self.restore_mode(mode)
        self.render_form()
        self.note_label=ttk.Label(self, textvariable=self.note, wraplength=530, foreground=MUTED)
        self.note_label.pack(fill='x', padx=16)
        buttons = ttk.Frame(self, padding=12)
        buttons.pack(fill='x')
        self.action_buttons=[]
        for label, command in [('开始', self.start), ('暂停 / 继续', self.pause), ('停止', self.stop)]:
            button=ttk.Button(buttons, text=label, command=command, style='Compact.TButton')
            button.pack(side='left', padx=(0, 6))
            self.action_buttons.append(button)
        self.summary_label=ttk.Label(self, textvariable=self.summary, wraplength=530)
        self.summary_label.pack(fill='x', padx=16, pady=(0, 8))
        body = ttk.Frame(self, padding=(12, 0, 12, 12))
        body.pack(fill='both', expand=True)
        self.output = tk.Text(body, bg=CARD, fg=TEXT, wrap='word', relief='flat', state='disabled', height=5)
        scrollbar = ttk.Scrollbar(body, command=self.output.yview)
        scrollbar.pack(side='right', fill='y')
        self.output.pack(fill='both', expand=True)
        self.output.configure(yscrollcommand=scrollbar.set)
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.bind('<Escape>', lambda _: self.stop())
        self.bind('<Configure>',self.resize_labels,add='+')

    def mode_id(self):
        return next(key for key, label in MODES.items() if label == self.mode.get())

    def resize_labels(self,event):
        if event.widget is self:
            for label in (self.note_label,self.summary_label):
                label.configure(wraplength=max(300,event.width-36))

    def restore_mode(self,mode):
        self.active_mode=mode
        defaults=asdict(Config(mode=mode,resource_stop='sky' if mode=='shop' else 'none',
                               sky_floor=2000,gold_floor=1000000,keep_gold=1000000 if mode=='theater' else 0))
        record=self.saved_modes.get(mode,{})
        try:
            candidate=Config(**record.get('config',defaults))
            if candidate.mode!=mode:raise ValueError('任务类型不一致')
            config=asdict(candidate)
            timed=record.get('timed',False)
            minutes=record.get('minutes',120)
            if type(timed) is not bool or type(minutes) is not int or not 1<=minutes<=10080:
                raise ValueError('无效定时设置')
        except (TypeError,ValueError,AttributeError):
            config=defaults;timed=False;minutes=120
        self.base_config=dict(config)
        for key,var in self.values.items():var.set(str(config[key]))
        self.resource_stop.set(config['resource_stop'])
        self.purchases.set(config['purchases'])
        self.gear_buy.set(config['gear_buy'])
        for key,var in self.gear_rules.items():var.set(config[key])
        for key,var in self.targets.items():var.set(key in config['targets'])
        self.timed_stop.set(timed);self.minutes.set(str(minutes))

    def collect_config(self):
        values=dict(self.base_config)
        values.update({key:int(var.get()) for key,var in self.values.items()})
        minutes=int(self.minutes.get())
        if not 1<=minutes<=10080:raise ValueError('定时停止应为1至10080分钟')
        if self.timed_stop.get():values['max_seconds']=minutes*60
        values.update(mode=self.mode_id(),purchases=self.purchases.get(),
                      targets=tuple(key for key,var in self.targets.items() if var.get()),
                      resource_stop=self.resource_stop.get() if self.mode_id()=='shop' else 'none',
                      gear_buy=self.gear_buy.get() if self.mode_id()=='shop' else False,
                      **{key:var.get() for key,var in self.gear_rules.items()})
        return Config(**values)

    def remember_settings(self):
        config=self.collect_config()
        self.saved_modes[self.mode_id()]={'config':asdict(config),'timed':self.timed_stop.get(),'minutes':int(self.minutes.get())}
        if self.settings_file is not None:
            from fribbels_sync import save_atomic
            save_atomic(self.settings_file,{'schema':1,'modes':self.saved_modes})

    def render_form(self):
        for child in self.mode_form.winfo_children():child.destroy()
        self.config_widgets=[self.mode_selector]
        self.floor_entries={}
        self.timer_entry=None
        self.heading.configure(text=MODES[self.mode_id()])
        form=self.mode_form
        def entry(parent,key,width=12):
            widget=ttk.Entry(parent,textvariable=self.values[key],width=width)
            self.config_widgets.append(widget)
            return widget
        def check(parent,text,variable):
            widget=ttk.Checkbutton(parent,text=text,variable=variable)
            self.config_widgets.append(widget)
            return widget
        if self.mode_id()=='shop':
            row=ttk.Frame(form);row.pack(fill='x',pady=3)
            for col,(key,label) in enumerate([('sky_floor','天空石停止线'),('gold_floor','金币停止线')]):
                row.columnconfigure(col*2+1,weight=1)
                ttk.Label(row,text=label).grid(row=0,column=col*2,padx=(0,5))
                field=entry(row,key)
                field.grid(row=0,column=col*2+1,sticky='ew',padx=(0,12))
                self.floor_entries[key]=field
            row=ttk.Frame(form);row.pack(fill='x',pady=3)
            ttk.Label(row,text='停止条件').pack(side='left',padx=(0,12))
            for label,value in [('天空石','sky'),('金币','gold'),('任一','either')]:
                radio=ttk.Radiobutton(row,text=label,value=value,variable=self.resource_stop,command=self.update_optional_fields)
                radio.pack(side='left',padx=(0,12));self.config_widgets.append(radio)
            row=ttk.Frame(form);row.pack(fill='x',pady=3)
            check(row,'购买书签',self.purchases).pack(side='left',padx=(0,12))
            for key,label in [('covenant','誓约'),('mystic','神秘')]:
                check(row,label,self.targets[key]).pack(side='left',padx=(0,12))
            row=ttk.Frame(form);row.pack(fill='x',pady=3)
            check(row,'自动购买极品红装（85 传说）',self.gear_buy).pack(side='left',padx=(0,10))
            detail=ttk.Button(row,text='详情',style='Compact.TButton',command=self.gear_details)
            detail.pack(side='left');self.config_widgets.append(detail)
        elif self.mode_id()=='theater':
            row=ttk.Frame(form);row.pack(fill='x',pady=6)
            ttk.Label(row,text='保留金币：').pack(side='left',padx=(0,6))
            entry(row,'keep_gold',15).pack(side='left')
            ttk.Label(row,text='自动买票：核对50万票价，保留以上金币',foreground=MUTED).pack(side='left',padx=10)
        else:
            ttk.Label(form,text='自动战斗推进；战败、体力不足或未知画面时停止。',wraplength=510).pack(anchor='w',pady=6)
        if self.mode_id()!='theater':
            row=ttk.Frame(form);row.pack(fill='x',pady=(6,2))
            timer=check(row,'定时停止',self.timed_stop)
            timer.configure(command=self.update_optional_fields)
            timer.pack(side='left',padx=(0,8))
            minutes=ttk.Entry(row,textvariable=self.minutes,width=6)
            minutes.pack(side='left');self.config_widgets.append(minutes)
            self.timer_entry=minutes
            ttk.Label(row,text='分钟').pack(side='left',padx=6)
        self.update_optional_fields()

    def update_optional_fields(self):
        for key,widget in self.floor_entries.items():
            active=self.resource_stop.get() in (('sky','either') if key=='sky_floor' else ('gold','either'))
            widget.state(['!disabled'] if active and not self.running_locked else ['disabled'])
        if self.timer_entry is not None:
            self.timer_entry.state(['!disabled'] if self.timed_stop.get() and not self.running_locked else ['disabled'])

    def gear_details(self):
        if self.live_runner is not None and self.live_runner.alive():self.note.set('请先停止实机任务再修改条件。');return
        if self.session and self.session.status in {'running','paused'}:return
        old=getattr(self,'gear_dialog',None)
        if old is not None and old.winfo_exists():old.lift();return old
        window=tk.Toplevel(self);self.gear_dialog=window
        window.title('红装购买条件');window.geometry('420x320');window.resizable(False,False)
        window.transient(self);window.grab_set()
        body=ttk.Frame(window,padding=14);body.pack(fill='both',expand=True)
        ttk.Label(body,text='满足任一勾选条件即购买：').pack(anchor='w',pady=(0,10))
        draft={key:tk.BooleanVar(value=var.get()) for key,var in self.gear_rules.items()}
        for key,label in [('gear_gs','装备分数 ≥ 27（原项目规则）'),('gear_speed','速度 ≥ 3'),('gear_combo','同时拥有「暴击伤害 / 暴击 / 速度」三条词条')]:
            ttk.Checkbutton(body,text=label,variable=draft[key]).pack(anchor='w',pady=5)
        ttk.Label(body,text='使用原项目的红装检查和购买流程。\n价格为1,400,000金币，85级传说；未勾选条件不购买。\n“装备分数”按原项目读取游戏详情，不是角色总分。',wraplength=385,foreground=MUTED).pack(fill='x',pady=12)
        def save():
            for key,var in draft.items():self.gear_rules[key].set(var.get())
            try:self.remember_settings()
            except (OSError,ValueError,TypeError) as error:
                messagebox.showerror('未保存',str(error),parent=window);return
            window.destroy()
        ttk.Button(body,text='保存',command=save).pack(side='bottom')
        return window

    def advanced_settings(self):
        if self.live_runner is not None and self.live_runner.alive():self.note.set('请先停止实机任务再修改设置。');return
        if self.session and self.session.status in {'running','paused'}:
            self.note.set('请先停止测试再修改高级设置。');return
        old=getattr(self,'advanced_dialog',None)
        if old is not None and old.winfo_exists():old.lift();return old
        window=tk.Toplevel(self);self.advanced_dialog=window
        window.title('高级测试设置');window.geometry('420x390')
        window.transient(self);window.grab_set()
        body=ttk.Frame(window,padding=14);body.pack(fill='both',expand=True)
        ttk.Label(body,text='实机预算/刷新次数为0时只按余额停止线控制。回放仍使用其原有预算规则。',wraplength=380).pack(anchor='w',pady=(0,12))
        draft={key:tk.StringVar(value=self.values[key].get()) for key in ('gold_budget','sky_budget','max_refreshes','max_steps','max_seconds')}
        for key,label in [('gold_budget','金币消费预算'),('sky_budget','天空石消费预算'),('max_refreshes','最多刷新次数'),('max_steps','最多动作'),('max_seconds','回放时长上限（秒）')]:
            row=ttk.Frame(body);row.pack(fill='x',pady=5)
            ttk.Label(row,text=label).pack(side='left')
            ttk.Entry(row,textvariable=draft[key],width=15).pack(side='right')
        def save():
            previous={key:self.values[key].get() for key in draft}
            for key,var in draft.items():self.values[key].set(var.get())
            try:self.remember_settings()
            except (OSError,ValueError,TypeError) as error:
                for key,value in previous.items():self.values[key].set(value)
                messagebox.showerror('未保存',str(error),parent=window);return
            window.destroy()
        ttk.Button(body,text='保存',command=save).pack(side='bottom')
        return window

    def cancel_timer(self):
        if self.job:
            self.after_cancel(self.job)
            self.job = None

    def lock_config(self, locked):
        self.running_locked=locked
        for widget in self.config_widgets:
            widget.state(['disabled'] if locked else ['!disabled'])
        self.update_optional_fields()

    def reset(self):
        selected=self.mode_id()
        if selected!=self.active_mode:
            self.mode.set(MODES[self.active_mode])
            try:self.remember_settings()
            except (OSError,ValueError,TypeError):pass
            self.mode.set(MODES[selected])
        self.stop()
        self.session = None
        self.frames = []
        self.index = 0
        self.restore_mode(selected)
        self.render_form()
        self.lock_config(False)
        self.note.set('请选择当前模式的示例或回放 JSON。')
        self.summary.set('等待测试')

    def load(self, data):
        config, frames = load_replay(data)
        self.stop()
        self.mode.set(MODES[config.mode])
        self.active_mode=config.mode
        self.frames = frames
        self.session = None
        self.index = 0
        self.base_config = asdict(config)
        self.synthetic = data.get('synthetic') is True
        for key, var in self.values.items():
            var.set(str(getattr(config, key)))
        self.purchases.set(config.purchases)
        self.resource_stop.set(config.resource_stop if config.resource_stop!='none' or config.mode!='shop' else 'sky')
        self.gear_buy.set(config.gear_buy)
        for key,var in self.gear_rules.items():var.set(getattr(config,key))
        self.timed_stop.set(False)
        for key,var in self.targets.items():
            var.set(key in config.targets)
        self.render_form()
        self.lock_config(False)
        self.note.set(('合成示例' if self.synthetic else '用户导入回放（非实机验证）') + f' · {len(frames)}帧 · 时间按回放文件计算')
        self.summary.set('已载入，点击开始或单步测试')
        self.write('已载入；商品目标：' + ', '.join(config.targets))

    def example(self):
        self.load(demo(self.mode_id()))

    def import_file(self):
        path = filedialog.askopenfilename(parent=self, filetypes=[('任务回放', '*.json')])
        if not path:
            return
        try:
            self.load(read_json(path))
        except (OSError, TypeError, ValueError) as error:
            messagebox.showerror('未载入', str(error), parent=self)

    def write(self, text):
        self.output.configure(state='normal')
        self.output.insert('end', text + '\n')
        self.output.see('end')
        self.output.configure(state='disabled')

    def prepare(self):
        if self.live_runner is not None and self.live_runner.alive():
            self.note.set('请先停止实机任务。');return False
        if self.session is not None:
            return self.session.status == 'running'
        if not self.frames:
            self.note.set('请先载入示例或回放 JSON。')
            return False
        try:
            self.remember_settings()
            self.session = Session(self.collect_config())
            self.session.start()
            self.lock_config(True)
            self.write('开始 · 设置已锁定；更改设置需重新载入。')
            return True
        except (OSError, TypeError, ValueError) as error:
            messagebox.showerror('设置有误', str(error), parent=self)
            return False

    def step(self):
        self.cancel_timer()
        self.advance()

    def advance(self):
        if not self.prepare():
            return
        if self.index >= len(self.frames):
            self.session.stop('回放结束' + ('；最后动作尚无回执' if self.session.pending else ''))
        else:
            frame = self.frames[self.index]
            self.index += 1
            action = self.session.feed(frame, frame['at'])
            self.write(f"{frame['at']:g}s · {frame['state']} → " + (json.dumps(asdict(action), ensure_ascii=False) if action else self.session.reason))
            if self.index == len(self.frames) and self.session.status == 'running':
                self.session.stop('回放结束' + ('；最后动作尚无回执' if self.session.pending else ''))
        session = self.session
        self.summary.set(f'{self.index}/{len(self.frames)}帧 · {session.steps}动作 · 完成{session.completed}次 · '
                         f'金币预留{session.gold_used} · 天空石预留{session.sky_used} · {session.reason}')

    def start_replay(self):
        self.cancel_timer()
        if self.live_runner is not None and self.live_runner.alive():
            self.note.set('请先停止实机任务。');return
        if self.prepare():
            self.tick()

    def start(self):
        if self.live_runner is not None and self.live_runner.alive():
            self.note.set('当前任务尚未结束，请先停止。');return
        try:
            config=self.collect_config();self.remember_settings()
            from desktop_capture import find_game_windows
            windows=find_game_windows()
            if not windows:raise ValueError('没有找到第七史诗窗口，请先打开游戏。')
            index=0
            if len(windows)>1:
                from tkinter import simpledialog
                chosen=simpledialog.askinteger('选择游戏窗口','\n'.join(f'{i+1}. {w["title"]} PID {w["pid"]}' for i,w in enumerate(windows)),minvalue=1,maxvalue=len(windows),parent=self)
                if chosen is None:return
                index=chosen-1
            if windows[index]['minimized']:raise ValueError('请恢复游戏窗口，不要最小化。')
            self.stop()
            if self.live_poll_job:
                self.after_cancel(self.live_poll_job);self.live_poll_job=None
            while True:
                try:self.live_events.get_nowait()
                except queue.Empty:break
            target=dict(windows[index],capture_mode={'自动兼容':'auto','仅后台取图':'background','无遮挡窗口':'visible'}[self.capture_mode.get()])
            from pilot_runner import PilotRunner
            self.live_runner=PilotRunner(target,config,self.live_events,seconds=int(self.minutes.get())*60 if self.timed_stop.get() else None,user_dir=self.master.user_dir)
            self.lock_config(True);self.live_runner.start();self.poll_live()
        except (OSError,ValueError,TypeError) as error:
            self.lock_config(False);self.note.set(str(error))

    def poll_live(self):
        self.live_poll_job=None
        while True:
            try:event=self.live_events.get_nowait()
            except queue.Empty:break
            kind=event['event']
            if kind=='observation':self.summary.set(f"识别：{event['scene']} · 金币 {event['gold'] if event['gold'] is not None else '待识别'} · 天空石 {event['sky'] if event['sky'] is not None else '待识别'}")
            elif kind=='done':
                if event.get('source_engine'):self.write(event['text'])
                else:self.write(f"停止：{event['actions']}次操作；金币消费预留{event['gold']}，天空石消费预留{event['sky']}")
                self.lock_config(False)
            else:
                self.note.set(event.get('text',''));self.write(event.get('text',''))
        if self.live_runner is not None and self.live_runner.alive():self.live_poll_job=self.after(100,self.poll_live)

    def tick(self):
        self.job = None
        self.advance()
        if self.session and self.session.status == 'running':
            self.job = self.after(400, self.tick)

    def pause(self):
        if self.live_runner is not None and self.live_runner.alive():
            if self.live_runner.paused.is_set():self.live_runner.resume();self.note.set('实机任务继续')
            else:self.live_runner.pause();self.note.set('实机任务已暂停，不再发出新点击')
            return
        if not self.session:
            return
        if self.session.status == 'running':
            self.cancel_timer()
            self.session.pause()
        elif self.session.status == 'paused':
            self.session.resume()
            self.start_replay()
        self.summary.set(self.session.reason)

    def stop(self):
        if self.live_runner is not None and self.live_runner.alive():self.live_runner.stop()
        self.cancel_timer()
        if self.session and self.session.status in {'running', 'paused'}:
            self.session.stop()
            self.summary.set(self.session.reason)

    def save_json(self, data, filename):
        path = filedialog.asksaveasfilename(parent=self, initialfile=filename, defaultextension='.json', filetypes=[('JSON', '*.json')])
        if path:
            try:
                from pathlib import Path
                Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf8')
            except OSError as error:
                messagebox.showerror('未保存', str(error), parent=self)

    def export_example(self):
        self.save_json(demo(self.mode_id()), 'task-replay-example.json')

    def export_log(self):
        if not self.session:
            self.note.set('运行回放后才能导出日志。')
            return
        self.save_json(dict(schema=1, replay_only=True, synthetic=self.synthetic, config=asdict(self.session.config),
                            status=self.session.status, reason=self.session.reason, events=self.session.log), 'task-replay-log.json')

    def test_capture(self):
        if self.capture_busy:
            return
        from desktop_capture import find_game_windows
        from tkinter import simpledialog
        windows = find_game_windows()
        if not windows:
            self.note.set('没有找到第七史诗窗口。检测只取游戏客户区，不操作游戏。')
            return
        index = 0
        if len(windows) > 1:
            selected = simpledialog.askinteger('选择游戏窗口', '\n'.join(f'{i+1}. {w["title"]} PID {w["pid"]}' for i,w in enumerate(windows)),
                                               minvalue=1,maxvalue=len(windows),parent=self)
            if selected is None:
                return
            index = selected-1
        target = dict(windows[index],capture_mode={'自动兼容':'auto','仅后台取图':'background','无遮挡窗口':'visible'}[self.capture_mode.get()])
        self.capture_busy = True
        self.note.set('正在检测取图兼容性；兼容模式需无遮挡，不切换焦点或点击游戏。')
        def work():
            try:
                from window_capture import capture_game_window
                self.capture_results.put(('ok', capture_game_window(target)))
            except Exception as error:
                self.capture_results.put(('error', str(error)))
        threading.Thread(target=work, daemon=True).start()
        self.capture_job = self.after(150, self.poll_capture)

    def poll_capture(self):
        self.capture_job = None
        try:
            state, result = self.capture_results.get_nowait()
        except queue.Empty:
            self.capture_job = self.after(150, self.poll_capture)
            return
        self.capture_busy = False
        if state == 'error':
            self.note.set('后台取图未通过：' + result)
            return
        self.note.set('收到图像：'+result.info.get('capture_backend','窗口取图')+'。请核对当前画面；尚未验证点击。')
        from PIL import ImageTk
        preview=tk.Toplevel(self)
        preview.title('后台取图检测 · 请核对画面')
        preview.geometry('660x440')
        ttk.Label(preview,text='窗口客户区取图；未使用桌面截图。黑屏、停帧或内容不正确都应视为未通过。',wraplength=620).pack(fill='x',padx=12,pady=12)
        result.thumbnail((630,350))
        preview.photo=ImageTk.PhotoImage(result,master=preview)
        ttk.Label(preview,image=preview.photo).pack(fill='both',expand=True,padx=12,pady=8)

    def close(self):
        self.stop()
        try:self.remember_settings()
        except (OSError,TypeError,ValueError):pass
        if self.capture_job:
            self.after_cancel(self.capture_job)
            self.capture_job=None
        if self.live_poll_job:
            self.after_cancel(self.live_poll_job);self.live_poll_job=None
        self.destroy()


def open_task_replay(app, mode='shop'):
    from pilot_task_ui import open_task
    return open_task(app,mode)
    # One window per application; do not leave orphan timers in hidden windows.
    previous = getattr(app, 'task_replay_window', None)
    if previous is not None and previous.winfo_exists():
        if previous.mode_id() != mode:
            if (previous.session and previous.session.status in {'running', 'paused'}) or (previous.live_runner is not None and previous.live_runner.alive()):
                previous.note.set('另一个任务正在回放；请先停止，再切换模式。')
            else:
                previous.mode.set(MODES[mode])
                previous.reset()
        previous.lift()
        return previous
    window = TaskReplayWindow(app, mode)
    app.task_replay_window = window
    return window
