"""环境诊断（用户反馈「识别不到游戏」时用）：把窗口/进程/注册表现场写进 debug\\环境诊断.txt。

只做只读枚举，不做任何识别决定、不改任何运行状态；任何异常都吞掉，保证不影响主流程。
"""
from __future__ import annotations

import ctypes
import datetime
import os
import platform
import sys
import winreg
from ctypes import wintypes
from pathlib import Path

import win32gui
import win32process

_EMU_WORDS = ("mumu", "nemu", "netease", "网易", "bluestacks", "leidian", "ldplayer", "nox")


def _exe_of(pid: int) -> str:
    try:
        from core import _exe_name_of_pid

        return _exe_name_of_pid(pid) or ""
    except Exception:  # noqa: BLE001
        return ""


def _reg_uninstall() -> list[str]:
    """枚举三个 Uninstall 根下所有含模拟器关键词的项。"""
    rows: list[str] = []
    roots = (
        ("HKLM 64", winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
        ("HKLM 32", winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
        ("HKCU 64", winreg.HKEY_CURRENT_USER, winreg.KEY_WOW64_64KEY),
    )
    sub = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    for tag, hive, wow in roots:
        try:
            with winreg.OpenKey(hive, sub, 0, winreg.KEY_READ | wow) as root:
                n = winreg.QueryInfoKey(root)[0]
                for i in range(n):
                    try:
                        name = winreg.EnumKey(root, i)
                    except OSError:
                        continue
                    low = name.lower()
                    vals: dict[str, str] = {}
                    try:
                        with winreg.OpenKey(root, name) as k:
                            for vn in ("DisplayName", "InstallLocation", "DisplayVersion"):
                                try:
                                    vals[vn] = str(winreg.QueryValueEx(k, vn)[0])
                                except OSError:
                                    pass
                    except OSError:
                        pass
                    blob = (low + " " + vals.get("DisplayName", "").lower()).strip()
                    if any(w in blob for w in _EMU_WORDS):
                        rows.append(
                            "%s | %s | DisplayName=%s | InstallLocation=%s | Version=%s"
                            % (
                                tag,
                                name,
                                vals.get("DisplayName", "-"),
                                vals.get("InstallLocation", "-"),
                                vals.get("DisplayVersion", "-"),
                            )
                        )
        except OSError:
            continue
    return rows


def _emu_processes() -> list[str]:
    rows: list[str] = []
    for pid in win32process.EnumProcesses():
        if not pid:
            continue
        exe = _exe_of(pid)
        if exe and any(w in exe.lower() for w in _EMU_WORDS):
            rows.append("pid=%d exe=%s" % (pid, exe))
    return rows


def _rect_text(hwnd: int) -> str:
    try:
        l, t, r, b = win32gui.GetWindowRect(hwnd)
    except Exception:  # noqa: BLE001
        l = t = r = b = 0
    try:
        cl, ct, cr, cb = win32gui.GetClientRect(hwnd)
    except Exception:  # noqa: BLE001
        cl = ct = cr = cb = 0
    try:
        vis = int(bool(win32gui.IsWindowVisible(hwnd)))
    except Exception:  # noqa: BLE001
        vis = -1
    try:
        ico = int(bool(win32gui.IsIconic(hwnd)))
    except Exception:  # noqa: BLE001
        ico = -1
    return "rect=(%d,%d,%d,%d) client=%dx%d visible=%d iconic=%d" % (
        l, t, r, b, cr - cl, cb - ct, vis, ico)


def _wnd_line(hwnd: int) -> str:
    try:
        cls = win32gui.GetClassName(hwnd)
    except Exception:  # noqa: BLE001
        cls = "?"
    try:
        title = (win32gui.GetWindowText(hwnd) or "")[:40]
    except Exception:  # noqa: BLE001
        title = ""
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
    except Exception:  # noqa: BLE001
        pid = 0
    return "hwnd=0x%08X class=%-22s title=%-40s pid=%-6d exe=%-22s %s" % (
        int(hwnd), cls, title, pid, _exe_of(pid) or "-", _rect_text(hwnd))


def _is_emu_window(hwnd: int, cls: str, title: str, exe: str) -> bool:
    blob = " ".join((cls, title, exe)).lower()
    return any(w in blob for w in _EMU_WORDS)


def _child_tree(hwnd: int, depth: int = 0, max_depth: int = 3) -> list[str]:
    rows: list[str] = []
    if depth >= max_depth:
        return rows
    try:
        children = win32gui.GetChildWindows(hwnd)
    except Exception:  # noqa: BLE001
        return rows
    for ch in children or []:
        rows.append("  " * (depth + 1) + _wnd_line(ch))
        rows.extend(_child_tree(ch, depth + 1, max_depth))
    return rows


def write_env_diag(tag: str = "") -> Path | None:
    """写 debug\\环境诊断.txt，返回路径；失败返回 None（绝不抛异常）。"""
    try:
        from core import EMULATOR_INFO, find_emulator_window, find_game_window, runtime_root

        lines: list[str] = []
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines.append("===== E7Pilot 环境诊断 =====")
        lines.append("说明: 本文件只含窗口标题/进程名/安装路径/分辨率，不含截图与账号信息；发送前可自行打开检查。")
        lines.append("生成时间: %s" % now)
        lines.append("场景: %s" % (tag or "-"))
        lines.append("程序: %s" % sys.executable)
        lines.append("工作目录: %s" % os.getcwd())
        lines.append("E7_ROOT: %s" % os.environ.get("E7_ROOT", "-"))
        lines.append("Windows: %s | Python: %s | 64位: %s"
                     % (platform.platform(), platform.python_version(), platform.machine()))
        try:
            admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:  # noqa: BLE001
            admin = None
        try:
            w = ctypes.windll.user32.GetSystemMetrics(0)
            h = ctypes.windll.user32.GetSystemMetrics(1)
            screen = "%dx%d" % (w, h)
        except Exception:  # noqa: BLE001
            screen = "?"
        lines.append("管理员: %s | 主屏: %s" % (admin, screen))

        lines.append("")
        lines.append("---- 1. MuMu 安装探测 ----")
        try:
            from mumu_ipc import find_mumu_root, locate_ipc_dll

            root = find_mumu_root()
            lines.append("find_mumu_root(): %s" % (root or "None"))
            lines.append("external_renderer_ipc.dll: %s" % ((locate_ipc_dll(root) if root else None) or "None"))
            if root:
                try:
                    vers = sorted(p.name for p in (root / "nx_device").iterdir() if p.is_dir())
                    lines.append("nx_device 版本目录: %s" % (vers or "无"))
                except Exception:  # noqa: BLE001
                    lines.append("nx_device 版本目录: 读取失败")
        except Exception as exc:  # noqa: BLE001
            lines.append("探测异常: %r" % (exc,))

        lines.append("")
        lines.append("---- 2. 注册表 Uninstall 含模拟器关键词的项 ----")
        rows = _reg_uninstall()
        lines.extend(rows or ["(无)"])

        lines.append("")
        lines.append("---- 3. 进程名含模拟器关键词 ----")
        rows = _emu_processes()
        lines.extend(rows or ["(无)"])

        lines.append("")
        lines.append("---- 4. 顶层窗口（只列：模拟器关键词命中 + 可见且客户区≥400x300 的窗口）----")
        emu_hwnds: list[int] = []
        emu_rows: list[str] = []
        big_rows: list[str] = []
        _skip_cls = ("IME", "tooltips_class32", "MSCTFIME UI")

        def _cb(hwnd, _lparam):
            try:
                cls = win32gui.GetClassName(hwnd)
                if cls in _skip_cls:
                    return True
                title = (win32gui.GetWindowText(hwnd) or "").strip()[:24]
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                exe = _exe_of(pid) or ""
                if _is_emu_window(hwnd, cls, title, exe):
                    emu_hwnds.append(int(hwnd))
                    emu_rows.append(_wnd_line(hwnd))
                    return True
                if not win32gui.IsWindowVisible(hwnd) or not title:
                    return True
                cl, ct, cr, cb = win32gui.GetClientRect(hwnd)
                if (cr - cl) >= 400 and (cb - ct) >= 300:
                    big_rows.append(_wnd_line(hwnd))
            except Exception:  # noqa: BLE001
                pass
            return True

        cb_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        ctypes.windll.user32.EnumWindows(cb_proc(lambda h, p: bool(_cb(h, p))), 0)
        lines.append("[4a] 模拟器关键词命中（类名/标题/进程名含 mumu/nemu/网易/雷电/夜神/蓝叠）：")
        lines.extend(emu_rows or ["  (无)"])
        lines.append("[4b] 其他可见窗口（客户区≥400x300，仅用于判断是否被误判/遮挡）：")
        lines.extend(big_rows[:25] or ["  (无)"])
        if len(big_rows) > 25:
            lines.append("  ... 省略 %d 个" % (len(big_rows) - 25))

        lines.append("")
        lines.append("---- 5. 模拟器候选窗口的子窗口树 ----")
        if emu_hwnds:
            for hwnd in emu_hwnds[:6]:
                lines.append("[" + _wnd_line(hwnd) + "]")
                lines.extend(_child_tree(hwnd) or ["  (无子窗口)"])
        else:
            lines.append("(未发现标题/类名/进程名含模拟器关键词的顶层窗口)")

        lines.append("")
        lines.append("---- 6. 当前判定结果 ----")
        try:
            hwnd = find_game_window()
            lines.append("find_game_window(): 0x%08X" % int(hwnd or 0))
        except Exception as exc:  # noqa: BLE001
            lines.append("find_game_window() 异常: %r" % (exc,))
        try:
            top = find_emulator_window()
            lines.append("find_emulator_window(): 0x%08X" % int(top or 0))
            if top:
                from core import resolve_render_hwnd

                lines.append("resolve_render_hwnd(top): 0x%08X" % int(resolve_render_hwnd(top) or 0))
        except Exception as exc:  # noqa: BLE001
            lines.append("模拟器窗口探测异常: %r" % (exc,))
        try:
            lines.append("EMULATOR_INFO: %r" % (dict(EMULATOR_INFO or {}),))
        except Exception:  # noqa: BLE001
            pass

        out_dir = Path(runtime_root()) / "debug"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / "环境诊断.txt"
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return out
    except Exception:  # noqa: BLE001
        return None
