"""Formula editor with a current-equipment preview and explicit activation."""
import json,tkinter as tk
from tkinter import ttk,filedialog,messagebox
from pathlib import Path
from core import LABELS
import scoring_settings as scoring
from ui_theme import BG,CARD,FIELD,TEXT,MUTED,ACCENT,SUCCESS,FONT,Card,Button,dark_title

def open_editor(parent,path,on_save):
 win=tk.Toplevel(parent);win.title('自定义算分算法');win.geometry('1040x760');win.configure(bg=BG);profile=scoring.current();variables={};name=tk.StringVar(value=profile['name']);enabled=tk.BooleanVar(value=True)
 head=tk.Frame(win,bg=BG);head.pack(fill='x',padx=22,pady=(18,14));tk.Label(head,text='自定义算分算法',bg=BG,fg=TEXT,font=(FONT,18,'bold')).pack(anchor='w');tk.Label(head,text='编辑词条算式 · 预览当前装备 · 保存后切换到自定义算法',bg=BG,fg=MUTED,font=(FONT,9)).pack(anchor='w',pady=(3,0))
 body=tk.Frame(win,bg=BG);body.pack(fill='both',expand=True,padx=20)
 right=Card(body,height=530);right.pack(side='right',fill='y',padx=(15,0));right.configure(width=300);right.pack_propagate(False)
 left=Card(body,height=530);left.pack(side='left',fill='both',expand=True)
 top=tk.Frame(left.body,bg=CARD);top.pack(fill='x',pady=(0,12));tk.Label(top,text='算法名称',bg=CARD,fg=MUTED,font=(FONT,9)).pack(side='left',padx=(0,10));ttk.Entry(top,textvariable=name,width=24).pack(side='left',fill='x',expand=True)
 for key,label in LABELS.items():
  row=tk.Frame(left.body,bg=CARD);row.pack(fill='x',pady=3);tk.Label(row,text=label,bg=CARD,fg=TEXT,font=(FONT,10),width=12,anchor='w').pack(side='left');var=tk.StringVar(value=profile['formulas'][key]);variables[key]=var;ttk.Entry(row,textvariable=var).pack(side='left',fill='x',expand=True)
 tk.Label(right.body,text='当前装备预览',bg=CARD,fg=TEXT,font=(FONT,12,'bold')).pack(anchor='w')
 preview=tk.Label(right.body,text='—',bg=CARD,fg=SUCCESS,font=(FONT,35,'bold'));preview.pack(anchor='w',pady=(8,10));details=tk.Label(right.body,text='',bg=CARD,fg=MUTED,font=(FONT,9),wraplength=250,justify='left');details.pack(anchor='w')
 tk.Label(right.body,text='变量与函数',bg=CARD,fg=TEXT,font=(FONT,11,'bold')).pack(anchor='w',pady=(22,8))
 tk.Label(right.body,text='value：当前词条数值\nbase：固定攻/防/生命对应基础值\n其他词条的base为1\n\nbase_atk / base_hp / base_def\nbase_spd：角色基础速度\nlevel / enhance：装备等级和强化\n\n支持 + - * / **\nmin、max、abs、round\n总分为已出现词条的算式结果相加。',bg=CARD,fg=MUTED,font=(FONT,9),wraplength=250,justify='left').pack(anchor='w')
 tk.Label(right.body,text='更换算法后，请同步检查强化门槛。',bg=CARD,fg='#e4bd7c',font=(FONT,9),wraplength=250,justify='left').pack(anchor='w',pady=(20,0))
 status=tk.StringVar(value='默认算式与当前角色换算规则一致。只有保存后才会改变评分。');ttk.Label(win,textvariable=status,wraplength=990).pack(fill='x',padx=22,pady=12)
 def values():return {'schema':1,'enabled':enabled.get(),'name':name.get(),'formulas':{k:v.get() for k,v in variables.items()}}
 def preview_now(*_):
  if not win.winfo_exists():return
  try:
   data=scoring.validate(values());gear=parent.last_gear
   if gear is None or not gear.subs:preview.configure(text='—');details.configure(text='读取装备后，这里显示按当前算式计算的分数。');return
   base={k:float(v.get()) for k,v in parent.base.items()};parts=[(LABELS[s.key],scoring.score_stat(s,base,gear,data)) for s in gear.subs];preview.configure(text=f'{sum(v for _,v in parts):.2f}');details.configure(text='\n'.join(f'{label}  {value:.2f} 分' for label,value in parts));status.set('预览使用当前装备，尚未改变正在使用的算法。')
  except (ValueError,TypeError) as e:preview.configure(text='待修正');details.configure(text=str(e))
 for var in [name,enabled,*variables.values()]:var.trace_add('write',preview_now)
 def apply(data):
  clean=scoring.validate(data);name.set(clean['name']);enabled.set(clean['enabled'])
  for k,var in variables.items():var.set(clean['formulas'][k])
 def reset():apply(scoring.DEFAULT)
 def import_json():
  filename=filedialog.askopenfilename(parent=win,filetypes=[('算分算法JSON','*.json')])
  if not filename:return
  try:apply(__import__('local_json').read_json(filename))
  except (ValueError,OSError) as e:messagebox.showerror('导入失败',str(e),parent=win)
 def export_json():
  try:data=scoring.validate(values())
  except ValueError as e:messagebox.showerror('无法导出',str(e),parent=win);return
  filename=filedialog.asksaveasfilename(parent=win,initialfile='custom-scoring.json',defaultextension='.json',filetypes=[('算分算法JSON','*.json')])
  if filename:Path(filename).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
 def save():
  try:scoring.save(path,values());parent.score_mode.set('custom');on_save();win.destroy()
  except (ValueError,OSError) as e:messagebox.showerror('未保存',str(e),parent=win)
 footer=tk.Frame(win,bg=BG);footer.pack(fill='x',padx=20,pady=(0,18));Button(footer,'恢复默认',reset,width=110).pack(side='left');Button(footer,'导入 JSON',import_json,width=110).pack(side='left',padx=7);Button(footer,'导出 JSON',export_json,width=110).pack(side='left');Button(footer,'保存并重新计算',save,width=180,primary=True).pack(side='right');preview_now()
 return win
