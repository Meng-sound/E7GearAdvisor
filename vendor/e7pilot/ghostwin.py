"""幽灵窗口：给目标窗口加点击穿透样式（WS_EX_LAYERED | WS_EX_TRANSPARENT）。

安全性：
- 只改目标窗口的 GWL_EXSTYLE，不碰输入层；
- 记录原始样式，随时可还原；
- 附带看门狗子进程：主进程异常退出时自动还原，避免"窗口点不动"；
- 独占全屏（无边框 + 铺满显示器）直接拒绝，避免闪屏/无效。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
GWL_EXSTYLE = -20
GWL_STYLE = -16
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_CAPTION = 0x00C00000
LWA_ALPHA = 0x00000002
GA_ROOT = 2
SWP_NOMOVE, SWP_NOSIZE, SWP_NOZORDER, SWP_FRAMECHANGED = 0x2, 0x1, 0x4, 0x20
MONITOR_DEFAULTTONEAREST = 2

_STATE = {"hwnd": 0, "orig": 0, "watch": None}


def _top_hwnd(hwnd: int) -> int:
    """模拟器渲染子窗口需取其顶层父窗口，穿透样式才对鼠标生效。"""
    if not hwnd:
        return 0
    root = user32.GetAncestor(int(hwnd), GA_ROOT)
    return int(root) if root else int(hwnd)


def _ex(hwnd: int) -> int:
    return user32.GetWindowLongW(int(hwnd), GWL_EXSTYLE) & 0xFFFFFFFF


def _set_ex(hwnd: int, val: int) -> int:
    """写入 GWL_EXSTYLE 并返回写入后的真实值（用于回读校验）。"""
    signed_val = ctypes.c_long(val & 0xFFFFFFFF).value
    kernel32.SetLastError(0)
    user32.SetWindowLongW(int(hwnd), GWL_EXSTYLE, signed_val)
    user32.SetWindowPos(
        int(hwnd), 0, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED,
    )
    return _ex(hwnd)


def _style(hwnd: int) -> int:
    return user32.GetWindowLongW(int(hwnd), GWL_STYLE) & 0xFFFFFFFF


def _state_file() -> Path:
    from core import user_data_dir

    return user_data_dir() / "ghostwin.json"


def is_exclusive_fullscreen(hwnd: int) -> bool:
    """无边框 + 铺满所在显示器 → 视为独占全屏，拒绝开启。"""
    try:
        rect = wt.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w, h = rect.right - rect.left, rect.bottom - rect.top
        mon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        info = wt.MONITORINFO()
        info.cbSize = ctypes.sizeof(info)
        user32.GetMonitorInfoW(mon, ctypes.byref(info))
        mw = info.rcMonitor.right - info.rcMonitor.left
        mh = info.rcMonitor.bottom - info.rcMonitor.top
        borderless = not (_style(hwnd) & WS_CAPTION)
        return borderless and w >= mw - 2 and h >= mh - 2
    except Exception:  # noqa: BLE001
        return False


def enable(hwnd: int) -> tuple[bool, str]:
    """开启穿透并回读校验真实样式。返回 (成功, 说明)。"""
    hwnd = _top_hwnd(hwnd)
    if not hwnd or not user32.IsWindow(hwnd):
        return False, "没有游戏窗口"
    if is_exclusive_fullscreen(hwnd):
        return False, "全屏模式不支持（请用窗口化）"

    cur = _ex(hwnd)
    if _STATE["hwnd"] == hwnd and (cur & WS_EX_TRANSPARENT):
        return True, f"已开启 (EX=0x{cur:08X})"

    orig = cur & ~WS_EX_TRANSPARENT
    target = orig | WS_EX_LAYERED | WS_EX_TRANSPARENT
    try:
        after = _set_ex(hwnd, target)
        user32.SetLayeredWindowAttributes(int(hwnd), 0, 255, LWA_ALPHA)
    except Exception as exc:  # noqa: BLE001
        return False, f"设置失败：{exc}"

    if not (after & WS_EX_TRANSPARENT):
        err = kernel32.GetLastError()
        hint = "权限不足，请以管理员身份运行 E7Pilot" if err in (0, 5) else f"错误码 {err}"
        return False, f"未生效（{hint}，EX=0x{after:08X}）"

    _STATE.update(hwnd=hwnd, orig=orig)
    try:
        _state_file().write_text(
            json.dumps({"hwnd": hwnd, "orig": orig, "pid": os.getpid()}), encoding="utf-8"
        )
    except Exception:  # noqa: BLE001
        pass
    _start_watchdog(hwnd, orig)
    return True, f"已开启 (0x{cur:08X}→0x{after:08X})"


def disable(target_hwnd: int = 0) -> None:
    """关闭穿透：内存 → ghostwin.json → 当前游戏窗口 三级兜底，强制清位。"""
    hwnd = _STATE.get("hwnd") or 0
    orig = _STATE.get("orig") or 0
    f = _state_file()
    if not hwnd and f.exists():
        try:
            data = json.loads(f.read_text(encoding="utf-8")) or {}
            hwnd = int(data.get("hwnd") or 0)
            orig = int(data.get("orig") or 0)
        except Exception:  # noqa: BLE001
            pass
    if not hwnd and target_hwnd:
        hwnd = _top_hwnd(target_hwnd)

    if hwnd and user32.IsWindow(int(hwnd)):
        try:
            cur = _ex(hwnd)
            restore = (cur & ~(WS_EX_LAYERED | WS_EX_TRANSPARENT)) | (orig & WS_EX_LAYERED)
            _set_ex(hwnd, restore)
        except Exception:  # noqa: BLE001
            pass
    _STATE.update(hwnd=0, orig=0)
    _stop_watchdog()
    try:
        if f.exists():
            f.unlink()
    except Exception:  # noqa: BLE001
        pass


def _start_watchdog(hwnd: int, orig: int) -> None:
    if _STATE.get("watch") is not None:
        return
    try:
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--ghost-watch", str(os.getpid()), str(hwnd), str(orig)]
        else:
            cmd = [sys.executable, str(Path(sys.argv[0]).resolve()), "--ghost-watch",
                   str(os.getpid()), str(hwnd), str(orig)]
        _STATE["watch"] = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:  # noqa: BLE001
        _STATE["watch"] = None


def _stop_watchdog() -> None:
    p = _STATE.get("watch")
    if p is not None:
        try:
            p.terminate()
        except Exception:  # noqa: BLE001
            pass
    _STATE["watch"] = None


def run_watchdog(pid: int, hwnd: int, orig: int) -> None:
    """看门狗：父进程退出后把窗口样式还原。"""
    try:
        import win32api

        handle = win32api.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    except Exception:  # noqa: BLE001
        handle = None

    while True:
        time.sleep(1.0)
        alive = False
        if handle is not None:
            try:
                alive = win32api.WaitForSingleObject(handle, 0) == 0x102  # WAIT_TIMEOUT
            except Exception:  # noqa: BLE001
                alive = False
        else:
            try:
                os.kill(pid, 0)
                alive = True
            except Exception:  # noqa: BLE001
                alive = False
        if not alive:
            try:
                cur = user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF
                restore = (cur & ~(WS_EX_LAYERED | WS_EX_TRANSPARENT)) | (orig & WS_EX_LAYERED)
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, restore)
                user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED)
            except Exception:  # noqa: BLE001
                pass
            return
