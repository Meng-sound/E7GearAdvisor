"""Read-only Windows integrity checks for background window messages."""
import ctypes,os
from ctypes import wintypes

def integrity_level(pid):
 if os.name!='nt':return None
 kernel=ctypes.WinDLL('kernel32',use_last_error=True);advapi=ctypes.WinDLL('advapi32',use_last_error=True)
 kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
 kernel.CloseHandle.argtypes=[wintypes.HANDLE]
 advapi.OpenProcessToken.argtypes=[wintypes.HANDLE,wintypes.DWORD,ctypes.POINTER(wintypes.HANDLE)]
 advapi.GetTokenInformation.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)]
 advapi.GetSidSubAuthorityCount.argtypes=[ctypes.c_void_p];advapi.GetSidSubAuthorityCount.restype=ctypes.POINTER(ctypes.c_ubyte)
 advapi.GetSidSubAuthority.argtypes=[ctypes.c_void_p,wintypes.DWORD];advapi.GetSidSubAuthority.restype=ctypes.POINTER(wintypes.DWORD)
 process=kernel.OpenProcess(0x1000,False,pid);token=wintypes.HANDLE()
 if not process:return None
 try:
  if not advapi.OpenProcessToken(process,8,ctypes.byref(token)):return None
  size=wintypes.DWORD();advapi.GetTokenInformation(token,25,None,0,ctypes.byref(size))
  if not size.value:return None
  buffer=ctypes.create_string_buffer(size.value)
  if not advapi.GetTokenInformation(token,25,buffer,size,ctypes.byref(size)):return None
  sid=ctypes.cast(buffer,ctypes.POINTER(ctypes.c_void_p))[0]
  count=advapi.GetSidSubAuthorityCount(sid)[0]
  return advapi.GetSidSubAuthority(sid,count-1)[0] if count else None
 finally:
  if token:kernel.CloseHandle(token)
  kernel.CloseHandle(process)

def input_permission_error(target):
 current=integrity_level(os.getpid());game=integrity_level(target['pid'])
 if current is not None and game is not None and current<game:
  return '游戏以更高权限运行，Windows阻止后台点击。请关闭本工具，右键启动脚本选择“以管理员身份运行”，再启动任务。'
 return None
