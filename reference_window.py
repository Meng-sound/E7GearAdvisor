"""Hero reference dashboard with real game icons and explicit data provenance."""
import json,math,webbrowser,tkinter as tk,queue,threading
from pathlib import Path
from tkinter import ttk
from PIL import Image,ImageTk,ImageDraw,ImageOps
from build_reference import references,primary_reference
from adaptation_storage import overrides
from set_icons import display,canonical,layout_text
from candidate_panel import library_url

ROOT=Path(__file__).parent/'data'
BG='#171b23';CARD='#202630';EDGE='#29394d';TEXT='#edf3fb';MUTED='#93a6bd';GOLD='#bdcbff';MINT='#8adfce';BLUE='#b6cff3';FONT='Microsoft YaHei UI'
FIELDS=[('atk','攻击力'),('def','防御力'),('hp','生命值'),('spd','速度'),('crit','暴击率'),('cdmg','暴击伤害'),('eff','效果命中'),('res','效果抗性')]

class Surface(tk.Canvas):
 def __init__(self,parent,height=290,padding=14):
  super().__init__(parent,height=height,bg=BG,highlightthickness=0,bd=0);self.padding=padding
  self.shape=self.create_polygon(0,0,1,0,1,1,fill=CARD,outline=EDGE,width=1,smooth=True,splinesteps=24)
  self.body=tk.Frame(self,bg=CARD);self.window=self.create_window(padding,padding,window=self.body,anchor='nw');self.bind('<Configure>',self.resize)
 def resize(self,e):
  w,h=e.width,e.height;r=14;self.coords(self.shape,r,0,w-r,0,w,0,w,r,w,h-r,w,h,w-r,h,r,h,0,h,0,h-r,0,r,0,0);self.itemconfigure(self.window,width=max(1,w-2*self.padding),height=max(1,h-2*self.padding))

class ReferenceWindow(tk.Toplevel):
 def __init__(self,parent,hero):
  super().__init__(parent);self.parent_app=parent;self.hero=hero;self.photos={};self.page=0;self.columns=3;self.reference_cards=[];self.stat_icon_labels=[];self.artifact_rows=[]
  self.title(hero['name']+' · 配装参考');self.configure(bg=BG);self.geometry(f'{min(1540,self.winfo_screenwidth()-60)}x{min(960,self.winfo_screenheight()-65)}');self.minsize(880,540)
  self.ref=overrides().get(hero['name_en']) or references().get('heroes',{}).get(hero['name_en']) or {}
  self.artifact_catalog=json.loads((ROOT/'artifact-catalog.json').read_text(encoding='utf8'))['artifacts']
  self.set_files={canonical(r['name']):ROOT/'set-icons'/r['file'] for r in json.loads((ROOT/'set-icons/index.json').read_text(encoding='utf8'))}
  self.primary=primary_reference(self.ref);self.all_variants=sorted(self.ref.get('variants') or ([self.ref] if self.ref.get('panel') else []),key=lambda v:v.get('sample_count',0),reverse=True)
  self.variants=[v for v in self.all_variants if v is not self.primary]
  self.compare=tk.BooleanVar(value=False)
  self.build_header()
  self.layout_page=ttk.Frame(self,padding=0);self.layout_page.body=self.layout_page;self.layout_page.pack(fill='both',expand=True)
  layout=tk.Frame(self.layout_page.body,bg=BG);layout.pack(fill='both',expand=True,padx=12,pady=(0,10))
  self.sidebar=tk.Frame(layout,bg=BG,width=230);self.sidebar.pack(side='right',fill='y',padx=(14,0));self.sidebar.pack_propagate(False);self.build_sidebar()
  self.featured=Surface(layout,height=650,padding=18);self.featured.pack(side='left',fill='y',padx=(0,12));self.featured.configure(width=280)
  self.build_featured()
  compare_row=tk.Frame(self.featured.body,bg=CARD);compare_row.pack(fill='x',pady=(8,0))
  ttk.Checkbutton(compare_row,text='对比已读当前面板（参考 − 当前）',variable=self.compare,command=self.toggle_comparison).pack(anchor='w')
  self.after_idle(lambda:self.featured.configure(height=max(650,self.featured.body.winfo_reqheight()+self.featured.padding*2+10)))
  center=tk.Frame(layout,bg=BG);center.pack(side='left',fill='both',expand=True)
  strip=tk.Frame(center,bg=BG);strip.pack(fill='x',pady=(0,9));tk.Label(strip,text='其他配装参考',bg=BG,fg=TEXT,font=(FONT,12,'bold')).pack(side='left')
  self.canvas=tk.Canvas(center,bg=BG,highlightthickness=0);self.canvas.pack(fill='both',expand=True)
  self.board=tk.Frame(self.canvas,bg=BG);self.board_item=self.canvas.create_window(0,0,window=self.board,anchor='nw');self.board.bind('<Configure>',lambda e:self.canvas.configure(scrollregion=self.canvas.bbox('all')));self.canvas.bind('<Configure>',self.resize_board)
  footer=tk.Frame(self,bg=BG);footer.pack(side='bottom',before=self.layout_page,fill='x',padx=20,pady=(0,14))
  tk.Label(footer,text='统计参考 · 中位数组合不代表一套真实装备',bg=BG,fg=MUTED,font=(FONT,9)).pack(side='left')
  self.page_label=tk.Label(footer,bg=BG,fg=MUTED,font=(FONT,9));self.page_label.pack(side='left',padx=10)
  self.prev=ttk.Button(footer,text='上一页',style='Compact.TButton',command=lambda:self.change_page(-1));self.prev.pack(side='left',padx=3)
  self.next=ttk.Button(footer,text='下一页',style='Compact.TButton',command=lambda:self.change_page(1));self.next.pack(side='left',padx=3)
  self.page_label.pack_forget();self.prev.pack_forget();self.next.pack_forget()
  ttk.Button(footer,text='打开 Fribbels 原站 ↗',style='Compact.TButton',command=lambda:webbrowser.open(library_url(hero))).pack(side='right')
  self.render_cards()
 def image(self,path,size,circle=False):
  if path and Path(path).parent.name=='artifact-icons':
   cached=self.parent_app.user_dir/'artifact-icons'/Path(path).name
   if cached.is_file():path=cached
  if not path or not Path(path).is_file():return None
  key=(str(path),size,circle)
  if key not in self.photos:
   try:
    with Image.open(path) as source:im=ImageOps.contain(source.convert('RGBA'),size,Image.Resampling.LANCZOS)
   except (OSError,ValueError):return None
   if circle:
    im=ImageOps.fit(im,size,Image.Resampling.LANCZOS);mask=Image.new('L',size,0);ImageDraw.Draw(mask).ellipse((1,1,size[0]-2,size[1]-2),fill=255);im.putalpha(mask);ImageDraw.Draw(im).ellipse((1,1,size[0]-2,size[1]-2),outline=GOLD,width=2)
   self.photos[key]=ImageTk.PhotoImage(im,master=self)
  return self.photos[key]
 def label_icon(self,parent,path,size=(22,22),bg=CARD):
  picture=self.image(path,size)
  if picture:return tk.Label(parent,image=picture,bg=bg,bd=0)
  fallback=tk.Canvas(parent,width=size[0],height=size[1],bg=bg,highlightthickness=0)
  w,h=size;fallback.create_polygon(w*.5,2,w-2,h*.25,w-2,h*.75,w*.5,h-2,2,h*.75,2,h*.25,outline=MUTED,fill=BG,width=1)
  fallback.create_text(w/2,h/2,text='?',fill=MUTED,font=(FONT,max(8,int(h*.28)),'bold'));return fallback
 def build_header(self):
  header=tk.Frame(self,bg=BG);header.pack(fill='x',padx=22,pady=(20,18))
  self.portrait_label=self.label_icon(header,ROOT/self.hero['portrait'],(84,84),BG);portrait=self.image(ROOT/self.hero['portrait'],(84,84),True)
  if portrait:self.portrait_label.configure(image=portrait)
  self.portrait_label.pack(side='left',padx=(0,16));identity=tk.Frame(header,bg=BG);identity.pack(side='left',fill='x',expand=True)
  tk.Label(identity,text=self.hero['name'],font=(FONT,22,'bold'),fg=TEXT,bg=BG).pack(anchor='w')
  row=tk.Frame(identity,bg=BG);row.pack(anchor='w',pady=(4,0))
  for key,prefix in [('element','element-'),('role','role-')]:
   path=ROOT/'filter-icons'/(prefix+str(self.hero.get(key,''))+'.png')
   if path.is_file():self.label_icon(row,path,(22,22),BG).pack(side='left',padx=(0,7))
  tk.Label(row,text='配装面板参考',bg=BG,fg=GOLD,font=(FONT,10,'bold')).pack(side='left',padx=(0,12))
  samples=self.ref.get('sample_count');date=self.ref.get('updated_at',references().get('fetched_at',''))[:10]
  tk.Label(row,text=(f'{samples:,} 条样本' if isinstance(samples,(int,float)) else '样本待同步')+('  ·  '+date if date else ''),fg=MUTED,bg=BG,font=(FONT,9)).pack(side='left')
  self.reference_update_button=ttk.Button(header,text='更新本英雄',command=self.update_reference,style='Compact.TButton');self.reference_update_button.pack(side='right',padx=3)
  ttk.Button(header,text='刷新显示',command=self.reload,style='Compact.TButton').pack(side='right',padx=3)
  self.icon_update_button=ttk.Button(header,text='补齐神器图标',command=self.update_icons,style='Compact.TButton');self.icon_update_button.pack(side='right',padx=3)
 def update_reference(self):
  from tkinter import messagebox
  if self.parent_app.sync_active:
   messagebox.showinfo('正在同步','已有同步任务正在运行，请待其完成后再更新本英雄。',parent=self);return
  if self.parent_app.sync_cancel.is_set():self.parent_app.sync_cancel.clear()
  self.parent_app.sync_reference_hero(self.hero['name_en'])
  self.reference_update_button.configure(state='disabled',text='更新中…')
  def wait():
   if not self.winfo_exists():return
   if self.parent_app.sync_active:self.parent_app.after(400,wait);return
   message=self.parent_app.sync_message.get()
   if '已更新 ' not in message:
    self.reference_update_button.configure(state='normal',text='更新本英雄');messagebox.showinfo('更新结果',message,parent=self);return
   self.reload()
  self.parent_app.after(500,wait)
 def update_icons(self):
  from artifact_assets import update_missing
  messages=queue.Queue();self.icon_update_button.configure(state='disabled',text='正在补图…')
  def worker():
   try:messages.put(('done',update_missing(self.artifact_catalog,ROOT/'artifact-icons',self.parent_app.user_dir/'artifact-icons',lambda i,n,s,f:messages.put(('progress',f'{i}/{n}')))))
   except Exception as error:messages.put(('error',str(error)))
  def poll():
   if not self.winfo_exists():return
   try:
    while True:
     kind,value=messages.get_nowait()
     if kind=='progress':self.icon_update_button.configure(text='补图 '+value)
     else:
      from tkinter import messagebox
      self.icon_update_button.configure(state='normal',text='补齐神器图标')
      if kind=='error':messagebox.showerror('图标更新失败',value,parent=self)
      else:
       saved,failed=value;messagebox.showinfo('图标更新结果',f'补齐 {saved} 个图标；未取得 {len(failed)} 个。\n未取得的图标保留占位标识，可稍后重试。',parent=self);self.reload()
      return
   except queue.Empty:self.after(150,poll)
  threading.Thread(target=worker,daemon=True).start();poll()
 def reload(self):
  position=self.geometry();self.destroy();win=ReferenceWindow(self.parent_app,self.hero);win.geometry(position)
 def resize_board(self,e):
  self.canvas.itemconfigure(self.board_item,width=max(1,e.width),height=0)
  self.after_idle(self.fit_reference_cards)
 def fit_reference_cards(self):
  if not self.winfo_exists():return
  for card in self.reference_cards:
   card.configure(height=card.body.winfo_reqheight()+card.padding*2+4)
 def change_page(self,delta):
  self.page=max(0,min(max(0,math.ceil(len(self.variants)/self.columns)-1),self.page+delta));self.render_cards();self.canvas.yview_moveto(0)
 def render_cards(self):
  for child in self.board.winfo_children():child.destroy()
  self.reference_cards=[];self.stat_icon_labels=[]
  self.columns=3
  for column in range(3):self.board.columnconfigure(column,weight=1,uniform='reference')
  for row in range(2):self.board.rowconfigure(row,weight=0,uniform='reference-row')
  if not self.variants:
   tk.Label(self.board,text='尚无配装面板样本',bg=BG,fg=TEXT,font=(FONT,16,'bold')).pack(pady=(80,12));tk.Label(self.board,text='在“更多 → 角色候选”中同步或导入参考数据。',bg=BG,fg=MUTED,font=(FONT,10)).pack()
  for index,variant in enumerate(self.variants[:6]):
   card=Surface(self.board,height=330,padding=10);card.grid(row=index//3,column=index%3,sticky='nsew',padx=(0,8),pady=(0,8));self.reference_cards.append(card);body=card.body
   head=tk.Frame(body,bg=CARD);head.pack(fill='x');tk.Label(head,text='推荐参考 · 样本最多' if variant==self.primary else f'参考面板 {index+1:02}',bg=CARD,fg=MINT if variant==self.primary else GOLD,font=(FONT,11,'bold')).pack(side='left')
   share=variant.get('share');tk.Label(head,text=f'{share:.1%}' if isinstance(share,(int,float)) else '',bg=CARD,fg=MINT,font=(FONT,11,'bold')).pack(side='right')
   sets=tk.Frame(body,bg=CARD);sets.pack(fill='x',pady=(3,5))
   for name in variant.get('sets',[]):self.label_icon(sets,self.set_files.get(canonical(name)),(23,23)).pack(side='left',padx=(0,3))
   tk.Label(sets,text=layout_text(variant),bg=CARD,fg=BLUE,font=(FONT,9)).pack(side='left',padx=3)
   stats=tk.Frame(body,bg=CARD);stats.pack(fill='x',pady=6)
   for column in range(2):stats.columnconfigure(column,weight=1,uniform='stat')
   for position,(key,label) in enumerate(FIELDS):
    color='#203c47' if key=='spd' else CARD;row=tk.Frame(stats,bg=color);row.grid(row=position//2,column=position%2,sticky='ew',padx=2,pady=3)
    icon=self.label_icon(row,ROOT/'stat-icons'/(key+'.png'),(18,18),color);icon.pack(side='left',padx=(0,4));self.stat_icon_labels.append(icon)
    tk.Label(row,text=label,bg=color,fg=MUTED,font=(FONT,9)).pack(side='left')
    value=variant.get('panel',{}).get(key);text='—' if value is None else f'{value:g}'+('%' if key in ('crit','cdmg','eff','res') else '')
    tk.Label(row,text=text,bg=color,fg=MINT if key=='spd' else TEXT,font=(FONT,11,'bold')).pack(side='right',padx=2)
   self.score_row(body,variant)
   self.artifact_badge(body,variant)
   count=variant.get('sample_count');tk.Label(head,text=f'{count:,}样本' if isinstance(count,(int,float)) else '',bg=CARD,fg=MUTED,font=(FONT,9)).pack(side='left',padx=8)
  pages=max(1,math.ceil(len(self.variants)/self.columns));self.page_label.configure(text=f'{self.page+1} / {pages}');self.prev.configure(state='normal' if self.page else 'disabled');self.next.configure(state='normal' if self.page+1<pages else 'disabled')
  self.after_idle(self.fit_reference_cards)
 def score_row(self,parent,variant,large=False):
  row=tk.Frame(parent,bg=CARD);row.pack(fill='x',pady=(7,3))
  self.label_icon(row,ROOT/'stat-icons'/'gear_score.png',(23,23) if large else (18,18)).pack(side='left',padx=(3,7))
  tk.Label(row,text='装备总分',bg=CARD,fg=GOLD,font=(FONT,12 if large else 9,'bold')).pack(side='left')
  score=variant.get('gear_score');value=f'{score:g}' if isinstance(score,(int,float)) else '暂无数据'
  label=tk.Label(row,text=value,bg=CARD,fg=MINT,font=(FONT,26 if large else 18,'bold'));label.pack(side='right',padx=5)
  if not hasattr(self,'score_labels'):self.score_labels=[]
  self.score_labels.append(label)
 def artifact_badge(self,parent,variant,large=False):
  rates=variant.get('artifact_rates') or {};basis='本套样本常用'
  if not rates:rates=self.ref.get('artifact_rates') or {};basis='全体样本常用'
  known=[(code,rate) for code,rate in rates.items() if code in self.artifact_catalog]
  row=tk.Frame(parent,bg=CARD);row.pack(fill='x',pady=(8 if large else 4,0))
  if not known:
   tk.Label(row,text='神器统计待同步',bg=CARD,fg=MUTED,font=(FONT,9)).pack(anchor='w');return
  code,rate=max(known,key=lambda p:p[1]);size=(64,64) if large else (34,34)
  self.label_icon(row,ROOT/'artifact-icons'/(code+'.png'),size).pack(side='left',padx=(0,8))
  text=tk.Frame(row,bg=CARD);text.pack(side='left',fill='x',expand=True)
  tk.Label(text,text=self.artifact_catalog[code]['name'],bg=CARD,fg=TEXT,font=(FONT,11 if large else 10,'bold'),wraplength=205 if large else 170,justify='left').pack(anchor='w')
  tk.Label(text,text=f'{basis} · {rate:.1%}',bg=CARD,fg=MUTED,font=(FONT,9)).pack(anchor='w')
 def build_featured(self):
  body=self.featured.body;variant=self.primary
  tk.Label(body,text='推荐参考 · 样本最多',bg=CARD,fg=MINT,font=(FONT,16,'bold')).pack(anchor='w',pady=(0,12))
  if not variant:
   tk.Label(body,text='暂无配装样本，请先同步参考。',bg=CARD,fg=MUTED,font=(FONT,10),wraplength=260).pack(anchor='w');return
  identity=tk.Frame(body,bg=CARD);identity.pack(fill='x',pady=(0,14))
  self.label_icon(identity,ROOT/self.hero['portrait'],(64,64)).pack(side='left',padx=(0,12))
  text=tk.Frame(identity,bg=CARD);text.pack(side='left',fill='x',expand=True)
  tk.Label(text,text=self.hero['name'],bg=CARD,fg=TEXT,font=(FONT,14,'bold'),wraplength=135,justify='left').pack(anchor='w')
  count=variant.get('sample_count');share=variant.get('share')
  tk.Label(text,text=(f'{count:,} 样本' if isinstance(count,(int,float)) else '')+(f' · {share:.1%}' if isinstance(share,(int,float)) else ''),bg=CARD,fg=MINT,font=(FONT,10)).pack(anchor='w',pady=(8,0))
  sets=tk.Frame(body,bg=CARD);sets.pack(fill='x',pady=(0,12))
  for name in variant.get('sets',[]):self.label_icon(sets,self.set_files.get(canonical(name)),(28,28)).pack(side='left',padx=(0,4))
  tk.Label(sets,text=layout_text(variant),bg=CARD,fg=BLUE,font=(FONT,10)).pack(side='left')
  self.featured_values={}
  for key,title in FIELDS:
   color='#203c47' if key=='spd' else CARD;row=tk.Frame(body,bg=color);row.pack(fill='x',pady=2)
   self.label_icon(row,ROOT/'stat-icons'/(key+'.png'),(23,23),color).pack(side='left',padx=(3,8))
   tk.Label(row,text=title,bg=color,fg=MUTED,font=(FONT,11)).pack(side='left')
   value=variant.get('panel',{}).get(key);value='—' if value is None else f'{value:g}'+('%' if key in ('crit','cdmg','eff','res') else '')
   label=tk.Label(row,text=value,bg=color,fg=MINT if key=='spd' else TEXT,font=(FONT,16,'bold'));label.pack(side='right',padx=4);self.featured_values[key]=label
  self.score_row(body,variant,True);self.artifact_badge(body,variant,True)
  tk.Label(body,text='同套装样本各属性取中位数，\n不代表某一套真实装备。',bg=CARD,fg=MUTED,font=(FONT,9),justify='left').pack(anchor='w',pady=(14,0))
 def toggle_comparison(self):
  current=getattr(self.parent_app,'last_character_panel',{}) if getattr(self.parent_app,'last_character_hero_id',None)==self.hero['id'] else {}
  for key,label in getattr(self,'featured_values',{}).items():
   value=self.primary.get('panel',{}).get(key)
   if value is None:continue
   unit='%' if key in ('crit','cdmg','eff','res') else ''
   text=f'{value:g}{unit}'
   if self.compare.get():text+=f' ({value-current[key]:+g}{unit})' if key in current else ' (未读当前值)'
   label.configure(text=text,font=(FONT,12 if self.compare.get() else 16,'bold'))
 def panel(self,title,height):
  surface=Surface(self.sidebar,height=height,padding=13);surface.pack(fill='x',pady=(0,12));tk.Label(surface.body,text=title,bg=CARD,fg=GOLD,font=(FONT,12,'bold')).pack(anchor='w',pady=(0,10));return surface.body
 def build_sidebar(self):
  art=self.panel('神器推荐',365);rates=self.ref.get('artifact_rates') or {};preferences=self.preferences();entries=[]
  for code in preferences:
   if code in self.artifact_catalog:entries.append((code,rates.get(code),True))
  for code,rate in sorted(rates.items(),key=lambda p:p[1],reverse=True):
   if code in self.artifact_catalog and code not in preferences:entries.append((code,rate,False))
  if not entries:
   tk.Label(art,text='神器统计待同步',bg=CARD,fg=TEXT,font=(FONT,12,'bold')).pack(anchor='w',pady=(18,9))
   tk.Label(art,text='当前缓存没有神器使用率。\n同步或导入含神器统计的数据后，\n这里显示图标、名称和排名。',bg=CARD,fg=MUTED,font=(FONT,9),justify='left').pack(anchor='w')
   tk.Label(art,text='也可以先配置个人神器推荐。',bg=CARD,fg=MUTED,font=(FONT,9)).pack(anchor='w',pady=12)
  for code,rate,personal in entries[:4]:
   row=tk.Frame(art,bg=CARD);row.pack(fill='x',pady=(0,9));self.artifact_rows.append(row);self.label_icon(row,ROOT/'artifact-icons'/(code+'.png'),(44,44)).pack(side='left',padx=(0,9))
   text=tk.Frame(row,bg=CARD);text.pack(side='left',fill='x',expand=True);tk.Label(text,text=self.artifact_catalog[code]['name'],bg=CARD,fg=TEXT,font=(FONT,9,'bold'),wraplength=155,justify='left',anchor='w').pack(fill='x')
   tk.Label(text,text=(f'使用率 {rate:.1%}' if isinstance(rate,(int,float)) else '个人推荐 · 无使用率')+('  ★' if personal else ''),bg=CARD,fg=MINT if rate is not None else MUTED,font=(FONT,8)).pack(anchor='w',pady=(3,0))
  ttk.Button(art,text='配置个人神器',style='Compact.TButton',command=self.edit_artifacts).pack(side='bottom',anchor='w',pady=3)
  sets=self.panel('套装出现率',250)
  for name,rate in sorted((self.ref.get('set_rates') or {}).items(),key=lambda p:p[1],reverse=True)[:4]:
   row=tk.Frame(sets,bg=CARD);row.pack(fill='x',pady=(0,10));self.label_icon(row,self.set_files.get(canonical(name)),(25,25)).pack(side='left',padx=(0,7));tk.Label(row,text=display(name),bg=CARD,fg=TEXT,font=(FONT,10)).pack(side='left');tk.Label(row,text=f'{rate:.1%}',bg=CARD,fg=MINT,font=(FONT,10,'bold')).pack(side='right')
  if not self.ref.get('set_rates'):tk.Label(sets,text='暂无套装统计',bg=CARD,fg=MUTED,font=(FONT,10)).pack(anchor='w',pady=12)
  tk.Label(sets,text='出现率包含多套装搭配，不要求合计100%。',bg=CARD,fg=MUTED,font=(FONT,8),wraplength=220,justify='left').pack(side='bottom',anchor='w')
 def preferences(self):
  try:return json.loads((self.parent_app.user_dir/'artifact-preferences.json').read_text(encoding='utf8')).get(self.hero['id'],[])
  except (OSError,ValueError,AttributeError):return []
 def edit_artifacts(self):
  win=tk.Toplevel(self);win.title(self.hero['name']+' · 个人神器推荐');win.geometry('650x620');win.configure(bg=BG)
  selected=list(self.preferences());query=tk.StringVar();ttk.Entry(win,textvariable=query).pack(fill='x',padx=16,pady=12)
  table=ttk.Treeview(win,columns=('name','code'),show='tree headings',height=9);table.heading('#0',text='图标');table.column('#0',width=50,stretch=False);table.heading('name',text='神器（可搜索中文／英文）');table.column('name',width=410);table.heading('code',text='代码');table.column('code',width=100);table.pack(fill='both',expand=True,padx=16)
  status=tk.StringVar();ttk.Label(win,textvariable=status,wraplength=610).pack(fill='x',padx=16,pady=10)
  def render(*_):
   table.delete(*table.get_children());key=query.get().casefold()
   for code,item in self.artifact_catalog.items():
    if key and key not in (item['name']+' '+item['name_en']+' '+code).casefold():continue
    image=self.image(ROOT/'artifact-icons'/(code+'.png'),(34,34));table.insert('','end',iid=code,image=image or '',values=(('★ ' if code in selected else '')+item['name'],code))
   status.set('已选：'+'、'.join(self.artifact_catalog[c]['name'] for c in selected if c in self.artifact_catalog))
  def toggle(_=None):
   for code in table.selection():
    if code in selected:selected.remove(code)
    elif len(selected)<8:selected.append(code)
   render()
  def save():
   path=self.parent_app.user_dir/'artifact-preferences.json'
   try:data=json.loads(path.read_text(encoding='utf8'))
   except (OSError,ValueError):data={}
   data[self.hero['id']]=selected;tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(path);win.destroy();self.reload()
  row=ttk.Frame(win,padding=16);row.pack(fill='x');ttk.Button(row,text='添加／移除所选',command=toggle).pack(side='left');ttk.Button(row,text='保存个人推荐',command=save).pack(side='right');table.bind('<Double-1>',toggle);query.trace_add('write',render);render()

def show_reference(parent,hero):return ReferenceWindow(parent,hero)
