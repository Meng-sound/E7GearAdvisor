"""Persistent, process-isolated WGC capture. One PNG reply per requested frame."""
import ctypes,json,os,queue,subprocess,sys,tempfile,threading,time
from ctypes import wintypes
from pathlib import Path

class StreamCapture:
 def __init__(self,target):
  self.target=dict(target);self.process=None;self.failed=False;self.responses=queue.Queue()
  self.directory=tempfile.TemporaryDirectory(prefix='e7-stream-')
 def __call__(self,target):
  from window_capture import capture_game_window
  if target.get('capture_mode')=='visible' or self.failed:return capture_game_window(target)
  try:
   if self.process is None:
    self.process=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),json.dumps(self.target,ensure_ascii=False),self.directory.name],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    def read():
     for line in self.process.stdout:
      try:self.responses.put(json.loads(line))
      except ValueError:pass
     self.responses.put({'error':'后台取图进程已结束'})
    threading.Thread(target=read,daemon=True).start()
   self.process.stdin.write('capture\n');self.process.stdin.flush()
   response=self.responses.get(timeout=6)
   if response.get('error'):raise RuntimeError(response['error'])
   from PIL import Image
   with Image.open(Path(self.directory.name)/'frame.png') as image:picture=image.copy()
   picture.info['capture_backend']=response.get('backend') or 'Windows图形捕获（常驻，支持遮挡）'
   picture.info['loading']=bool(response.get('loading',False));return picture
  except (OSError,RuntimeError,queue.Empty):
   self.failed=True;self.close();return capture_game_window(target)
 def close(self):
  if self.process:
   try:self.process.stdin.close();self.process.wait(timeout=2)
   except (OSError,subprocess.TimeoutExpired):self.process.kill();self.process.wait()
   self.process=None
  self.directory.cleanup()

def serve(target,directory):
 sys.path.insert(0,str(Path(__file__).parent/'neural'))
 from windows_capture import WindowsCapture
 from PIL import Image,ImageStat
 import emulator
 # MuMu's device frame is native resolution, so a small/scaled/covered window no
 # longer limits the frame. Other emulators keep the window path (ADB is slower).
 device=None
 if emulator.prefers_native_capture(target.get('title')):
  try:device=emulator.open_input(target,backend='emulator')
  except (OSError,RuntimeError):device=None
 if device is not None:
  try:
   for request in sys.stdin:
    if request.strip()!='capture':continue
    picture=device.capture().convert('RGB')
    stat=ImageStat.Stat(picture.resize((64,64)))
    picture.save(Path(directory)/'frame.png',compress_level=0)
    print(json.dumps({'ok':True,'loading':max(stat.mean)<3,
                      'backend':f"{target.get('emulator') or '模拟器'}原生取图（常驻，支持遮挡/最小化）"}),flush=True)
  finally:device.close()
  return
 user=ctypes.WinDLL('user32',use_last_error=True)
 user.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
 user.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
 user.GetClientRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
 user.ClientToScreen.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.POINT)]
 user.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
 user.IsIconic.argtypes=[wintypes.HWND]
 def bounds():
  hwnd=target['hwnd'];pid=wintypes.DWORD();title=ctypes.create_unicode_buffer(1024)
  user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid));user.GetWindowTextW(hwnd,title,len(title))
  if pid.value!=target['pid'] or title.value!=target['title'] or user.IsIconic(hwnd):raise RuntimeError('游戏窗口发生变化或已最小化')
  client=wintypes.RECT();origin=wintypes.POINT();rect=wintypes.RECT()
  user.GetClientRect(hwnd,ctypes.byref(client));user.ClientToScreen(hwnd,ctypes.byref(origin));user.GetWindowRect(hwnd,ctypes.byref(rect))
  extended=wintypes.RECT();dwm=ctypes.WinDLL('dwmapi');dwm.DwmGetWindowAttribute.argtypes=[wintypes.HWND,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD]
  if dwm.DwmGetWindowAttribute(hwnd,9,ctypes.byref(extended),ctypes.sizeof(extended))!=0:extended=rect
  return (client.right,client.bottom,origin.x,origin.y),[(rect.left,rect.top,rect.right,rect.bottom),(extended.left,extended.top,extended.right,extended.bottom)]
 initial,_=bounds();condition=threading.Condition();latest=[None];generation=[0];closed=[False];updated=[0.0]
 session=WindowsCapture(cursor_capture=False,draw_border=False,minimum_update_interval=target.get('capture_interval_ms',80),window_hwnd=target['hwnd'])
 @session.event
 def on_frame_arrived(frame,control):
  with condition:latest[0]=frame.frame_buffer[:,:,:3][:,:,::-1].copy();generation[0]+=1;updated[0]=time.monotonic();condition.notify_all()
 @session.event
 def on_closed():
  with condition:closed[0]=True;condition.notify_all()
 controller=session.start_free_threaded()
 try:
  for request in sys.stdin:
   if request.strip()!='capture':continue
   current,areas=bounds()
   if current[:2]!=initial[:2]:raise RuntimeError('游戏尺寸改变，请重新开始任务')
   with condition:
    old=generation[0]
    if latest[0] is None or time.monotonic()-updated[0]>.08:
     condition.wait_for(lambda:generation[0]>old or closed[0],timeout=.12 if latest[0] is not None else 3)
    if latest[0] is None or closed[0]:raise RuntimeError('未获得有效游戏画面')
    picture=Image.fromarray(latest[0].copy())
   width,height,x,y=current
   if picture.size!=(width,height):
    area=min(areas,key=lambda a:abs(a[2]-a[0]-picture.width)+abs(a[3]-a[1]-picture.height))
    left,top=x-area[0],y-area[1]
    if min(left,top)<0 or left+width>picture.width or top+height>picture.height:raise RuntimeError('客户区边界不一致')
    picture=picture.crop((left,top,left+width,top+height))
   import emulator
   if target.get('source')=='emulator' or (not target.get('preview_only') and emulator.is_game_window(target.get('title'))):
    # Emulator windows carry a tab bar / toolbar; keep frames identical to the device frame.
    picture=emulator.crop_content(picture)
   if target.get('preview_only'):
    picture.thumbnail((target['preview_width'],target['preview_height']),Image.Resampling.BILINEAR)
   stat=ImageStat.Stat(picture.resize((64,64)))
   loading=max(stat.mean)<3
   picture.save(Path(directory)/'frame.png',compress_level=0);print(json.dumps({'ok':True,'loading':loading}),flush=True)
 finally:controller.stop()

if __name__=='__main__':
 sys.path.insert(0,str(Path(__file__).parent))
 try:
  try:ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
  except (AttributeError,OSError):pass
  serve(json.loads(sys.argv[1]),sys.argv[2])
 except Exception as error:print(json.dumps({'error':str(error)}),flush=True)
