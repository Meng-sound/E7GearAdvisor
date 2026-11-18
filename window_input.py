"""Background messages to one pinned game window; never moves the real cursor."""
import ctypes
from ctypes import wintypes
import math
import os
import time


def packed_point(x,y):
    if not -32768<=x<=32767 or not -32768<=y<=32767:
        raise ValueError('坐标超出窗口消息范围')
    return (x & 65535) | ((y & 65535)<<16)


class WindowInput:
    def __init__(self,target):
        if os.name!='nt':raise RuntimeError('后台输入仅支持Windows')
        if target.get('title') not in {'第七史诗','Epic Seven','EPIC SEVEN'}:
            raise ValueError('目标不是第七史诗')
        if any(type(target.get(key)) is not int for key in ('hwnd','pid')):
            raise ValueError('目标窗口标识无效')
        self.target=dict(target)
        from process_permissions import input_permission_error
        error=input_permission_error(self.target)
        if error:raise RuntimeError(error)
        self.user=ctypes.WinDLL('user32',use_last_error=True)
        for name in ('IsWindow','IsIconic','IsWindowVisible'):
            getattr(self.user,name).argtypes=[wintypes.HWND]
        self.user.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
        self.user.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
        self.user.GetClientRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
        self.user.ClientToScreen.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.POINT)]
        self.user.PostMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
        self.user.PostMessageW.restype=wintypes.BOOL
        self.user.GetAsyncKeyState.argtypes=[ctypes.c_int]
        self.user.GetAsyncKeyState.restype=ctypes.c_short

    def emergency_pressed(self):return bool(self.user.GetAsyncKeyState(0x79)&0x8000) # F10

    def check(self,size):
        target=self.target;hwnd=target['hwnd'];pid=wintypes.DWORD();title=ctypes.create_unicode_buffer(1024)
        self.user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid));self.user.GetWindowTextW(hwnd,title,len(title))
        if not self.user.IsWindow(hwnd) or pid.value!=target['pid'] or title.value!=target['title']:
            raise RuntimeError('游戏窗口已关闭或改变，已停止输入')
        if self.user.IsIconic(hwnd) or not self.user.IsWindowVisible(hwnd):
            raise RuntimeError('游戏已最小化或隐藏，请恢复窗口')
        rect=wintypes.RECT()
        if not self.user.GetClientRect(hwnd,ctypes.byref(rect)) or (rect.right,rect.bottom)!=tuple(size):
            raise RuntimeError('游戏窗口尺寸改变，停止本次输入并重新识别')
        return hwnd

    def send(self,hwnd,message,wparam,lparam):
        ctypes.set_last_error(0)
        if not self.user.PostMessageW(hwnd,message,wparam,lparam):
            code=ctypes.get_last_error()
            if code==5:raise RuntimeError('Windows拒绝后台消息（错误5）：请使用管理员启动入口，使工具与游戏权限一致。')
            raise RuntimeError(f'后台消息发送失败（Win32错误{code}），任务已停止。')

    def perform(self,command,size,allowed):
        if not allowed():return False
        x,y=command.point
        if not all(type(v) in (int,float) and math.isfinite(v) and 0<v<1 for v in (x,y)):
            raise ValueError('输入坐标必须位于游戏客户区内')
        hwnd=self.check(size);px=int(x*size[0]);py=int(y*size[1]);point=packed_point(px,py)
        if self.emergency_pressed() or not allowed():return False
        self.send(hwnd,0x200,0,point) # WM_MOUSEMOVE, window-local only
        if command.kind=='scroll':
            screen=wintypes.POINT(px,py)
            if not self.user.ClientToScreen(hwnd,ctypes.byref(screen)):raise RuntimeError('无法换算滚动坐标')
            if command.delta not in (-120,120,720):raise ValueError('滚动步长无效')
            self.send(hwnd,0x20A,(command.delta&65535)<<16,packed_point(screen.x,screen.y))
        else:
            self.send(hwnd,0x201,1,point)
            try:time.sleep(.08)
            finally:self.send(hwnd,0x202,0,point)
        return True

    def inspect_gear(self,command,size,capture,allowed):
        if not allowed() or self.emergency_pressed():return []
        x,y=command.point
        if not 0<x<1 or not 0<y<1:raise ValueError('详情坐标超出窗口')
        hwnd=self.check(size);point=packed_point(int(x*size[0]),int(y*size[1]))
        self.send(hwnd,0x200,0,point);self.send(hwnd,0x201,1,point)
        try:
            for _ in range(9):
                if not allowed() or self.emergency_pressed():return []
                time.sleep(.05)
            frames=[]
            for _ in range(2):
                if not allowed() or self.emergency_pressed():return []
                frame=capture()
                if frame.size!=tuple(size):raise RuntimeError('读取详情期间窗口尺寸改变')
                frames.append(frame);time.sleep(.15)
            return frames
        finally:self.send(hwnd,0x202,0,point)
