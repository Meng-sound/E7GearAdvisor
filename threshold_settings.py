"""User-editable score/speed gates, separate from suitability weights."""
import copy,json,math
from pathlib import Path
DEFAULTS={'left':{'purple':20,'red':22,'6':34,'9':40,'12':46,'15':52,'90':65},'right':{'purple':18,'red':20,'6':32,'9':38,'12':44,'15':50,'90':63},'speed':{'entry':4,'6':10,'12':15,'15':15,'90':20,'usable_score':40}}
_settings=copy.deepcopy(DEFAULTS)
MODES={'gs':'Fribbels 装备 GS','role':'Fribbels 角色换算','custom':'自定义算法'}
_profiles={mode:copy.deepcopy(DEFAULTS) for mode in MODES}
def current(mode='role'):
 if mode not in MODES:raise ValueError('未知算分算法')
 return copy.deepcopy(_profiles[mode])
def validate(data):
 if not isinstance(data,dict) or set(data)!=set(DEFAULTS):raise ValueError('门槛配置需包含left、right、speed')
 clean=copy.deepcopy(DEFAULTS)
 for group,values in DEFAULTS.items():
  if not isinstance(data[group],dict) or set(data[group])!=set(values):raise ValueError(group+'门槛字段不完整')
  for key,value in data[group].items():
   if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=1000:raise ValueError('门槛必须是0至1000的有限数字')
   clean[group][key]=value
 for side in ('left','right'):
  v=clean[side];seq=[max(v['purple'],v['red']),v['6'],v['9'],v['12'],v['15'],v['90']]
  if seq!=sorted(seq):raise ValueError('后续阶段的门槛不能低于前一阶段')
 if clean['speed']['usable_score']>clean['left']['12']:raise ValueError('追速保留分不能高于左侧+12门槛')
 return clean
def configure(path):
 global _settings,_profiles
 _profiles={mode:copy.deepcopy(DEFAULTS) for mode in MODES}
 if Path(path).exists():
  data=json.loads(Path(path).read_text(encoding='utf8'))
  if isinstance(data,dict) and data.get('schema')==2:
   if set(data.get('profiles',{}))!=set(MODES):raise ValueError('算法门槛配置不完整')
   _profiles={mode:validate(data['profiles'][mode]) for mode in MODES}
  else:
   legacy=validate(data)
   _profiles={mode:copy.deepcopy(legacy) for mode in MODES}
 _settings=copy.deepcopy(_profiles['role'])
def save(path,data,mode='role'):
 global _settings,_profiles
 if mode not in MODES:raise ValueError('未知算分算法')
 clean=validate(data);profiles=copy.deepcopy(_profiles);profiles[mode]=clean
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.tmp')
 tmp.write_text(json.dumps({'schema':2,'profiles':profiles},ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(path)
 _profiles=profiles;_settings=copy.deepcopy(_profiles['role'])

def open_editor(parent,path,on_save,mode='role'):
 import tkinter as tk
 from tkinter import ttk,messagebox
 win=tk.Toplevel(parent);win.configure(bg='#0e1522');win.geometry(f'620x{min(730,parent.winfo_screenheight()-70)}');win.minsize(540,450)
 from scrollable_page import ScrollablePage
 page=ScrollablePage(win,padding=14);page.pack(fill='both',expand=True);frame=page.body;variables={}
 win.title(MODES[mode]+' · 分数与速度门槛')
 ttk.Label(frame,text=MODES[mode]+'：各算法分别保存门槛；比较未取整原始分。',wraplength=570).pack(anchor='w',pady=(0,10))
 grid=ttk.Frame(frame);grid.pack(fill='x')
 for col,side in enumerate(('left','right','speed')):
  cell=ttk.Frame(grid);cell.grid(row=0,column=col,sticky='n',padx=9);ttk.Label(cell,text={'left':'左三件','right':'右三件','speed':'左侧追速'}[side]).pack(anchor='w')
  for key,value in current(mode)[side].items():
   label={'purple':'未强化紫装','red':'未强化红装','entry':'初始速度','usable_score':'追速能用分','90':'重铸后优秀'}.get(key,'+'+key+('速度' if side=='speed' else '分数'))
   ttk.Label(cell,text=label).pack(anchor='w',pady=(3,1));var=tk.StringVar(value=str(value));variables[side,key]=var;ttk.Entry(cell,textvariable=var,width=13,style='Compact.TEntry').pack(fill='x')
 ttk.Label(frame,text='右三件固定攻／防／生命主属性仍不推荐强化；蓝装仍按既定规则分解。',wraplength=570).pack(anchor='w',pady=12)
 def apply():
  try:
   data={group:{key:float(variables[group,key].get()) for key in values} for group,values in DEFAULTS.items()};save(path,data,mode);on_save();win.destroy()
  except (ValueError,OSError) as e:messagebox.showerror('未保存',str(e),parent=win)
 def reset():
  for (group,key),var in variables.items():var.set(str(DEFAULTS[group][key]))
 buttons=ttk.Frame(frame);buttons.pack(fill='x');ttk.Button(buttons,text='恢复流程图默认值',command=reset).pack(side='left');ttk.Button(buttons,text='保存并重新计算',command=apply).pack(side='right')
 return win
