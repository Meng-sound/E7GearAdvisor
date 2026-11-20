"""Window capture with a guarded, unobstructed-client compatibility path.

PrintWindow depends on the target application's renderer. A nonblack frame does
not prove freshness or recognition accuracy. Invoke the isolated worker through
capture_game_window so a blocked target cannot hang the GUI.
"""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def client_image(hwnd, expected_pid, expected_title):
    if os.name != 'nt':
        raise RuntimeError('后台窗口取图仅支持 Windows')
    from PIL import Image, ImageStat
    user = ctypes.WinDLL('user32', use_last_error=True)
    gdi = ctypes.WinDLL('gdi32', use_last_error=True)
    user.IsWindow.argtypes = [wintypes.HWND]
    user.IsIconic.argtypes = [wintypes.HWND]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.GetDC.argtypes = [wintypes.HWND]
    user.GetDC.restype = wintypes.HDC
    user.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi.CreateCompatibleDC.restype = wintypes.HDC
    gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
    gdi.SelectObject.restype = wintypes.HANDLE
    gdi.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi.DeleteDC.argtypes = [wintypes.HDC]

    class Header(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('width', wintypes.LONG), ('height', wintypes.LONG),
                    ('planes', wintypes.WORD), ('bits', wintypes.WORD), ('compression', wintypes.DWORD),
                    ('size_image', wintypes.DWORD), ('xppm', wintypes.LONG), ('yppm', wintypes.LONG),
                    ('colors', wintypes.DWORD), ('important', wintypes.DWORD)]

    class BitmapInfo(ctypes.Structure):
        _fields_ = [('header', Header), ('colors', wintypes.DWORD * 3)]

    gdi.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BitmapInfo), wintypes.UINT,
                                    ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
    gdi.CreateDIBSection.restype = wintypes.HANDLE

    def check_target():
        pid = wintypes.DWORD()
        title = ctypes.create_unicode_buffer(1024)
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        user.GetWindowTextW(hwnd, title, len(title))
        if not user.IsWindow(hwnd) or pid.value != expected_pid or title.value != expected_title:
            raise RuntimeError('游戏窗口已关闭或发生变化，请重新选择')
        if user.IsIconic(hwnd) or not user.IsWindowVisible(hwnd):
            raise RuntimeError('最小化或隐藏窗口尚不支持，请恢复窗口；允许被其他窗口遮挡')

    check_target()
    rect = wintypes.RECT()
    if not user.GetClientRect(hwnd, ctypes.byref(rect)):
        raise RuntimeError('无法读取窗口客户区')
    width, height = rect.right, rect.bottom
    if not 40 <= width <= 8000 or not 40 <= height <= 8000 or width * height > 32_000_000:
        raise RuntimeError('窗口尺寸不适合取图')
    dc = user.GetDC(hwnd)
    memory = bitmap = previous = None
    try:
        if not dc:
            raise RuntimeError('无法创建窗口取图上下文')
        memory = gdi.CreateCompatibleDC(dc)
        info = BitmapInfo()
        info.header = Header(ctypes.sizeof(Header), width, -height, 1, 32, 0, width*height*4, 0, 0, 0, 0)
        bits = ctypes.c_void_p()
        bitmap = gdi.CreateDIBSection(dc, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
        if not memory or not bitmap or not bits.value:
            raise RuntimeError('无法创建窗口取图缓冲区')
        previous = gdi.SelectObject(memory, bitmap)
        if not previous or previous == ctypes.c_void_p(-1).value:
            previous = None
            raise RuntimeError('无法选择窗口取图缓冲区')
        ctypes.memset(bits, 0, width*height*4)
        returned=False
        for flags in (3,1):
            ctypes.memset(bits,0,width*height*4)
            if not user.PrintWindow(hwnd,memory,flags):continue
            preview=Image.frombytes('RGB',(width,height),ctypes.string_at(bits,width*height*4),'raw','BGRX')
            stats=ImageStat.Stat(preview.resize((64,64)))
            if max(stats.mean)>=2 and max(stats.stddev)>=.5:returned=True;break
        if not returned:
            raise RuntimeError('当前渲染器未返回有效PrintWindow图像')
        check_target()
        current = wintypes.RECT()
        if not user.GetClientRect(hwnd, ctypes.byref(current)) or (current.right, current.bottom) != (width, height):
            raise RuntimeError('取图时窗口尺寸改变，请重试')
        picture = Image.frombytes('RGB', (width, height), ctypes.string_at(bits, width*height*4), 'raw', 'BGRX')
        stat = ImageStat.Stat(picture.resize((64, 64)))
        if max(stat.mean) < 2 or max(stat.stddev) < .5:
            raise RuntimeError('后台图像为空白或黑屏；该渲染方式尚未通过兼容性检测')
        picture.info['capture_backend']='PrintWindow后台';return picture
    finally:
        if previous:
            gdi.SelectObject(memory, previous)
        if bitmap:
            gdi.DeleteObject(bitmap)
        if memory:
            gdi.DeleteDC(memory)
        if dc:
            user.ReleaseDC(hwnd, dc)


def intersects(a,b):return min(a[2],b[2])>max(a[0],b[0]) and min(a[3],b[3])>max(a[1],b[1])

def visible_client_bounds(hwnd,expected_pid,expected_title):
    """Prove the complete client area is on-screen and not covered by other apps."""
    user=ctypes.WinDLL('user32',use_last_error=True)
    user.IsWindow.argtypes=[wintypes.HWND];user.IsWindowVisible.argtypes=[wintypes.HWND];user.IsIconic.argtypes=[wintypes.HWND]
    user.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
    user.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    user.GetClientRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
    user.ClientToScreen.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.POINT)]
    user.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
    title=ctypes.create_unicode_buffer(1024);pid=wintypes.DWORD()
    user.GetWindowTextW(hwnd,title,len(title));user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
    if not user.IsWindow(hwnd) or pid.value!=expected_pid or title.value!=expected_title:raise RuntimeError('游戏窗口已变化，请重新选择')
    if user.IsIconic(hwnd) or not user.IsWindowVisible(hwnd):raise RuntimeError('请恢复游戏窗口，不要最小化')
    rect=wintypes.RECT();origin=wintypes.POINT(0,0)
    if not user.GetClientRect(hwnd,ctypes.byref(rect)) or not user.ClientToScreen(hwnd,ctypes.byref(origin)):raise RuntimeError('无法读取游戏客户区位置')
    bounds=(origin.x,origin.y,origin.x+rect.right,origin.y+rect.bottom)
    desktop=(user.GetSystemMetrics(76),user.GetSystemMetrics(77),user.GetSystemMetrics(76)+user.GetSystemMetrics(78),user.GetSystemMetrics(77)+user.GetSystemMetrics(79))
    if rect.right<40 or rect.bottom<40 or bounds[0]<desktop[0] or bounds[1]<desktop[1] or bounds[2]>desktop[2] or bounds[3]>desktop[3]:raise RuntimeError('兼容取图要求游戏客户区完整显示在屏幕内')
    blockers=[];found=[]
    callback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    user.EnumWindows.argtypes=[callback,wintypes.LPARAM]
    @callback
    def visit(other,_):
        if int(other)==hwnd:found.append(True);return False
        if not user.IsWindowVisible(other) or user.IsIconic(other):return True
        other_pid=wintypes.DWORD();user.GetWindowThreadProcessId(other,ctypes.byref(other_pid))
        if other_pid.value==expected_pid:return True
        area=wintypes.RECT()
        if user.GetWindowRect(other,ctypes.byref(area)) and intersects(bounds,(area.left,area.top,area.right,area.bottom)):
            # Cloaked virtual-desktop windows do not cover visible pixels.
            try:
                dwm=ctypes.WinDLL('dwmapi');dwm.DwmGetWindowAttribute.argtypes=[wintypes.HWND,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD]
                cloaked=wintypes.DWORD();status=dwm.DwmGetWindowAttribute(other,14,ctypes.byref(cloaked),ctypes.sizeof(cloaked))
                if status==0 and cloaked.value:return True
            except OSError:pass
            blockers.append(True)
        return True
    user.EnumWindows(visit,0)
    if not found:raise RuntimeError('无法确认游戏窗口的可见顺序')
    if blockers:raise RuntimeError('后台取图不受支持，兼容取图检测到游戏被遮挡；请把工具移到旁边，完整露出游戏后重试')
    return bounds

def visible_client_image(hwnd,expected_pid,expected_title):
    from PIL import ImageGrab,ImageStat
    before=visible_client_bounds(hwnd,expected_pid,expected_title)
    picture=ImageGrab.grab(bbox=before,all_screens=True)
    after=visible_client_bounds(hwnd,expected_pid,expected_title)
    if before!=after:raise RuntimeError('兼容取图时游戏窗口移动或缩放，请重试')
    stats=ImageStat.Stat(picture.resize((64,64)))
    if max(stats.mean)<2 or max(stats.stddev)<.5:raise RuntimeError('兼容取图仍为空白，请确认游戏已进入场景')
    picture.info['capture_backend']='兼容取图（游戏需无遮挡）';return picture

def device_image(target):
    """Emulator frame straight from the device (works while minimized/occluded)."""
    import emulator
    backend=emulator.open_input(target,backend='emulator')
    if backend is None:raise RuntimeError('该模拟器没有可用的原生取图接口')
    try:
        picture=backend.capture()
    finally:
        backend.close()
    picture=picture.convert('RGB')
    # A wrong MuMu instance (multi-open) or a reconnecting renderer gives an
    # all-black frame; treat it as a failed backend so window capture can run.
    from PIL import ImageStat
    stats=ImageStat.Stat(picture.resize((32,32)))
    if max(stats.mean)<3 and max(stats.stddev)<1:
        raise RuntimeError('模拟器原生取图返回黑屏（多开时请确认游戏所在实例）')
    picture.info['capture_backend']=f"{target.get('emulator') or '模拟器'}原生取图（支持遮挡/最小化）"
    return picture

def capture_client(hwnd,pid,title,mode='auto',process=''):
    if mode not in ('auto','background','visible'):raise ValueError('未知取图模式')
    import emulator
    target={'hwnd':hwnd,'pid':pid,'title':title,'process':process}
    info=emulator.identify(title,'',process)
    emulated=bool(info and info['kind']=='emulator')
    def finish(picture):
        # Emulator windows carry a tab bar / toolbar; hand the caller the phone screen only.
        return emulator.crop_content(picture) if emulated else picture
    if mode!='visible':
        # MuMu's device frame is the phone screen at native resolution, so window
        # size, DPI scaling, chrome and occlusion no longer affect recognition.
        if emulator.prefers_native_capture(title,'',process):
            try:return device_image(target)
            except (ImportError,OSError,RuntimeError) as error:
                if mode=='background':raise
        try:
            from graphics_capture import capture
            return finish(capture(hwnd,pid,title))
        except (ImportError,OSError,RuntimeError,ValueError):pass
        try:return finish(client_image(hwnd,pid,title))
        except RuntimeError:
            if mode=='background' and not emulated:raise
        if emulated:
            try:return device_image(target)
            except (ImportError,OSError,RuntimeError) as error:
                if mode=='background':raise
    return finish(visible_client_image(hwnd,pid,title))

def capture_game_window(window, timeout=12):
    """Capture only a user-selected known game window in a bounded worker."""
    import emulator
    process=window.get('process') or ''
    if not emulator.is_game_window(window.get('title'),'',process):
        raise ValueError('请选择第七史诗游戏窗口（PC 客户端或模拟器）')
    if type(window.get('hwnd')) is not int or type(window.get('pid')) is not int:
        raise ValueError('窗口标识缺失，请重新检测')
    from PIL import Image
    with tempfile.TemporaryDirectory(prefix='e7-window-') as directory:
        target = Path(directory)/'frame.png'
        allowance=timeout
        for attempt in range(2):
            try:
                # argv: mode hwnd pid title out.png [process]
                result = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()),window.get('capture_mode','auto'),
                                         str(window['hwnd']), str(window['pid']), window['title'], str(target), process],
                                        capture_output=True, text=True, encoding='utf8', errors='replace',
                                        timeout=allowance, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                break
            except subprocess.TimeoutExpired:
                if attempt == 0:
                    # A cold worker (large 4K frame, antivirus scan) can exceed the
                    # first budget; the second run reuses the warm file cache.
                    allowance=round(timeout*1.5)
                    continue
                raise RuntimeError(f'后台取图超时（已等待 {allowance} 秒）：窗口过大或显卡驱动响应慢。'
                                   '请把游戏窗口缩小到 1920×1080 附近再试；未切换前台或点击游戏') from None
        if result.returncode or not target.is_file():
            raise RuntimeError(result.stderr.strip()[-500:] or '后台取图失败')
        with Image.open(target) as image:
            return image.copy()


if __name__ == '__main__':
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    try:
        if os.name == 'nt':
            try:
                ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
            except (AttributeError, OSError):
                ctypes.windll.user32.SetProcessDPIAware()
        from PIL.PngImagePlugin import PngInfo
        process=sys.argv[6] if len(sys.argv)>6 else ''
        picture=capture_client(int(sys.argv[2]),int(sys.argv[3]),sys.argv[4],sys.argv[1],process)
        metadata=PngInfo();metadata.add_text('capture_backend',picture.info.get('capture_backend','窗口取图'))
        picture.save(sys.argv[5],pnginfo=metadata,compress_level=1)
    except Exception as error:
        sys.stderr.reconfigure(encoding='utf8')
        print(str(error), file=sys.stderr)
        sys.exit(1)
