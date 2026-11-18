"""Discover the game's visible Windows rectangle; no game input or process reads."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import os


def find_game_windows():
    if os.name!='nt':return []
    user=ctypes.WinDLL('user32',use_last_error=True)
    callback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    user.GetWindowTextLengthW.argtypes=[wintypes.HWND]
    user.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
    user.IsWindowVisible.argtypes=[wintypes.HWND]
    user.IsIconic.argtypes=[wintypes.HWND]
    user.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
    user.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    user.EnumWindows.argtypes=[callback,wintypes.LPARAM]
    found=[]
    @callback
    def visit(hwnd,_):
        if not user.IsWindowVisible(hwnd):return True
        length=user.GetWindowTextLengthW(hwnd)
        if not length:return True
        title=ctypes.create_unicode_buffer(length+1);user.GetWindowTextW(hwnd,title,length+1)
        text=title.value.strip()
        if text not in {'第七史诗','Epic Seven','EPIC SEVEN'}:return True
        rect=wintypes.RECT()
        try:
            dwm=ctypes.WinDLL('dwmapi')
            dwm.DwmGetWindowAttribute.argtypes=[wintypes.HWND,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD]
            status=dwm.DwmGetWindowAttribute(hwnd,9,ctypes.byref(rect),ctypes.sizeof(rect))
            if status!=0:user.GetWindowRect(hwnd,ctypes.byref(rect))
        except OSError:user.GetWindowRect(hwnd,ctypes.byref(rect))
        bounds=[rect.left,rect.top,rect.right,rect.bottom]
        pid=wintypes.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        found.append({'hwnd':int(hwnd),'pid':pid.value,'title':text,'rect':bounds,'minimized':bool(user.IsIconic(hwnd))})
        return True
    user.EnumWindows(visit,0)
    return found


def select_game_rectangle(windows,selection=None):
    if not windows:raise ValueError('没有找到“第七史诗”游戏窗口。请打开游戏，或关闭自动定位后手动框选。')
    if selection is None and len(windows)>1:raise ValueError('发现多个游戏窗口，请指定窗口或使用手动框选。')
    window=windows[0] if selection is None else windows[selection]
    if window['minimized']:raise ValueError('游戏窗口已最小化，请先还原到装备强化界面。')
    left,top,right,bottom=window['rect']
    if right-left<300 or bottom-top<200:raise ValueError('游戏窗口太小，无法可靠读取装备属性。')
    return list(window['rect'])
