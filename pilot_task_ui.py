"""Task controls exposing only E7Pilot's own settings and original defaults."""
import json,queue,tkinter as tk
from tkinter import ttk,messagebox,simpledialog
from types import SimpleNamespace
from task_replay import MODES
from ui_theme import BG,MUTED,FONT
import pilot_settings

class NativeTaskWindow(tk.Toplevel):
 def __init__(self,app,mode):
  super().__init__(app);self.app=app;self.current_mode=mode;self.settings=pilot_settings.load(app.user_dir)
  self.title('自动任务');self.geometry('650x530');self.configure(bg=BG)
  self.live_runner=None;self.events=queue.Queue();self.poll_job=None;self.vars={}
  self.mode=tk.StringVar(value=MODES[mode]);self.capture_mode=tk.StringVar(value='自动兼容');self.note=tk.StringVar(value='F8暂停/继续，F10停止。')
  head=ttk.Frame(self,padding=14);head.pack(fill='x')
  self.heading=ttk.Label(head,text=MODES[mode],font=(FONT,16,'bold'));self.heading.pack(side='left')
  ttk.Button(head,text='高级设置…',command=self.edit_settings).pack(side='right')
  selector=ttk.Combobox(head,textvariable=self.mode,values=list(MODES.values()),state='readonly',width=12);selector.pack(side='right',padx=8);selector.bind('<<ComboboxSelected>>',self.switch)
  ttk.Label(self,text='后台操作 · 不抢前台鼠标 · 不要最小化游戏',foreground=MUTED).pack(anchor='w',padx=14)
  self.form=ttk.Frame(self,padding=14);self.form.pack(fill='x');self.render()
  ttk.Label(self,textvariable=self.note,wraplength=610).pack(fill='x',padx=14,pady=8)
  actions=ttk.Frame(self,padding=(14,0));actions.pack(fill='x')
  for label,command in [('开始',self.start),('暂停 / 继续',self.pause),('停止',self.stop)]:ttk.Button(actions,text=label,command=command).pack(side='left',padx=(0,8))
  self.output=tk.Text(self,height=10,wrap='word',bg='#202630',fg='#edf2fa',font=(FONT,9),state='disabled');self.output.pack(fill='both',expand=True,padx=14,pady=14)
  self.protocol('WM_DELETE_WINDOW',self.close)
 def mode_id(self):return self.current_mode
 def running(self):return self.live_runner is not None and self.live_runner.alive()
 def render(self):
  for child in self.form.winfo_children():child.destroy()
  self.vars={};self.heading.configure(text=MODES[self.current_mode]);self.title('自动任务 · '+MODES[self.current_mode])
  def number(key,label,default):
   row=ttk.Frame(self.form);row.pack(fill='x',pady=3);ttk.Label(row,text=label,width=20).pack(side='left')
   var=tk.StringVar(value=str(self.settings.get(key,default)));self.vars[key]=var;ttk.Entry(row,textvariable=var,width=16).pack(side='left')
  if self.current_mode=='shop':
   number('stop_skystones','天空石停止线',2000);number('shop_stop_gold','金币停止线',1000000)
   row=ttk.Frame(self.form);row.pack(fill='x',pady=4);ttk.Label(row,text='停止条件',width=20).pack(side='left')
   var=tk.StringVar(value=self.settings.get('shop_stop_mode','sky'));self.vars['shop_stop_mode']=var
   for label,value in [('天空石','sky'),('金币','gold'),('任一','either')]:ttk.Radiobutton(row,text=label,value=value,variable=var).pack(side='left',padx=5)
   for key,label in [('gear_auto_buy','自动购买85级传说红装'),('gear_cond_score27','装备分数 ≥ 27'),('gear_cond_speed3','速度 ≥ 3'),('gear_cond_combo','同时有暴击、暴伤、速度')]:
    var=tk.BooleanVar(value=bool(self.settings.get(key,False)));self.vars[key]=var;ttk.Checkbutton(self.form,text=label,variable=var).pack(anchor='w',pady=2)
   ttk.Label(self.form,text='自动扫描货架、购买书签，按所选条件筛选红装。',foreground=MUTED).pack(anchor='w',pady=5)
  elif self.current_mode=='theater':
   number('theater_keep_gold','买票后保留金币',1000000)
   ttk.Label(self.form,text=f"剧场门票：{self.settings.get('theater_ticket_cost',500000):,}金币 / 张",foreground=MUTED).pack(anchor='w',pady=8)
  else:
   self.vars['combat_mode']=tk.StringVar(value='auto')
   ttk.Label(self.form,text='使用系统AUTO自动战斗，自动推进关卡和剧情。',foreground=MUTED).pack(anchor='w',pady=6)
 def save(self):
  for key,var in self.vars.items():
   value=var.get()
   if key in ('stop_skystones','shop_stop_gold','theater_keep_gold'):
    value=int(value)
    if value<0:raise ValueError('数值不能为负数')
   self.settings[key]=value
  pilot_settings.save(self.app.user_dir,self.settings)
 def switch(self,event=None):
  wanted=next(k for k,v in MODES.items() if v==self.mode.get())
  if self.running():self.mode.set(MODES[self.current_mode]);self.note.set('请先停止当前任务再切换。');return
  self.save();self.current_mode=wanted;self.render()
 def edit_settings(self):
  if self.running():self.note.set('请先停止任务再修改设置。');return
  self.save();window=tk.Toplevel(self);window.title('自动任务 · 高级设置');window.geometry('700x650')
  text=tk.Text(window,wrap='none',font=('Consolas',10));text.pack(fill='both',expand=True,padx=12,pady=12);text.insert('1.0',json.dumps(self.settings,ensure_ascii=False,indent=2))
  def save():
   try:
    settings=json.loads(text.get('1.0','end'))
    if not isinstance(settings,dict):raise ValueError('设置必须为JSON对象')
    pilot_settings.save(self.app.user_dir,settings);self.settings=pilot_settings.load(self.app.user_dir);self.render();window.destroy()
   except (ValueError,OSError) as error:messagebox.showerror('未保存',str(error),parent=window)
  ttk.Button(window,text='保存设置',command=save).pack(pady=(0,12))
 def start(self):
  if self.running():return
  try:
   self.save()
   from desktop_capture import find_game_windows
   from pilot_runner import PilotRunner
   windows=find_game_windows()
   if not windows:raise ValueError('未找到第七史诗窗口')
   index=0
   if len(windows)>1:
    choice=simpledialog.askinteger('选择游戏窗口','\n'.join(f'{i+1}. {w["title"]} PID {w["pid"]}' for i,w in enumerate(windows)),minvalue=1,maxvalue=len(windows),parent=self)
    if choice is None:return
    index=choice-1
   target=dict(windows[index],capture_mode='auto')
   if target['minimized']:raise ValueError('请还原游戏窗口')
   self.live_runner=PilotRunner(target,SimpleNamespace(mode=self.current_mode),self.events,user_dir=self.app.user_dir)
   self.live_runner.start();self.note.set('正在启动任务…');self.poll()
  except (ValueError,OSError) as error:self.note.set(str(error))
 def poll(self):
  self.poll_job=None
  while not self.events.empty():
   event=self.events.get_nowait();text=event.get('text','')
   if text:
    self.note.set(text);self.output.configure(state='normal');self.output.insert('end',text+'\n');self.output.see('end');self.output.configure(state='disabled')
  if self.running():self.poll_job=self.after(100,self.poll)
 def pause(self):
  if self.running():
   if self.live_runner.paused.is_set():self.live_runner.resume()
   else:self.live_runner.pause()
 def stop(self):
  if self.live_runner:self.live_runner.stop()
 def close(self):
  self.stop()
  if self.poll_job:self.after_cancel(self.poll_job)
  self.destroy()

def open_task(app,mode):
 previous=getattr(app,'task_replay_window',None)
 if previous is not None and previous.winfo_exists():
  if isinstance(previous,NativeTaskWindow):
   previous.mode.set(MODES[mode]);previous.switch();previous.lift();return previous
  if previous.live_runner is not None and previous.live_runner.alive():previous.lift();return previous
  previous.destroy()
 window=NativeTaskWindow(app,mode);app.task_replay_window=window;return window
