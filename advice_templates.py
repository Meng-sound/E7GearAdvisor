"""User wording customizations do not alter scores, gates, or decisions."""
import copy,json
from pathlib import Path
from ui_theme import BG,FIELD,TEXT
LABELS={'enhance':'继续强化','reforge':'考虑重铸','discard':'分解候选','backup':'留作替补','usable':'保留使用','excellent':'重点保留'}
_templates={key:'' for key in LABELS}
def configure(path):
 global _templates
 _templates={key:'' for key in LABELS}
 if Path(path).exists():_templates=validate(json.loads(Path(path).read_text('utf8')))
def validate(data):
 if not isinstance(data,dict) or set(data)-set(LABELS):raise ValueError('建议说明类型无效')
 result={key:data.get(key,'') for key in LABELS}
 if any(not isinstance(v,str) or len(v)>1000 for v in result.values()):raise ValueError('每条建议说明应为1000字以内文本')
 return result
def current():return copy.deepcopy(_templates)
def text(kind):return _templates.get(kind,'')
def save(path,data):
 global _templates
 clean=validate(data);path=Path(path);tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(clean,ensure_ascii=False,indent=2),'utf8');tmp.replace(path);_templates=clean
def open_editor(parent,path,on_save):
 import tkinter as tk
 from tkinter import ttk,messagebox
 win=tk.Toplevel(parent);win.title('自定义强化建议说明');win.configure(bg=BG);win.geometry(f'640x{min(740,parent.winfo_screenheight()-70)}');win.minsize(520,450)
 footer=ttk.Frame(win,padding=12);footer.pack(side='bottom',fill='x');bar=ttk.Scrollbar(win);bar.pack(side='right',fill='y');canvas=tk.Canvas(win,bg=BG,highlightthickness=0,yscrollcommand=bar.set);canvas.pack(fill='both',expand=True);bar.configure(command=canvas.yview);body=ttk.Frame(canvas,padding=12);item=canvas.create_window(0,0,window=body,anchor='nw');body.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')));canvas.bind('<Configure>',lambda e:canvas.itemconfigure(item,width=e.width));win.bind('<MouseWheel>',lambda e:canvas.yview_scroll(-int(e.delta/120),'units'))
 ttk.Label(body,text='空白使用默认说明；自定义文字附加显示，不改变得分、门槛和判断。',wraplength=580).pack(fill='x',pady=(0,8));widgets={}
 for key,label in LABELS.items():
  ttk.Label(body,text=label).pack(anchor='w');field=tk.Text(body,height=3,wrap='word',bg=FIELD,fg=TEXT,insertbackground=TEXT,relief='flat');field.insert('1.0',_templates[key]);field.pack(fill='x',pady=(3,10));widgets[key]=field
 def apply(reset=False):
  try:save(path,{k:'' if reset else w.get('1.0','end-1c').strip() for k,w in widgets.items()});on_save();win.destroy()
  except (OSError,ValueError) as error:messagebox.showerror('未保存',str(error),parent=win)
 ttk.Button(footer,text='恢复默认说明',command=lambda:apply(True)).pack(side='left');ttk.Button(footer,text='保存说明',command=apply).pack(side='right');return win
