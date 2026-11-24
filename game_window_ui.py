"""Main-window controls for sizing and previewing a selected game window."""
import ctypes
import queue
import threading
import time
import tkinter as tk
from ctypes import wintypes
from tkinter import simpledialog, ttk

from desktop_capture import find_game_windows
from ui_theme import FONT, MUTED


class MonitorInfo(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('monitor', wintypes.RECT),
                ('work', wintypes.RECT), ('flags', wintypes.DWORD)]


def resize_game(target, width, height):
    """Resize the client area and center the visible window on its current monitor."""
    user = ctypes.WinDLL('user32', use_last_error=True)
    dwm = ctypes.WinDLL('dwmapi')
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.IsZoomed.argtypes = [wintypes.HWND]
    user.IsIconic.argtypes = [wintypes.HWND]
    user.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user.MonitorFromWindow.restype = wintypes.HMONITOR
    user.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MonitorInfo)]
    user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND] + [ctypes.c_int] * 4 + [wintypes.UINT]
    dwm.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD,
                                          ctypes.c_void_p, wintypes.DWORD]
    hwnd = target['hwnd']
    pid = wintypes.DWORD()
    user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value != target['pid']:
        raise ValueError('游戏窗口已关闭，请重新选择。')
    if user.IsZoomed(hwnd) or user.IsIconic(hwnd):
        raise ValueError('请先把游戏还原为普通窗口。')

    monitor = user.MonitorFromWindow(hwnd, 2)
    info = MonitorInfo()
    info.size = ctypes.sizeof(info)
    outer = wintypes.RECT()
    client = wintypes.RECT()
    if (not user.GetMonitorInfoW(monitor, ctypes.byref(info))
            or not user.GetWindowRect(hwnd, ctypes.byref(outer))
            or not user.GetClientRect(hwnd, ctypes.byref(client))):
        raise ctypes.WinError(ctypes.get_last_error())
    work = info.work
    work_width, work_height = work.right - work.left, work.bottom - work.top
    visible = wintypes.RECT()
    if dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(visible), ctypes.sizeof(visible)) != 0:
        visible = outer
    visible_width = width + visible.right - visible.left - client.right
    visible_height = height + visible.bottom - visible.top - client.bottom
    if visible_width > work_width or visible_height > work_height:
        raise ValueError(f'含窗口边框需要 {visible_width}×{visible_height}，当前屏幕可用 {work_width}×{work_height}。请输入更小的尺寸。')
    x = work.left + (work_width - visible_width) // 2 + outer.left - visible.left
    y = work.top + (work_height - visible_height) // 2 + outer.top - visible.top
    width += outer.right - outer.left - client.right
    height += outer.bottom - outer.top - client.bottom
    if not user.SetWindowPos(hwnd, None, x, y, width, height, 0x0014):
        raise ctypes.WinError(ctypes.get_last_error())


def bounded_number(variable, label, minimum, maximum):
    try:
        value = int(variable.get())
    except ValueError:
        value = 0
    if not minimum <= value <= maximum:
        raise ValueError(f'{label}请输入 {minimum}–{maximum} 之间的整数。')
    return value


class GameWindowControls(ttk.Frame):
    def __init__(self, app):
        super().__init__(app, style='Card.TFrame', padding=(7, 4))
        self.app = app
        self.preview = None
        self.preview_stop = None
        self.preview_job = None
        self.preview_target = None
        self.preview_width = tk.StringVar(self, '1080')
        self.preview_fps = tk.StringVar(self, '30')
        self.window_width = tk.StringVar(self, '1819')
        self.window_height = tk.StringVar(self, '1023')
        self.preview_enabled = tk.BooleanVar(self, False)
        self._build()

    def _build(self):
        size = ttk.Frame(self, style='Card.TFrame')
        size.pack(fill='x', pady=(0, 3))
        ttk.Label(size, text='游戏窗口', style='Game.TLabel').pack(side='left', padx=(0, 5))
        ttk.Entry(size, textvariable=self.window_width, width=5).pack(side='left')
        ttk.Label(size, text='×', style='Game.TLabel').pack(side='left', padx=3)
        ttk.Entry(size, textvariable=self.window_height, width=5).pack(side='left')
        ttk.Button(size, text='应用尺寸', style='Compact.TButton',
                   command=self.apply_size).pack(side='left', padx=(6, 0))
        preview = ttk.Frame(self, style='Card.TFrame')
        preview.pack(fill='x')
        ttk.Checkbutton(preview, text='画中画', variable=self.preview_enabled,
                        command=self.apply_preview).pack(side='left', padx=(0, 5))
        for label, variable, width in [('宽度', self.preview_width, 5), ('帧率', self.preview_fps, 3)]:
            ttk.Label(preview, text=label, style='Game.TLabel').pack(side='left', padx=(0, 3))
            ttk.Entry(preview, textvariable=variable, width=width).pack(side='left', padx=(0, 5))
        ttk.Button(preview, text='应用', style='Compact.TButton',
                   command=self.apply_preview).pack(side='left')

    def choose_target(self):
        windows = find_game_windows()
        if not windows:
            raise ValueError('没有找到第七史诗窗口，请先打开游戏。')
        if len(windows) == 1:
            return windows[0]
        choice = simpledialog.askinteger('选择游戏窗口',
                                         '\n'.join(f"{i}. {row['title']}（PID {row['pid']}）"
                                                   for i, row in enumerate(windows, 1)),
                                         minvalue=1, maxvalue=len(windows), parent=self.app)
        return windows[choice - 1] if choice is not None else None

    def apply_size(self):
        task = getattr(self.app, 'task_replay_window', None)
        runner = getattr(task, 'live_runner', None)
        if runner is not None and runner.alive():
            self.app.status.set('请先停止自动任务，再调整游戏窗口尺寸。')
            return
        try:
            width = bounded_number(self.window_width, '窗口宽度', 320, 7680)
            height = bounded_number(self.window_height, '窗口高度', 240, 4320)
            target = self.choose_target()
            if target is None:
                return
            resize_game(target, width, height)
            self.after(350, self.verify_size, target, width, height)
        except (OSError, ValueError) as error:
            if getattr(error, 'winerror', None) == 5:
                self.app.status.set('Windows 拒绝调整游戏窗口。请关闭本工具，双击 Start-Local-Test.cmd 并确认管理员授权后重试。')
            else:
                self.app.status.set(str(error))

    def verify_size(self, target, width, height):
        current = next((row for row in find_game_windows()
                        if row['hwnd'] == target['hwnd'] and row['pid'] == target['pid']), None)
        if current is None:
            self.app.status.set('游戏窗口已关闭或变化，请重新应用尺寸。')
            return
        actual_width, actual_height = current['client']
        actual = f'{actual_width}×{actual_height}'
        if (actual_width, actual_height) == (width, height):
            self.app.status.set(f'游戏客户区已应用 {actual}。')
        else:
            self.app.status.set(f'请求 {width}×{height}，游戏实际客户区为 {actual}。请检查游戏内的窗口模式与分辨率。')
        if self.preview_target and self.preview_target['hwnd'] == current['hwnd']:
            self.apply_preview(current)

    def apply_preview(self, target=None):
        if not self.preview_enabled.get():
            self.close_preview()
            return
        try:
            width = bounded_number(self.preview_width, '画中画宽度', 240, 3840)
            fps = bounded_number(self.preview_fps, '画中画帧率', 1, 60)
            target = target or self.preview_target or self.choose_target()
            if target is None:
                self.close_preview()
                return
            if target.get('minimized'):
                raise ValueError('请先还原游戏窗口。')
        except (OSError, ValueError) as error:
            if self.preview is None:
                self.close_preview()
            self.app.status.set(str(error))
            return

        position = (self.preview.winfo_x(), self.preview.winfo_y()) if self.preview else None
        self.close_preview()
        self.preview_enabled.set(True)
        self.preview_target = target
        self.preview_stop = stop = threading.Event()
        frames = queue.Queue(maxsize=1)
        preview = self.preview = tk.Toplevel(self.app)
        preview.title('第七史诗 · 画中画')
        preview.configure(bg='#0a111c')
        preview.attributes('-topmost', True)
        preview.protocol('WM_DELETE_WINDOW', self.close_preview)
        width = min(width, max(240, preview.winfo_screenwidth() - 40))
        max_height = max(120, preview.winfo_screenheight() - 100)
        if position is not None:
            preview.geometry(f'{position[0]:+d}{position[1]:+d}')
        label = tk.Label(preview, text='正在读取游戏画面…', bg='#0a111c',
                         fg=MUTED, font=(FONT, 10), borderwidth=0)
        label.pack(fill='both', expand=True)

        def show():
            from PIL import ImageTk

            self.preview_job = None
            try:
                frame = frames.get_nowait()
            except queue.Empty:
                pass
            else:
                if isinstance(frame, Exception):
                    self.app.status.set(f'画中画已停止：{frame}')
                    self.close_preview()
                    return
                label.image = ImageTk.PhotoImage(frame, master=preview)
                label.configure(image=label.image, text='')
            self.preview_job = self.after(max(1, round(1000 / fps)), show)

        capture_target = dict(target, capture_mode='background',
                              capture_interval_ms=max(1, round(1000 / fps)),
                              preview_only=True, preview_width=width, preview_height=max_height)
        threading.Thread(target=self.capture_frames,
                         args=(capture_target, width, max_height, fps, stop, frames), daemon=True).start()
        show()

    @staticmethod
    def capture_frames(target, width, max_height, fps, stop, frames):
        from PIL import Image
        from stream_capture import StreamCapture

        def publish(value):
            try:
                frames.get_nowait()
            except queue.Empty:
                pass
            frames.put_nowait(value)

        stream = None
        try:
            stream = StreamCapture(target)
            while not stop.is_set():
                started = time.monotonic()
                image = stream(target)
                scale = min(width / image.width, max_height / image.height)
                size = tuple(max(1, round(side * scale)) for side in image.size)
                publish(image.resize(size, Image.Resampling.BILINEAR))
                stop.wait(max(0, 1 / fps - (time.monotonic() - started)))
        except Exception as error:
            if not stop.is_set():
                publish(error)
        finally:
            if stream is not None:
                stream.close()

    def close_preview(self):
        if self.preview_stop is not None:
            self.preview_stop.set()
            self.preview_stop = None
        if self.preview_job is not None:
            self.after_cancel(self.preview_job)
            self.preview_job = None
        if self.preview is not None:
            self.preview.destroy()
            self.preview = None
        self.preview_target = None
        self.preview_enabled.set(False)
