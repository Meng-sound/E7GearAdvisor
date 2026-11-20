"""Android emulator support for the Chinese (国服) client.

The PC client renders its own 16:9 window; an Android emulator renders the phone
screen inside a Qt window that also carries a tab bar / side toolbar.  This module
keeps that difference in one place:

* which windows belong to the game (PC client or emulator)
* where the 16:9 game content sits inside a window client area
* how to read frames and send touches to an emulator

Read-only by default: nothing here starts a task or consumes in-game resources.
"""
from __future__ import annotations

import ctypes
import os
import re
import subprocess
import time
from ctypes import wintypes
from pathlib import Path

PC_TITLES = {'第七史诗', 'epic seven', 'epicseven'}

# Titles are matched on the lower-cased window text, as groups of keywords that
# must all appear (so "MuMuManager" is not mistaken for the MuMu device window).
# Process names are matched on the lower-cased executable; the first hit wins.
EMULATORS = (
    {'name': 'MuMu', 'titles': (('mumu', '安卓'), ('mumu', '模拟'), ('mumu', 'player'), ('nemuplayer',), ('mumunxdevice',)),
     'processes': ('mumunxdevice.exe', 'mumuplayer.exe', 'mumuplayer12.exe', 'nemuplayer.exe', 'mumuvmmheadless.exe'),
     'adb_ports': (16384, 7555, 5555), 'ipc': True},
    {'name': '雷电模拟器', 'titles': (('雷电',), ('ldplayer',), ('dnplayer',)),
     'processes': ('dnplayer.exe', 'ldplayer.exe', 'ldvboxheadless.exe'),
     'adb_ports': (5555, 5557, 5559), 'ipc': False},
    {'name': 'BlueStacks', 'titles': (('bluestacks',), ('蓝叠',)),
     'processes': ('hd-player.exe', 'bluestacks.exe'), 'adb_ports': (5555, 5565, 5575), 'ipc': False},
    {'name': '夜神模拟器', 'titles': (('夜神',), ('noxplayer',)),
     'processes': ('nox.exe', 'noxplayer.exe'), 'adb_ports': (62001, 62025), 'ipc': False},
    {'name': '逍遥模拟器', 'titles': (('逍遥',), ('memu',)),
     'processes': ('memu.exe', 'memuplayer.exe'), 'adb_ports': (21503,), 'ipc': False},
    {'name': '腾讯手游助手', 'titles': (('腾讯手游助手',), ('gameloop',)),
     'processes': ('aow_exe.exe', 'gameloop.exe'), 'adb_ports': (5555, 21503), 'ipc': False},
)

GAME_PACKAGES = ('com.zlongame.cn.epicseven', 'com.stove.epic7.google', 'com.e7.winzzj2')

# Chosen in the settings window; 'auto' prefers the emulator's native interface.
DEFAULT_INPUT = 'auto'
INPUT_MODES = {'自动（模拟器优先原生）': 'auto', '后台窗口消息': 'window', '模拟器原生/ADB': 'emulator'}

MIN_STRIP = 6        # smaller differences are just rounding, not emulator chrome
MAX_STRIP = 160      # a tab bar / toolbar is never a third of the window


def _norm(text):
    return re.sub(r'\s+', '', str(text or '')).lower()


def identify(title='', class_name='', process=''):
    """Classify a window: {'kind': 'pc'|'emulator', 'name': str} or None.

    The process name wins over the title: some emulators put the running app's
    name in the window title, which would otherwise look like the PC client.
    """
    title_key, process_key = _norm(title), _norm(process)
    for profile in EMULATORS:
        if process_key in profile['processes']:
            return {'kind': 'emulator', 'name': profile['name']}
    if title_key in PC_TITLES:
        return {'kind': 'pc', 'name': '第七史诗客户端'}
    for profile in EMULATORS:
        if any(all(keyword in title_key for keyword in group) for group in profile['titles']):
            return {'kind': 'emulator', 'name': profile['name']}
    return None


def is_game_window(title='', class_name='', process=''):
    return identify(title, class_name, process) is not None


def profile_for(name):
    for profile in EMULATORS:
        if profile['name'] == name:
            return profile
    return None


def prefers_native_capture(title='', class_name='', process=''):
    """True when the device frame is better than the window surface.

    MuMu's shared-memory interface returns the phone screen at native device
    resolution, so window size, DPI scaling, chrome and occlusion stop mattering.
    Other emulators only expose ADB capture, which is slower than the window.
    """
    info = identify(title, class_name, process)
    if not info or info['kind'] != 'emulator':
        return False
    return bool((profile_for(info['name']) or {}).get('ipc'))


def content_rect(width, height):
    """Largest 16:9 game area inside a window client image.

    MuMu puts a tab bar on top (1920x1120 -> 40px), LDPlayer a toolbar on the
    right.  Returns (left, top, right, bottom); unknown chrome returns the whole
    client so the caller keeps the previous behaviour.
    """
    if width < 64 or height < 64:
        return (0, 0, width, height)
    content_h = width * 9 / 16
    content_w = height * 16 / 9
    top_gap = height - content_h
    if MIN_STRIP <= top_gap <= min(MAX_STRIP, height * 0.25):
        return (0, round(top_gap), width, height)
    side_gap = width - content_w
    if MIN_STRIP <= side_gap <= min(MAX_STRIP, width * 0.25):
        return (0, 0, width - round(side_gap), height)
    return (0, 0, width, height)


def crop_content(image):
    """Trim emulator chrome so the frame is exactly the 16:9 phone screen."""
    box = content_rect(*image.size)
    if box == (0, 0, image.width, image.height):
        return image
    cropped = image.crop(box)
    cropped.info.update(image.info)
    return cropped


def process_path(pid):
    """Full image path of a process, or '' when it cannot be read."""
    if os.name != 'nt':
        return ''
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                 ctypes.POINTER(wintypes.DWORD)]
    handle = kernel.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return ''
    try:
        size = wintypes.DWORD(260)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ''
        return buffer.value
    finally:
        kernel.CloseHandle(handle)


def process_name(pid):
    return Path(process_path(pid)).name if process_path(pid) else ''


def mumu_root(pid=None):
    """MuMu install root from the running device process, then the registry."""
    candidates = []
    path = process_path(pid) if pid else ''
    if path:
        directory = Path(path).parent
        for parent in (directory, *directory.parents):
            if (parent / 'nx_device').is_dir() or (parent / 'nx_main').is_dir():
                candidates.append(parent)
                break
            if len(candidates) > 1:
                break
    if os.name == 'nt':
        import winreg
        for hive, sub in (
                (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\MuMuPlayer-12.0'),
                (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\MuMuPlayer-12.0'),
                (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Netease\MuMuPlayer')):
            try:
                with winreg.OpenKey(hive, sub) as key:
                    value, _ = winreg.QueryValueEx(key, 'InstallLocation')
                    if Path(str(value).strip('"')).is_dir():
                        candidates.append(Path(str(value).strip('"')))
            except OSError:
                continue
    for drive in ('C:', 'D:', 'E:', 'F:'):
        for sub in ('Program Files/Netease/MuMu', 'Program Files/Netease/MuMuPlayer-12.0',
                    'Program Files/Netease/MuMu Player 12', 'MuMu'):
            candidate = Path(drive) / sub
            if candidate.is_dir():
                candidates.append(candidate)
    for candidate in candidates:
        if candidate and ((candidate / 'nx_device').is_dir() or (candidate / 'nx_main').is_dir()):
            return candidate
    return None


def adb_path(pid=None):
    """Prefer the emulator's own adb (no version mismatch with its server).

    LDPlayer/BlueStacks/Nox ship adb.exe next to their player executable, and
    users rarely add it to PATH, so the emulator's own folder is searched first.
    """
    root = mumu_root(pid)
    if root:
        for relative in ('nx_main/adb.exe', 'nx_device/15.0/shell/adb.exe'):
            candidate = root / relative
            if candidate.is_file():
                return candidate
        hits = sorted(root.glob('nx_device/*/shell/adb.exe'))
        if hits:
            return hits[0]
    executable = process_path(pid) if pid else ''
    if executable:
        directory = Path(executable).parent
        for base in (directory, directory.parent):
            for relative in ('adb.exe', 'adb/adb.exe', 'shell/adb.exe'):
                candidate = base / relative
                if candidate.is_file():
                    return candidate
    for name in ('adb.exe', 'adb'):
        for directory in os.environ.get('PATH', '').split(os.pathsep):
            candidate = Path(directory) / name
            if candidate.is_file():
                return candidate
    return None


class MuMuIpc:
    """MuMu 12/15 shared-memory display + native touch (works while occluded).

    The buffer is 32-bit RGB, rows bottom-up: verified against `adb screencap`
    on MuMu 15.0 (0.0 mean difference after the flip).  Channel order is NOT
    BGRA, so skipping the flip or assuming BGRA swaps red and blue.
    """

    holds_touch = True  # native down/up, so a long press can span captures

    def __init__(self, root=None, instance=0, timeout=5.0, pid=None):
        if os.name != 'nt':
            raise RuntimeError('MuMu 原生接口仅支持 Windows')
        self.root = Path(root) if root else mumu_root(pid)
        if not self.root or not self.root.is_dir():
            raise RuntimeError('未找到 MuMu 安装目录')
        dll = self._locate_dll(self.root)
        if dll is None:
            raise RuntimeError('未找到 external_renderer_ipc.dll')
        for directory in {str(dll.parent), str(dll.parent.parent), str(self.root), str(self.root / 'shell')}:
            try:
                os.add_dll_directory(directory)
            except (AttributeError, OSError):
                pass
        self._lib = ctypes.CDLL(str(dll))
        self._setup()
        self._conn = 0
        self._width = self._height = 0
        self._buffer = None
        self._connect(instance, timeout)

    @staticmethod
    def _locate_dll(root):
        for relative in (('nx_device', '15.0', 'shell', 'sdk', 'external_renderer_ipc.dll'),
                         ('nx_device', '12.0', 'shell', 'sdk', 'external_renderer_ipc.dll'),
                         ('nx_main', 'sdk', 'external_renderer_ipc.dll')):
            candidate = root.joinpath(*relative)
            if candidate.is_file():
                return candidate
        hits = sorted(root.glob('nx_device/*/shell/sdk/external_renderer_ipc.dll'))
        return hits[-1] if hits else None

    def _setup(self):
        lib = self._lib
        lib.nemu_connect.argtypes = [ctypes.c_wchar_p, ctypes.c_int]
        lib.nemu_connect.restype = ctypes.c_int
        lib.nemu_disconnect.argtypes = [ctypes.c_int]
        lib.nemu_capture_display.argtypes = [ctypes.c_int, ctypes.c_uint, ctypes.c_int,
                                             ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                                             ctypes.c_void_p]
        lib.nemu_capture_display.restype = ctypes.c_int
        for name in ('nemu_input_event_touch_down', 'nemu_input_event_touch_up',
                     'nemu_input_event_key_down', 'nemu_input_event_key_up'):
            fn = getattr(lib, name)
            fn.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
            fn.restype = ctypes.c_int

    def _connect(self, instance, timeout=5.0):
        if self._conn > 0:
            try:
                self._lib.nemu_disconnect(self._conn)
            except OSError:
                pass
        deadline = time.monotonic() + max(1.0, timeout)
        while True:
            self._conn = self._lib.nemu_connect(str(self.root), int(instance))
            if self._conn > 0:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('MuMu 原生接口连接失败（模拟器未运行或实例序号不同）')
            time.sleep(.4)
        width, height = ctypes.c_int(0), ctypes.c_int(0)
        status = self._lib.nemu_capture_display(self._conn, 0, 0, ctypes.byref(width),
                                                ctypes.byref(height), None)
        if status != 0 or width.value <= 0 or height.value <= 0:
            raise RuntimeError(f'MuMu 分辨率读取失败（ret={status}）')
        self._width, self._height = int(width.value), int(height.value)
        self._buffer = (ctypes.c_ubyte * (self._width * self._height * 4))()

    @property
    def size(self):
        return self._width, self._height

    def alive(self):
        return self._conn > 0

    def capture(self):
        """Return a PIL RGB image of the device screen."""
        from PIL import Image
        width, height = ctypes.c_int(self._width), ctypes.c_int(self._height)
        status = self._lib.nemu_capture_display(self._conn, 0, self._width * self._height * 4,
                                                ctypes.byref(width), ctypes.byref(height),
                                                ctypes.byref(self._buffer))
        if status != 0:
            self._connect(0)
            width, height = ctypes.c_int(self._width), ctypes.c_int(self._height)
            status = self._lib.nemu_capture_display(self._conn, 0, self._width * self._height * 4,
                                                    ctypes.byref(width), ctypes.byref(height),
                                                    ctypes.byref(self._buffer))
            if status != 0:
                raise RuntimeError(f'MuMu 取图失败（ret={status}）')
        if (width.value, height.value) != (self._width, self._height):
            self._width, self._height = int(width.value), int(height.value)
            self._buffer = (ctypes.c_ubyte * (self._width * self._height * 4))()
            return self.capture()
        raw = ctypes.string_at(self._buffer, self._width * self._height * 4)
        # 'RGBX' drops the alpha byte; stride -1 turns the bottom-up rows around.
        return Image.frombytes('RGB', (self._width, self._height), raw, 'raw', 'RGBX', 0, -1)

    def tap(self, x, y, hold=.08):
        x = max(1, min(self._width - 2, int(x)))
        y = max(1, min(self._height - 2, int(y)))
        self._lib.nemu_input_event_touch_down(self._conn, 0, x, y)
        time.sleep(max(.01, hold))
        self._lib.nemu_input_event_touch_up(self._conn, 0, 0, 0)

    def long_press(self, x, y, seconds=1.0):
        self.tap(x, y, hold=max(.3, seconds))

    def press_start(self, x, y):
        self._lib.nemu_input_event_touch_down(self._conn, 0, int(x), int(y))

    def press_end(self):
        self._lib.nemu_input_event_touch_up(self._conn, 0, 0, 0)

    def swipe(self, x1, y1, x2, y2, duration=.3, steps=12):
        self._lib.nemu_input_event_touch_down(self._conn, 0, int(x1), int(y1))
        try:
            for index in range(1, steps + 1):
                ratio = index / steps
                self._lib.nemu_input_event_touch_down(
                    self._conn, 0,
                    int(round(x1 + (x2 - x1) * ratio)), int(round(y1 + (y2 - y1) * ratio)))
                time.sleep(max(.008, duration / steps))
            time.sleep(.05)
        finally:
            self._lib.nemu_input_event_touch_up(self._conn, 0, 0, 0)

    def key(self, code):
        self._lib.nemu_input_event_key_down(self._conn, 0, int(code), 0)
        time.sleep(.05)
        self._lib.nemu_input_event_key_up(self._conn, 0, int(code), 0)

    def close(self):
        if self._conn > 0:
            try:
                self._lib.nemu_disconnect(self._conn)
            except OSError:
                pass
            self._conn = 0


class AdbInput:
    """`adb shell input` backend: any emulator, no window messages required."""

    holds_touch = False  # `input` cannot keep a touch down across calls

    def __init__(self, pid=None, serial=None, ports=None, timeout=6.0):
        self.executable = adb_path(pid)
        if not self.executable:
            raise RuntimeError('未找到 adb.exe。雷电/蓝叠/夜神等模拟器后台点击需要 ADB：'
                               '请在模拟器设置里开启 ADB 调试，或把模拟器自带的 adb.exe 所在目录加入 PATH')
        self.timeout = timeout
        self.serial = serial or self._connect(ports)

    def _run(self, *args, timeout=None):
        return subprocess.run([str(self.executable), *args], capture_output=True, text=True,
                              encoding='utf8', errors='replace',
                              timeout=timeout or self.timeout,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    def _devices(self):
        """Serials currently in the `device` state."""
        try:
            listed = self._run('devices', timeout=4).stdout or ''
        except (OSError, subprocess.TimeoutExpired):
            return []
        serials = []
        for line in listed.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == 'device':
                serials.append(parts[0])
        return serials

    def _connect(self, ports):
        ready = self._devices()
        # Never hijack a USB phone when an emulator is already attached.
        emulated = [s for s in ready if s.startswith(('127.0.0.1:', 'emulator-'))]
        if emulated:
            return emulated[0]
        tried = []
        for port in ports or (16384, 7555, 5555, 62001, 21503):
            serial = f'127.0.0.1:{port}'
            tried.append(serial)
            try:
                self._run('connect', serial, timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                continue
            if serial in self._devices():
                return serial
        if ready:
            return ready[0]
        raise RuntimeError('ADB 未连接到模拟器（已尝试 ' + '、'.join(tried) +
                           '）。请确认模拟器已启动并开启了 ADB 调试')

    @property
    def size(self):
        text = self._run('-s', self.serial, 'shell', 'wm', 'size').stdout or ''
        match = re.search(r'Override size:\s*(\d+)x(\d+)', text) or re.search(r'Physical size:\s*(\d+)x(\d+)', text)
        if not match:
            raise RuntimeError('无法读取模拟器分辨率')
        width, height = int(match.group(1)), int(match.group(2))
        return (width, height) if width >= height else (height, width)

    def capture(self):
        from PIL import Image
        import io
        result = self._run('-s', self.serial, 'exec-out', 'screencap', '-p', timeout=max(self.timeout, 12))
        if result.returncode or not result.stdout:
            raise RuntimeError('ADB 取图失败：' + (result.stderr or '')[-200:])
        # text=True is wrong for binary frames; re-run without decoding.
        raw = subprocess.run([str(self.executable), '-s', self.serial, 'exec-out', 'screencap', '-p'],
                             capture_output=True, timeout=max(self.timeout, 12),
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
        if not raw:
            raise RuntimeError('ADB 取图为空')
        return Image.open(io.BytesIO(raw)).convert('RGB')

    def tap(self, x, y, hold=0.08):
        self._run('-s', self.serial, 'shell', 'input', 'tap', str(int(x)), str(int(y)))
        if hold > .25:
            time.sleep(hold - .08)

    def long_press(self, x, y, seconds=1.0):
        # `input swipe` with identical endpoints is Android's long press.
        self._run('-s', self.serial, 'shell', 'input', 'swipe', str(int(x)), str(int(y)),
                  str(int(x)), str(int(y)), str(int(max(0.3, seconds) * 1000)))

    def press_start(self, x, y):
        # ADB's `input` has no hold/release pair, so the press is resolved on
        # release: a short down/up becomes a tap, a long one a real long press.
        # (Killing a background swipe left the touch stuck down on the device.)
        self._press_point = (x, y)
        self._press_time = time.monotonic()

    def press_end(self):
        point = getattr(self, '_press_point', None)
        self._press_point = None
        if point is None:
            return
        now = time.monotonic()
        seconds = now - getattr(self, '_press_time', now)
        if seconds >= .35:
            self.long_press(point[0], point[1], seconds)
        else:
            self.tap(point[0], point[1])

    def swipe(self, x1, y1, x2, y2, duration=.3):
        self._run('-s', self.serial, 'shell', 'input', 'swipe', str(int(x1)), str(int(y1)),
                  str(int(x2)), str(int(y2)), str(int(max(.05, duration) * 1000)))

    def key(self, code):
        self._run('-s', self.serial, 'shell', 'input', 'keyevent', str(int(code)))

    def packages(self):
        text = self._run('-s', self.serial, 'shell', 'pm', 'list', 'packages', timeout=15).stdout or ''
        return {line.split(':', 1)[1].strip() for line in text.splitlines() if line.startswith('package:')}

    def close(self):
        return None


def open_input(target, backend='auto', logger=None):
    """Create the best input backend for a window target.

    backend: 'auto' | 'window' (Win32 messages) | 'emulator' (IPC/ADB) | 'adb'
    Returns None when Win32 messages should be used.
    """
    info = identify(target.get('title'), target.get('class_name'), target.get('process'))
    if backend == 'window' or info is None:
        return None
    if info['kind'] == 'pc':
        return None
    profile = profile_for(info['name']) or {}
    if backend in ('auto', 'emulator') and profile.get('ipc'):
        try:
            return MuMuIpc(pid=target.get('pid'))
        except (OSError, RuntimeError) as error:
            if backend == 'emulator':
                raise
            if logger:
                logger(f'MuMu 原生接口不可用（{error}），改用 ADB。')
    try:
        return AdbInput(pid=target.get('pid'), ports=profile.get('adb_ports'))
    except (OSError, RuntimeError) as error:
        # Surface the real reason: a silent fallback to window messages would
        # "work" for capture but every click would be ignored by the emulator.
        message = f"{info['name']} 后台点击需要 ADB，但 {error}"
        if logger:
            logger(message)
        raise RuntimeError(message) from error
