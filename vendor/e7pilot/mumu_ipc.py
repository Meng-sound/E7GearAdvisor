"""MuMu 模拟器 12+ 原生 IPC 驱动（截图 6ms、触控 <1ms、支持遮挡与最小化）。

与 core.GameWindow 接口保持一致，可直接替换使用：
    client_size / capture / click / click_ratio / press / press_ratio
    drag_ratio / wheel / press_key / is_alive / is_minimized / activate
"""
from __future__ import annotations

import ctypes
import os
import random
import time
import winreg
from pathlib import Path

import cv2
import numpy as np

from core import CLICK_GAP, CLICK_HOLD, CLICK_HOLD_FAST, read_click_timing

DLL_RELATIVE = (
    ("nx_device", "15.0", "shell", "sdk", "external_renderer_ipc.dll"),
    ("nx_device", "12.0", "shell", "sdk", "external_renderer_ipc.dll"),
    ("nx_main", "sdk", "external_renderer_ipc.dll"),
    ("shell", "sdk", "external_renderer_ipc.dll"),
)

ANDROID_KEYCODE_BACK = 4


def find_mumu_root() -> Path | None:
    """从注册表/常见路径找 MuMu 安装根目录。"""
    for hive, sub in (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\MuMuPlayer-12.0"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\MuMuPlayer-12.0"),
    ):
        try:
            with winreg.OpenKey(hive, sub) as key:
                val, _ = winreg.QueryValueEx(key, "InstallLocation")
                p = Path(str(val).strip('"'))
                if p.exists():
                    return p
        except OSError:
            continue

    for drive in ("C:", "D:", "E:", "F:"):
        for sub in (
            "Program Files/Netease/MuMu",
            "Program Files/Netease/MuMuPlayer-12.0",
            "Program Files/Netease/MuMu Player 12",
            "MuMu",
        ):
            p = Path(f"{drive}/{sub}")
            if p.exists() and list(p.glob("nx_*")):
                return p
    return None


def locate_ipc_dll(root: Path) -> Path | None:
    for parts in DLL_RELATIVE:
        p = root.joinpath(*parts)
        if p.exists():
            return p
    hits = list(root.glob("nx_*/**/external_renderer_ipc.dll"))
    return hits[0] if hits else None


class MuMuIpcWindow:
    """MuMu 12/15 原生共享内存驱动（接口对齐 core.GameWindow）。"""

    def __init__(self, root: str | Path | None = None, instance_index: int = 0, display_id: int = 0) -> None:
        root_path = Path(root) if root else find_mumu_root()
        if root_path is None or not root_path.exists():
            raise RuntimeError("未找到 MuMu 安装目录")
        dll = locate_ipc_dll(root_path)
        if dll is None:
            raise RuntimeError("未找到 external_renderer_ipc.dll")

        self.mumu_root = root_path
        self.instance_index = instance_index
        self.display_id = display_id
        self.hwnd = 0  # 兼容主循环里的 self.win.hwnd 赋值
        self.click_mode = "background"
        self.click_hold, self.click_gap = read_click_timing()
        self.viewport_offset = (0, 0)
        self.viewport_size: tuple[int, int] | None = None

        for d in {str(dll.parent), str(dll.parent.parent), str(root_path), str(root_path / "shell")}:
            try:
                os.add_dll_directory(d)
            except Exception:  # noqa: BLE001
                pass
        self._lib = ctypes.CDLL(str(dll))
        self._setup()

        self._conn = 0
        self._w = 0
        self._h = 0
        self._buf = None
        self._connect()

    # ---------- 初始化 ----------
    def _setup(self) -> None:
        lib = self._lib
        lib.nemu_connect.argtypes = [ctypes.c_wchar_p, ctypes.c_int]
        lib.nemu_connect.restype = ctypes.c_int
        lib.nemu_disconnect.argtypes = [ctypes.c_int]
        lib.nemu_capture_display.argtypes = [
            ctypes.c_int,
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.c_void_p,
        ]
        lib.nemu_capture_display.restype = ctypes.c_int
        lib.nemu_input_event_touch_down.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        lib.nemu_input_event_touch_down.restype = ctypes.c_int
        lib.nemu_input_event_touch_up.argtypes = [ctypes.c_int, ctypes.c_int]
        lib.nemu_input_event_touch_up.restype = ctypes.c_int
        lib.nemu_input_event_key_down.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
        lib.nemu_input_event_key_down.restype = ctypes.c_int
        lib.nemu_input_event_key_up.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
        lib.nemu_input_event_key_up.restype = ctypes.c_int

    def _connect(self) -> None:
        if self._conn > 0:
            try:
                self._lib.nemu_disconnect(self._conn)
            except Exception:  # noqa: BLE001
                pass
        self._conn = self._lib.nemu_connect(str(self.mumu_root), self.instance_index)
        if self._conn <= 0:
            raise RuntimeError(f"nemu_connect 失败 (conn={self._conn})")
        w, h = ctypes.c_int(0), ctypes.c_int(0)
        ret = self._lib.nemu_capture_display(self._conn, self.display_id, 0, ctypes.byref(w), ctypes.byref(h), None)
        if ret != 0 or w.value <= 0 or h.value <= 0:
            raise RuntimeError(f"查询分辨率失败 ret={ret} {w.value}x{h.value}")
        self._w, self._h = w.value, h.value
        self._buf = (ctypes.c_ubyte * (self._w * self._h * 4))()

    def close(self) -> None:
        if self._conn > 0:
            try:
                self._lib.nemu_disconnect(self._conn)
            except Exception:  # noqa: BLE001
                pass
            self._conn = 0

    # ---------- 启动兼容性自检（反馈问题时发这一行即可定位） ----------
    def build_compat_diag_line(self, capture_cfg: str = "auto") -> str:
        """IPC 驱动自检：设备分辨率/安装目录/版本目录/关联窗口/首帧亮度。"""
        import win32gui
        import win32process

        from core import EMULATOR_INFO, _exe_name_of_pid, runtime_root

        dev_w, dev_h = self.client_size()
        ver = "-"
        try:
            vers = sorted(p.name for p in (self.mumu_root / "nx_device").iterdir() if p.is_dir())
            ver = ",".join(vers) or "-"
        except Exception:  # noqa: BLE001
            pass
        top = int((EMULATOR_INFO or {}).get("top") or 0)
        win_w = int((EMULATOR_INFO or {}).get("w") or 0)
        win_h = int((EMULATOR_INFO or {}).get("h") or 0)
        win_cls = win_title = win_exe = "-"
        if top:
            try:
                win_cls = win32gui.GetClassName(top)
                win_title = (win32gui.GetWindowText(top) or "")[:24]
                _, pid = win32process.GetWindowThreadProcessId(top)
                win_exe = _exe_name_of_pid(pid) or "-"
            except Exception:  # noqa: BLE001
                pass
        all_mean = mid_mean = -1.0
        try:
            img = self.capture()
            if img is not None and getattr(img, "size", 0) > 0:
                all_mean = float(img.mean())
                hh, ww = img.shape[:2]
                mid_mean = float(
                    img[int(hh * 0.18): int(hh * 0.82), int(ww * 0.18): int(ww * 0.82)].mean()
                )
        except Exception:  # noqa: BLE001
            pass
        line = (
            f"🔎 [兼容自检] 平台=emulator(IPC) | "
            f"设备={dev_w}x{dev_h}(display={self.display_id},实例={self.instance_index}) | "
            f"安装={self.mumu_root} | nx_device={ver} | "
            f"窗口=0x{top:X}({win_cls}/{win_exe}/{win_title!r}) {win_w}x{win_h} | "
            f"首帧亮度: IPC(全图={all_mean:.1f},中心={mid_mean:.1f}) | 截图方式=ipc"
        )
        try:
            d = runtime_root() / "debug"
            d.mkdir(parents=True, exist_ok=True)
            with (d / "启动自检.txt").open("a", encoding="utf-8") as fp:
                fp.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {line}\n")
        except Exception:  # noqa: BLE001
            pass
        return line

    # ---------- 与 GameWindow 对齐的几何接口 ----------
    def is_alive(self) -> bool:
        if self._conn > 0:
            return True
        try:
            self._connect()
            return True
        except Exception:  # noqa: BLE001
            return False

    def is_minimized(self) -> bool:
        return False

    def activate(self) -> None:
        return None

    def client_size(self) -> tuple[int, int]:
        return self._w, self._h

    def client_origin_on_screen(self) -> tuple[int, int]:
        return 0, 0

    def set_viewport(self, x1: int, y1: int, x2: int, y2: int) -> None:
        if x2 <= x1 or y2 <= y1:
            self.viewport_offset = (0, 0)
            self.viewport_size = None
            return
        self.viewport_offset = (int(x1), int(y1))
        self.viewport_size = (int(x2 - x1), int(y2 - y1))

    def viewport(self) -> tuple[int, int, int, int]:
        if self.viewport_size is not None:
            return self.viewport_size[0], self.viewport_size[1], self.viewport_offset[0], self.viewport_offset[1]
        return self._w, self._h, 0, 0

    # ---------- 截图 ----------
    def capture(self, method: str = "auto") -> np.ndarray:
        w, h = ctypes.c_int(self._w), ctypes.c_int(self._h)
        ret = self._lib.nemu_capture_display(
            self._conn, self.display_id, self._w * self._h * 4, ctypes.byref(w), ctypes.byref(h), ctypes.byref(self._buf)
        )
        if ret != 0:
            self._connect()
            w, h = ctypes.c_int(self._w), ctypes.c_int(self._h)
            ret = self._lib.nemu_capture_display(
                self._conn, self.display_id, self._w * self._h * 4,
                ctypes.byref(w), ctypes.byref(h), ctypes.byref(self._buf),
            )
            if ret != 0:
                raise RuntimeError(f"nemu_capture_display 失败 ret={ret}")
        # ① 运行中用户改了模拟器分辨率：重新分配缓冲后重抓一次
        if w.value != self._w or h.value != self._h:
            self._w, self._h = int(w.value), int(h.value)
            self._buf = (ctypes.c_ubyte * (self._w * self._h * 4))()
            w2, h2 = ctypes.c_int(self._w), ctypes.c_int(self._h)
            ret2 = self._lib.nemu_capture_display(
                self._conn, self.display_id, self._w * self._h * 4,
                ctypes.byref(w2), ctypes.byref(h2), ctypes.byref(self._buf),
            )
            if ret2 != 0:
                self._connect()
                w3, h3 = ctypes.c_int(self._w), ctypes.c_int(self._h)
                self._lib.nemu_capture_display(
                    self._conn, self.display_id, self._w * self._h * 4,
                    ctypes.byref(w3), ctypes.byref(h3), ctypes.byref(self._buf),
                )

        arr = np.ctypeslib.as_array(self._buf).reshape((self._h, self._w, 4))
        img = cv2.flip(cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR), 0)
        if self.viewport_size is not None:
            ox, oy = self.viewport_offset
            vw, vh = self.viewport_size
            img = img[oy : oy + vh, ox : ox + vw]
        return img

    # ---------- 触控 ----------
    def _tap_at(self, x: int, y: int, hold: float) -> None:
        self._lib.nemu_input_event_touch_down(self._conn, self.display_id, int(x), int(y))
        time.sleep(max(0.01, hold))
        self._lib.nemu_input_event_touch_up(self._conn, self.display_id)

    def click(
        self,
        x: int,
        y: int,
        jitter: int = 4,
        clicks: int = 1,
        click_gap: float | None = None,
        quick: bool = False,
        hold: float | None = None,
    ) -> None:
        vw, vh, ox, oy = self.viewport()
        x = ox + max(1, min(vw - 2, x))
        y = oy + max(1, min(vh - 2, y))
        n = max(1, int(clicks))
        gap = self.click_gap if click_gap is None else float(click_gap)
        press_hold = float(hold) if hold is not None else random.uniform(
            *(CLICK_HOLD_FAST if quick else self.click_hold)
        )
        for i in range(n):
            if i > 0:
                time.sleep(random.uniform(gap * 0.9, gap * 1.1))
            jx = x + random.randint(-jitter, jitter)
            jy = y + random.randint(-jitter, jitter)
            self._tap_at(jx, jy, press_hold)

    def click_ratio(
        self,
        rx: float,
        ry: float,
        jitter: int = 3,
        clicks: int = 1,
        click_gap: float | None = None,
        quick: bool = False,
        hold: float | None = None,
    ) -> None:
        vw, vh, ox, oy = self.viewport()
        self.click(
            ox + int(vw * rx) - ox,
            oy + int(vh * ry) - oy,
            jitter=jitter,
            clicks=clicks,
            click_gap=click_gap,
            quick=quick,
            hold=hold,
        )

    def press_start(self, x: int, y: int, jitter: int = 2) -> None:
        vw, vh, ox, oy = self.viewport()
        px = ox + max(1, min(vw - 2, x + random.randint(-jitter, jitter)))
        py = oy + max(1, min(vh - 2, y + random.randint(-jitter, jitter)))
        self._press_pt = (px, py)
        self._lib.nemu_input_event_touch_down(self._conn, self.display_id, px, py)

    def press_end(self) -> None:
        if getattr(self, "_press_pt", None) is None:
            return
        self._press_pt = None
        self._lib.nemu_input_event_touch_up(self._conn, self.display_id)

    def press_start_ratio(self, rx: float, ry: float, jitter: int = 2) -> None:
        vw, vh, _ox, _oy = self.viewport()
        self.press_start(int(vw * rx), int(vh * ry), jitter=jitter)

    def press(self, x: int, y: int, seconds: float = 1.5, jitter: int = 2) -> None:
        vw, vh, ox, oy = self.viewport()
        px = ox + max(1, min(vw - 2, x + random.randint(-jitter, jitter)))
        py = oy + max(1, min(vh - 2, y + random.randint(-jitter, jitter)))
        self._lib.nemu_input_event_touch_down(self._conn, self.display_id, px, py)
        time.sleep(max(0.2, float(seconds)))
        self._lib.nemu_input_event_touch_up(self._conn, self.display_id)

    def press_ratio(self, rx: float, ry: float, seconds: float = 1.5, jitter: int = 2) -> None:
        vw, vh, _ox, _oy = self.viewport()
        self.press(int(vw * rx), int(vh * ry), seconds=seconds, jitter=jitter)

    def drag_ratio(
        self,
        rx1: float,
        ry1: float,
        rx2: float,
        ry2: float,
        duration: float = 0.24,
        steps: int = 14,
    ) -> None:
        vw, vh, ox, oy = self.viewport()
        x1, y1 = ox + int(vw * rx1), oy + int(vh * ry1)
        x2, y2 = ox + int(vw * rx2), oy + int(vh * ry2)
        n = max(4, int(steps))
        step_sleep = max(0.008, duration / n)
        self._lib.nemu_input_event_touch_down(self._conn, self.display_id, x1, y1)
        for i in range(1, n + 1):
            t = i / n
            cx = int(round(x1 + (x2 - x1) * t))
            cy = int(round(y1 + (y2 - y1) * t))
            self._lib.nemu_input_event_touch_down(self._conn, self.display_id, cx, cy)
            time.sleep(step_sleep)
        time.sleep(0.06)
        self._lib.nemu_input_event_touch_up(self._conn, self.display_id)

    def wheel(self, rx: float, ry: float, notches: int = 3, up: bool = False) -> None:
        """滚轮在模拟器里用触摸滑动模拟。"""
        vw, vh, _ox, _oy = self.viewport()
        distance = 0.10 * max(1, notches)
        y1 = ry + (distance if up else -distance)
        y2 = ry - (distance if up else -distance)
        self.drag_ratio(rx, max(0.05, min(0.95, y1)), rx, max(0.05, min(0.95, y2)), duration=0.35, steps=12)

    def press_key(self, vk: int) -> None:
        """把 Windows 的 ESC 映射成 Android BACK，其它键忽略。"""
        if vk == 27:
            self._lib.nemu_input_event_key_down(self._conn, self.display_id, ANDROID_KEYCODE_BACK)
            time.sleep(0.05)
            self._lib.nemu_input_event_key_up(self._conn, self.display_id, ANDROID_KEYCODE_BACK)


# ---------------- 工厂：优先 Steam，其次 MuMu IPC ----------------
def open_mumu_ipc() -> MuMuIpcWindow | None:
    """尝试连接 MuMu；失败返回 None（不影响 Steam 用法）。"""
    try:
        return MuMuIpcWindow()
    except Exception:  # noqa: BLE001
        return None
