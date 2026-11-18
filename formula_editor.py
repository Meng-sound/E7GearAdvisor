"""Explicit formula editor; saving selects the custom dropdown mode."""
import json,tkinter as tk
from tkinter import ttk,filedialog,messagebox
from pathlib import Path
from core import LABELS
import scoring_settings as scoring
from ui_theme import BG,MUTED,SUCCESS,FONT
from scrollable_page import ScrollablePage
from local_json import read_json
def open_editor(parent,path,on_save):
 win=tk.Toplevel(parent);win.title('自定义算分算法');win.geometry(f'{min(1120,parent.winfo_screenwidth()-50)}x{min(720,parent.winfo_screenheight()-85)}');win.minsize(860,540);win.configure(bg=BG)
 profile=scoring.current();name=tk.StringVar(value=profile['name']);variables={}
 footer=ttk.Frame(win,padding=12);footer.pack(side='bottom',fill='x');page=ScrollablePage(win);page.pack(fill='both',expand=True);body=page.body
 ttk.Label(body,text='自定义算法',font=(FONT,16,'bold')).pack(anchor='w');ttk.Label(body,text='保存后切换到主界面的“自定义算法”；不覆盖两个 Fribbels 内置算法。',wraplength=700).pack(fill='x',pady=(2,12))
 ttk.Label(body,text='算法名称').pack(anchor='w');ttk.Entry(body,textvariable=name).pack(fill='x',pady=(3,9))
 formulas=ttk.Frame(body);formulas.pack(fill='x')
 for index,(key,label) in enumerate(LABELS.items()):
  row=ttk.Frame(formulas);row.grid(row=index//2,column=index%2,sticky='ew',padx=5,pady=3);formulas.columnconfigure(index%2,weight=1)
  ttk.Label(row,text=label,width=11).pack(side='left');var=tk.StringVar(value=profile['formulas'][key]);variables[key]=var;ttk.Entry(row,textvariable=var).pack(side='left',fill='x',expand=True)
 ttk.Label(body,text='变量：value、base、base_atk / base_hp / base_def / base_spd、level、enhance。支持 + - * / ** 和 min / max / abs / round；不执行 Python 代码。',wraplength=700,foreground=MUTED).pack(fill='x',pady=12)
 preview=tk.StringVar(value='读取装备后可预览分数');status=tk.StringVar();ttk.Label(body,textvariable=preview,font=(FONT,14,'bold'),foreground=SUCCESS).pack(anchor='w',pady=6);ttk.Label(body,textvariable=status,wraplength=700,justify='left').pack(fill='x')
 def values():return {'schema':1,'enabled':True,'name':name.get(),'formulas':{k:v.get() for k,v in variables.items()}}
 def preview_now(*_):
  try:
   data=scoring.validate(values());gear=parent.last_gear
   if gear is None or not gear.subs:preview.set('读取装备后可预览分数');return
   base={k:float(v.get()) for k,v in parent.base.items()};parts=[(LABELS[s.key],scoring.score_stat(s,base,gear,data)) for s in gear.subs];preview.set(f'当前装备 · 自定义原始分 {sum(v for _,v in parts):.3f}');status.set('；'.join(f'{label} {value:.3f}分' for label,value in parts))
  except (ValueError,TypeError) as error:preview.set('公式待校验');status.set(str(error))
 for var in [name,*variables.values()]:var.trace_add('write',preview_now)
 def apply(data):
  clean=scoring.validate(data);name.set(clean['name'])
  for key,var in variables.items():var.set(clean['formulas'][key])
 def import_json():
  filename=filedialog.askopenfilename(parent=win,filetypes=[('算分算法 JSON','*.json')])
  if filename:
   try:apply(read_json(filename))
   except (OSError,ValueError) as error:messagebox.showerror('未导入',str(error),parent=win)
 def export_json():
  try:data=scoring.validate(values())
  except ValueError as error:messagebox.showerror('未导出',str(error),parent=win);return
  filename=filedialog.asksaveasfilename(parent=win,initialfile='custom-scoring.json',defaultextension='.json')
  if filename:Path(filename).write_text(json.dumps(data,ensure_ascii=False,indent=2),'utf8')
 def save():
  try:scoring.save(path,values());parent.score_mode.set('custom');on_save();win.destroy()
  except (OSError,ValueError) as error:messagebox.showerror('未保存',str(error),parent=win)
 ttk.Button(footer,text='恢复 Fribbels 系数',command=lambda:apply(scoring.DEFAULT)).pack(side='left');ttk.Button(footer,text='导入 JSON',command=import_json).pack(side='left',padx=5);ttk.Button(footer,text='导出 JSON',command=export_json).pack(side='left');ttk.Button(footer,text='保存并应用',command=save).pack(side='right')
 ttk.Button(body,text='自定义算法的分数门槛…',command=lambda:__import__('threshold_settings').open_editor(parent,parent.threshold_path,on_save,'custom')).pack(anchor='w',pady=12);preview_now();return win
