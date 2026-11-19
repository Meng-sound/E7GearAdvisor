"""Discover the game's visible Windows rectangle; no game input or process reads."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import os

import emulator

WS_EX_TOOLWINDOW = 0x00000080


def _describe(hwnd, user):
    """Window text/class/process/geometry, or None when unreadable."""
    length = user.GetWindowTextLengthW(hwnd)
    title = ''
    if length:
        buffer = ctypes.create_unicode_buffer(length + 1)
        user.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.strip()
    class_buffer = ctypes.create_unicode_buffer(256)
    user.GetClassNameW(hwnd, class_buffer, 256)
    pid = wintypes.DWORD()
    user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    rect = wintypes.RECT()
    try:
        dwm = ctypes.WinDLL('dwmapi')
        dwm.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        status = dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect))
        if status != 0:
            user.GetWindowRect(hwnd, ctypes.byref(rect))
    except OSError:
        user.GetWindowRect(hwnd, ctypes.byref(rect))
    client = wintypes.RECT()
    user.GetClientRect(hwnd, ctypes.byref(client))
    return {
        'hwnd': int(hwnd), 'pid': pid.value, 'title': title,
        'class_name': class_buffer.value, 'process': emulator.process_name(pid.value),
        'rect': [rect.left, rect.top, rect.right, rect.bottom],
        'client': [client.right, client.bottom],
        'ex_style': user.GetWindowLongW(hwnd, -20) & 0xFFFFFFFF,
        'minimized': bool(user.IsIconic(hwnd)),
    }


def find_game_windows():
    """Visible PC-client or emulator windows that host the game, largest first."""
    if os.name != 'nt':
        return []
    user = ctypes.WinDLL('user32', use_last_error=True)
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.IsIconic.argtypes = [wintypes.HWND]
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.EnumWindows.argtypes = [callback, wintypes.LPARAM]
    found = []

    @callback
    def visit(hwnd, _):
        if not user.IsWindowVisible(hwnd):
            return True
        if not user.GetWindowTextLengthW(hwnd):
            return True
        row = _describe(hwnd, user)
        if not row['title']:
            return True
        info = emulator.identify(row['title'], row['class_name'], row['process'])
        if info is None:
            return True
        # MuMu exposes the device surface as a separate tool window whose
        # PrintWindow/GraphicsCapture frame is black; the framed window is the host.
        if info['kind'] == 'emulator' and row['ex_style'] & WS_EX_TOOLWINDOW:
            return True
        row.update(source=info['kind'], emulator=info['name'] if info['kind'] == 'emulator' else '')
        found.append(row)
        return True
    user.EnumWindows(visit, 0)
    found.sort(key=lambda r: (r['client'][0] * r['client'][1]), reverse=True)
    # One window per process keeps MuMu's helper windows out of the picker.
    unique, seen = [], set()
    for row in found:
        key = (row['pid'], row['title'])
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def select_game_rectangle(windows, selection=None):
    if not windows:
        raise ValueError('没有找到游戏窗口。请打开第七史诗（PC 客户端或模拟器），或关闭自动定位后手动框选。')
    if selection is None and len(windows) > 1:
        raise ValueError('发现多个游戏窗口，请指定窗口或使用手动框选。')
    window = windows[0] if selection is None else windows[selection]
    if window['minimized']:
        if window.get('source') != 'emulator':
            raise ValueError('游戏窗口已最小化，请先还原到装备强化界面。')
        return list(window['rect'])
    left, top, right, bottom = window['rect']
    if right - left < 300 or bottom - top < 200:
        raise ValueError('游戏窗口太小，无法可靠读取装备属性。')
    return list(window['rect'])
