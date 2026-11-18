"""Optional external executable launcher; no optimizer or game importer is bundled."""
import json,os,subprocess,tkinter as tk
from pathlib import Path
from tkinter import ttk,filedialog,messagebox

def load_path(config):
 try:
  value=json.loads(Path(config).read_text('utf8')).get('executable','')
  return value if isinstance(value,str) else ''
 except (OSError,ValueError,AttributeError):return ''

def validate_path(value):
 path=Path(value.strip().strip('"'))
 if not value.strip() or not path.is_absolute() or path.suffix.lower()!='.exe' or not path.is_file():
  raise ValueError('请选择已安装的配装器 EXE 文件。')
 return path

def save_path(config,value):
 path=validate_path(value) if value.strip() else None
 config=Path(config);config.parent.mkdir(parents=True,exist_ok=True)
 temp=config.with_suffix('.tmp');temp.write_text(json.dumps({'executable':str(path) if path else ''},ensure_ascii=False,indent=2),'utf8');os.replace(temp,config)

def launch(value):
 path=validate_path(value)
 return subprocess.Popen([str(path)],cwd=str(path.parent),shell=False)

def open_interface(app):
 existing=getattr(app,'optimizer_interface_window',None)
 if existing is not None and existing.winfo_exists():existing.lift();return existing
 window=tk.Toplevel(app);app.optimizer_interface_window=window;window.title('配装器接口');window.geometry('650x285');window.minsize(560,285);window.configure(bg='#171b23');window.transient(app)
 frame=ttk.Frame(window,padding=20);frame.pack(fill='both',expand=True)
 ttk.Label(frame,text='外部配装器启动入口',font=('Microsoft YaHei UI',16,'bold')).pack(anchor='w')
 ttk.Label(frame,text='暂未内置配装器。可以选择本机配装器程序，今后从这里启动。\n此接口只启动程序，尚不传输英雄或装备数据。',wraplength=590).pack(fill='x',pady=(12,18))
 config=app.user_dir/'optimizer-interface.json';value=tk.StringVar(value=load_path(config));row=ttk.Frame(frame);row.pack(fill='x')
 ttk.Entry(row,textvariable=value).pack(side='left',fill='x',expand=True)
 def browse():
  path=filedialog.askopenfilename(parent=window,title='选择配装器程序',filetypes=[('Windows 程序','*.exe')])
  if path:value.set(path)
 ttk.Button(row,text='选择 EXE',command=browse).pack(side='left',padx=(8,0))
 status=tk.StringVar(value='未配置程序时，可留空保存。');ttk.Label(frame,textvariable=status).pack(anchor='w',pady=12)
 def save():
  try:save_path(config,value.get());status.set('已保存启动入口。')
  except (OSError,ValueError) as error:messagebox.showerror('未保存',str(error),parent=window)
 def start():
  try:launch(value.get());status.set('已启动外部配装器。')
  except (OSError,ValueError) as error:messagebox.showerror('未启动',str(error),parent=window)
 actions=ttk.Frame(frame);actions.pack(fill='x');ttk.Button(actions,text='清空路径',command=lambda:value.set('')).pack(side='left');ttk.Button(actions,text='启动配装器',command=start).pack(side='right');ttk.Button(actions,text='保存设置',command=save).pack(side='right',padx=8)
 return window
