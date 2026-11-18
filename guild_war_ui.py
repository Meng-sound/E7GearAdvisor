"""Read-only PC guild-war recognition and public attack reference window."""
import json,queue,threading,tkinter as tk,webbrowser
from pathlib import Path
from tkinter import ttk,filedialog,messagebox
from PIL import Image,ImageTk,ImageOps,ImageDraw
from desktop_capture import find_game_windows,select_game_rectangle
from hero_picker import HeroPicker
from e7gw_source import fetch_e7gw,counters_url
from ep7_gw_source import fetch_ep7,client_key,ORIGIN as EP7_ORIGIN
from e7wiki_source import fetch_e7wiki,ORIGIN as E7WIKI_ORIGIN
from guild_combined import fetch_combined
from guild_filters import attack_rows,guide_rows
from guild_war import fetch_ark,fetch_fribbels,team_key,ARK_SOURCE,fribbels_team_url

BG='#171b23';CARD='#202630';TEXT='#edf3fb';MUTED='#93a6bd';ACCENT='#8adfce';RED='#ff9b9b';FONT='Microsoft YaHei UI'
DATA=Path(__file__).parent/'data'

class GuildWarWindow(tk.Toplevel):
 def __init__(self,parent):
  super().__init__(parent);self.app=parent;self.catalog=parent.hero_catalog;self.heroes={h['id']:h for h in self.catalog['heroes']};self.photos={};self.tasks=queue.Queue();self.busy=False;self.matcher=None;self.records={}
  parent.update_idletasks();main_width=parent.winfo_width()
  if getattr(parent,'candidate_sidebar',None) is not None and parent.candidate_sidebar.winfo_ismapped():main_width-=parent.candidate_sidebar.winfo_width()
  width=min(max(390,main_width)*2,self.winfo_screenwidth()-24);height=min(max(640,parent.winfo_height()),self.winfo_screenheight()-65)
  self.title('团战进攻参考');self.configure(bg=BG);self.geometry(f'{width}x{height}');self.minsize(780,640)
  self.provider=tk.StringVar(value='综合查询');self.minimum=tk.IntVar(value=5);self.sort=tk.StringVar(value='样本数');self.status=tk.StringVar(value='识别或导入备战图后自动搜索；手动改角色后点击查询。')
  header=tk.Frame(self,bg=BG);header.pack(fill='x',padx=12,pady=(8,6));tk.Label(header,text='团战进攻参考',font=(FONT,14,'bold'),bg=BG,fg=TEXT).pack(side='left')
  ttk.Button(header,text='识别敌方阵容',style='Read.TButton',command=self.capture).pack(side='right');ttk.Button(header,text='导入截图',style='Compact.TButton',command=self.open_image).pack(side='right',padx=6)
  more=ttk.Menubutton(header,text='更多 ▾',style='Compact.TButton');more.pack(side='right');menu=tk.Menu(more,tearoff=False,bg=CARD,fg=TEXT);more.configure(menu=menu);menu.add_command(label='登记本地皮肤头像模板',command=self.register_portrait);menu.add_command(label='更新官方皮肤模板（仅缺失/变化）',command=self.update_skin_templates);menu.add_command(label='暂停皮肤更新 / 保存进度',command=self.cancel_skin_update);menu.add_command(label='当前来源原站查询 · 上半场',command=lambda:self.open_original(0));menu.add_command(label='当前来源原站查询 · 下半场',command=lambda:self.open_original(1));menu.add_command(label='配装器接口',command=self.app.open_optimizer_interface);menu.add_command(label='数据来源',command=lambda:webbrowser.open('https://e7gw.xyz' if self.provider.get()=='E7GW' else 'https://fribbels.github.io/e7/gw-meta.html' if self.provider.get().startswith('Fribbels') else ARK_SOURCE['origin']))
  menu.entryconfigure('数据来源',command=self.open_source)
  menu.add_separator();menu.add_command(label='百里 E7BOT 网页查询（需登录）',command=lambda:webbrowser.open('https://www.e7bot.top/#/e7/gvg'));menu.add_command(label='百里 Discord 团战命令指南',command=lambda:webbrowser.open('https://discord.com/channels/1133903405262327859/1396418865197744190/threads/1396430604836536433'))
  controls=tk.Frame(self,bg=BG);controls.pack(fill='x',padx=12,pady=(0,8));ttk.Combobox(controls,textvariable=self.provider,values=['综合查询','E7WIKI 在线作业','E7GW','EP7 公开战报','Fribbels 历史战报','Ark 公开战报'],state='readonly',width=16).pack(side='left');ttk.Button(controls,text='查询两场',style='Compact.TButton',command=self.query).pack(side='left',padx=6);tk.Label(controls,text='最小样本',bg=BG,fg=MUTED,font=(FONT,9)).pack(side='left',padx=(6,4));ttk.Spinbox(controls,from_=1,to=100000,textvariable=self.minimum,width=5,command=self.render).pack(side='left');ttk.Combobox(controls,textvariable=self.sort,values=['样本数','胜率'],state='readonly',width=7).pack(side='left',padx=6)
  self.query_controls=controls;self.update_source_controls()
  self.unique=tk.BooleanVar(value=True);self.selected_teams=[(),()];self.include=set();self.exclude=set();self.round_feedback={}
  filters=tk.Frame(self,bg=BG);filters.pack(fill='x',padx=12,pady=(0,7))
  ttk.Checkbutton(filters,text='两队进攻不重复英雄',variable=self.unique,command=self.unique_changed).pack(side='left')
  self.gate_button=ttk.Button(filters,text='分数门槛',style='Compact.TButton',command=self.app.open_threshold_config);self.gate_button.pack(side='left',padx=6)
  ttk.Button(filters,text='包含英雄',style='Compact.TButton',command=lambda:self.add_filter(False)).pack(side='left')
  ttk.Button(filters,text='排除英雄',style='Compact.TButton',command=lambda:self.add_filter(True)).pack(side='left',padx=5)
  ttk.Button(filters,text='清除筛选',style='Compact.TButton',command=self.clear_filters).pack(side='left')
  self.filter_label=tk.Label(self,text='点击进攻头像选用整队；另一场排除这队英雄。右键查看角色参考。',bg=BG,fg=MUTED,font=(FONT,8),anchor='w',wraplength=850);self.filter_label.pack(fill='x',padx=12,pady=(0,5))
  selected=tk.Frame(self,bg=CARD);selected.pack(fill='x',padx=12,pady=(0,6));self.selection_summary=tk.Text(selected,height=3,wrap='word',font=(FONT,9),bg=CARD,fg='#b9cfff',relief='flat',state='disabled');bar=ttk.Scrollbar(selected,command=self.selection_summary.yview);bar.pack(side='right',fill='y');self.selection_summary.configure(yscrollcommand=bar.set);self.selection_summary.pack(fill='x',expand=True)
  self.refresh_filter_label()
  self.ids=[[None]*3 for _ in range(2)];self.slot_buttons=[[],[]];self.slot_notes=[[],[]];self.boards=[];self.canvases=[];self.data_captions=[];self.panes=[];self.defense_totals=[];self.result_titles=[];self.result_limits=[20,20]
  columns=tk.Frame(self,bg=BG);columns.pack(fill='both',expand=True,padx=8,pady=(0,4));columns.columnconfigure(0,weight=1,uniform='round');columns.columnconfigure(1,weight=1,uniform='round');columns.rowconfigure(0,weight=1)
  for index,title in enumerate(('上半场','下半场')):
   pane=tk.Frame(columns,bg=CARD,padx=6,pady=5);pane.grid(row=0,column=index,sticky='nsew',padx=(0,3) if index==0 else (3,0));self.panes.append(pane)
   heading=tk.Frame(pane,bg=CARD);heading.pack(fill='x');tk.Label(heading,text=title+' · 防守队伍',font=(FONT,11,'bold'),bg=CARD,fg=TEXT).pack(side='left');ttk.Button(heading,text='更新战报',style='Compact.TButton',command=lambda r=index:self.query(index=r,force=True)).pack(side='right');ttk.Button(heading,text='查询',style='Compact.TButton',command=lambda r=index:self.query(index=r)).pack(side='right',padx=6)
   defense=tk.Frame(pane,bg=CARD);defense.pack(fill='x',pady=(6,4))
   totals=tk.Frame(defense,bg=CARD,width=98);totals.pack(side='right',fill='y',padx=(4,0));totals.pack_propagate(False);self.defense_totals.append(totals)
   slots=tk.Frame(defense,bg=CARD);slots.pack(side='left',fill='both',expand=True)
   for slot in range(3):
    slots.columnconfigure(slot,weight=1,uniform='slot');cell=tk.Frame(slots,bg=CARD);cell.grid(row=0,column=slot,sticky='nsew',padx=2)
    button=tk.Button(cell,text='选择英雄',compound='top',bg=CARD,fg=TEXT,activebackground='#29394d',activeforeground=TEXT,relief='flat',command=lambda r=index,s=slot:self.pick(r,s),font=(FONT,8),wraplength=82,padx=0,pady=0);button.pack(fill='x');self.slot_buttons[index].append(button)
    button.bind('<Button-3>',lambda e,r=index,s=slot:self.show_hero_reference(self.heroes.get(self.ids[r][s])))
    note=tk.Label(cell,text='',bg=CARD,fg=MUTED,font=(FONT,7),wraplength=82);self.slot_notes[index].append(note)
   caption=tk.Label(pane,text='请确认三名防守英雄',bg=CARD,fg=MUTED,font=(FONT,8),anchor='w',justify='left',wraplength=500);caption.pack(fill='x',pady=(0,5));self.data_captions.append(caption)
   divider=tk.Frame(pane,bg='#46505a',height=1);divider.pack(fill='x')
   title_label=tk.Label(pane,text='网友进攻',bg=CARD,fg='#c9b78e',font=(FONT,10,'bold'),anchor='w');title_label.pack(fill='x',pady=(4,3));self.result_titles.append(title_label)
   area=tk.Frame(pane,bg=CARD);area.pack(fill='both',expand=True);bar=ttk.Scrollbar(area);bar.pack(side='right',fill='y');canvas=tk.Canvas(area,bg=CARD,highlightthickness=0,yscrollcommand=bar.set);canvas.pack(fill='both',expand=True);bar.configure(command=canvas.yview);board=tk.Frame(canvas,bg=CARD);item=canvas.create_window(0,0,window=board,anchor='nw');canvas.bind('<Configure>',lambda e,c=canvas,w=item,label=caption:(c.itemconfigure(w,width=e.width),label.configure(wraplength=max(200,e.width))));board.bind('<Configure>',lambda e,c=canvas:c.configure(scrollregion=c.bbox('all')));self.boards.append(board);self.canvases.append(canvas)
  self.bind('<MouseWheel>',self.scroll_round)
  self.sort.trace_add('write',lambda *_:self.render());self.minimum.trace_add('write',lambda *_:self.render());self.provider.trace_add('write',lambda *_:self.source_changed())
  self.status_widget=ttk.Label(self,textvariable=self.status,wraplength=width-24,font=(FONT,8));self.status_widget.pack(fill='x',padx=12,pady=(0,3));tk.Label(self,text='胜负为进攻方视角；跨队去重按英雄本体判断（含皮肤）。注意来源日期和当前筛选条件。',bg=BG,fg=MUTED,font=(FONT,8)).pack(anchor='w',padx=12,pady=(0,6));self.app.after(150,self.poll)
  self.bind('<Configure>',lambda e:(self.status_widget.configure(wraplength=max(300,e.width-24)),self.filter_label.configure(wraplength=max(300,e.width-24))) if e.widget is self else None,add='+')
  self.protocol('WM_DELETE_WINDOW',self.close_window);self.render()
 def close_window(self):
  self.cancel_skin_update();self.hide_name()
  for picker in (getattr(self,'filter_picker',None),getattr(self,'picker',None)):
   if picker is not None and picker.winfo_exists():picker.destroy()
  self.destroy()
 def open_source(self):
  provider=self.provider.get()
  if provider=='综合查询':messagebox.showinfo('综合查询来源','E7GW、EP7 公开战报、Ark 公开战报、Fribbels 历史战报、E7WIKI 在线作业。\n同队按单一来源最大样本数排序，各来源场次不累加；历史数据与投稿作业单独标明。',parent=self);return
  if provider.startswith('E7WIKI'):webbrowser.open(E7WIKI_ORIGIN);return
  webbrowser.open('https://e7gw.xyz' if provider=='E7GW' else EP7_ORIGIN+'/en/meta' if provider.startswith('EP7') else 'https://fribbels.github.io/e7/gw-meta.html' if provider.startswith('Fribbels') else ARK_SOURCE['origin'])
 def open_original(self,index):
  if self.provider.get()=='综合查询' or self.provider.get().startswith(('E7WIKI','EP7','Ark')):self.open_source();return
  try:url=counters_url(self.current_defense(index),self.catalog) if self.provider.get()=='E7GW' else fribbels_team_url(self.current_defense(index),self.catalog)
  except (ValueError,KeyError):self.status.set('请先选择并确认本场三个不同的防守英雄。');return
  webbrowser.open(url)
 def unique_changed(self):
  if self.unique.get() and set(self.selected_teams[0]).intersection(self.selected_teams[1]):self.selected_teams[1]=()
  self.refresh_filter_label();self.render()
 def select_attack(self,index,heroes):
  team=team_key(heroes);self.selected_teams[index]=() if team==self.selected_teams[index] else team
  if self.unique.get() and set(self.selected_teams[index]).intersection(self.selected_teams[1-index]):self.selected_teams[1-index]=()
  self.status.set(('上半场' if index==0 else '下半场')+'进攻已选；另一场按英雄本体过滤。再次点击可取消。');self.refresh_filter_label();self.render()
 def add_filter(self,exclude):
  previous=getattr(self,'filter_picker',None)
  if previous is not None and previous.winfo_exists():
   if self.filter_picker_exclude==exclude:previous.lift();return previous
   previous.destroy()
  def accept(hero):
   target=self.exclude if exclude else self.include;other=self.include if exclude else self.exclude
   target.symmetric_difference_update({hero['id']});other.discard(hero['id']);self.refresh_filter_label();self.render()
  self.filter_picker_exclude=exclude
  self.filter_picker=HeroPicker(self.app,self.catalog,DATA,accept,multiple=True,selected_ids=self.exclude if exclude else self.include,selection_label='已排除' if exclude else '已包含',selection_color='#573645' if exclude else '#284c70')
  self.filter_picker.transient(self);return self.filter_picker

 def refresh_filter_label(self):
  label=lambda group:'、'.join(self.heroes.get(h,{}).get('name',h) for h in sorted(group)) or '无'
  self.filter_label.configure(text='包含/排除支持多选，点击已选角色可取消；点击进攻头像选用整队，右键看参考。')
  if hasattr(self,'selection_summary'):
   self.selection_summary.configure(state='normal');self.selection_summary.delete('1.0','end')
   text=f'已包含（{len(self.include)}，需同时出现）：'+label(self.include)+f'\n已排除（{len(self.exclude)}）：'+label(self.exclude)
   if any(self.selected_teams):text+='\n进攻已选：上半场 '+label(self.selected_teams[0])+'；下半场 '+label(self.selected_teams[1])+('（另一场去重）' if self.unique.get() else '（未启用跨队去重）')
   self.selection_summary.insert('1.0',text);self.selection_summary.configure(state='disabled',height=3 if any(self.selected_teams) else 2)

 def clear_filters(self):
  self.include.clear();self.exclude.clear();self.selected_teams=[(),()];self.refresh_filter_label();self.render()
  picker=getattr(self,'filter_picker',None)
  if picker is not None and picker.winfo_exists():picker.selected_ids.clear();picker.render()


 def clear_records(self):
  self.records.clear();self.round_feedback.clear();self.selected_teams=[(),()];self.result_limits=[20,20];self.refresh_filter_label();self.render()
 def source_changed(self):
  if self.provider.get()=='综合查询':self.sort.set('样本数')
  self.update_source_controls();self.clear_records();self.status.set('已切换到'+self.provider.get()+'，等待重新查询。')
  revision=self.source_query_revision=getattr(self,'source_query_revision',0)+1
  def refresh():
   if not self.winfo_exists() or revision!=self.source_query_revision:return
   if self.busy:self.app.after(150,refresh);return
   if any(all(row) and len(set(row))==3 for row in self.ids):self.query()
   else:self.status.set('已切换到'+self.provider.get()+'；请先识别或选择三名防守英雄。')
  self.app.after(150,refresh)
 def update_source_controls(self):
  guide_mode=self.provider.get().startswith('E7WIKI')
  for widget in self.query_controls.winfo_children():
   kind=widget.winfo_class()
   if kind not in ('TSpinbox','TCombobox') or str(widget.cget('textvariable')) not in (str(self.minimum),str(self.sort)):continue
   widget.configure(state='disabled' if guide_mode or (self.provider.get()=='综合查询' and str(widget.cget('textvariable'))==str(self.sort)) else 'readonly' if kind=='TCombobox' else 'normal')
 def photo(self,hero_id,size=50):
  key=(hero_id,size)
  if key not in self.photos:
   hero=self.heroes.get(hero_id)
   if not hero:return None
   path=DATA/hero.get('portrait','')
   if not path.is_file():return None
   with Image.open(path) as source:image=ImageOps.fit(source.convert('RGBA'),(size,size),method=Image.Resampling.LANCZOS)
   mask=Image.new('L',(size,size),0);ImageDraw.Draw(mask).ellipse((1,1,size-2,size-2),fill=255);image.putalpha(mask);ImageDraw.Draw(image).ellipse((1,1,size-2,size-2),outline='#a89974',width=1)
   self.photos[key]=ImageTk.PhotoImage(image,master=self)
  return self.photos[key]
 def pick(self,index,slot):
  picker=HeroPicker(self.app,self.catalog,DATA,lambda hero:self.set_hero(index,slot,hero['id'],'手动确认'));picker.transient(self);self.picker=picker;return picker
 def set_hero(self,index,slot,hero_id,note='已识别'):
  if hero_id and any(h==hero_id for i,h in enumerate(self.ids[index]) if i!=slot):
   self.status.set(('上半场' if index==0 else '下半场')+'不能重复选择 '+self.heroes[hero_id]['name']+'，本次未替换；请选择其他英雄。');return
  self.ids[index][slot]=hero_id;hero=self.heroes.get(hero_id);self.round_feedback.pop(index,None)
  button=self.slot_buttons[index][slot];button.configure(image=self.photo(hero_id,48) or '',text=hero['name'] if hero else '选择英雄',height=0);self.slot_notes[index][slot].configure(text='')
  self.records.pop(index,None);self.selected_teams[index]=();self.result_limits[index]=20
  self.refresh_filter_label()
  self.render(index)
  if note=='手动确认':
   self.source_query_revision=getattr(self,'source_query_revision',0)+1
   self.status.set(('上半场' if index==0 else '下半场')+'角色已修改，点击查询更新阵容结果。')
 def current_defense(self,index=0):return team_key(self.ids[index])
 def run(self,job,label):
  if self.busy:self.status.set('已有识别或查询任务，请稍候。');return
  self.busy=True;self.status.set(label)
  def worker():
   try:self.tasks.put(('done',job()))
   except Exception as error:self.tasks.put(('error',str(error)[:500]))
  threading.Thread(target=worker,daemon=True).start()
 def capture(self):
  if self.busy:return
  try:
   windows=find_game_windows();rect=select_game_rectangle(windows)
  except ValueError as error:messagebox.showinfo('无法自动定位',str(error)+'\n可使用“导入截图”。',parent=self);return
  def take():
   from window_capture import capture_game_window
   return self.match_image(capture_game_window(windows[0]))
  self.run(take,'正在后台读取敌方阵容；游戏可被遮挡，请勿最小化…')
 def update_skin_templates(self):
  if self.busy:return
  self.skin_cancel=threading.Event()
  def job():
   from skin_sync import update
   result=update(self.catalog,DATA/'hero-skins',self.app.user_dir/'portrait-templates',lambda done,total,saved,skipped:self.tasks.put(('progress',f'皮肤模板 {done}/{total} · 新增/变化 {saved} · 已有 {skipped}')),self.skin_cancel)
   return ('skin-updated',result)
  self.run(job,'正在检查官方仓库的皮肤模板，已完成文件会保留。')
 def cancel_skin_update(self):
  if hasattr(self,'skin_cancel'):self.skin_cancel.set();self.status.set('已请求停止皮肤更新；当前文件完成后保存断点。')
 def register_portrait(self):
  path=filedialog.askopenfilename(parent=self,title='选择已裁剪的单个英雄皮肤头像（仅本地）',filetypes=[('头像图片','*.png *.jpg *.jpeg *.webp')])
  if not path:return
  def accept(hero):
   try:
    from portrait_templates import register
    register(path,hero['id'],self.app.user_dir/'portrait-templates');self.matcher=None
    self.status.set('已登记 '+hero['name']+' 的本地头像模板；下次识别生效，不上传图片。')
   except (ValueError,OSError) as error:messagebox.showerror('未登记',str(error),parent=self)
  self.picker=HeroPicker(self.app,self.catalog,DATA,accept);self.picker.transient(self)
 def open_image(self):
  path=filedialog.askopenfilename(parent=self,filetypes=[('团战备战截图','*.png *.jpg *.jpeg *.bmp')])
  if path:
   with Image.open(path) as image:self.recognize(image.convert('RGB'))
 def recognize(self,image):
  self.run(lambda:self.match_image(image),'正在本地匹配右侧敌方头像…')
 def match_image(self,image):
  if self.matcher is None:
   from guild_portraits import PortraitMatcher
   self.matcher=PortraitMatcher(self.catalog,DATA,self.app.user_dir/'portrait-templates')
  return ('recognized',self.matcher.recognize(image))
 def query(self,force=False,index=None):
  if self.busy:self.status.set('正在识别或查询，请稍候。');return
  self.source_query_revision=getattr(self,'source_query_revision',0)+1
  targets=[]
  for r in ([index] if index is not None else range(2)):
   try:targets.append((r,self.current_defense(r)))
   except ValueError:
    from guild_feedback import defense_issue
    self.round_feedback[r]=defense_issue(self.ids[r],{h:d['name'] for h,d in self.heroes.items()});self.records.pop(r,None);self.render(r)
  if not targets:self.status.set('未发起查询：'+'；'.join(('上半场' if r==0 else '下半场')+'：'+self.round_feedback[r] for r in range(2) if r in self.round_feedback));return
  provider=self.provider.get()
  def job():
   results=[];resolved={}
   for r,defense in targets:
    if defense in resolved:
     data,error=resolved[defense];results.append((r,defense,data,error));continue
    try:
     if provider=='综合查询':
      data=fetch_combined(defense,{
       'E7GW':lambda:fetch_e7gw(defense,self.catalog),
       'EP7 公开战报':lambda:fetch_ep7(defense,self.catalog,client_key(self.app.user_dir)),
       'Ark 公开战报':lambda:fetch_ark(defense,self.catalog),
       'Fribbels 历史战报':lambda:fetch_fribbels(defense),
       'E7WIKI 在线作业':lambda:fetch_e7wiki(defense,self.catalog),
      },lambda text,r=r:self.tasks.put(('progress',('上半场' if r==0 else '下半场')+'：'+text)))
     elif provider.startswith('E7WIKI'):data=fetch_e7wiki(defense,self.catalog)
     elif provider=='E7GW':data=fetch_e7gw(defense,self.catalog)
     elif provider.startswith('EP7'):data=fetch_ep7(defense,self.catalog,client_key(self.app.user_dir))
     elif provider.startswith('Ark'):data=fetch_ark(defense,self.catalog,lambda n,r=r:self.tasks.put(('progress',('上半场' if r==0 else '下半场')+f'：已读取 {n} 条战报。')))
     elif provider.startswith('Fribbels'):data=fetch_fribbels(defense)
     else:raise ValueError('请选择一个在线战报来源')
     results.append((r,defense,data,None))
     resolved[defense]=(data,None)
    except Exception as error:
     reason=str(error)[:300];resolved[defense]=(None,reason);results.append((r,defense,None,reason))
   return ('queried',provider,results)
  self.run(job,'正在查询所选防守的真实战报；两场分别统计。')
 def poll(self):
  if not self.winfo_exists():return
  try:
   while True:
    kind,data=self.tasks.get_nowait()
    if kind=='progress':self.status.set(data);continue
    self.busy=False
    if kind=='error':self.status.set('未取得在线战报：'+data+'。请重试或更换来源。');continue
    if data[0]=='skin-updated':
     self.matcher=None;result=data[1];self.status.set(f"皮肤模板：新增/变化 {result['saved']}，跳过已有 {result['skipped']}，共 {result['total']}；"+('已停止，下次继续。' if result['cancelled'] else '下次识别生效。'))
    elif data[0]=='recognized':
     result=data[1]
     # Replace the recognized lineup as a batch: checking a new slot against
     # the previous lineup can otherwise reject a hero that moved slots.
     self.ids=[[None]*3 for _ in range(2)];self.records.clear();self.round_feedback.clear()
     for index,row in enumerate(result['rounds']):
      for slot in range(3):
       match=row[slot] if slot<len(row) else {};hero_id=match.get('hero_id');note=f"匹配 {match.get('score',0):.0%}" if hero_id else ('待确认：'+match['candidates'][0]['name'] if match.get('candidates') else '未检测到头像，请手动选择')
       self.set_hero(index,slot,hero_id,note)
     self.status.set('识别完成；标为待确认的头像需手动修正。')
     self.query()
    else:
     _,provider,results=data
     if provider!=self.provider.get():continue
     self.render();failed=0;applied=[]
     for index,defense,record,error in results:
      if tuple(sorted(h for h in self.ids[index] if h))!=defense:continue
      applied.append((index,defense,record,error))
      if error:
       failed+=1;self.records.pop(index,None);self.round_feedback[index]='接口请求失败：'+error+'\n本次无法判断是否有进攻阵容，请重试或切换来源。';self.render(index)
      else:self.round_feedback.pop(index,None);self.records[index]=record;self.render(index)
     summary=[]
     for r,defense,record,error in applied:
      prefix='上半场' if r==0 else '下半场'
      summary.append(prefix+('：请求失败' if error else f'：{len(record["offenses"])}组战报＋{len(record["guides"])}条作业，{len(record["source_errors"])}个来源失败' if record.get('record_kind')=='combined' else f'：{len(record.get("guides",[]))}条在线作业' if record.get('record_kind')=='community_guides' else f'：{len(record.get("offenses",[]))}组战报' if record.get('offenses') else '：当前来源返回0组战报'))
     self.status.set('；'.join(summary) if summary else '阵容已变化，已忽略旧阵容的查询结果，请重新查询。')
  except queue.Empty:pass
  self.app.after(150,self.poll)
 def render(self,index=None):
  if not hasattr(self,'boards'):return
  if index is None:
   for r in range(2):self.render(r)
   return
  board=self.boards[index];caption=self.data_captions[index]
  for child in board.winfo_children():child.destroy()
  record=self.records.get(index)
  for child in self.defense_totals[index].winfo_children():child.destroy()
  if not record:
   from guild_feedback import defense_issue
   text=self.round_feedback.get(index) or defense_issue(self.ids[index],{h:d['name'] for h,d in self.heroes.items()}) or '防守阵容已选齐，点击查询读取进攻战报。'
   caption.configure(text=text);self.result_titles[index].configure(text='网友进攻 · 待查询' if index not in self.round_feedback else '网友进攻 · 请检查提示')
   tk.Label(board,text=text,bg=CARD,fg='#e2bd80',font=(FONT,10),wraplength=340,justify='left').pack(anchor='w',pady=12)
   tk.Label(self.defense_totals[index],text='防守战报\n待查询',bg=CARD,fg=MUTED,font=(FONT,9),pady=12).pack()
   return
  if record.get('record_kind')=='community_guides':self.render_guides(index,record);return
  first=record.get('first_match','')[:10];last=record.get('last_match','')[:10]
  dates=('统计快照 '+record.get('report_date','未提供')) if record.get('date_kind')=='统计快照' else first+' ～ '+last if last else '日期未提供'
  caption.configure(text=f"{record.get('source','在线战报')} · {dates}"+(f" · {record['invalid_rows']}行未解析" if record.get('invalid_rows') else ''))
  mixed=record.get('record_kind')=='combined'
  if mixed:
   failures=record['source_errors'];sources=record['sources']
   caption.configure(text=f'综合在线查询 · {len(sources)}/{len(sources)+len(failures)}个来源成功\n同队按最大来源样本数排序，场次不累加；投稿作业列在后面。'+('\n未取得：'+'、'.join(row['provider'] for row in failures) if failures else ''))
   tk.Label(self.defense_totals[index],text=f'合并阵容\n{len(record["offenses"])} 组',bg=CARD,fg=ACCENT,font=(FONT,9),pady=12).pack()
  elif record.get('adapter','').startswith('e7gw'):
   tk.Label(self.defense_totals[index],text='全局守住次数\n来源未提供',bg=CARD,fg=MUTED,font=(FONT,8),pady=12).pack()
  elif record['offenses']:
   wins=sum(r['losses'] for r in record['offenses']);losses=sum(r['wins'] for r in record['offenses'])
   self.draw_counts(self.defense_totals[index],wins,losses,CARD,defense=True)
  else:
   tk.Label(self.defense_totals[index],text='暂无记录',bg=CARD,fg=MUTED,font=(FONT,10),pady=12).pack()
  try:minimum=max(1,int(self.minimum.get()))
  except (tk.TclError,ValueError):minimum=1
  partner=self.selected_teams[1-index] if self.unique.get() else ()
  rows=attack_rows(record,minimum,'样本数' if mixed else self.sort.get(),self.include,self.exclude,partner)
  if not rows:
   from guild_feedback import empty_feedback
   text='暂无符合筛选条件的统计战报；下方显示在线投稿作业。' if mixed and record.get('guides') else empty_feedback(record,minimum,self.include,self.exclude,partner)
   tk.Label(board,text=text,bg=CARD,fg=MUTED,font=(FONT,10),wraplength=340,justify='left').pack(anchor='w',pady=12)
  self.result_titles[index].configure(text=f'网友进攻 · {len(rows)} 组阵容')
  for number,row in enumerate(rows[:self.result_limits[index]],1):
   chosen=tuple(sorted(row['heroes']))==self.selected_teams[index]
   frame=tk.Frame(board,bg=CARD,padx=1,pady=1,highlightthickness=1,highlightbackground='#5076ff' if chosen else CARD);frame.pack(fill='x')
   stats=tk.Frame(frame,bg=CARD,width=104,height=54);stats.pack(side='right',padx=(4,1));stats.pack_propagate(False)
   self.draw_counts(stats,row['wins'],row['losses'],CARD)
   detail=f"{row['wins']/max(1,row['samples']):.0%} · {row['samples']}场"
   if row.get('draws'):detail+=f" · {row['draws']}平"
   tk.Label(stats,text=detail,bg=CARD,fg=MUTED,font=(FONT,7),padx=0,pady=0,borderwidth=0).pack(anchor='w')
   team=tk.Frame(frame,bg=CARD);team.pack(side='left',fill='both',expand=True)
   tk.Label(team,text=f'{number:02}',bg=CARD,fg='#74849a',font=(FONT,8),width=2).pack(side='left')
   for hero_id in row['heroes']:
    hero=self.heroes.get(hero_id);cell=tk.Frame(team,bg=CARD);cell.pack(side='left',expand=True,fill='x',padx=1)
    avatar=tk.Label(cell,image=self.photo(hero_id,48) or '',bg=CARD,cursor='hand2');avatar.pack();avatar.bind('<Button-3>',lambda e,h=hero:self.show_hero_reference(h))
    avatar.bind('<Button-1>',lambda e,r=index,team=row['heroes']:self.select_attack(r,team))
    avatar.bind('<Enter>',lambda e,h=hero,i=hero_id:self.show_name(e,h['name'] if h else i));avatar.bind('<Leave>',lambda e:self.hide_name())
   if row.get('source_stats'):
    details='当前显示：'+row['display_source']+'\n'+'\n'.join(item['source']+f"：{item['samples']}场 · {item['wins']}胜/{item['losses']}负"+(f"/{item['draws']}平" if item['draws'] else '') for item in row['source_stats'])
    label=tk.Label(board,text=details,bg=CARD,fg=MUTED,font=(FONT,8),justify='left',anchor='w',wraplength=340);label.pack(fill='x',padx=8,pady=(1,5));label.bind('<Configure>',lambda e,l=label:l.configure(wraplength=max(160,e.width-4)))
   tk.Frame(board,bg='#2d3540',height=1).pack(fill='x')
  if len(rows)>self.result_limits[index]:ttk.Button(board,text=f'显示更多（还有 {len(rows)-self.result_limits[index]} 组）',style='Compact.TButton',command=lambda:self.more_results(index)).pack(fill='x',pady=6)
  if mixed and record.get('guides'):self.render_guides(index,record,append=True)
 def render_guides(self,index,record,append=False):
  board=self.boards[index];all_guides=record.get('guides',[])
  if not append:
   self.data_captions[index].configure(text=record['source']+' · 实时查询\n投稿作业不按最小样本筛选；成功／失败为网站用户反馈。')
   tk.Label(self.defense_totals[index],text=f'在线作业\n{len(all_guides)} 条',bg=CARD,fg=ACCENT,font=(FONT,10),pady=12).pack()
  partner=self.selected_teams[1-index] if self.unique.get() else ()
  rows=guide_rows(record,self.include,self.exclude,partner)
  if not append:self.result_titles[index].configure(text=f'网友进攻 · {len(rows)} 条在线作业')
  else:tk.Label(board,text=f'在线投稿作业 · {len(rows)} 条（无统计样本数）',bg=CARD,fg=ACCENT,font=(FONT,10,'bold'),anchor='w').pack(fill='x',pady=(12,4))
  def paragraph(parent,text,color=TEXT,bold=False):
   label=tk.Label(parent,text=text,bg=CARD,fg=color,font=(FONT,9,'bold') if bold else (FONT,9),wraplength=340,justify='left',anchor='w');label.pack(fill='x',pady=3)
   label.bind('<Configure>',lambda e,l=label:l.configure(wraplength=max(160,e.width-4)))
  if not rows:
   paragraph(board,'网站本次未返回这组三人防守的作业。' if not all_guides else '网站已返回作业，当前被包含／排除英雄或跨队去重条件过滤。',MUTED);return
  for number,guide in enumerate(rows[:self.result_limits[index]],1):
   chosen=team_key(guide['heroes'])==self.selected_teams[index]
   card=tk.Frame(board,bg=CARD,padx=8,pady=7,highlightthickness=1,highlightbackground='#5076ff' if chosen else '#344150');card.pack(fill='x',pady=(3,8))
   paragraph(card,f"{number:02} · {guide['scene'] or '进攻作业'} · {guide['author'] or '作者未提供'}",ACCENT,True)
   if guide.get('source'):paragraph(card,guide['source'],MUTED)
   team=tk.Frame(card,bg=CARD);team.pack(fill='x',pady=5)
   for hero_id in guide['heroes']:
    hero=self.heroes[hero_id];cell=tk.Frame(team,bg=CARD);cell.pack(side='left',expand=True,fill='x')
    avatar=tk.Label(cell,image=self.photo(hero_id,48) or '',text=hero['name'],compound='top',bg=CARD,fg=TEXT,font=(FONT,8),cursor='hand2');avatar.pack()
    avatar.bind('<Button-1>',lambda e,r=index,heroes=guide['heroes']:self.select_attack(r,heroes));avatar.bind('<Button-3>',lambda e,h=hero:self.show_hero_reference(h))
   paragraph(card,f"用户反馈：成功 {guide['feedback_wins']} · 失败 {guide['feedback_losses']}",MUTED)
   for title,key in (('装备','equipment'),('神器','artifact'),('打法','strategy'),('注意','note')):
    if guide[key]:paragraph(card,title,ACCENT,True);paragraph(card,guide[key])
   if guide['updateTime']:paragraph(card,'作业更新：'+guide['updateTime'],MUTED)
  if len(rows)>self.result_limits[index]:ttk.Button(board,text=f'显示更多（还有 {len(rows)-self.result_limits[index]} 条作业）',style='Compact.TButton',command=lambda:self.more_results(index)).pack(fill='x',pady=6)
 def more_results(self,index):
  position=self.canvases[index].yview()[0];self.result_limits[index]+=20;self.render(index);self.update_idletasks();self.canvases[index].yview_moveto(position)
 def draw_counts(self,parent,wins,losses,bg,defense=False):
  for value,label,color in ((wins,'胜利','#7ee0bc'),(losses,'失败','#ff9e9e')):
   line=tk.Frame(parent,bg=bg);line.pack(fill='x')
   name=('defense' if defense else 'attack')+('-win' if label=='胜利' else '-loss');key=('result-icon',name)
   if key not in self.photos:
    with Image.open(DATA/'guild-war-icons'/(name+'.png')) as source:icon=ImageOps.contain(source.convert('RGBA'),(20,20),Image.Resampling.LANCZOS)
    self.photos[key]=ImageTk.PhotoImage(icon,master=self)
   tk.Label(line,image=self.photos[key],bg=bg,padx=0,pady=0,borderwidth=0).pack(side='left',padx=(0,4))
   tk.Label(line,text=f'{value:,} {label}',bg=bg,fg=color,font=(FONT,10,'bold'),anchor='w',padx=0,pady=0,borderwidth=0).pack(side='left')
 def scroll_round(self,event):
  widget=event.widget
  while widget is not None:
   if widget in self.panes:
    self.canvases[self.panes.index(widget)].yview_scroll(-int(event.delta/120),'units');return 'break'
   widget=getattr(widget,'master',None)
 def show_hero_reference(self,hero):
  self.hide_name()
  if hero:
   from reference_window import show_reference
   window=show_reference(self.app,hero);window.transient(self)
 def hide_name(self):
  tip=getattr(self,'name_tip',None)
  if tip is not None and tip.winfo_exists():tip.destroy()
  self.name_tip=None
 def show_name(self,event,name):
  self.hide_name();tip=tk.Toplevel(self);self.name_tip=tip;tip.overrideredirect(True)
  tip.geometry(f'+{min(event.x_root+10,self.winfo_screenwidth()-230)}+{event.y_root+20}')
  tk.Label(tip,text=name+' · 右键查看配装',bg='#333d4b',fg=TEXT,font=(FONT,9),padx=8,pady=5).pack()

def open_guild_war(parent):
 existing=getattr(parent,'guild_war_window',None)
 if existing is not None and existing.winfo_exists():existing.deiconify();existing.lift();return existing
 parent.guild_war_window=GuildWarWindow(parent);return parent.guild_war_window
