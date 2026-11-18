"""Bounded user-file JSON imports; unrelated to network-response limits."""
import json,re
from pathlib import Path
_limit_mb=100
def configure(path):
 global _limit_mb
 _limit_mb=100
 if Path(path).exists():_limit_mb=validate_limit(json.loads(Path(path).read_text('utf8')).get('limit_mb'))
def validate_limit(value):
 if isinstance(value,bool) or not isinstance(value,int) or not 10<=value<=256:raise ValueError('JSON 文件上限应为10到256MB的整数')
 return value
def limit_mb():return _limit_mb
def save_limit(path,value):
 global _limit_mb
 value=validate_limit(value);path=Path(path);tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps({'limit_mb':value}),'utf8');tmp.replace(path);_limit_mb=value
def unique_object(pairs):
 result={}
 for key,value in pairs:
  if key in result:raise ValueError('JSON重复字段：'+key)
  result[key]=value
 return result
def read_json(path):
 limit=_limit_mb*1024*1024;path=Path(path)
 if path.stat().st_size>limit:raise ValueError(f'JSON超过当前{_limit_mb}MB上限，请在导入设置中调整')
 with path.open('rb') as stream:raw=stream.read(limit+1)
 if len(raw)>limit:raise ValueError(f'JSON超过当前{_limit_mb}MB上限')
 # Bound nesting before the C JSON parser, including runtimes with a raised
 # recursion limit. Braces in quoted text do not count toward structural depth.
 depth=0;quoted=False;escaped=False;previous=-2
 for token in re.finditer(rb'["\\{}\[\]]',raw):
  char=token.group();position=token.start()
  if position>previous+1:escaped=False
  if quoted:
   if char==b'\\':escaped=not escaped
   else:
    if char==b'"' and not escaped:quoted=False
    escaped=False
  elif char==b'"':quoted=True;escaped=False
  elif char in (b'{',b'['):
   depth+=1
   if depth>100:raise ValueError('JSON 嵌套不能超过100层')
  elif char in (b'}',b']'):depth-=1
  previous=position
 try:return json.loads(raw.decode('utf-8-sig'),object_pairs_hook=unique_object,parse_constant=lambda value:(_ for _ in ()).throw(ValueError('JSON不能包含'+value)))
 except RecursionError:raise ValueError('JSON 嵌套层数过多') from None
def open_settings(parent,path):
 import tkinter as tk
 from tkinter import ttk,messagebox
 win=tk.Toplevel(parent);win.title('本地 JSON 导入设置');win.geometry('480x220');frame=ttk.Frame(win,padding=16);frame.pack(fill='both',expand=True)
 ttk.Label(frame,text='本地文件上限（MB，10–256）').pack(anchor='w');var=tk.StringVar(value=str(_limit_mb));ttk.Spinbox(frame,from_=10,to=256,textvariable=var).pack(fill='x',pady=8)
 ttk.Label(frame,text='默认100MB。导入会先校验格式，再写入；网络响应上限不随此项改变。',wraplength=440).pack(anchor='w')
 def save():
  try:save_limit(path,int(var.get()));win.destroy()
  except (OSError,ValueError) as error:messagebox.showerror('未保存',str(error),parent=win)
 ttk.Button(frame,text='保存上限',command=save).pack(side='bottom',anchor='e')
 return win
