"""Isolated upstream E7Pilot story/theater engine, strictly background-only."""
import ctypes,json,os,re,sys,threading,time
from pathlib import Path

def configure_stdio():
 for stream in (sys.stdin,sys.stdout,sys.stderr):
  if stream is not None and hasattr(stream,'reconfigure'):
   stream.reconfigure(encoding='utf-8',errors='replace')

configure_stdio()

class TaskStopped(BaseException):pass

def setup_paths():
 root=Path(__file__).resolve().parent;deps=root/'pilot_dependencies'
 for path in (root,root/'neural',deps,deps/'win32',deps/'win32/lib',deps/'Pythonwin',deps/'pywin32_system32'):
  sys.path.insert(0,str(path))
 handles=[]
 if os.name=='nt' and (deps/'pywin32_system32').is_dir():handles.append(os.add_dll_directory(str(deps/'pywin32_system32')))
 sys.path.insert(0,str(root/'vendor/e7pilot'))
 return root,handles

def run(request,check_only=False):
 root,dll_handles=setup_paths()
 import core as pilot
 import yaml,win32api,win32gui
 from stream_capture import StreamCapture
 from process_permissions import input_permission_error
 from window_input import WindowInput
 from emulator import identify,content_rect
 config=request['config'];target=request['target'];state={'stop':False,'pause':False,'actions':0,'held':None,'epoch':0};bots=[]
 # Android emulators (国服) ignore Win32 mouse messages: touches go through the
 # emulator's native interface / ADB and the frame is the phone screen only.
 emulated=bool((identify(target.get('title'),target.get('class_name'),target.get('process')) or {}).get('kind')=='emulator')
 emulator_input=None
 if emulated:emulator_input=WindowInput(target,request.get('input_backend'))
 data=Path(request['user_dir'])/'e7pilot';data.mkdir(parents=True,exist_ok=True)
 pilot.user_data_dir=lambda:data
 pilot.runtime_root=lambda:root/'vendor/e7pilot'
 pilot.read_click_mode=lambda *a,**k:'background'
 pilot.find_game_window=lambda:target['hwnd']
 pilot.cursor_control_probe=lambda:'后台模式，不检查前台鼠标'
 pilot.GameWindow.build_compat_diag_line=lambda *a,**k:'Windows图形捕获 · 后台输入'
 stream=StreamCapture(target)
 def commands():
  for line in sys.stdin:
   try:
    value=json.loads(line);state.update({k:v for k,v in value.items() if k in ('stop','pause')})
    if 'pause' in value and bots:bots[0].paused=bool(value['pause'])
   except ValueError:pass
  state['stop']=True
 threading.Thread(target=commands,daemon=True).start()
 original_post=win32gui.PostMessage
 original_size=pilot.GameWindow.client_size
 def window_size(window):
  width,height=original_size(window)
  if not emulated:return width,height
  left,top,right,bottom=content_rect(width,height)
  return right-left,bottom-top
 def release():
  if state['held'] is not None:
   try:
    # Taps are atomic, so there is no held button left to release.
    if not emulated:original_post(target['hwnd'],0x202,0,state['held'])
   finally:state['held']=None
 def guard():
  if state['stop']:raise TaskStopped()
  if ctypes.windll.user32.GetAsyncKeyState(0x79)&0x8000:raise TaskStopped()
  while state['pause']:
   release()
   if state['stop'] or ctypes.windll.user32.GetAsyncKeyState(0x79)&0x8000:raise TaskStopped()
   time.sleep(.05)
 def touch(msg,wparam,lparam):
  """Translate Win32 mouse traffic into emulator touches."""
  width,height=window_size(window)
  if msg in (0x200,0x201,0x202):
   px=(lparam&65535)*width/1819;py=((lparam>>16)&65535)*height/1023
   if msg==0x201:
    # One real tap per press. ADB's `input` cannot hold a touch between calls,
    # so deferring it to the up event silently dropped the click.
    emulator_input.backend.tap(px,py);state['held']=lparam;state['actions']+=1
   elif msg==0x202:state['held']=None
   if msg in (0x201,) or (msg==0x200 and wparam==1):state['epoch']+=1
   return True
  if msg==0x20A:
   x=ctypes.c_short(lparam&65535).value;y=ctypes.c_short((lparam>>16)&65535).value
   ox,oy=window.client_origin_on_screen()
   rx=(x-ox)/max(1,width);ry=(y-oy)/max(1,height)
   notches=int((wparam>>16)&0xFFFF)
   emulator_input.scroll(max(.02,min(.98,rx)),max(.02,min(.98,ry)),-120 if notches>32767 else 120)
   state['epoch']+=1;return True
  return False
 def post(hwnd,msg,wparam,lparam):
  if hwnd!=target['hwnd']:raise TaskStopped('输入目标不是绑定的游戏窗口')
  if msg not in (0x202,0x101):guard()
  if emulated:
   if touch(msg,wparam,lparam):return True
   return True  # keyboard/other messages have no emulator equivalent
  if msg in (0x200,0x201,0x202):
   x=lparam&65535;y=(lparam>>16)&65535;w,h=original_size(window)
   lparam=(round(x*w/1819)&65535)|((round(y*h/1023)&65535)<<16)
  elif msg==0x20A:
   x=ctypes.c_short(lparam&65535).value;y=ctypes.c_short((lparam>>16)&65535).value
   ox,oy=window.client_origin_on_screen();w,h=original_size(window)
   lparam=((ox+round((x-ox)*w/1819))&65535)|(((oy+round((y-oy)*h/1023))&65535)<<16)
  result=original_post(hwnd,msg,wparam,lparam)
  if msg in (0x201,0x20A,0x100) or msg==0x200 and wparam==1:state['epoch']+=1
  if msg==0x201:state['held']=lparam;state['actions']+=1
  elif msg==0x202:state['held']=None
  return result
 win32gui.PostMessage=post
 def forbidden(*args,**kwargs):raise TaskStopped('已阻止前台鼠标或窗口激活动作')
 win32api.mouse_event=forbidden;win32api.keybd_event=forbidden;win32api.SetCursorPos=forbidden
 pilot.GameWindow.activate=forbidden;pilot.GameWindow._move_cursor=forbidden
 original_init=pilot.GameWindow.__init__
 def init(self,hwnd,*args,**kwargs):
  if hwnd!=target['hwnd']:raise TaskStopped('窗口绑定不一致')
  original_init(self,hwnd,'background')
 pilot.GameWindow.__init__=init
 pilot.GameWindow.client_size=lambda self:(1819,1023)
 def capture(self,*args,**kwargs):
  guard()
  import numpy as np
  import cv2
  from loading_frame import wait_for_picture
  def loading():
   release();print('游戏正在加载，等待画面恢复…',flush=True)
  picture=wait_for_picture(lambda:stream(target),guard,on_loading=loading,on_ready=lambda:print('加载结束，继续任务。',flush=True))
  return cv2.resize(np.asarray(picture)[:,:,::-1],(1819,1023))
 pilot.GameWindow.capture=capture;pilot.GameWindow._capture_printwindow=capture
 cfg=yaml.safe_load((root/'vendor/e7pilot/rules.yaml').read_text('utf8'))
 cfg.setdefault('settings',{}).update(request.get('source_settings',{}))
 cfg['settings']['click_mode']='background'
 pilot.load_rules_cfg=lambda *a,**k:cfg
 import main as story
 if check_only:
  import theater
  import numpy as np
  items=[pilot.OcrItem('跳过',.99,(1450,30,1550,70))]
  rules=[story.Rule(**row) for row in cfg['rules']]
  action=story.analyze_frame(np.zeros((900,1600,3),dtype=np.uint8),items,rules,cfg.get('global_forbid',[]),8,enable_auto_check=False)
  assert action.get('rule') and action['rule'].name=='跳过剧情',action
  assert theater.classify_state([], '购买剧场门票',False)=='buy_ticket'
  assert theater.classify_state([], '月光剧场进行观览',False)=='movie'
  assert theater.classify_state([], '使用剧场门票',False)=='use_ticket'
  if request.get('fixture'):
   import cv2
   image=cv2.imdecode(np.fromfile(request['fixture'],dtype=np.uint8),cv2.IMREAD_COLOR)
   ocr=pilot.Ocr();words=ocr.read(image)
   assert theater.classify_state(words,theater._join(words),False)=='buy_ticket'
  import shop
  assert callable(shop.ShopBot.step)
  try:forbidden();raise AssertionError('foreground input not blocked')
  except TaskStopped:pass
  shop.log('🛒 中文日志与表情输出测试 ✓')
  story.log('📜 推图日志输出测试 ✓')
  assert pilot.Ocr.read.__module__=='core'
  print('PILOT_CHECK_OK native source policies and OCR, no host expense guard; UTF8 and background input',flush=True);stream.close();return
 if not emulated:
  error=input_permission_error(target)
  if error:raise RuntimeError(error)
 backend=emulator_input if emulated else WindowInput(target)
 # Check identity, dimensions and cancellation before every background input.
 original_post_guarded=win32gui.PostMessage
 def checked_post(hwnd,msg,wparam,lparam):
  if msg not in (0x202,0x101):backend.check(window_size(window))
  return original_post_guarded(hwnd,msg,wparam,lparam)
 win32gui.PostMessage=checked_post
 window=pilot.GameWindow(target['hwnd'],'background')
 pilot.open_game_window=lambda *a,**k:window
 bot=None
 try:
  if config['mode']=='shop':
   import shop
   from ocr_crop_cache import enable
   bot=shop.ShopBot(window,enable(pilot.Ocr(),epoch=lambda:state['epoch'],ignore_portrait=not cfg['settings'].get('gear_auto_buy',False)),int(cfg['settings'].get('stop_skystones',2000)))
  elif config['mode']=='story':
   bot=story.Bot(cfg,mode_override='auto');bot._pw_verified=True
  else:
   import theater
   settings=cfg['settings'];bot=theater.TheaterBot(window,pilot.Ocr(),int(settings.get('theater_keep_gold',1000000)),int(settings.get('theater_ticket_cost',500000)))
   bot.story_click_ms=float(settings.get('theater_story_click_ms',bot.story_click_ms));bot.story_burst=int(settings.get('theater_story_burst',bot.story_burst))
   bot.action_gap=float(settings.get('theater_action_gap_ms',bot.action_gap*1000))/1000
   bot.story_hold_ms=tuple(float(value)/1000 for value in settings.get('theater_story_hold_ms',[60,80]))
   if settings.get('theater_poll_ms'):bot.poll_ms=float(settings['theater_poll_ms'])/1000
  bots.append(bot)
  print('任务已启动；后台取图与操作，不抢鼠标；F8暂停/继续，F10停止。',flush=True)
  while True:
   guard()
   if not bot.poll_hotkeys():break
   if bot.paused:
    time.sleep(.1);continue
   if bot.step() is False:break
   until=time.monotonic()+max(0,getattr(bot,'_next_sleep',.2))
   while time.monotonic()<until:
    guard()
    if not bot.poll_hotkeys():raise TaskStopped()
    time.sleep(.05)
 except TaskStopped as error:print('任务停止：'+str(error),flush=True)
 finally:
  release();stream.close()
  print('后台流程结束 · 动作 '+str(state['actions']),flush=True)

if __name__=='__main__':
 try:
  ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
 except (AttributeError,OSError):pass
 try:run(json.loads(Path(sys.argv[1]).read_text('utf8')),check_only='--check' in sys.argv)
 except TaskStopped as error:print('任务停止：'+str(error),flush=True)
 except Exception as error:
  import traceback
  traceback.print_exc();sys.exit(1)
