"""User-launched elevated entry; Windows UAC remains under the user's control."""
import ctypes,os,runpy,subprocess,sys
from pathlib import Path

if __name__=='__main__':
 root=Path(__file__).resolve().parent
 if not ctypes.windll.shell32.IsUserAnAdmin():
  shell=ctypes.WinDLL('shell32',use_last_error=True)
  shell.ShellExecuteW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_int]
  shell.ShellExecuteW.restype=ctypes.c_ssize_t
  result=shell.ShellExecuteW(None,'runas',sys.executable,subprocess.list2cmdline([str(Path(__file__).resolve())]),str(root),0)
  if result<=32:ctypes.windll.user32.MessageBoxW(None,'未获得管理员权限，未启动后台任务。','管理员启动',0x30)
 else:
  sys.path.insert(0,str(root));os.chdir(root)
  os.environ['TCL_LIBRARY']=str(root/'runtime/tcl/tcl8.6');os.environ['TK_LIBRARY']=str(root/'runtime/tcl/tk8.6')
  runpy.run_path(str(root/'pc_app.py'),run_name='__main__')
