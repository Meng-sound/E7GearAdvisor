"""Supervise the vendored E7Pilot engine without importing its core into the UI."""
import json,os,subprocess,sys,tempfile,threading,time
from dataclasses import asdict
from pathlib import Path

class PilotRunner:
 def __init__(self,target,config,events,seconds=None,user_dir=None):
  self.target=target;self.config=config;self.events=events
  self.seconds=None
  self.user_dir=str(user_dir or Path(__file__).parent/'userdata')
  self.cancel=threading.Event();self.paused=threading.Event();self.thread=None;self.process=None;self.status='idle';self.lock=threading.Lock()
 def emit(self,event,**values):self.events.put(dict(event=event,**values))
 def alive(self):return self.thread is not None and self.thread.is_alive()
 def start(self):
  self.status='running';self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
 def control(self,**value):
  with self.lock:
   if self.process and self.process.poll() is None:
    try:self.process.stdin.write(json.dumps(value)+'\n');self.process.stdin.flush()
    except (OSError,ValueError):pass
 def pause(self):self.paused.set();self.status='paused';self.control(pause=True)
 def resume(self):self.paused.clear();self.status='running';self.control(pause=False)
 def stop(self):self.cancel.set();self.status='stopping';self.control(stop=True)
 def run(self):
  try:
   from process_permissions import input_permission_error
   import emulator
   emulated=bool((emulator.identify(self.target.get('title'),self.target.get('class_name'),self.target.get('process')) or {}).get('kind')=='emulator')
   if not emulated:
    error=input_permission_error(self.target)
    if error:raise RuntimeError(error)
   with tempfile.TemporaryDirectory(prefix='e7-pilot-') as folder:
    from pilot_settings import load
    request=Path(folder)/'request.json';request.write_text(json.dumps(dict(target=self.target,config={'mode':self.config.mode},input_backend=emulator.DEFAULT_INPUT,source_settings=load(self.user_dir),user_dir=self.user_dir),ensure_ascii=False),'utf8')
    python=Path(sys.executable).with_name('python.exe')
    if not python.is_file():python=Path(sys.executable)
    environment=dict(os.environ,PYTHONIOENCODING='utf-8',PYTHONUTF8='1')
    self.process=subprocess.Popen([str(python),'-u','-B',str(Path(__file__).parent/'pilot_worker.py'),str(request)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf8',errors='replace',env=environment,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if self.cancel.is_set():self.control(stop=True)
    elif self.paused.is_set():self.control(pause=True)
    for line in self.process.stdout:
     text=line.strip()
     if text:self.emit('status',text=text)
    self.process.wait()
    if self.process.returncode:self.emit('status',text='任务异常退出，请查看上方完整错误。')
  except Exception as error:self.emit('status',text='任务未启动：'+str(error))
  finally:
   self.status='stopped';self.cancel.set()
   self.emit('done',source_engine=True,actions=0,gold=0,sky=0,text='任务已结束，操作和资源记录请查看运行日志。')
