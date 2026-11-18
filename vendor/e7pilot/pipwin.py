"""画中画：显示「玩家正在玩的游戏」——Steam 优先 → MuMu IPC → 模拟器窗口回退（与主程序一致）。

显示方式：DWM 硬件缩略图合成（高帧率、0 CPU、支持遮挡）；注册失败时回退 PrintWindow 抓帧；
MuMu 模拟器有 IPC 时优先走 IPC 抓帧（6ms、原生分辨率、最小化也能看）。
源切换/异常会写入 debug\\画中画日志.txt，便于玩家反馈时定位。
"""
from __future__ import annotations

import ctypes
import os
import time
import tkinter as tk
from ctypes import wintypes

import cv2
import win32con
import win32gui
import win32process
from PIL import Image, ImageTk

from core import GameWindow

dwmapi = ctypes.windll.dwmapi

DWM_TNP_RECTDESTINATION = 0x00000001
DWM_TNP_OPACITY = 0x00000004
DWM_TNP_VISIBLE = 0x00000008
DWM_TNP_SOURCECLIENTAREAONLY = 0x00000010


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class _THUMB_PROPS(ctypes.Structure):
    _fields_ = [
        ("dwFlags", wintypes.DWORD),
        ("rcDestination", _RECT),
        ("rcSource", _RECT),
        ("opacity", ctypes.c_ubyte),
        ("fVisible", wintypes.BOOL),
        ("fSourceClientAreaOnly", wintypes.BOOL),
    ]


dwmapi.DwmRegisterThumbnail.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.POINTER(ctypes.c_void_p)]
dwmapi.DwmRegisterThumbnail.restype = ctypes.c_long
dwmapi.DwmUnregisterThumbnail.argtypes = [ctypes.c_void_p]
dwmapi.DwmUnregisterThumbnail.restype = ctypes.c_long
dwmapi.DwmUpdateThumbnailProperties.argtypes = [ctypes.c_void_p, ctypes.POINTER(_THUMB_PROPS)]
dwmapi.DwmUpdateThumbnailProperties.restype = ctypes.c_long
dwmapi.DwmQueryThumbnailSourceSize.argtypes = [ctypes.c_void_p, ctypes.POINTER(_SIZE)]
dwmapi.DwmQueryThumbnailSourceSize.restype = ctypes.c_long


def _toplevel_hwnd(win: tk.Toplevel) -> int:
    """Tk Toplevel 的真实顶层 HWND（winfo_id 是内部 TkChild，不能直接给 DWM）。"""
    win.update_idletasks()
    try:
        frame = win.wm_frame()
        if frame and frame not in ("0x0", "0"):
            return int(frame, 16)
    except Exception:  # noqa: BLE001
        pass
    hwnd = win.winfo_id()
    parent = win32gui.GetParent(hwnd)
    return parent or hwnd


def _pip_log(msg: str) -> None:
    """只记录关键状态变化/异常到 debug/画中画日志.txt，绝不影响预览。"""
    try:
        from core import runtime_root

        d = runtime_root() / "debug"
        d.mkdir(parents=True, exist_ok=True)
        with (d / "画中画日志.txt").open("a", encoding="utf-8") as fp:
            fp.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:  # noqa: BLE001
        pass


def _find_steam_hwnd() -> int | None:
    """只读查找 Steam 游戏窗口（不修改全局 EMULATOR_INFO/ACTIVE_PLATFORM）。"""
    from core import (
        EMULATOR_EXE_NAMES,
        EMULATOR_TITLE_KEYWORDS,
        EXCLUDED_EXE_NAMES,
        GAME_EXACT_TITLES,
        GAME_EXE_NAMES,
        GAME_TITLE_KEYWORDS,
        _exe_name_of_pid,
    )

    my_pid = os.getpid()
    candidates: list[tuple[int, int, int]] = []

    def _cb(hwnd, _):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid == my_pid:
                return True
            exe = _exe_name_of_pid(pid)
            if exe in EXCLUDED_EXE_NAMES or exe in EMULATOR_EXE_NAMES:
                return True
            title = win32gui.GetWindowText(hwnd).strip().lower()
            if any(k in title for k in EMULATOR_TITLE_KEYWORDS):
                return True
            prio = 0
            if exe in GAME_EXE_NAMES:
                prio = 3
            elif title in GAME_EXACT_TITLES:
                prio = 2
            elif any(k in title for k in GAME_TITLE_KEYWORDS):
                prio = 1
            if prio > 0:
                l, t, r, b = win32gui.GetClientRect(hwnd)
                area = max(0, r - l) * max(0, b - t)
                if area > 200 * 200 or (prio == 3 and win32gui.IsIconic(hwnd)):
                    candidates.append((prio, area, hwnd))
        except Exception:  # noqa: BLE001
            pass
        return True

    cb_t = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    ctypes.windll.user32.EnumWindows(cb_t(lambda h, l: bool(_cb(h, l))), 0)
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][2]


def _find_emulator_windows() -> list[int]:
    """只读列出可见（含最小化）的模拟器顶层窗口，按面积降序。"""
    from core import EMULATOR_EXE_NAMES, EMULATOR_TITLE_KEYWORDS, _exe_name_of_pid

    my_pid = os.getpid()
    found: list[tuple[int, int]] = []

    def _cb(hwnd, _):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid == my_pid:
                return True
            exe = _exe_name_of_pid(pid).lower()
            title = win32gui.GetWindowText(hwnd).strip().lower()
            if not (exe in EMULATOR_EXE_NAMES or any(k in title for k in EMULATOR_TITLE_KEYWORDS)):
                return True
            l, t, r, b = win32gui.GetClientRect(hwnd)
            area = max(0, r - l) * max(0, b - t)
            if area > 200 * 200 or win32gui.IsIconic(hwnd):
                found.append((area, hwnd))
        except Exception:  # noqa: BLE001
            pass
        return True

    cb_t = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    ctypes.windll.user32.EnumWindows(cb_t(lambda h, l: bool(_cb(h, l))), 0)
    found.sort(reverse=True)
    return [h for _area, h in found]


def _open_ipc():
    try:
        from mumu_ipc import open_mumu_ipc

        return open_mumu_ipc()
    except Exception:  # noqa: BLE001
        return None


def _resolve_render(top_hwnd: int) -> int:
    from core import resolve_render_hwnd

    return resolve_render_hwnd(top_hwnd)


def select_pip_source(current_ipc=None, allow_ipc: bool = True) -> dict:
    """源选择顺序对齐 core.open_game_window：Steam 优先 → MuMu IPC → 模拟器窗口回退 → none。"""
    steam_hwnd = _find_steam_hwnd()
    emu_hwnds = _find_emulator_windows()
    if steam_hwnd:
        return {
            "mode": "window",
            "kind": "steam",
            "target": steam_hwnd,
            "steam_hwnd": steam_hwnd,
            "emu_hwnds": emu_hwnds,
        }
    if current_ipc is not None:
        try:
            if current_ipc.is_alive():
                return {
                    "mode": "ipc",
                    "kind": "emulator_ipc",
                    "target": current_ipc,
                    "steam_hwnd": None,
                    "emu_hwnds": emu_hwnds,
                }
        except Exception:  # noqa: BLE001
            pass
    # 2026-11-14：没有检测到模拟器窗口时不再反复尝试 open_mumu_ipc()
    # （DLL 加载 + 失败连接会在 GUI 线程里卡顿），只在看到模拟器窗口时才连。
    if allow_ipc and emu_hwnds:
        ipc = _open_ipc()
        if ipc is not None:
            return {
                "mode": "ipc",
                "kind": "emulator_ipc",
                "target": ipc,
                "steam_hwnd": None,
                "emu_hwnds": emu_hwnds,
            }
    if emu_hwnds:
        return {
            "mode": "window",
            "kind": "emulator_window",
            "target": _resolve_render(emu_hwnds[0]),
            "steam_hwnd": None,
            "emu_hwnds": emu_hwnds,
        }
    return {
        "mode": "none",
        "kind": "none",
        "target": None,
        "steam_hwnd": None,
        "emu_hwnds": emu_hwnds,
    }


def detect_dual_clients() -> tuple[int | None, list[int]]:
    """只读检测：返回 (Steam 版第七史诗窗口句柄, 可见模拟器窗口列表)。

    仅供 GUI 做「双客户端同时运行」提示用；不修改 core.EMULATOR_INFO / ACTIVE_PLATFORM，
    也不创建/移动任何窗口。
    """
    try:
        steam_hwnd = _find_steam_hwnd()
    except Exception:  # noqa: BLE001
        steam_hwnd = None
    try:
        emu_hwnds = _find_emulator_windows()
    except Exception:  # noqa: BLE001
        emu_hwnds = []
    return steam_hwnd, emu_hwnds


class PiPWindow:
    """游戏画面小窗：源选择与主程序一致；DWM 硬件合成优先，失败回退 PrintWindow。"""

    def __init__(self, master: tk.Misc, width: int = 1080, fps: float = 30.0) -> None:
        self.master = master
        self.width = max(240, min(1600, int(width)))
        self.fps = max(1.0, min(30.0, float(fps)))
        self.enabled = False
        self.mode = "dwm"
        self._ipc = None          # 模拟器模式下的 MuMu IPC 驱动
        self._win: tk.Toplevel | None = None
        self._label: tk.Label | None = None
        self._hint: tk.Label | None = None
        self._after_id = None
        self._frame_after = None
        self._dest_hwnd = 0
        self._src_hwnd = 0
        self._thumb = ctypes.c_void_p(0)
        self._src_size = (0, 0)
        self._win_obj: GameWindow | None = None
        self._photo = None
        self._src_kind = "none"
        self._next_ipc_try = 0.0
        self._ipc_fail_streak = 0
        self._last_emu_warn_cnt = 0
        self._logged_first_frame = False

    # ---------- 生命周期 ----------
    def start(self) -> None:
        if self.enabled:
            return
        self.enabled = True
        self.mode = "dwm"
        self._win = tk.Toplevel(self.master)
        self._win.title("E7Pilot 画中画")
        self._win.configure(bg="#101418")
        self._win.attributes("-topmost", True)
        self._win.geometry(f"{self.width}x{max(1, int(self.width * 9 / 16))}+40+80")
        self._win.protocol("WM_DELETE_WINDOW", self.stop)

        self._label = tk.Label(self._win, bg="#101418")
        self._label.pack(fill="both", expand=True)
        self._hint = tk.Label(self._win, text="正在连接游戏窗口...", fg="#888", bg="#101418")
        self._hint.place(relx=0.5, rely=0.5, anchor="center")

        self._dest_hwnd = _toplevel_hwnd(self._win)
        self._noactivate(self._dest_hwnd)
        self._win.bind("<Configure>", lambda _e: self._update_rect())
        self._src_kind = "none"
        self._next_ipc_try = 0.0
        self._ipc_fail_streak = 0
        self._last_emu_warn_cnt = 0
        self._logged_first_frame = False
        _pip_log(f"start width={self.width} fps={self.fps}")
        self._watchdog()

    def _close_ipc(self) -> None:
        if self._ipc is not None:
            try:
                self._ipc.close()
            except Exception:  # noqa: BLE001
                pass
            self._ipc = None

    def _clear_label_image(self) -> None:
        if self._label is not None:
            try:
                self._label.configure(image="", text="")
            except Exception:  # noqa: BLE001
                pass
        self._photo = None

    def stop(self) -> None:
        self.enabled = False
        _pip_log(f"stop last_mode={self.mode} last_kind={self._src_kind}")
        for attr in ("_after_id", "_frame_after"):
            aid = getattr(self, attr, None)
            if aid is not None:
                try:
                    self.master.after_cancel(aid)
                except Exception:  # noqa: BLE001
                    pass
                setattr(self, attr, None)
        self._unregister()
        self._close_ipc()
        if self._win is not None:
            try:
                self._win.destroy()
            except Exception:  # noqa: BLE001
                pass
        self._win = None
        self._label = None
        self._hint = None
        self._photo = None
        self._win_obj = None
        self._dest_hwnd = 0
        self._src_hwnd = 0
        self._src_kind = "none"

    def set_fps(self, fps: float) -> None:
        """DWM 模式帧率跟随显示器；只有回退模式才用这个值。"""
        self.fps = max(1.0, min(30.0, float(fps)))

    def set_width(self, width: int) -> None:
        self.width = max(240, min(1600, int(width)))
        if self._win is not None and self.mode == "ipc":
            try:
                self._win.geometry(f"{self.width}x{max(1, int(self.width * 9 / 16))}")
            except Exception:  # noqa: BLE001
                pass
            return
        if self._win is not None:
            sw, sh = self._src_size
            ratio = (sh / sw) if sw and sh else 9 / 16
            try:
                self._win.geometry(f"{self.width}x{max(1, int(self.width * ratio))}")
            except Exception:  # noqa: BLE001
                pass
            self._update_rect()

    # ---------- DWM ----------
    @staticmethod
    def _noactivate(hwnd: int) -> None:
        try:
            ex = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex | win32con.WS_EX_NOACTIVATE)
        except Exception:  # noqa: BLE001
            pass

    def _unregister(self) -> None:
        if self._thumb.value:
            try:
                dwmapi.DwmUnregisterThumbnail(self._thumb)
            except Exception:  # noqa: BLE001
                pass
            self._thumb = ctypes.c_void_p(0)

    def _register(self, src: int) -> bool:
        self._unregister()
        thumb = ctypes.c_void_p(0)
        hr = dwmapi.DwmRegisterThumbnail(self._dest_hwnd, src, ctypes.byref(thumb))
        if hr != 0 or not thumb.value:
            return False
        self._thumb = thumb
        self._src_hwnd = src
        self.mode = "dwm"
        return True

    def _update_rect(self) -> None:
        if not self._thumb.value:
            return
        size = _SIZE()
        if dwmapi.DwmQueryThumbnailSourceSize(self._thumb, ctypes.byref(size)) != 0:
            return
        sw, sh = size.cx, size.cy
        if sw <= 0 or sh <= 0:
            return
        self._src_size = (sw, sh)
        try:
            _l, _t, r, b = win32gui.GetClientRect(self._dest_hwnd)
        except Exception:  # noqa: BLE001
            return
        dw, dh = max(1, r), max(1, b)
        scale = min(dw / sw, dh / sh)
        vw, vh = int(round(sw * scale)), int(round(sh * scale))
        ox, oy = (dw - vw) // 2, (dh - vh) // 2
        props = _THUMB_PROPS()
        props.dwFlags = (
            DWM_TNP_RECTDESTINATION | DWM_TNP_VISIBLE | DWM_TNP_OPACITY | DWM_TNP_SOURCECLIENTAREAONLY
        )
        props.rcDestination = _RECT(ox, oy, ox + vw, oy + vh)
        props.opacity = 255
        props.fVisible = True
        props.fSourceClientAreaOnly = True
        dwmapi.DwmUpdateThumbnailProperties(self._thumb, ctypes.byref(props))

    # ---------- 看门狗（500ms 一次，几乎不耗 CPU） ----------
    def _watchdog(self) -> None:
        if not self.enabled:
            return
        try:
            self._check()
        except Exception:  # noqa: BLE001
            pass
        self._after_id = self.master.after(500, self._watchdog)

    def _check(self) -> None:
        now = time.monotonic()
        allow_ipc = now >= self._next_ipc_try
        sel = select_pip_source(current_ipc=self._ipc, allow_ipc=allow_ipc)
        emu_hwnds = sel["emu_hwnds"]
        if len(emu_hwnds) > 1 and len(emu_hwnds) != self._last_emu_warn_cnt:
            self._last_emu_warn_cnt = len(emu_hwnds)
            _pip_log(
                f"warn multi_emu count={len(emu_hwnds)} "
                f"hwnds={[hex(h) for h in emu_hwnds]} single_instance_only=True"
            )
        elif len(emu_hwnds) <= 1:
            self._last_emu_warn_cnt = 0

        if sel["mode"] == "ipc":
            if self._ipc is not sel["target"]:
                self._unregister()
                self._stop_fallback()
                self._src_hwnd = 0
                self._ipc = sel["target"]
                self.mode = "ipc"
                self._src_kind = sel["kind"]
                self._ipc_fail_streak = 0
                self._logged_first_frame = False
                self._win_obj = None
                self._clear_label_image()
                self._hide_hint()
                _pip_log(
                    f"switch mode=ipc kind={sel['kind']} steam={sel['steam_hwnd']} "
                    f"emu={[hex(h) for h in emu_hwnds]} "
                    f"inst={getattr(self._ipc, 'instance_index', 0)}/{getattr(self._ipc, 'display_id', 0)}"
                )
            if self._frame_after is None:
                self._frame_after = self.master.after(0, self._ipc_frame_loop)
            return

        if not sel["steam_hwnd"] and allow_ipc:
            # 没有 Steam 时才需要重试 IPC；select_pip_source 在无模拟器窗口时不会真的连接，
            # 这里退避 5 秒，避免无源状态下反复加载 DLL 造成 GUI 卡顿。
            self._next_ipc_try = now + 5.0

        if sel["mode"] == "none":
            if self._ipc is not None or self._src_hwnd or self._src_kind != "none":
                _pip_log(f"switch mode=none prev_mode={self.mode} prev_kind={self._src_kind}")
            self._close_ipc()
            self._unregister()
            self._stop_fallback()
            self._clear_label_image()
            self._src_hwnd = 0
            self._src_kind = "none"
            self._win_obj = None
            self.mode = "dwm"
            self._show_hint("未找到游戏窗口")
            return

        hwnd = int(sel["target"])
        kind = sel["kind"]
        if self._ipc is not None:
            self._close_ipc()
            self._stop_fallback()
            self._clear_label_image()
            self._win_obj = None

        # 模拟器窗口回退路径：target 是渲染子窗口，IsIconic 恒为 False；
        # 用模拟器顶层窗口判断最小化，避免 PrintWindow 失败后回退到屏幕抓取（会抓到桌面）。
        if kind == "emulator_window" and emu_hwnds and win32gui.IsIconic(emu_hwnds[0]):
            self._src_kind = kind
            self._src_hwnd = 0
            self._show_hint("游戏已最小化（恢复窗口即可预览）")
            return

        if self._src_hwnd != hwnd or self._src_kind != kind or not win32gui.IsWindow(self._src_hwnd):
            self._src_kind = kind
            self._win_obj = None
            self._logged_first_frame = False
            if not self._register(hwnd):
                self.mode = "fallback"
                self._src_hwnd = hwnd
                if win32gui.IsIconic(hwnd):
                    self._show_hint("游戏已最小化（恢复窗口即可预览）")
                else:
                    self._hide_hint()
                self._start_fallback()
                _pip_log(
                    f"switch mode=fallback kind={kind} hwnd={hex(hwnd)} "
                    f"emu={[hex(h) for h in emu_hwnds]}"
                )
                return
            self.mode = "dwm"
            self._stop_fallback()
            self._clear_label_image()
            _pip_log(
                f"switch mode=dwm kind={kind} hwnd={hex(hwnd)} "
                f"emu={[hex(h) for h in emu_hwnds]}"
            )

        if win32gui.IsIconic(hwnd):
            self._show_hint("游戏已最小化（恢复窗口即可预览）")
            return
        self._hide_hint()
        self._update_rect()
        if self.mode == "dwm":
            self._stop_fallback()

    def _show_hint(self, text: str) -> None:
        if self._hint is not None:
            self._hint.configure(text=text)
            self._hint.place(relx=0.5, rely=0.5, anchor="center")

    def _hide_hint(self) -> None:
        if self._hint is not None:
            self._hint.place_forget()

    # ---------- 回退：PrintWindow 抓帧 ----------
    def _start_fallback(self) -> None:
        if self._frame_after is None and self.enabled:
            self._frame_loop()

    def _ipc_frame_loop(self) -> None:
        """模拟器模式：直接从 MuMu 共享内存取帧（6ms/帧）。"""
        if not self.enabled or self.mode != "ipc" or self._ipc is None:
            self._frame_after = None
            return
        try:
            self._draw_ipc_frame()
        except Exception as exc:  # noqa: BLE001
            self._ipc_fail_streak += 1
            if self._ipc_fail_streak >= 3:
                _pip_log(f"error ipc_capture failed x{self._ipc_fail_streak}: {exc!r}")
                self._close_ipc()
                self._clear_label_image()
                self.mode = "dwm"
                self._src_kind = "none"
                self._src_hwnd = 0
                self._logged_first_frame = False
                self._frame_after = None
                self._show_hint("未找到游戏窗口")
                return
        self._frame_after = self.master.after(int(1000 / max(1.0, self.fps)), self._ipc_frame_loop)

    def _draw_ipc_frame(self) -> None:
        if self._label is None or self._ipc is None:
            return
        img = self._ipc.capture()
        if img is None or getattr(img, "size", 0) == 0:
            raise RuntimeError("empty ipc frame")
        self._ipc_fail_streak = 0
        h, w = img.shape[:2]
        if not self._logged_first_frame:
            self._logged_first_frame = True
            _pip_log(f"frame mode=ipc kind={self._src_kind} size={w}x{h} mean={float(img.mean()):.1f}")
        tw = self.width
        th = max(1, int(h * tw / w))
        small = cv2.resize(img, (tw, th), interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        self._photo = ImageTk.PhotoImage(Image.fromarray(rgb))
        self._label.configure(image=self._photo, text="")

    def _stop_fallback(self) -> None:
        if self._frame_after is not None:
            try:
                self.master.after_cancel(self._frame_after)
            except Exception:  # noqa: BLE001
                pass
            self._frame_after = None

    def _frame_loop(self) -> None:
        if not self.enabled or self.mode != "fallback":
            self._frame_after = None
            return
        try:
            self._draw_frame()
        except Exception:  # noqa: BLE001
            pass
        self._frame_after = self.master.after(int(1000 / self.fps), self._frame_loop)

    def _draw_frame(self) -> None:
        if self._label is None:
            return
        hwnd = self._src_hwnd
        if not hwnd or not win32gui.IsWindow(hwnd) or win32gui.IsIconic(hwnd):
            return
        if self._win_obj is None or self._win_obj.hwnd != hwnd:
            self._win_obj = GameWindow(hwnd, "background")
        img = self._win_obj.capture("auto")
        if img is None or img.size == 0 or float(img.mean()) < 2.0:
            return
        h, w = img.shape[:2]
        if not self._logged_first_frame:
            self._logged_first_frame = True
            _pip_log(f"frame mode=fallback kind={self._src_kind} hwnd={hex(hwnd)} size={w}x{h} mean={float(img.mean()):.1f}")
        tw = self.width
        th = max(1, int(h * tw / w))
        small = cv2.resize(img, (tw, th), interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        self._photo = ImageTk.PhotoImage(Image.fromarray(rgb))
        self._label.configure(image=self._photo, text="")
