"""Compact two-column character calculator with artifact and imprint profiles."""
import json,tkinter as tk
from tkinter import ttk,messagebox,filedialog
from character_bs import KEYS,SET_SIZE,calculate_bs
from core import LABELS
from ui_theme import BG,CARD,TEXT,MUTED,ACCENT,FONT

class BSWindow(tk.Toplevel):
 def __init__(self,app):
  super().__init__(app);self.app=app;self.hero_id=None;self.equipped_data=None;self._gear_refresh_job=None;self._filling=False;self.artifact_code=None
  self.title('角色总分计算 · Fribbels');self.configure(bg=BG)
  self.geometry(f'{min(1040,self.winfo_screenwidth()-50)}x{min(740,self.winfo_screenheight()-85)}');self.minsize(min(980,self.winfo_screenwidth()-50),min(650,self.winfo_screenheight()-85))
  head=ttk.Frame(self,padding=(24,18));head.pack(fill='x')
  self.hero_label=ttk.Label(head,text='先选择角色',font=(FONT,14,'bold'));self.hero_label.pack(side='left')
  more=ttk.Menubutton(head,text='更多 ▾',style='Compact.TButton');more.pack(side='right')
  self.actions_menu=tk.Menu(more,tearoff=False,bg=CARD,fg=TEXT,activebackground=ACCENT,activeforeground=TEXT)
  more.configure(menu=self.actions_menu)
  self.actions_menu.add_command(label='选择角色…',command=app.choose_hero)
  ttk.Button(head,text='读取角色 F8',style='Accent.TButton',command=self.read_panel).pack(side='right',padx=8)
  self.bind('<F8>',lambda _:self.read_panel())
  scorebox=ttk.Frame(self,padding=(24,8));scorebox.pack(fill='x')
  self.gear_result=tk.StringVar(value='装备总分 —');self.gear_status=tk.StringVar(value='需导入当前角色六件完整的已装备数据')
  self.result=tk.StringVar(value='角色总分 —')
  self.gear_score_label=ttk.Label(scorebox,textvariable=self.result,font=(FONT,30,'bold'),foreground='#55d7a0');self.gear_score_label.pack(side='left')
  ttk.Label(self,text='Fribbels BS · 读取角色面板、套装、神器与刻印后自动计算',foreground=MUTED).pack(anchor='w',padx=12,pady=(0,14))
  footer=ttk.Frame(self,padding=(12,8));footer.pack(side='bottom',fill='x')
  ttk.Label(footer,text='F8 读取角色 · 数据变化后自动更新总分',foreground=MUTED).pack(side='left')
  self.confirmed=tk.BooleanVar(value=False)
  self.body=ttk.Frame(self,padding=(24,8));self.body.pack(fill='both',expand=True)
  self.body.columnconfigure(0,weight=6);self.body.columnconfigure(1,weight=4);self.body.rowconfigure(0,weight=1)
  left=ttk.Frame(self.body);left.grid(row=0,column=0,sticky='nsew',padx=(0,12))
  right=ttk.Frame(self.body);right.grid(row=0,column=1,sticky='nsew')
  ttk.Label(left,text='角色面板',font=(FONT,12,'bold')).pack(anchor='w',pady=(0,8))
  grid=ttk.Frame(left,padding=10);grid.pack(fill='x',pady=(0,10))
  self.correction_window=tk.Toplevel(self);self.correction_window.title('基础与额外校正');self.correction_window.configure(bg=BG);self.correction_window.withdraw()
  self.correction_window.protocol('WM_DELETE_WINDOW',self.correction_window.withdraw)
  advanced=ttk.Frame(self.correction_window,padding=18);advanced.pack(fill='both',expand=True)
  self.actions_menu.add_command(label='基础与额外校正…',command=self.correction_window.deiconify)
  self.panel={};self.base={};self.corrections={}
  for parent,titles in ((grid,('属性','当前数值')),(advanced,('属性','基础 / 被动','额外加成'))):
   for col,title in enumerate(titles):
    ttk.Label(parent,text=title,font=(FONT,9)).grid(row=0,column=col,sticky='w',padx=6,pady=6);parent.columnconfigure(col,weight=1 if col else 0)
  for row,key in enumerate(KEYS,1):
   for parent in (grid,advanced):ttk.Label(parent,text=LABELS[key],font=(FONT,9)).grid(row=row,column=0,sticky='w',padx=6,pady=5)
   for col,dest in enumerate((self.panel,self.base,self.corrections),1):
    var=tk.StringVar(value='0' if col==3 else '');dest[key]=var
    ttk.Entry(grid if col==1 else advanced,textvariable=var,width=10,style='Compact.TEntry').grid(row=row,column=1 if col==1 else col-1,sticky='ew',padx=6,pady=5)
    var.trace_add('write',lambda *_:self.invalidate())
  ttk.Label(left,text='已激活套装（可重复选择两件套）',font=(FONT,9)).pack(anchor='w',pady=(9,3));sets=ttk.Frame(left);sets.pack(fill='x');self.sets=[]
  for i in range(3):
   var=tk.StringVar(value='无');self.sets.append(var);ttk.Combobox(sets,textvariable=var,values=['无',*SET_SIZE],state='readonly',width=9,style='Compact.TCombobox').pack(side='left',fill='x',expand=True,padx=3);var.trace_add('write',lambda *_:self.invalidate())
  ttk.Label(left,text='额外加成按最终面板单位扣除。特殊被动请校正基础值。',foreground=MUTED,font=(FONT,9),wraplength=540).pack(fill='x',pady=7)
  self.details=tk.StringVar(value='未读取角色面板。');ttk.Label(left,textvariable=self.details,wraplength=540,justify='left',font=(FONT,9)).pack(fill='x')
  self.addon_heading=tk.StringVar(value='神器')
  ttk.Label(right,textvariable=self.addon_heading,font=(FONT,12,'bold')).pack(anchor='w',pady=(0,8))
  ttk.Style(self).layout('Quiet.TNotebook.Tab',[])
  self.addon_tabs=ttk.Notebook(right,style='Quiet.TNotebook');self.addon_tabs.pack(fill='both',expand=True)
  art=ttk.Frame(self.addon_tabs,padding=10);imp=ttk.Frame(self.addon_tabs,padding=10)
  equipment=ttk.Frame(self.addon_tabs,padding=10)
  self.addon_tabs.add(art,text='神器');self.addon_tabs.add(imp,text='刻印');self.addon_tabs.add(equipment,text='六件装备 GS')
  self.actions_menu.add_separator()
  for title,page in (('神器',art),('刻印',imp),('六件装备 GS',equipment)):
   self.actions_menu.add_command(label='查看'+title,command=lambda p=page,t=title:(self.addon_tabs.select(p),self.addon_heading.set(t)))
  self.actions_menu.add_separator()
  self.actions_menu.add_command(label='神器全部等级数值…',command=self.show_artifact_levels)
  self.actions_menu.add_command(label='导入已装备 JSON…',command=self.import_equipped)
  ttk.Label(equipment,textvariable=self.gear_result,font=(FONT,18,'bold')).pack(anchor='w',pady=8)
  ttk.Label(equipment,textvariable=self.gear_status,wraplength=360).pack(fill='x',pady=8)
  from character_loadout import artifacts
  catalog=json.loads((__import__('pathlib').Path(__file__).parent/'data/artifact-catalog.json').read_text('utf8'))['artifacts']
  self.artifact_names={catalog.get(code,{}).get('name',record['name_en']):code for code,record in artifacts().items()}
  self.artifact_name=tk.StringVar(value='未确认');self.artifact_level=tk.StringVar(value='')
  ttk.Label(art,text='神器（可输入中文名称或下拉选择）',font=(FONT,9)).pack(anchor='w')
  name=ttk.Combobox(art,textvariable=self.artifact_name,values=['未确认','已卸下',*sorted(self.artifact_names)],style='Compact.TCombobox');name.pack(fill='x',pady=(3,8));name.bind('<<ComboboxSelected>>',lambda _:self.select_artifact())
  level=ttk.Frame(art);level.pack(fill='x');ttk.Label(level,text='强化等级 +').pack(side='left')
  ttk.Combobox(level,textvariable=self.artifact_level,values=['',*map(str,range(31))],state='readonly',width=5,style='Compact.TCombobox').pack(side='left',padx=6)
  self.artifact={};row=ttk.Frame(art);row.pack(fill='x',pady=10)
  for key,label in (('atk','神器攻击'),('hp','神器生命')):
   cell=ttk.Frame(row);cell.pack(side='left',fill='x',expand=True,padx=2);ttk.Label(cell,text=label).pack(anchor='w')
   var=tk.StringVar(value='');self.artifact[key]=var;ttk.Entry(cell,textvariable=var,width=11,style='Compact.TEntry').pack(fill='x');var.trace_add('write',lambda *_:self.invalidate())
  self.artifact_growth=tk.StringVar(value='识别神器和实际强化等级后自动填写白字。')
  ttk.Label(art,textvariable=self.artifact_growth,wraplength=380,justify='left',foreground=MUTED,font=(FONT,9)).pack(fill='x',pady=5)
  self.artifact_level.trace_add('write',lambda *_:self.update_artifact_stats() if not self._filling else None)
  self.loadout_status=tk.StringVar(value='套装、神器和刻印待识别。')
  ttk.Label(art,textvariable=self.loadout_status,wraplength=380,justify='left',foreground=MUTED,font=(FONT,9)).pack(fill='x',pady=7)
  ttk.Separator(art,orient='horizontal').pack(fill='x',pady=(10,12))
  ttk.Label(art,text='当前刻印',font=(FONT,12,'bold')).pack(anchor='w',pady=(0,8))
  controls=ttk.Frame(art);controls.pack(fill='x');self.imprint_controls=controls;self.imprint_mode=tk.StringVar(value='待确认');self.imprint_rank=tk.StringVar(value='')
  ttk.Combobox(controls,textvariable=self.imprint_mode,values=['待确认','锁定 / 未刻印','开放型刻印','自身刻印'],state='readonly',width=15,style='Compact.TCombobox').pack(side='left',fill='x',expand=True)
  ttk.Combobox(controls,textvariable=self.imprint_rank,values=['','D','C','B','A','S','SS','SSS'],state='readonly',width=5,style='Compact.TCombobox').pack(side='left',padx=(6,0))
  self.imprint_status=tk.StringVar(value='读取当前刻印类型与等级；也可手动核对。')
  self.imprint_summary=ttk.Label(art,textvariable=self.imprint_status,wraplength=380,font=(FONT,9));self.imprint_summary.pack(fill='x',pady=7)
  ttk.Label(imp,textvariable=self.imprint_status,wraplength=380,font=(FONT,9)).pack(fill='x',pady=7)
  style=ttk.Style(self);style.configure('Imprint.Treeview',rowheight=24,font=(FONT,9))
  self.imprint_table=ttk.Treeview(imp,columns=('rank','team','self'),show='headings',height=7,style='Imprint.Treeview')
  for key,label,width in (('rank','等级',45),('team','开放型刻印',145),('self','自身刻印',145)):
   self.imprint_table.heading(key,text=label);self.imprint_table.column(key,width=width,anchor='center',stretch=True)
  self.imprint_table.pack(fill='x')
  self.imprint_source=tk.StringVar();ttk.Label(imp,textvariable=self.imprint_source,wraplength=380,font=(FONT,8),foreground=MUTED).pack(fill='x',pady=7)
  ttk.Label(imp,text='开放型刻印作用于队友，不扣本角色面板。等级表只列出可选值；当前启用类型和等级需单独识别。',wraplength=380,font=(FONT,9),foreground=MUTED).pack(fill='x')
  self.imprint_mode.trace_add('write',lambda *_:self.apply_imprint() if not self._filling else None)
  self.imprint_rank.trace_add('write',lambda *_:self.apply_imprint() if not self._filling else None)
  self._imprint_correction=None
  hero=next((h for h in app.hero_catalog['heroes'] if h['id']==app.selected_hero_id),None)
  if hero:self.set_hero(hero)
  if self.hero_id is not None and getattr(app,'last_character_hero_id',None)==self.hero_id and hasattr(app,'last_character_panel'):
   self.fill_panel(app.last_character_panel)
   if hasattr(app,'last_character_loadout'):self.fill_loadout(app.last_character_loadout)

 def current_hero(self):return next((h for h in self.app.hero_catalog['heroes'] if h['id']==self.hero_id),None)
 def select_artifact(self):
  self.artifact_code=self.artifact_names.get(self.artifact_name.get());self.update_artifact_stats()
 def update_artifact_stats(self):
  from character_loadout import artifact_stats,artifacts
  if self.artifact_name.get()=='已卸下':
   for var in self.artifact.values():var.set('0')
   self.artifact_growth.set('已卸下神器，攻击和生命均为0。');return
  try:
   if not self.artifact_code:raise ValueError('神器未确认，请核对名称或手填白字。')
   level=int(self.artifact_level.get());stats=artifact_stats(self.artifact_code,level)
   for key,var in self.artifact.items():var.set(f'{stats[key]:g}')
   base=artifacts()[self.artifact_code]
   text=f'+0基础：攻击 {base["atk"]:g} / 生命 {base["hp"]:g}\n每级：攻击 +{base["atk"]*.4:g} / 生命 +{base["hp"]*.4:g}\n当前 +{level}：攻击 {stats["atk"]:g} / 生命 {stats["hp"]:g}'
   if level<30:
    following=artifact_stats(self.artifact_code,level+1)
    text+=f'\n下一级：攻击 +{following["atk"]-stats["atk"]:.1f} / 生命 +{following["hp"]-stats["hp"]:.1f}'
   self.artifact_growth.set(text)
  except (ValueError,TypeError) as error:
   for var in self.artifact.values():var.set('')
   self.artifact_growth.set('强化等级待确认，不默认+30。' if self.artifact_code else str(error))
 def show_artifact_levels(self):
  if not self.artifact_code:self.artifact_growth.set('请先识别或选择神器。');return
  from character_loadout import artifact_progression
  win=tk.Toplevel(self);win.title(self.artifact_name.get()+' · 每级攻击与生命');win.geometry(f'{min(920,self.winfo_screenwidth()-60)}x{min(560,self.winfo_screenheight()-90)}')
  ttk.Label(win,text='各级白字与相对上一级的实际增量（保留一位小数）',padding=10).pack(fill='x')
  area=ttk.Frame(win,padding=10);area.pack(fill='both',expand=True)
  rows=artifact_progression(self.artifact_code)
  for subset in (rows[:16],rows[16:]):
   table=ttk.Treeview(area,columns=('level','atk','hp','delta_atk','delta_hp'),show='headings',height=16,style='Imprint.Treeview');table.pack(side='left',fill='both',expand=True,padx=4)
   for key,label in [('level','等级'),('atk','攻击'),('hp','生命'),('delta_atk','攻击增量'),('delta_hp','生命增量')]:table.heading(key,text=label);table.column(key,width=70,anchor='center')
   for row in subset:table.insert('', 'end', values=[f'{row[key]:g}' for key in ('level','atk','hp','delta_atk','delta_hp')])
 def refresh_imprints(self):
  from hero_imprints import profiles,RANKS
  records=profiles(self.current_hero());self.imprint_table.delete(*self.imprint_table.get_children())
  def value(mode,rank):
   row=records.get(mode,{})
   if rank not in row.get('grades',{}):return '—'
   return LABELS.get(row['key'],'夹攻率').rstrip('%')+f' +{row["grades"][rank]:g}'+('%' if row['percent'] else '')
  for rank in RANKS:self.imprint_table.insert('', 'end',values=(rank,value('team',rank),value('self',rank)))
  self.imprint_source.set('；'.join(('开放型' if mode=='team' else '自身')+'：'+records.get(mode,{}).get('source','暂无本地资料，需读取详情') for mode in ('team','self')))
 def apply_imprint(self):
  from hero_imprints import MODES,imprint_value
  if self._imprint_correction:
   key,old=self._imprint_correction
   if key in self.corrections and self.corrections[key].get()==old:self.corrections[key].set('0')
  self._imprint_correction=None
  mode=next((key for key,label in MODES.items() if label==self.imprint_mode.get()),'unknown');rank=self.imprint_rank.get()
  row=imprint_value(self.current_hero(),mode,rank)
  if mode=='locked':self.imprint_status.set('当前刻印锁定 / 未刻印，不计入加成。')
  elif mode=='team':self.imprint_status.set('当前为开放型刻印，作用于队友，不扣本角色面板。')
  elif row and mode=='self':
   value=row['value'];key=row['key']
   if row['percent'] and key in ('atk','hp','def'):
    try:value=float(self.base[key].get())*value/100
    except ValueError:self.imprint_status.set('基础值未填全，刻印换算待确认。');return
   if key in self.corrections:
    self.corrections[key].set(f'{value:g}');self._imprint_correction=(key,f'{value:g}')
   self.imprint_status.set(f'自身刻印 {rank}：'+LABELS.get(key,'夹攻率').rstrip('%')+f' +{row["value"]:g}'+('%' if row['percent'] else '')+f'；面板扣除 {value:g}')
  else:self.imprint_status.set('刻印类型 / 等级 / 本地数值未确定，请读取详情或手动核对。')
  self.invalidate()
 def invalidate(self):
  self.result.set('角色总分 —')
  if hasattr(self,'confirmed'):self.confirmed.set(False)
  if self._gear_refresh_job is None:self._gear_refresh_job=self.after_idle(self.refresh_equipped)
  if hasattr(self.app,'character_bs_label'):self.app.character_bs_label.configure(text='角色 BS — · 面板或加成待核对')
 def refresh_equipped(self):
  self._gear_refresh_job=None
  if not self._filling:self.calculate()
  if self.equipped_data is None:
   self.gear_result.set('装备总分 —');self.gear_status.set('需要当前角色六件完整的已装备数据');return None
  try:
   from character_loadout import equipped_total
   hero=next(h for h in self.app.hero_catalog['heroes'] if h['id']==self.hero_id)
   panel={key:float(self.panel[key].get()) for key in ('crit','cdmg')}
   record=equipped_total(self.equipped_data,hero,panel)
   self.gear_result.set(f'装备总分  {record["gear_score"]}')
   self.gear_status.set('已导入装备快照 · '+ ' / '.join(f'{row["slot"]} {row["score"]}' for row in record['item_scores'])+'\n'+f'副属性合计 {record["uncapped_score"]} − 暴率溢出 {record["crit_penalty"]:g} − 暴伤溢出 {record["cdmg_penalty"]:g}，向上取整')
   return record
  except (ValueError,TypeError,StopIteration) as error:
   self.gear_result.set('装备总分 —');self.gear_status.set('未计算：'+str(error));return None
 def read_panel(self):
  if self.app.busy:return
  task=getattr(self.app,'task_replay_window',None)
  if task is not None and task.winfo_exists() and task.live_runner is not None and task.live_runner.alive():
   self.details.set('请先停止自动任务，再读取角色面板。');return
  from desktop_capture import find_game_windows
  from tkinter import simpledialog
  windows=find_game_windows()
  if not windows:self.details.set('未找到第七史诗窗口，请打开游戏角色面板。');return
  index=0
  if len(windows)>1:
   chosen=simpledialog.askinteger('选择游戏窗口','\n'.join(f'{i+1}. {w["title"]} PID {w["pid"]}' for i,w in enumerate(windows)),minvalue=1,maxvalue=len(windows),parent=self)
   if chosen is None:return
   index=chosen-1
  self.details.set('正在后台读取游戏角色面板、套装与神器…')
  self.app.start_scan({'window':windows[index],'mode':'single','character_read':True,'hero_id':self.hero_id})
 def set_hero(self,hero):
  if self.hero_id==hero['id']:return
  self._filling=True
  self.hero_id=hero['id'];self.equipped_data=None;self.hero_label.configure(text=hero['name']+' · 角色总分')
  self.gear_result.set('装备总分 —')
  self.loadout_status.set('套装、神器和刻印待识别。')
  for key in KEYS:self.base[key].set(str(hero['base'].get(key,0)));self.panel[key].set('');self.corrections[key].set('0')
  for var in self.sets:var.set('无')
  for var in self.artifact.values():var.set('')
  self.artifact_code=None;self.artifact_name.set('待识别神器');self.artifact_level.set('')
  self.artifact_growth.set('识别神器和实际强化等级后自动填写白字。')
  self.imprint_mode.set('待确认');self.imprint_rank.set('');self._imprint_correction=None
  self.refresh_imprints();self.imprint_status.set('当前刻印类型与等级待识别。');self._filling=False
  self.confirmed.set(False);self.invalidate()
 def fill_panel(self,panel):
  # A new capture may show changed equipment, so an old export is no longer current.
  self.equipped_data=None
  for key,var in self.panel.items():var.set(str(panel[key]) if key in panel else '')
  self.confirmed.set(False);self.details.set('已填入 OCR 白字面板；请逐项核对，不完整项需要手填。')
 def fill_loadout(self,data):
  self._filling=True;self._imprint_correction=None
  for var in self.corrections.values():var.set('0')
  for index,var in enumerate(self.sets):var.set(data.get('sets',[])[index] if index<len(data.get('sets',[])) else '无')
  artifact=data.get('artifact') or {}
  self.artifact_code=artifact.get('code');self.artifact_name.set(artifact.get('name','待识别神器'))
  self.artifact_level.set(str(artifact['level']) if artifact.get('level') is not None else '')
  for key,var in self.artifact.items():var.set(str(artifact[key]) if key in artifact else '')
  imprint=data.get('imprint')
  if imprint and imprint.get('scope')=='self':
   key=imprint['key'];value=imprint['value']
   if imprint.get('percent') and key in ('atk','hp','def'):
    try:value=float(self.base[key].get())*value/100
    except ValueError:value=None
   if key in self.corrections:
    self.corrections[key].set('' if value is None else str(value));self._imprint_correction=(key,self.corrections[key].get())
  name=artifact.get('name','神器待确认');level=artifact.get('level')
  imprint_text='刻印待确认'
  if imprint and imprint.get('scope')=='self':imprint_text='刻印集中：'+LABELS[imprint['key']].rstrip('%')+f' +{imprint["value"]:g}'+('%' if imprint.get('percent') else '')
  self.loadout_status.set(name+(f' +{level}' if level is not None else ' · 等级待确认')+'\n'+imprint_text+'\n'+'；'.join(data.get('warnings',[])))
  profiles=data.get('imprint_profiles')
  if profiles and self.current_hero():
   from hero_imprints import save_profiles
   try:save_profiles(self.app.user_dir/'hero-imprints.json',self.current_hero(),profiles)
   except (OSError,ValueError):self.imprint_source.set('刻印表保存失败，请重新读取。')
  from hero_imprints import MODES
  state=data.get('imprint_state') or {}
  self.imprint_mode.set(MODES.get(state.get('mode'),'待确认'));self.imprint_rank.set(state.get('rank') or '')
  self.refresh_imprints();self.imprint_status.set(state.get('reason','当前刻印类型和等级待确认。'))
  self._filling=False
  if self.artifact_code or self.artifact_name.get()=='已卸下':self.update_artifact_stats()
  else:self.artifact_growth.set('神器或强化等级待识别；也可手动核对白字。')
  if state.get('mode')=='locked' or state.get('mode') in ('team','self') and state.get('rank'):self.apply_imprint()
  self.confirmed.set(False)
 def import_equipped(self):
  path=filedialog.askopenfilename(parent=self,filetypes=[('Fribbels JSON','*.json')])
  if not path:return
  try:
   from local_json import read_json
   from character_loadout import equipped_total
   hero=next(h for h in self.app.hero_catalog['heroes'] if h['id']==self.hero_id)
   panel={key:float(self.panel[key].get()) for key in ('crit','cdmg')}
   data=read_json(path);equipped_total(data,hero,panel)
   self.equipped_data=data;self.refresh_equipped()
  except (OSError,ValueError,TypeError,StopIteration) as error:
   messagebox.showerror('导入未完成',str(error),parent=self)
 def calculate(self):
  try:
   if not self.hero_id:raise ValueError('请先选择角色')
   result=calculate_bs({k:float(v.get()) for k,v in self.panel.items()},{k:float(v.get()) for k,v in self.base.items()},[v.get() for v in self.sets],{k:float(v.get()) for k,v in self.artifact.items()},{k:float(v.get()) for k,v in self.corrections.items()})
   self.result.set(f'角色总分 {result["bs"]}');self.details.set('Fribbels BS 原始值 '+f'{result["raw_score"]:.3f}'+'（向下取整）\n'+'；'.join(LABELS[k]+f'：{v:.3f}分' for k,v in result['contributions'].items()))
   self.app.character_bs_label.configure(text=f'角色配装分 BS {result["bs"]} · 自动计算')
  except (ValueError,TypeError) as error:
   self.result.set('角色总分 —')
   self.details.set('自动计算等待完整数据：'+str(error))
 def destroy(self):
  if self._gear_refresh_job is not None:
   try:self.after_cancel(self._gear_refresh_job)
   except tk.TclError:pass
   self._gear_refresh_job=None
  super().destroy()
def open_bs(app):
 window=getattr(app,'character_bs_window',None)
 if window is None or not window.winfo_exists():window=BSWindow(app);app.character_bs_window=window
 else:
  hero=next((h for h in app.hero_catalog['heroes'] if h['id']==app.selected_hero_id),None)
  if hero:window.set_hero(hero)
  window.deiconify();window.lift()
 return window
