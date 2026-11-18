"""One-shot HWND Windows Graphics Capture, isolated by window_capture's worker."""
import ctypes,sys,threading
from ctypes import wintypes
from pathlib import Path

def capture(hwnd,pid,title,timeout=2.5):
 from PIL import Image,ImageStat
 user=ctypes.WinDLL('user32',use_last_error=True)
 user.IsWindow.argtypes=[wintypes.HWND];user.IsIconic.argtypes=[wintypes.HWND]
 user.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
 user.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
 user.GetClientRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
 user.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
 user.ClientToScreen.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.POINT)]
 def geometry():
  name=ctypes.create_unicode_buffer(1024);owner=wintypes.DWORD()
  user.GetWindowTextW(hwnd,name,len(name));user.GetWindowThreadProcessId(hwnd,ctypes.byref(owner))
  if not user.IsWindow(hwnd) or owner.value!=pid or name.value!=title:raise RuntimeError('游戏窗口标识发生变化')
  if user.IsIconic(hwnd):raise RuntimeError('游戏已最小化，请还原窗口')
  rect=wintypes.RECT();client=wintypes.RECT();origin=wintypes.POINT()
  user.GetWindowRect(hwnd,ctypes.byref(rect));user.GetClientRect(hwnd,ctypes.byref(client));user.ClientToScreen(hwnd,ctypes.byref(origin))
  dwm=ctypes.WinDLL('dwmapi');dwm.DwmGetWindowAttribute.argtypes=[wintypes.HWND,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD]
  bounds=wintypes.RECT()
  if dwm.DwmGetWindowAttribute(hwnd,9,ctypes.byref(bounds),ctypes.sizeof(bounds))!=0:bounds=rect
  return (rect.left,rect.top,rect.right,rect.bottom),(bounds.left,bounds.top,bounds.right,bounds.bottom),(origin.x,origin.y,client.right,client.bottom)
 before=geometry()
 sys.path.insert(0,str(Path(__file__).parent/'neural'))
 from windows_capture import WindowsCapture
 ready=threading.Event();frames=[];errors=[]
 session=WindowsCapture(cursor_capture=False,draw_border=False,window_hwnd=hwnd)
 @session.event
 def on_frame_arrived(frame,control):
  try:
   frames.append(Image.fromarray(frame.frame_buffer[:,:,:3][:,:,::-1].copy()))
  except Exception as error:errors.append(str(error))
  finally:control.stop();ready.set()
 @session.event
 def on_closed():ready.set()
 controller=session.start_free_threaded()
 if not ready.wait(timeout):controller.stop();raise RuntimeError('Windows图形捕获取图超时')
 controller.wait()
 if not frames:raise RuntimeError('Windows图形捕获未返回画面：'+';'.join(errors))
 if geometry()!=before:raise RuntimeError('取图期间游戏窗口发生移动或缩放')
 picture=frames[0];rect,bounds,client=before
 if picture.size!=(client[2],client[3]):
  area=min((rect,bounds),key=lambda b:abs((b[2]-b[0])-picture.width)+abs((b[3]-b[1])-picture.height))
  if abs(area[2]-area[0]-picture.width)>4 or abs(area[3]-area[1]-picture.height)>4:raise RuntimeError('Windows图形捕获尺寸与窗口不一致')
  x,y=client[0]-area[0],client[1]-area[1]
  if x<0 or y<0 or x+client[2]>picture.width or y+client[3]>picture.height:raise RuntimeError('无法定位捕获画面的客户区')
  picture=picture.crop((x,y,x+client[2],y+client[3]))
 stats=ImageStat.Stat(picture.resize((64,64)))
 if max(stats.mean)<3 or max(stats.stddev)<1:raise RuntimeError('Windows图形捕获返回黑屏')
 picture.info['capture_backend']='Windows图形捕获（支持遮挡）'
 return picture
