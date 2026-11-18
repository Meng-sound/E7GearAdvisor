"""Temporary six-slot Fribbels sum; never infer exact GS from final panels."""
import tkinter as tk
from tkinter import ttk
from copy import deepcopy
from core import SLOTS
from fribbels_gs import item_score,total_score
from build_reference import references

class GearTotalWindow(tk.Toplevel):
 def __init__(self,app):
  super().__init__(app);self.app=app;self.items={};self.hero_id=app.selected_hero_id;self.collecting=tk.BooleanVar(value=False)
  self.title('角色装备总分 · Fribbels GS');self.geometry('540x570');self.configure(bg='#171b23');self.transient(app)
  body=ttk.Frame(self,padding=16);body.pack(fill='both',expand=True)
  self.hero=ttk.Label(body,font=('Microsoft YaHei UI',15,'bold'));self.hero.pack(anchor='w')
  self.total=ttk.Label(body,font=('Microsoft YaHei UI',30,'bold'));self.total.pack(anchor='w',pady=8)
  self.reference=ttk.Label(body,wraplength=490);self.reference.pack(anchor='w')
  ttk.Label(body,text='按六件装备副属性计算，不受神器、套装、刻印或被动影响。\n角色最终面板不能唯一还原这个分数。',wraplength=490).pack(anchor='w',pady=10)
  self.rows=ttk.Treeview(body,columns=('slot','name','gs'),show='headings',height=6)
  for key,title,width in [('slot','部位',70),('name','装备',270),('gs','GS',75)]:self.rows.heading(key,text=title);self.rows.column(key,width=width)
  self.rows.pack(fill='x',pady=6)
  ttk.Checkbutton(body,text='开启收集：逐件打开角色装备详情，按 F8 读取',variable=self.collecting).pack(anchor='w',pady=8)
  actions=ttk.Frame(body);actions.pack(fill='x');ttk.Button(actions,text='加入当前装备',command=self.add_current).pack(side='left');ttk.Button(actions,text='移除所选',command=self.remove).pack(side='left',padx=6);ttk.Button(actions,text='重新开始',command=self.reset).pack(side='right')
  self.note=tk.StringVar(value='临时收集，不绑定装备。同一部位会替换，请确认六件属于同一角色。')
  ttk.Label(body,textvariable=self.note,wraplength=490).pack(anchor='w',pady=10);self.refresh()
 def reset(self):
  self.items.clear();self.hero_id=self.app.selected_hero_id;self.refresh();self.note.set('临时记录已清空，可以读取当前角色的六件装备。')
 def remove(self):
  for slot in self.rows.selection():self.items.pop(slot,None)
  self.refresh()
 def add_current(self):
  gear=getattr(self.app,'last_gear',None)
  if gear is None:self.note.set('请先读取单件装备详情。');return
  self.add(gear)
 def add(self,gear):
  if self.hero_id!=self.app.selected_hero_id:self.collecting.set(False);self.note.set('角色已切换，暂停收集。请点重新开始，避免混入另一角色的装备。');return
  if gear.slot not in SLOTS or not gear.subs or len({s.key for s in gear.subs})!=len(gear.subs):self.note.set('部位或副属性不完整，请核对后重读。');return
  expected=3 if gear.grade=='英雄' and gear.enhance is not None and gear.enhance<12 else 4
  if len(gear.subs)<expected:self.note.set(f'本件应有{expected}条副属性，当前只有{len(gear.subs)}条，请核对。');return
  try:item_score(gear)
  except ValueError as error:self.note.set(str(error));return
  self.items[gear.slot]=deepcopy(gear);self.refresh();self.note.set(f'已更新{gear.slot}，共 {len(self.items)}/6 件。')
 def refresh(self):
  hero=next((h for h in self.app.hero_catalog['heroes'] if h['id']==self.hero_id),None);self.hero.configure(text=hero['name'] if hero else '临时六件装备')
  ready=len(self.items)==6;value=total_score(self.items) if ready else None
  self.total.configure(text=f'{value} GS' if ready else f'已读取 {len(self.items)}/6 件')
  self.rows.delete(*self.rows.get_children())
  for slot in SLOTS:
   gear=self.items.get(slot);self.rows.insert('', 'end',iid=slot,values=(slot,(gear.name or '已读取') if gear else '—',item_score(gear) if gear else '—'))
  ref=references().get('heroes',{}).get(hero['name_en'],{}) if hero else {};featured=max(ref.get('variants',[]),key=lambda x:x.get('sample_count',0),default=ref);score=featured.get('gear_score')
  self.reference.configure(text=(f'样本最多套装组参考：{score:g} GS'+(f' · 差值 {value-score:+g}' if ready else '')) if isinstance(score,(int,float)) else '当前英雄暂无同口径参考总分。')
  summary=getattr(self.app,'character_gs_label',None)
  if summary is not None:summary.configure(text=f'装备总分 {value} GS' if ready else f'装备总分 — · {len(self.items)}/6 件')

def open_total(app):
 win=getattr(app,'gear_total_window',None)
 if win is not None and win.winfo_exists():win.lift();return win
 app.gear_total_window=GearTotalWindow(app);return app.gear_total_window
