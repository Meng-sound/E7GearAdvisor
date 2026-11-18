"""Release notification and user-triggered verified download UI."""
import json,os,queue,subprocess,threading,tkinter as tk,webbrowser
from tkinter import ttk,messagebox
from pathlib import Path
from software_update import repository,check_release,download_release,DEFAULT_REPOSITORY
from app_version import VERSION

def load_config(app):
 try:
  value=json.loads((app.user_dir/'software-update.json').read_text('utf8'))
  return value if isinstance(value,dict) else {}
 except (OSError,ValueError):return {}

class UpdateWindow(tk.Toplevel):
 def __init__(self,app,release=None):
  super().__init__(app);self.app=app;self.release=release;self.downloaded=None;self.events=queue.Queue();self.busy=False
  self.title('软件更新');self.geometry('630x550');self.minsize(540,480);self.configure(bg='#171b23');self.transient(app)
  frame=ttk.Frame(self,padding=18);frame.pack(fill='both',expand=True)
  ttk.Label(frame,text='软件更新',font=('Microsoft YaHei UI',18,'bold')).pack(anchor='w')
  ttk.Label(frame,text='当前版本 '+VERSION+' · 从你配置的 GitHub 仓库读取公开 Release').pack(anchor='w',pady=8)
  config=load_config(app);self.repo=tk.StringVar(value=config.get('repository') or DEFAULT_REPOSITORY);self.auto=tk.BooleanVar(value=bool(config.get('startup_check',False)))
  ttk.Label(frame,text='GitHub 仓库：owner/repo 或仓库链接').pack(anchor='w');ttk.Entry(frame,textvariable=self.repo).pack(fill='x',pady=5)
  options=ttk.Frame(frame);options.pack(fill='x');ttk.Checkbutton(options,text='启动时自动检查，有新版时弹窗',variable=self.auto).pack(side='left');ttk.Button(options,text='保存配置',command=self.save).pack(side='right')
  self.status=tk.StringVar(value='填写仓库后点击检查更新。');ttk.Label(frame,textvariable=self.status,wraplength=580).pack(fill='x',pady=10)
  self.notes=tk.Text(frame,height=10,wrap='word',bg='#202630',fg='#edf3fb',insertbackground='white',relief='flat',font=('Microsoft YaHei UI',10));self.notes.pack(fill='both',expand=True)
  self.progress=ttk.Progressbar(frame,maximum=100);self.progress.pack(fill='x',pady=10)
  actions=ttk.Frame(frame);actions.pack(fill='x');self.check_button=ttk.Button(actions,text='检查更新',command=self.check);self.check_button.pack(side='left');self.download_button=ttk.Button(actions,text='下载新版',command=self.download,state='disabled');self.download_button.pack(side='left',padx=8);self.start_button=ttk.Button(actions,text='启动新版',command=self.start,state='disabled');self.start_button.pack(side='left');ttk.Button(actions,text='发布页面',command=self.page).pack(side='right')
  ttk.Label(frame,text='下载经过 SHA256 校验；保留现有配置。不会自动覆盖正在运行的程序。',wraplength=580).pack(anchor='w',pady=(10,0))
  if release:self.show_release(release)
  self.after(100,self.poll)
 def save(self):
  try:
   repo=repository(self.repo.get()) if self.repo.get().strip() else ''
   if self.auto.get() and not repo:raise ValueError('开启启动检查前请填写仓库')
   (self.app.user_dir/'software-update.json').write_text(json.dumps({'repository':repo,'startup_check':self.auto.get()},ensure_ascii=False,indent=2),'utf8');self.repo.set(repo);self.status.set('已保存更新配置。');return repo
  except (OSError,ValueError) as error:self.status.set(str(error));return None
 def work(self,job,label):
  if self.busy:return
  self.busy=True;self.status.set(label);self.check_button.configure(state='disabled');self.download_button.configure(state='disabled')
  def worker():
   try:self.events.put(('done',job()))
   except Exception as error:self.events.put(('error',str(error)[:600]))
  threading.Thread(target=worker,daemon=True).start()
 def check(self):
  if self.busy:return
  if not self.repo.get().strip():
   self.status.set('尚未配置发布仓库，请填写 GitHub 仓库地址后检查更新。');return
  repo=self.save()
  if not repo:return
  self.release=None;self.downloaded=None;self.start_button.configure(state='disabled');self.work(lambda:('release',check_release(repo)),'正在检查 GitHub Release…')
 def show_release(self,release):
  self.release=release;self.status.set('发现新版 '+release['tag'] if release['newer'] else '当前版本已是最新，或比公开稳定版更新。')
  self.notes.delete('1.0','end');self.notes.insert('1.0',release['notes']);self.download_button.configure(state='normal' if release['newer'] and release['asset'] else 'disabled')
  if release['newer'] and not release['asset']:self.status.set('发现新版，但 Release 未提供适用的 Windows 文件，请查看发布页面。')
 def download(self):
  if not self.release:return
  data=self.release
  self.work(lambda:('download',download_release(data,self.app.user_dir/'updates',lambda size,total:self.events.put(('progress',(size,total))))),'正在下载并校验新版…')
 def start(self):
  if not self.downloaded:return
  path=Path(self.downloaded)
  if path.suffix.lower()=='.zip':os.startfile(str(path.parent));return
  if messagebox.askyesno('启动新版','新版将使用原有正式配置启动。现在启动吗？',parent=self):subprocess.Popen([str(path)],cwd=str(path.parent),shell=False)
 def page(self):
  if self.release:webbrowser.open(self.release['page'])
  else:
   try:webbrowser.open('https://github.com/'+repository(self.repo.get())+'/releases')
   except ValueError as error:self.status.set(str(error))
 def poll(self):
  try:
   while True:
    kind,data=self.events.get_nowait()
    if kind=='progress':self.progress.configure(value=data[0]/max(1,data[1])*100);continue
    self.busy=False;self.check_button.configure(state='normal')
    if kind=='error':self.status.set('更新未完成：'+data);continue
    if data[0]=='release':self.show_release(data[1])
    else:
     self.downloaded=data[1];self.progress.configure(value=100);self.status.set('下载完成，SHA256 校验通过。');self.start_button.configure(text='打开下载目录' if self.downloaded.suffix.lower()=='.zip' else '启动新版',state='normal')
  except queue.Empty:pass
  self.after(100,self.poll)

def open_update(app,release=None):
 existing=getattr(app,'software_update_window',None)
 if existing is not None and existing.winfo_exists():
  if release:existing.show_release(release)
  existing.lift();return existing
 app.software_update_window=UpdateWindow(app,release);return app.software_update_window

def startup_check(app):
 config=load_config(app)
 if not config.get('startup_check') or not config.get('repository'):return
 results=queue.Queue()
 def worker():
  try:results.put(check_release(config['repository']))
  except Exception:results.put(None)
 def poll():
  try:release=results.get_nowait()
  except queue.Empty:app.after(200,poll);return
  if release and release['newer']:open_update(app,release)
 threading.Thread(target=worker,daemon=True).start();app.after(200,poll)
