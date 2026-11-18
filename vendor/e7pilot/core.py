"""窗口查找 / 截图 / 点击 / OCR / OpenCV 图像识别等底层能力。"""
from __future__ import annotations

import ctypes
import os
import random
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

import cv2
import mss
import numpy as np
import win32api
import win32con
import win32gui
import win32process
import win32ui
import pywintypes

# 必须在任何窗口坐标调用之前声明 DPI 感知，否则高缩放屏幕下坐标会错位
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:  # noqa: BLE001
    ctypes.windll.user32.SetProcessDPIAware()

GAME_EXE_NAMES = ("epicseven_steam.exe", "epicseven.exe")
GAME_EXACT_TITLES = ("epic seven", "epicseven", "第七史诗")
GAME_TITLE_KEYWORDS = ("epic seven", "epicseven", "第七史诗")
# ==================== 繁 → 简 归一化 ====================
# 模拟器里的《第七史诗》多为繁中/国际服；规则关键词是简体，这里做「字级」映射，
# 简体文本不受影响（表里没有的字原样保留）。
SIMPLIFY_MAP = str.maketrans({"準": "准", "勵": "励", "靈": "灵", "體": "体", "進": "进", "務": "务", "選": "选", "擇": "择", "戰": "战", "鬥": "斗", "購": "购", "買": "买", "過": "过", "確": "确", "認": "认", "關": "关", "閉": "闭", "書": "书", "籤": "签", "簽": "签", "獎": "奖", "聖": "圣", "約": "约", "劇": "剧", "場": "场", "觀": "观", "領": "领", "開": "开", "畫": "画", "暫": "暂", "棄": "弃", "設": "设", "聲": "声", "隊": "队", "裝": "装", "備": "备", "幣": "币", "繼": "继", "續": "续", "討": "讨", "論": "论", "區": "区", "優": "优", "黨": "党", "詩": "诗", "輝": "辉", "歷": "历", "獲": "获", "點": "点", "擊": "击", "傳": "传", "門": "门", "層": "层", "難": "难", "圖": "图", "標": "标", "記": "记", "錄": "录", "幫": "帮", "給": "给", "協": "协", "請": "请", "刪": "删", "覽": "览", "節": "节", "話": "话", "說": "说", "讀": "读", "載": "载", "結": "结", "敗": "败", "勝": "胜", "線": "线", "別": "别", "時": "时", "間": "间", "編": "编", "喚": "唤", "競": "竞", "動": "动", "禮": "礼", "滿": "满", "這": "这", "個": "个", "們": "们", "來": "来", "會": "会", "裡": "里", "為": "为", "與": "与", "麼": "么", "沒": "没", "還": "还", "讓": "让", "從": "从", "種": "种", "樣": "样", "數": "数", "邊": "边", "發": "发", "現": "现", "應": "应", "該": "该", "無": "无", "雙": "双", "單": "单", "轉": "转", "換": "换", "順": "顺", "級": "级", "計": "计", "劃": "划", "頁": "页", "項": "项", "調": "调", "參": "参", "歸": "归", "屬": "属", "萬": "万", "億": "亿", "銀": "银", "鐵": "铁", "銅": "铜", "鑽": "钻", "寶": "宝", "鑰": "钥", "鎖": "锁", "盤": "盘", "鍵": "键"})


def to_simplified(text: str) -> str:
    """繁体文本归一化成简体（简体原样返回）。"""
    if not text:
        return text
    try:
        return text.translate(SIMPLIFY_MAP)
    except Exception:  # noqa: BLE001
        return text


# ==================== 模拟器兼容（P1） ====================
# 模拟器主窗口带工具栏，必须绑到内部渲染子窗口，坐标系才是纯安卓屏幕。
EMULATOR_EXE_NAMES = (
    "mumunxdevice.exe", "mumunxmain.exe", "nemuplayer.exe", "mumuplayer.exe",  # MuMu
    "mumuplayer12.exe", "mumuvmmheadless.exe", "nemuheadless.exe", "mumu.exe",  # MuMu 安卓15/国际版
    "mumunebula.exe", "nebula.exe",                                             # MuMu 国际版(Nebula)
    "dnplayer.exe", "ldplayer.exe",                                             # 雷电
    "hd-player.exe", "bluestacks.exe",                                          # 蓝叠
    "nox.exe", "noxplayer.exe",                                                 # 夜神
)
EMULATOR_TITLE_KEYWORDS = (
    "mumu安卓设备", "mumu模拟器", "mumu player", "mumu android", "mumu", "nebula",
    "雷电模拟器", "ldplayer", "bluestacks", "夜神模拟器", "noxplayer",
)
# 已知渲染子窗口的类名/标题（小写）
EMULATOR_RENDER_HINTS = (
    "nemudisplay", "nemuwin", "therender", "bluestacksapp",
    "screenboardclasswindow", "sub", "subwin", "canvas", "opengl",
)

EMULATOR_INFO: dict = {}   # 绑定结果：{"emu": 名称, "w": 宽, "h": 高, "hwnd": 渲染句柄, "top": 顶层句柄}

EXCLUDED_EXE_NAMES = {
    "explorer.exe",
    "cmd.exe",
    "powershell.exe",
    "pwsh.exe",
    "windowsterminal.exe",
    "conhost.exe",
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
    "brave.exe",
    "opera.exe",
    "code.exe",
    "antigravity.exe",
    "devenv.exe",
    "pycharm64.exe",
    "notepad.exe",
    "python.exe",
    "pythonw.exe",
    "uv.exe",
}

# 迷宫十字路口四个方向罗盘的检测区域与点击中心（相对客户区比例）
COMPASS_ZONES: dict[str, tuple[tuple[float, float, float, float], tuple[float, float], str]] = {
    "N": ((0.04, 0.24, 0.16, 0.46), (0.100, 0.355), "北(N)"),
    "W": ((0.04, 0.58, 0.16, 0.82), (0.100, 0.705), "西(W)"),
    "E": ((0.84, 0.24, 0.96, 0.46), (0.900, 0.350), "东(E)"),
    "S": ((0.84, 0.58, 0.96, 0.82), (0.900, 0.705), "南(S)"),
}

# ==================== 模拟人手的触控时序（想整体调快/调慢只改这里） ====================
# 用户反馈：整体出手可以再快一点，但每次点击「压在屏幕上」的停留时间要更长一点，更像真人按压。
# 运行时会被 rules.yaml 里的 click_hold_ms / click_gap_ms 覆盖（用户可自己微调，无需改代码）。
CLICK_HOLD = (0.065, 0.090)      # 按下→松开 的停留时长（秒）：真人轻点约 60~100ms（旧版 28~38ms 太"蜻蜓点水"）
CLICK_GAP = 0.030                # 连点两次之间的间隔（秒）：比旧版 0.042 更紧凑，双击更快触发
CLICK_AIM_DELAY = (0.006, 0.012)  # 光标就位→按下 的缓冲（秒）：旧版 15~25ms 偏慢
CLICK_HOLD_FAST = (0.035, 0.055)   # 战斗内双击放技能的短按档（长按会被游戏当成按住，连点识别不到）


def read_click_timing() -> tuple[tuple[float, float], float]:
    """读取 rules.yaml 里的 click_hold_ms / click_gap_ms；缺失或数值不合理时用内置默认值。"""
    hold, gap = CLICK_HOLD, CLICK_GAP
    try:
        import yaml

        cfg = yaml.safe_load((runtime_root() / "rules.yaml").read_text(encoding="utf-8")) or {}
        settings = cfg.get("settings") or {}
        raw_hold = settings.get("click_hold_ms")
        if isinstance(raw_hold, (list, tuple)) and len(raw_hold) == 2:
            lo, hi = float(raw_hold[0]) / 1000.0, float(raw_hold[1]) / 1000.0
            if 0.01 <= lo <= hi <= 0.25:
                hold = (lo, hi)
        raw_gap = settings.get("click_gap_ms")
        if isinstance(raw_gap, (list, tuple)) and len(raw_gap) == 2:
            gap = (float(raw_gap[0]) + float(raw_gap[1])) / 2.0 / 1000.0
        elif raw_gap is not None:
            gap = float(raw_gap) / 1000.0
        gap = max(0.005, min(0.15, gap))
    except Exception:  # noqa: BLE001  配置缺字段/环境异常都不影响点击
        pass
    return hold, gap


class InputBlockedError(RuntimeError):
    """系统拒绝模拟鼠标：进程权限不足（低完整性/沙箱被 UIPI 拦截）、锁屏或远程桌面。"""


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def read_click_mode(default: str = "foreground") -> str:
    """从 rules.yaml 读取 click_mode（background=后台消息点击不抢鼠标 / foreground=前台真实鼠标）。"""
    try:
        import yaml
        from pathlib import Path

        cfg = yaml.safe_load((Path(__file__).resolve().parent / "rules.yaml").read_text(encoding="utf-8"))
        mode = str(((cfg.get("settings") or {}).get("click_mode", default))).strip().lower()
        return mode if mode in ("foreground", "background") else default
    except Exception:  # noqa: BLE001
        return default


def user_data_dir() -> Path:
    """用户数据目录（统计/样本）：%LOCALAPPDATA%\\E7Pilot。

    放在这里的原因：程序目录（dist/E7Pilot）在重新打包或覆盖解压时会被整体替换，
    统计记录如果放在程序目录里会丢。
    """
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else (Path.home() / "AppData" / "Local")
    p = root / "E7Pilot"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:  # noqa: BLE001
        return runtime_root() / "debug"
    return p


def runtime_root() -> Path:
    """程序工作目录：源码运行=脚本目录；打包 exe 运行=E7_ROOT（exe 所在目录）。"""
    env = os.environ.get("E7_ROOT")
    if env:
        return Path(env)
    return Path(__file__).parent


INTEGRITY_NAMES = {0x1000: "Low", 0x2000: "Medium", 0x3000: "High", 0x4000: "System"}


def _integrity_of_token(tok) -> str:
    import win32security

    info = win32security.GetTokenInformation(tok, win32security.TokenIntegrityLevel)
    sid = info[0] if isinstance(info, tuple) else info
    lvl = int(sid.GetSubAuthority(sid.GetSubAuthorityCount() - 1))
    return INTEGRITY_NAMES.get(lvl, f"0x{lvl:X}")


def process_privilege_summary() -> str:
    """当前进程权限摘要（启动日志 / 排障用）。"""
    try:
        import win32process
        import win32security

        tok = win32security.OpenProcessToken(
            win32process.GetCurrentProcess(), win32security.TOKEN_QUERY
        )
        elev = bool(win32security.GetTokenInformation(tok, win32security.TokenElevation))
        return f"管理员={'是' if elev else '否'} 完整性={_integrity_of_token(tok)}"
    except Exception:  # noqa: BLE001
        return "未知"


def foreground_window_privilege() -> str:
    """前台窗口标题 + 所属进程完整性（排障：判断是否被 UIPI 拦截）。"""
    try:
        import win32process
        import win32security

        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd) or "(无标题)"
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        handle = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        try:
            tok = win32security.OpenProcessToken(handle, win32security.TOKEN_QUERY)
            return f"「{title[:18]}」完整性={_integrity_of_token(tok)}"
        finally:
            win32api.CloseHandle(handle)
    except Exception:  # noqa: BLE001
        return "无法读取前台窗口权限"


def write_startup_diag(root) -> None:
    """每次启动把进程权限 + 鼠标可控性 + 父进程写进 debug/启动自检.txt，便于事后排查"点击无效"。"""
    try:
        from pathlib import Path

        debug_dir = Path(root) / "debug"
        debug_dir.mkdir(exist_ok=True)
        line = (
            f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {process_privilege_summary()}"
            f"  鼠标自检={cursor_control_probe()}  {process_parent_info()}\n"
        )
        (debug_dir / "启动自检.txt").write_text(line, encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def is_low_integrity() -> bool:
    """当前进程是否被限制在 Low 完整性（沙箱/受限启动），这种进程无法控制鼠标。"""
    try:
        import win32process
        import win32security

        tok = win32security.OpenProcessToken(
            win32process.GetCurrentProcess(), win32security.TOKEN_QUERY
        )
        return _integrity_of_token(tok) == "Low"
    except Exception:  # noqa: BLE001
        return False


def _proc_name_il(pid: int) -> tuple[str, str]:
    """返回某进程的可执行文件名与完整性级别。"""
    name = _exe_name_of_pid(pid) or "?"
    try:
        import win32security

        handle = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        try:
            tok = win32security.OpenProcessToken(handle, win32security.TOKEN_QUERY)
            il = _integrity_of_token(tok)
        finally:
            win32api.CloseHandle(handle)
    except Exception:  # noqa: BLE001
        il = "?"
    return name, il


def _parent_pid(pid: int) -> int:
    """用 NtQueryInformationProcess 取父进程 PID（GetCurrentProcess 需按 64 位句柄处理）。"""
    kernel32 = ctypes.windll.kernel32
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    ntdll = ctypes.windll.ntdll

    class _PBI(ctypes.Structure):
        _fields_ = [
            ("ExitStatus", ctypes.c_ulong),
            ("PebBaseAddress", ctypes.c_void_p),
            ("AffinityMask", ctypes.c_void_p),
            ("BasePriority", ctypes.c_ulong),
            ("UniqueProcessId", ctypes.c_void_p),
            ("InheritedFromUniqueProcessId", ctypes.c_void_p),
        ]

    handle = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return 0
    try:
        pbi = _PBI()
        ret = ctypes.c_ulong()
        ntdll.NtQueryInformationProcess(
            ctypes.c_void_p(int(handle)),
            0,
            ctypes.byref(pbi),
            ctypes.sizeof(pbi),
            ctypes.byref(ret),
        )
        return int(pbi.InheritedFromUniqueProcessId or 0)
    finally:
        win32api.CloseHandle(handle)


def process_parent_info() -> str:
    """三层父进程链（名字+完整性）：一眼看出脚本是被谁启动的。"""
    try:
        chain: list[str] = []
        pid = os.getpid()
        for _ in range(3):
            pid = _parent_pid(pid)
            if not pid:
                break
            name, il = _proc_name_il(pid)
            chain.append(f"{name}({il})")
        return "父进程链=" + " <- ".join(chain) if chain else "父进程链=未知"
    except Exception:  # noqa: BLE001
        return "父进程链=未知"


def cursor_control_probe() -> str:
    """原地移动光标测试系统是否允许本进程控制鼠标（不产生可见移动）。"""
    try:
        x, y = win32api.GetCursorPos()
        win32api.SetCursorPos((x, y))
        return "正常"
    except pywintypes.error:
        return "被拒绝"


def _exe_name_of_pid(pid: int) -> str:
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value.rsplit("\\", 1)[-1].lower()
        return ""
    finally:
        kernel32.CloseHandle(handle)


def resize_game_window(hwnd: int, client_w: int, client_h: int, center: bool = True):
    """把游戏窗口的「客户区」调整为 client_w x client_h，并可选居中。返回实际客户区尺寸。"""
    try:
        l, t, r, b = win32gui.GetWindowRect(hwnd)
        cl, ct, cr, cb = win32gui.GetClientRect(hwnd)
        frame_w = (r - l) - (cr - cl)
        frame_h = (b - t) - (cb - ct)
        x, y = l, t
        if center:
            sw = win32api.GetSystemMetrics(0)
            sh = win32api.GetSystemMetrics(1)
            x = max(0, (sw - (client_w + frame_w)) // 2)
            y = max(0, (sh - (client_h + frame_h)) // 2)
        win32gui.MoveWindow(hwnd, x, y, client_w + frame_w, client_h + frame_h, True)
        time.sleep(0.35)
        cl, ct, cr, cb = win32gui.GetClientRect(hwnd)
        return (cr - cl, cb - ct)
    except Exception:  # noqa: BLE001
        return None


def _grab_window_gray(hwnd: int):
    """用 PrintWindow 抓一张图（灰度），失败返回 None。用于验证子窗口是否真的能出画面。"""
    try:
        l, t, r, b = win32gui.GetClientRect(hwnd)
        w, h = r - l, b - t
        if w <= 16 or h <= 16:
            return None
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfc_dc, w, h)
        save_dc.SelectObject(bmp)
        ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 3)
        arr = np.frombuffer(bmp.GetBitmapBits(True), dtype=np.uint8).reshape(h, w, 4)
        img = arr[:, :, :3].copy()
        win32gui.DeleteObject(bmp.GetHandle())
        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    except Exception:  # noqa: BLE001
        return None


def resolve_render_hwnd(top_hwnd: int) -> int:
    """模拟器：向下找真正的安卓渲染子窗口；Steam 原生窗口直接原样返回。

    判据：可见 + 面积占父窗口 >65% + PrintWindow 能抓出非黑画面；类名/标题命中已知渲染名优先。
    """
    try:
        tl, tt, tr, tb = win32gui.GetClientRect(top_hwnd)
        top_area = max(1, (tr - tl) * (tb - tt))
    except Exception:  # noqa: BLE001
        return top_hwnd

    candidates: list[tuple[int, int, int]] = []  # (优先级, 面积, hwnd)

    def _cb(ch, _):
        try:
            if not win32gui.IsWindowVisible(ch):
                return True
            cls = win32gui.GetClassName(ch).strip().lower()
            title = win32gui.GetWindowText(ch).strip().lower()
            l, t, r, b = win32gui.GetClientRect(ch)
            area = max(0, (r - l)) * max(0, (b - t))
            if area < top_area * 0.65:
                return True
            prio = 2 if (cls in EMULATOR_RENDER_HINTS or title in EMULATOR_RENDER_HINTS) else 1
            candidates.append((prio, area, ch))
        except Exception:  # noqa: BLE001
            pass
        return True

    try:
        win32gui.EnumChildWindows(top_hwnd, _cb, None)
    except Exception:  # noqa: BLE001
        return top_hwnd

    if not candidates:
        return top_hwnd

    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    for _prio, _area, ch in candidates[:4]:
        gray = _grab_window_gray(ch)
        if gray is not None and float(gray.mean()) > 2.0 and float((gray > 12).mean()) > 0.5:
            return ch
    # OpenGL 渲染下子窗口 PrintWindow 恒黑：若已命中明确渲染类名，仍优先绑它，而不是带工具栏的外框
    if candidates and candidates[0][0] >= 2:
        return candidates[0][2]
    return top_hwnd


# 当前驱动平台："steam" 原生窗口 / "emulator" 模拟器（供 platform_overrides 使用）
ACTIVE_PLATFORM = "steam"


def set_active_platform(platform: str) -> None:
    global ACTIVE_PLATFORM
    ACTIVE_PLATFORM = "emulator" if str(platform).lower().startswith("emulator") else "steam"


def apply_platform_overrides(cfg: dict) -> dict:
    """把 platform_overrides.<当前平台> 合并进 settings（只覆盖存在的键，不新增行为）。"""
    try:
        overrides = (cfg or {}).get("platform_overrides") or {}
        block = overrides.get(ACTIVE_PLATFORM) or {}
        if not isinstance(block, dict) or not block:
            return cfg
        settings = cfg.setdefault("settings", {})
        for k, v in block.items():
            settings[k] = v
    except Exception:  # noqa: BLE001
        pass
    return cfg


def load_rules_cfg(path: Path | None = None) -> dict:
    """统一读取 rules.yaml 并套用平台覆盖。"""
    import yaml as _yaml

    p = Path(path) if path else (runtime_root() / "rules.yaml")
    try:
        cfg = _yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        cfg = {}
    return apply_platform_overrides(cfg)


def open_game_window(click_mode: str = "foreground"):
    """统一创建游戏驱动：Steam 原生窗口优先 → MuMu IPC → 模拟器窗口截图回退。

    返回 GameWindow / MuMuIpcWindow；都没有时返回 None。
    """
    hwnd = find_game_window()
    steam_ok = bool(hwnd) and not EMULATOR_INFO
    if steam_ok:
        set_active_platform("steam")
        return GameWindow(hwnd, click_mode)
    try:
        from mumu_ipc import open_mumu_ipc

        win = open_mumu_ipc()
        if win is not None:
            set_active_platform("emulator")
            return win
    except Exception:  # noqa: BLE001
        pass
    if hwnd:
        return GameWindow(hwnd, click_mode)
    return None


def find_emulator_window() -> int | None:
    """查找模拟器设备窗口（返回顶层，后续再解析渲染子窗口）。"""
    best: tuple[int, int] | None = None  # (面积, hwnd)

    def _cb(hwnd, _):
        nonlocal best
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            exe = _exe_name_of_pid(pid).lower()
            title = win32gui.GetWindowText(hwnd).strip().lower()
            hit = exe in EMULATOR_EXE_NAMES or any(k in title for k in EMULATOR_TITLE_KEYWORDS)
            if not hit:
                return True
            l, t, r, b = win32gui.GetClientRect(hwnd)
            area = max(0, (r - l)) * max(0, (b - t))
            if area < 200 * 200:
                return True
            if best is None or area > best[0]:
                best = (area, hwnd)
        except Exception:  # noqa: BLE001
            pass
        return True

    try:
        win32gui.EnumWindows(_cb, None)
    except Exception:  # noqa: BLE001
        return None
    return best[1] if best else None


def find_game_window() -> int | None:
    """返回游戏主窗口句柄（严格优先匹配游戏进程名，排除浏览器/终端/资源管理器）。"""
    my_pid = os.getpid()
    candidates: list[tuple[int, int, int]] = []  # (匹配优先级, 面积, hwnd)

    def _cb(hwnd, _):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid == my_pid:
                return True
            exe = _exe_name_of_pid(pid)
            if exe in EXCLUDED_EXE_NAMES:
                return True
            title = win32gui.GetWindowText(hwnd).strip().lower()
            prio = 0
            if exe in GAME_EXE_NAMES:
                prio = 3
            elif title in GAME_EXACT_TITLES:
                prio = 2
            elif any(k in title for k in GAME_TITLE_KEYWORDS):
                prio = 1
            if prio > 0:
                l, t, r, b = win32gui.GetClientRect(hwnd)
                area = (r - l) * (b - t)
                # 最小化时客户区可能为 0，若是真实游戏进程依然保留候选以便提示恢复窗口
                if area > 200 * 200 or (prio == 3 and win32gui.IsIconic(hwnd)):
                    candidates.append((prio, area, hwnd))
        except Exception:  # noqa: BLE001  某个窗口在枚举途中被销毁等情况，忽略
            pass
        return True

    # 用 ctypes 版 EnumWindows，避免 pywin32 在回调异常时整体报错
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    ctypes.windll.user32.EnumWindows(enum_proc(lambda h, l: bool(_cb(h, l))), 0)
    if candidates:
        candidates.sort(reverse=True)
        try:
            set_active_platform("steam")
        except Exception:  # noqa: BLE001
            pass
        return candidates[0][2]

    # 没找到 Steam 客户端 → 尝试模拟器（MuMu/雷电/蓝叠/夜神）
    top = find_emulator_window()
    if top:
        render = resolve_render_hwnd(top)
        try:
            _, pid = win32process.GetWindowThreadProcessId(top)
            l, t, r, b = win32gui.GetClientRect(render)
            EMULATOR_INFO.clear()
            EMULATOR_INFO.update({
                "emu": _exe_name_of_pid(pid) or "emulator",
                "hwnd": render,
                "top": top,
                "w": r - l,
                "h": b - t,
            })
            set_active_platform("emulator")
        except Exception:  # noqa: BLE001
            pass
        return render
    return None


@dataclass
class OcrItem:
    text: str
    score: float
    box: tuple[int, int, int, int]
    brightness: float = 255.0  # 文字区域亮度 p95（<95 视为被遮罩压暗）  # x1, y1, x2, y2 (图像像素坐标)

    @property
    def center(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.box
        return (x1 + x2) // 2, (y1 + y2) // 2


class GameWindow:
    def __init__(self, hwnd: int, click_mode: str = "foreground"):
        self.hwnd = hwnd
        self.click_mode = click_mode
        self.click_hold, self.click_gap = read_click_timing()
        self._sct = mss.mss()
        # 视口抽象：默认 (0,0) + 客户区整图，等价于改造前的行为。
        # 模拟器场景下可把视口设成「渲染子窗口内的有效游戏区域」，Steam 下保持默认即可。
        self.viewport_offset: tuple[int, int] = (0, 0)
        self.viewport_size: tuple[int, int] | None = None

    def set_viewport(self, x1: int, y1: int, x2: int, y2: int) -> None:
        """设置有效游戏视口（左上右下，相对当前客户区像素）。传全 0 恢复默认。"""
        if x2 <= x1 or y2 <= y1:
            self.viewport_offset = (0, 0)
            self.viewport_size = None
            return
        self.viewport_offset = (int(x1), int(y1))
        self.viewport_size = (int(x2 - x1), int(y2 - y1))

    def viewport(self) -> tuple[int, int, int, int]:
        """返回 (宽, 高, 偏移x, 偏移y)。没有设置视口时就是客户区整图。"""
        w, h = self.client_size()
        if self.viewport_size is not None:
            return self.viewport_size[0], self.viewport_size[1], self.viewport_offset[0], self.viewport_offset[1]
        return w, h, 0, 0

    def is_alive(self) -> bool:
        return bool(win32gui.IsWindow(self.hwnd))

    # ---------- 几何 ----------
    def build_compat_diag_line(self, capture_cfg: str = "auto") -> str:
        """启动兼容性自检：窗口类名/进程/尺寸/首帧亮度/实际截图方式（用户发这一行即可定位）。"""
        hwnd = int(getattr(self, "hwnd", 0) or 0)
        top_hwnd = int((EMULATOR_INFO or {}).get("top") or hwnd or 0)
        try:
            top_cls = win32gui.GetClassName(top_hwnd) if top_hwnd else "IPC"
            top_title = (win32gui.GetWindowText(top_hwnd) or "")[:24] if top_hwnd else "MuMuIPC"
            _, pid = win32process.GetWindowThreadProcessId(top_hwnd) if top_hwnd else (0, 0)
            exe = _exe_name_of_pid(pid) if pid else "mumu_ipc"
            ren_cls = win32gui.GetClassName(hwnd) if hwnd else "ipc_display"
        except Exception:  # noqa: BLE001
            top_cls, top_title, exe, ren_cls = "?", "?", "?", "?"
        try:
            cw, ch = self.client_size()
        except Exception:  # noqa: BLE001
            cw, ch = 0, 0
        pw_all = pw_mid = mss_mid = -1.0
        mode_used = "ipc" if not hwnd else capture_cfg
        if hwnd:
            try:
                pw = self._capture_printwindow()
                if pw is not None and getattr(pw, "size", 0) > 0:
                    pw_all = float(pw.mean())
                    hh, ww = pw.shape[:2]
                    pw_mid = float(pw[int(hh * 0.18): int(hh * 0.82), int(ww * 0.18): int(ww * 0.82)].mean())
            except Exception:  # noqa: BLE001
                pass
            try:
                sc = self._capture_screen()
                if sc is not None and getattr(sc, "size", 0) > 0:
                    hh, ww = sc.shape[:2]
                    mss_mid = float(sc[int(hh * 0.18): int(hh * 0.82), int(ww * 0.18): int(ww * 0.82)].mean())
            except Exception:  # noqa: BLE001
                pass
            if capture_cfg in ("auto", "printwindow") and pw_all > 3.0 and pw_mid > 2.5:
                mode_used = "printwindow"
            else:
                mode_used = "screen(OpenGL/黑屏回退)" if pw_mid <= 2.5 else "screen"
        line = (
            f"🔎 [兼容自检] 平台={ACTIVE_PLATFORM} | "
            f'顶层=0x{top_hwnd:X}({top_cls}/{exe}/{top_title!r}) | ' 
            f"渲染=0x{hwnd:X}({ren_cls}/{cw}x{ch}) | "
            f"首帧亮度: PW(全图={pw_all:.1f},中心={pw_mid:.1f}) MSS(中心={mss_mid:.1f}) | "
            f"截图方式={mode_used}"
        )
        try:
            d = runtime_root() / "debug"
            d.mkdir(parents=True, exist_ok=True)
            with (d / "启动自检.txt").open("a", encoding="utf-8") as fp:
                fp.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {line}\n")
        except Exception:  # noqa: BLE001
            pass
        return line

    def client_size(self) -> tuple[int, int]:
        l, t, r, b = win32gui.GetClientRect(self.hwnd)
        return r - l, b - t

    def client_origin_on_screen(self) -> tuple[int, int]:
        return win32gui.ClientToScreen(self.hwnd, (0, 0))

    def is_minimized(self) -> bool:
        return bool(win32gui.IsIconic(self.hwnd))

    def activate(self) -> None:
        if self.is_minimized():
            win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
            time.sleep(0.5)
        if self.click_mode == "background":
            return  # 后台模式：不抢占前台/不抢焦点
        if win32gui.GetForegroundWindow() != self.hwnd:
            try:
                # 先模拟一次 Alt，绕过 Windows 对 SetForegroundWindow 的限制
                win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
                win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
                win32gui.SetForegroundWindow(self.hwnd)
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.25)

    # ---------- 截图 ----------
    def _capture_printwindow(self) -> np.ndarray | None:
        w, h = self.client_size()
        if w <= 0 or h <= 0:
            return None
        hwnd_dc = win32gui.GetWindowDC(self.hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfc_dc, w, h)
        save_dc.SelectObject(bmp)
        try:
            # 3 = PW_CLIENTONLY | PW_RENDERFULLCONTENT（可截取 DirectX 画面）
            ok = ctypes.windll.user32.PrintWindow(self.hwnd, save_dc.GetSafeHdc(), 3)
            if not ok:
                return None
            raw = bmp.GetBitmapBits(True)
            img = np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 4)
            return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        finally:
            win32gui.DeleteObject(bmp.GetHandle())
            save_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(self.hwnd, hwnd_dc)

    def _capture_screen(self) -> np.ndarray:
        w, h = self.client_size()
        x, y = self.client_origin_on_screen()
        shot = self._sct.grab({"left": x, "top": y, "width": w, "height": h})
        return cv2.cvtColor(np.asarray(shot), cv2.COLOR_BGRA2BGR)

    @staticmethod
    def _is_valid_pw_frame(img) -> bool:
        """PrintWindow 帧是否有效：整图够亮 且 中心视口不黑（排除外框工具栏骗过均值）。"""
        try:
            if img is None or getattr(img, "size", 0) == 0 or float(img.mean()) <= 3.0:
                return False
            h, w = img.shape[:2]
            center = img[int(h * 0.18): int(h * 0.82), int(w * 0.18): int(w * 0.82)]
            return center.size > 0 and float(center.mean()) > 2.5
        except Exception:  # noqa: BLE001
            return False

    def capture(self, method: str = "auto") -> np.ndarray:
        if method in ("auto", "printwindow"):
            img = self._capture_printwindow()
            if self._is_valid_pw_frame(img):
                return img
            if method == "printwindow":
                raise RuntimeError("PrintWindow 截图失败（全黑或中心视口黑屏）")
        return self._capture_screen()

    def _move_cursor(self, x: int, y: int) -> None:
        """移动光标：优先 SetCursorPos；被拦截时退回绝对坐标 mouse_event 并核实真的移动了。"""
        try:
            win32api.SetCursorPos((x, y))
            return
        except pywintypes.error:
            pass
        try:
            sx, sy = win32api.GetSystemMetrics(76), win32api.GetSystemMetrics(77)  # 虚拟屏幕原点
            sw, sh = win32api.GetSystemMetrics(78), win32api.GetSystemMetrics(79)  # 虚拟屏幕尺寸
            if sw > 1 and sh > 1:
                ax = int(round((x - sx) * 65535 / (sw - 1)))
                ay = int(round((y - sy) * 65535 / (sh - 1)))
                win32api.mouse_event(
                    win32con.MOUSEEVENTF_MOVE
                    | win32con.MOUSEEVENTF_ABSOLUTE
                    | win32con.MOUSEEVENTF_VIRTUALDESK,
                    ax,
                    ay,
                    0,
                    0,
                )
                time.sleep(0.02)
                px, py = win32api.GetCursorPos()
                if abs(px - x) <= 3 and abs(py - y) <= 3:
                    return
        except Exception:  # noqa: BLE001
            pass
        raise InputBlockedError(
            f"系统拒绝移动鼠标（{process_privilege_summary()}；前台{foreground_window_privilege()}）"
            + (
                "——当前进程被限制为 Low 低权限，无法操作更高权限的游戏窗口。请关闭本窗口后，"
                "从资源管理器双击 .bat，或按 Win+R 输入 cmd 后运行。"
                if is_low_integrity()
                else "——请检查是否有远程控制/录屏/安全软件拦截输入，或游戏是否以更高权限运行。"
            )
        )

    # ---------- 点击 ----------
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
        """x, y 为客户区坐标。连点/双击锁定同一像素坐标；按压停留更长(≈CLICK_HOLD)更像人手。"""
        x += random.randint(-jitter, jitter)
        y += random.randint(-jitter, jitter)
        w, h = self.client_size()
        x = max(1, min(w - 2, x))
        y = max(1, min(h - 2, y))
        n = max(1, int(clicks))
        gap = self.click_gap if click_gap is None else float(click_gap)
        if hold is not None:
            press_hold = float(hold)
        else:
            press_hold = random.uniform(*(CLICK_HOLD_FAST if quick else self.click_hold))
        if self.click_mode == "background":
            lparam = win32api.MAKELONG(x, y)
            win32gui.PostMessage(self.hwnd, win32con.WM_MOUSEMOVE, 0, lparam)
            for i in range(n):
                if i > 0:
                    time.sleep(random.uniform(gap * 0.9, gap * 1.1))
                win32gui.PostMessage(self.hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
                time.sleep(press_hold)
                win32gui.PostMessage(self.hwnd, win32con.WM_LBUTTONUP, 0, lparam)
            return
        self.activate()
        ox, oy = self.client_origin_on_screen()
        # 光标只移动一次，连点两下期间绝不偏移坐标，确保系统与游戏引擎稳定判定为快速双击
        self._move_cursor(ox + x, oy + y)
        time.sleep(random.uniform(*CLICK_AIM_DELAY))
        for i in range(n):
            if i > 0:
                time.sleep(random.uniform(gap * 0.9, gap * 1.1))
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(press_hold)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def press(self, x: int, y: int, seconds: float = 1.5, jitter: int = 2) -> None:
        """在 (x, y) 按住 seconds 秒再松开（长按跳过动态过场）。"""
        x += random.randint(-jitter, jitter)
        y += random.randint(-jitter, jitter)
        w, h = self.client_size()
        x = max(1, min(w - 2, x))
        y = max(1, min(h - 2, y))
        if self.click_mode == "background":
            lparam = win32api.MAKELONG(x, y)
            win32gui.PostMessage(self.hwnd, win32con.WM_MOUSEMOVE, 0, lparam)
            win32gui.PostMessage(self.hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
            time.sleep(max(0.2, float(seconds)))
            win32gui.PostMessage(self.hwnd, win32con.WM_LBUTTONUP, 0, lparam)
            return
        self.activate()
        ox, oy = self.client_origin_on_screen()
        self._move_cursor(ox + x, oy + y)
        time.sleep(random.uniform(*CLICK_AIM_DELAY))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(max(0.2, float(seconds)))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def press_start(self, x: int, y: int, jitter: int = 2) -> None:
        """按下不松（配合 press_end），用于长按期间抓图。"""
        x += random.randint(-jitter, jitter)
        y += random.randint(-jitter, jitter)
        w, h = self.client_size()
        x = max(1, min(w - 2, x))
        y = max(1, min(h - 2, y))
        self._press_pt = (x, y)
        if self.click_mode == "background":
            lparam = win32api.MAKELONG(x, y)
            win32gui.PostMessage(self.hwnd, win32con.WM_MOUSEMOVE, 0, lparam)
            win32gui.PostMessage(self.hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
            return
        self.activate()
        ox, oy = self.client_origin_on_screen()
        self._move_cursor(ox + x, oy + y)
        time.sleep(random.uniform(*CLICK_AIM_DELAY))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)

    def press_end(self) -> None:
        pt = getattr(self, "_press_pt", None)
        if pt is None:
            return
        x, y = pt
        self._press_pt = None
        if self.click_mode == "background":
            lparam = win32api.MAKELONG(x, y)
            win32gui.PostMessage(self.hwnd, win32con.WM_LBUTTONUP, 0, lparam)
            return
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def press_start_ratio(self, rx: float, ry: float, jitter: int = 2) -> None:
        vw, vh, ox, oy = self.viewport()
        self.press_start(ox + int(vw * rx), oy + int(vh * ry), jitter=jitter)

    def press_ratio(self, rx: float, ry: float, seconds: float = 1.5, jitter: int = 2) -> None:
        vw, vh, ox, oy = self.viewport()
        self.press(ox + int(vw * rx), oy + int(vh * ry), seconds=seconds, jitter=jitter)

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
            ox + int(vw * rx),
            oy + int(vh * ry),
            jitter=jitter,
            clicks=clicks,
            click_gap=click_gap,
            quick=quick,
            hold=hold,
        )

    def wheel(self, rx: float, ry: float, notches: int = 3, up: bool = False) -> None:
        """在窗口相对位置滚动鼠标滚轮（background 模式用 PostMessage，不移动物理鼠标）。"""
        w, h = self.client_size()
        x, y = int(w * rx), int(h * ry)
        n = max(1, int(notches))
        delta = 120 * n * (1 if up else -1)
        if self.click_mode == "background":
            ox, oy = self.client_origin_on_screen()
            lparam = win32api.MAKELONG(ox + x, oy + y)
            wparam = (delta & 0xFFFF) << 16
            win32gui.PostMessage(self.hwnd, win32con.WM_MOUSEWHEEL, wparam, lparam)
            return
        self.activate()
        ox, oy = self.client_origin_on_screen()
        self._move_cursor(ox + x, oy + y)
        for _ in range(n):
            win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, 120 if up else -120, 0)
            time.sleep(0.04)

    def drag_ratio(
        self,
        rx1: float,
        ry1: float,
        rx2: float,
        ry2: float,
        duration: float = 0.24,
        steps: int = 14,
        settle: float | None = None,
    ) -> None:
        """按窗口比例平滑拖拽滚动列表（末端停顿消除惯性回弹）。

        settle=None 时保持原行为（background 末端停 0.08s / 前台 0.09s）；
        传入 settle 秒数时，background 会在末端补发 3 次「零位移」WM_MOUSEMOVE 再松手，
        用于清零游戏列表的脱手速度（装备扫描翻页防 fling；不影响既有调用）。
        """
        vw, vh, ox, oy = self.viewport()
        x1 = ox + max(0, min(vw - 1, int(vw * rx1)))
        y1 = oy + max(0, min(vh - 1, int(vh * ry1)))
        x2 = ox + max(0, min(vw - 1, int(vw * rx2)))
        y2 = oy + max(0, min(vh - 1, int(vh * ry2)))
        n = max(4, int(steps))
        step_sleep = max(0.008, duration / n)

        if self.click_mode == "background":
            win32gui.PostMessage(self.hwnd, win32con.WM_MOUSEMOVE, 0, win32api.MAKELONG(x1, y1))
            time.sleep(0.02)
            win32gui.PostMessage(self.hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, win32api.MAKELONG(x1, y1))
            for i in range(1, n + 1):
                t = i / n
                cx = int(round(x1 + (x2 - x1) * t))
                cy = int(round(y1 + (y2 - y1) * t))
                win32gui.PostMessage(self.hwnd, win32con.WM_MOUSEMOVE, win32con.MK_LBUTTON, win32api.MAKELONG(cx, cy))
                time.sleep(step_sleep)
            if settle is None:
                time.sleep(0.08)
            else:
                hold = max(0.0, float(settle))
                if hold > 0:
                    end_lp = win32api.MAKELONG(x2, y2)
                    for _ in range(3):
                        time.sleep(hold / 3.0)
                        win32gui.PostMessage(self.hwnd, win32con.WM_MOUSEMOVE, win32con.MK_LBUTTON, end_lp)
            win32gui.PostMessage(self.hwnd, win32con.WM_LBUTTONUP, 0, win32api.MAKELONG(x2, y2))
            return

        self.activate()
        ox, oy = self.client_origin_on_screen()
        self._move_cursor(ox + x1, oy + y1)
        time.sleep(0.025)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.03)
        for i in range(1, n + 1):
            t = i / n
            cx = int(round(x1 + (x2 - x1) * t))
            cy = int(round(y1 + (y2 - y1) * t))
            self._move_cursor(ox + cx, oy + cy)
            time.sleep(step_sleep)
        # 终点稍微按住再松开，防止惯性滑动回弹或漏掉底部条目
        time.sleep(0.09 if settle is None else max(0.0, float(settle)))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def press_key(self, vk: int) -> None:
        if self.click_mode == "background":
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYDOWN, vk, 0)
            time.sleep(0.05)
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYUP, vk, 0)
            return
        self.activate()
        win32api.keybd_event(vk, 0, 0, 0)
        time.sleep(random.uniform(0.04, 0.09))
        win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)


_SPECS = (
    ("front",  (0.452, 0.626), (0.380, 0.245, 0.500, 0.370), (0.375, 0.585, 0.532, 0.668)),
    ("bottom", (0.345, 0.742), (0.285, 0.395, 0.405, 0.468), (0.268, 0.700, 0.422, 0.785)),
    ("top",    (0.325, 0.524), (0.265, 0.190, 0.380, 0.280), (0.248, 0.492, 0.402, 0.558)),
    ("back",   (0.222, 0.626), (0.155, 0.285, 0.272, 0.378), (0.148, 0.585, 0.296, 0.668)),
)


def _has_green_hp_bar(roi, min_w_px, max_h_px):
    if roi.size == 0:
        return False
    green = ((roi[:, :, 0] >= 35) & (roi[:, :, 0] <= 85)
             & (roi[:, :, 1] >= 95) & (roi[:, :, 2] >= 110)).astype(np.uint8) * 255
    if float((green > 0).mean()) < 0.005:
        return False
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 2))
    closed = cv2.morphologyEx(green, cv2.MORPH_CLOSE, k)
    n, labels, stats, _c = cv2.connectedComponentsWithStats(closed, 8)
    for i in range(1, n):
        _x, _y, bw, bh, area = stats[i]
        if bw >= min_w_px and 2 <= bh <= max_h_px and (bw / max(1, bh)) >= 3.2 \
                and area >= bw * bh * 0.45:
            return True
        # 2026-11-14：木属性英雄的等级牌「60」也是绿色，会被 MORPH_CLOSE 和绿色血条桥接成
        # 一个超高的粗块（实测 113x27，高度超过 max_h_px），逐行拆出细血条带再判一次。
        if bw >= min_w_px and bh > max_h_px:
            comp = labels[_y: _y + bh, _x: _x + bw] == i
            wide = np.zeros(bh, dtype=bool)
            for r in range(bh):
                xs = np.where(comp[r])[0]
                if xs.size and (int(xs[-1] - xs[0]) + 1) >= min_w_px \
                        and int(xs.size) >= min_w_px * 0.45:
                    wide[r] = True
            r = 0
            while r < bh:
                if not wide[r]:
                    r += 1
                    continue
                r2 = r
                while r2 < bh and wide[r2]:
                    r2 += 1
                sub_h = r2 - r
                if 2 <= sub_h <= max_h_px:
                    sub = comp[r:r2]
                    cols = np.where(sub.any(axis=0))[0]
                    if cols.size:
                        sub_w = int(cols[-1] - cols[0]) + 1
                        if sub_w >= min_w_px and (sub_w / sub_h) >= 3.2 \
                                and int(sub.sum()) >= sub_w * sub_h * 0.45:
                            return True
                r = r2
    return False


def blue_empty_pads(img, verbose=False):
    h, w = img.shape[:2]
    if h < 80 or w < 80:
        return []
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    blue_mask = ((hsv[:, :, 0] >= 88) & (hsv[:, :, 0] <= 125)
                 & (hsv[:, :, 1] >= 90) & (hsv[:, :, 2] >= 120))
    floor = blue_mask[int(h * 0.46): int(h * 0.82), int(w * 0.13): int(w * 0.55)]
    if floor.size == 0 or float(floor.mean()) < 0.008:
        return []
    min_bar_w = max(16, int(w * 0.022))
    max_bar_h = max(6, int(h * 0.018))
    out = []
    for name, (cx0, cy0), (hx1, hy1, hx2, hy2), (wx1, wy1, wx2, wy2) in _SPECS:
        hp = hsv[int(h * hy1): int(h * hy2), int(w * hx1): int(w * hx2)]
        has_hp = _has_green_hp_bar(hp, min_bar_w, max_bar_h)
        bare = False
        if name in ("front", "bottom", "back"):
            px1, px2 = max(0, int(w * (cx0 - 0.026))), min(w, int(w * (cx0 + 0.026)))
            py1, py2 = max(0, int(h * (cy0 - 0.072))), min(h, int(h * (cy0 + 0.016)))
            v = hsv[py1:py2, px1:px2, 2]
            if v.size > 0:
                bare = bool(float(v.mean()) < 55.0 and float(v.std()) < 14.0
                            and float((v > 110).mean()) < 0.03)
        if verbose:
            print(f"    {name}: has_hp={has_hp} bare={bare}")
        if (not has_hp) or bare:
            cx, cy = cx0, cy0
            sub_b = blue_mask[int(h * wy1): int(h * wy2), int(w * wx1): int(w * wx2)]
            ys, xs = np.where(sub_b)
            if xs.size >= 40:
                span_x = float(xs.max() - xs.min()) / w
                if span_x >= 0.095:
                    bx = wx1 + (float(xs.min() + xs.max()) * 0.5) / w
                    by = wy1 + (float(ys.min() + ys.max()) * 0.5) / h
                    cx = float(np.clip(bx, cx0 - 0.015, cx0 + 0.015))
                    cy = float(np.clip(by, cy0 - 0.015, cy0 + 0.015))
            out.append((round(cx, 3), round(cy, 3)))
    return out


def find_empty_slot(img, min_area: int = 8000) -> tuple[float, float] | None:
    """包装 blue_empty_pads，返回单个最优先的空位坐标。"""
    pads = blue_empty_pads(img)
    return pads[0] if pads else None


def hero_plus_btn(img):
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    def _ok(rx, ry):
        px0, px1 = max(0, int(w * (rx - 0.022))), min(w, int(w * (rx + 0.022)))
        py0, py1 = max(0, int(h * (ry - 0.028))), min(h, int(h * (ry + 0.028)))
        sub = hsv[py0:py1, px0:px1]
        if sub.size == 0:
            return False
        blue = ((sub[:, :, 0] >= 96) & (sub[:, :, 0] <= 124)
                & (sub[:, :, 1] >= 130) & (sub[:, :, 2] >= 130))
        yel = ((sub[:, :, 0] >= 15) & (sub[:, :, 0] <= 38)
               & (sub[:, :, 1] >= 140) & (sub[:, :, 2] >= 185))
        return float(blue.mean()) >= 0.15 and float(yel.mean()) >= 0.04

    hits = [(sc, cx, cy) for sc, cx, cy in find_template_points(img, "hero_plus.png", threshold=0.72)
            if 0.64 <= cx <= 0.79 and 0.28 <= cy <= 0.86 and _ok(cx, cy)]
    if hits:
        hits.sort(key=lambda x: (-x[0], x[2]))
        return (round(hits[0][1], 3), round(hits[0][2], 3))
    return None


def find_template_points(
    img,
    tmpl_path,
    threshold: float = 0.75,
    scales: tuple[float, ...] = (0.55, 0.65, 0.75, 0.85, 0.95, 1.05, 1.15, 1.3),
    max_hits: int = 4,
):
    """多尺度模板匹配，返回 [(score, cx, cy)]（比例为 0~1，已做简单去重）。"""
    import cv2 as _cv2
    import numpy as _np
    from pathlib import Path as _Path

    tp = _Path(runtime_root()) / "templates" / tmpl_path if not _Path(tmpl_path).is_absolute() else _Path(tmpl_path)
    if not tp.exists():
        return []
    tmpl = _cv2.imdecode(_np.fromfile(str(tp), dtype=_np.uint8), _cv2.IMREAD_GRAYSCALE)
    if tmpl is None:
        return []
    gray = _cv2.cvtColor(img, _cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    hits: list[tuple[float, float, float]] = []
    for sc in scales:
        tw, th = int(tmpl.shape[1] * sc), int(tmpl.shape[0] * sc)
        if tw < 12 or th < 12 or tw >= w or th >= h:
            continue
        t = _cv2.resize(tmpl, (tw, th))
        res = _cv2.matchTemplate(gray, t, _cv2.TM_CCOEFF_NORMED)
        _min_v, max_v, _min_l, max_l = _cv2.minMaxLoc(res)
        if max_v >= threshold:
            cx = (max_l[0] + tw / 2) / w
            cy = (max_l[1] + th / 2) / h
            hits.append((float(max_v), cx, cy))
    hits.sort(reverse=True)
    out: list[tuple[float, float, float]] = []
    for score, cx, cy in hits:
        if all(abs(cx - ox) > 0.05 or abs(cy - oy) > 0.05 for _s, ox, oy in out):
            out.append((score, cx, cy))
        if len(out) >= max_hits:
            break
    return out


def _low_spec_enabled() -> bool:
    """低配降载模式：环境变量优先，其次 rules.yaml settings.low_spec_mode。"""
    import os as _os

    env = _os.environ.get("E7PILOT_LOW_SPEC")
    if env is not None:
        return env.strip() in ("1", "true", "True", "yes")
    try:
        cfg = load_rules_cfg()
        return bool((cfg.get("settings") or {}).get("low_spec_mode", False))
    except Exception:  # noqa: BLE001
        return False


class Ocr:
    def __init__(self, low_spec: bool | None = None):
        from rapidocr_onnxruntime import RapidOCR

        self.low_spec = _low_spec_enabled() if low_spec is None else bool(low_spec)
        intra = 1 if self.low_spec else 2
        det_len = 576 if self.low_spec else 736

        # 关键：关闭 onnxruntime 线程池的忙等待自旋（自带请求，无需改第三方库源码）
        import onnxruntime as _ort

        _orig_so = _ort.SessionOptions

        def _patched_so(*a, **kw):
            so = _orig_so(*a, **kw)
            so.intra_op_num_threads = intra
            so.inter_op_num_threads = 1
            so.execution_mode = _ort.ExecutionMode.ORT_SEQUENTIAL
            try:
                so.add_session_config_entry("session.intra_op_thread_allow_spinning", "0")
                so.add_session_config_entry("session.inter_op_thread_allow_spinning", "0")
            except Exception:  # noqa: BLE001
                pass
            return so

        _ort.SessionOptions = _patched_so
        try:
            self._engine = RapidOCR(
                intra_op_num_threads=intra,
                inter_op_num_threads=1,
                use_cls=False,          # 游戏画面没有倒立文字，省 15~20% 算力
                det_limit_side_len=det_len,
                det_limit_type="max",
            )
        finally:
            _ort.SessionOptions = _orig_so
        self.last_dim_items: list[OcrItem] = []

    def read(
        self,
        img: np.ndarray,
        min_score: float = 0.5,
        min_brightness: float = 95.0,
        include_dim: bool = False,
    ) -> list[OcrItem]:
        """识别文字：亮场文字正常返回；暗场（被弹窗遮罩压暗）收集到 last_dim_items。

        暗场文字只允许用于「判断场景状态」，绝不能拿来点击。
        """
        result, _ = self._engine(img)
        h, w = img.shape[:2]
        items: list[OcrItem] = []
        dim_items: list[OcrItem] = []
        for box, text, score in result or []:
            if float(score) < min_score:
                continue
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            x1, y1 = max(0, int(min(xs))), max(0, int(min(ys)))
            x2, y2 = min(w, int(max(xs))), min(h, int(max(ys)))
            if x2 <= x1 or y2 <= y1:
                continue
            roi_v = img[y1:y2, x1:x2].max(axis=2)
            bright = float(np.percentile(roi_v, 95)) if roi_v.size else 0.0
            if bright < 25.0:
                continue
            item = OcrItem(
                text=str(text).strip(), score=float(score), box=(x1, y1, x2, y2), brightness=bright
            )
            if bright >= (min_brightness if min_brightness > 0 else 0.0):
                items.append(item)
            elif bright >= 40.0:
                dim_items.append(item)
        self.last_dim_items = dim_items
        if include_dim:
            return items + dim_items
        return items


# ==================== OpenCV 图像识别辅助能力 ====================


def detect_quest_compass(
    img: np.ndarray, min_red_ratio: float = 0.10, max_red_ratio: float = 0.42
) -> tuple[str, tuple[float, float], float] | None:
    """识别迷宫/探索关卡十字路口的「橙红色火焰高亮」任务方向罗盘。

    返回: (方向中文名, 点击比例坐标 (rx, ry), 红色高亮占比)，未检测到返回 None。
    """
    h, w = img.shape[:2]
    if h <= 0 or w <= 0:
        return None
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    full_red = (
        ((hsv[:, :, 0] <= 15) | (hsv[:, :, 0] >= 168))
        & (hsv[:, :, 1] >= 140)
        & (hsv[:, :, 2] >= 145)
    )
    # 防止火系角色大招（如济纽亚 S3）全屏红光特效被误判为方向罗盘
    if float(full_red.mean()) > 0.12:
        return None

    best: tuple[str, tuple[float, float], float] | None = None
    for _code, ((zx1, zy1, zx2, zy2), click_pt, label) in COMPASS_ZONES.items():
        x1, y1, x2, y2 = int(w * zx1), int(h * zy1), int(w * zx2), int(h * zy2)
        sub_red = full_red[y1:y2, x1:x2]
        sub_v = hsv[y1:y2, x1:x2, 2]
        if sub_red.size == 0:
            continue
        red_ratio = float(sub_red.mean())
        if not (min_red_ratio <= red_ratio <= max_red_ratio):
            continue
        # 真实方向罗盘内部有深色圆底，纯红光爆炸特效没有深色内圈
        dark_ratio = float((sub_v < 85).mean())
        if dark_ratio < 0.02:
            continue
        if best is None or red_ratio > best[2]:
            best = (label, click_pt, round(red_ratio, 4))
    return best


def find_single_compass_fallback(items: list[OcrItem], w: int, h: int) -> tuple[str, tuple[float, float]] | None:
    """死胡同兜底：当画面只有一个普通金色方向罗盘（N/S/E/W）时返回该方向。"""
    found: list[tuple[str, tuple[float, float]]] = []
    for it in items:
        t = it.text.strip().upper()
        if t not in COMPASS_ZONES:
            continue
        cx, cy = it.center[0] / w, it.center[1] / h
        (zx1, zy1, zx2, zy2), click_pt, label = COMPASS_ZONES[t]
        if zx1 <= cx <= zx2 and zy1 <= cy <= zy2:
            found.append((label, click_pt))
    if len(found) == 1:
        return found[0]
    return None


def check_team_auto_switch(
    img: np.ndarray, items: list[OcrItem]
) -> tuple[bool, tuple[float, float]] | None:
    """在队伍编成界面检测助战槽下方的 [AUTO] 按钮是否已开启（绿色）。

    若当前不在编队界面或未找到 AUTO 开关则返回 None；
    否则返回 (is_on, click_ratio_xy)。
    """
    h, w = img.shape[:2]
    for it in items:
        if it.text.strip().upper() != "AUTO":
            continue
        cx, cy = it.center[0] / w, it.center[1] / h
        if not (0.50 <= cx <= 0.72 and 0.60 <= cy <= 0.78):
            continue
        # 取开关胶囊区域检测绿色占比
        rx1, ry1 = max(0.0, cx - 0.05), max(0.0, cy - 0.025)
        rx2, ry2 = min(1.0, cx + 0.07), min(1.0, cy + 0.025)
        roi = img[int(h * ry1) : int(h * ry2), int(w * rx1) : int(w * rx2)]
        if roi.size == 0:
            continue
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        green_ratio = float(
            ((hsv[:, :, 0] >= 35) & (hsv[:, :, 0] <= 88) & (hsv[:, :, 1] >= 75) & (hsv[:, :, 2] >= 60)).mean()
        )
        return (green_ratio >= 0.20, (round(cx + 0.01, 3), round(cy, 3)))
    return None


def has_labyrinth_hud(img: np.ndarray, items: list[OcrItem]) -> bool:
    """判断当前是否处于迷宫探索跑图 HUD（区别于普通 1/3..3/3 波次战斗，防止火焰背景误判罗盘）。"""
    h, w = img.shape[:2]
    if h <= 0 or w <= 0:
        return False

    for it in items:
        t = it.text.strip()
        tl = t.lower()
        cx, cy = it.center[0] / w, it.center[1] / h
        if "跳过" in t and "教学" not in t and cx >= 0.65 and cy <= 0.20:
            return False
        # 若正在正式战斗回合中（有波次计数或灵魂槽），绝不属于迷宫十字路口选向态
        if ("灵魂不足" in t and cx >= 0.60 and cy >= 0.82) or (
            tl in ("burn!", "tap to burn", "taptoburn", "cancel") and 0.44 <= cx <= 0.65 and cy >= 0.82
        ):
            return False
        if any(wv in t for wv in ("1/3", "2/3", "3/3", "1/2", "2/2", "1/1")) and cx <= 0.22 and cy <= 0.24:
            return False
        # 迷宫内遭遇怪物进入回合制战斗时，左下角会出现当前行动英雄血量（如 15230/15230），此时不属于跑图选路态
        if 0.18 <= cx <= 0.36 and 0.92 <= cy <= 0.99 and "/" in t and any(ch.isdigit() for ch in t):
            return False

    for it in items:
        tl = it.text.strip().lower()
        cx, cy = it.center[0] / w, it.center[1] / h
        if "skill" in tl and cx >= 0.78 and cy >= 0.80:
            return True

    for ry1, ry2 in ((0.185, 0.232), (0.008, 0.052)):
        roi = img[int(h * ry1) : int(h * ry2), int(w * 0.090) : int(w * 0.172)]
        if roi.size > 0:
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            olive = (
                (hsv[:, :, 0] >= 35)
                & (hsv[:, :, 0] <= 65)
                & (hsv[:, :, 1] >= 90)
                & (hsv[:, :, 2] >= 45)
                & (hsv[:, :, 2] <= 145)
            )
            if float(olive.mean()) >= 0.45:
                return True
    return False


def has_battle_hud(img: np.ndarray, items: list[OcrItem]) -> bool:
    """判断当前画面是否处于关卡战斗/迷宫跑图 HUD 中（用于禁止在跑图或打怪时乱点地面）。"""
    h, w = img.shape[:2]
    if h <= 0 or w <= 0:
        return False

    # 若右上角存在剧情“跳过”按钮，说明处于剧情对话而非战斗操控态
    for it in items:
        if "跳过" in it.text and "教学" not in it.text:
            cx, cy = it.center[0] / w, it.center[1] / h
            if cx >= 0.65 and cy <= 0.20:
                return False

    for it in items:
        t = it.text.strip()
        tl = t.lower()
        cx, cy = it.center[0] / w, it.center[1] / h
        # 1. 迷宫跑图右下角技能栏 "Skill"
        if "skill" in tl and cx >= 0.78 and cy >= 0.80:
            return True
        # 2. 普通波次战斗右下角灵魂槽提示 "灵魂不足" 或灵魂燃烧按钮 "Burn!" / "Cancel"
        if "灵魂不足" in t and cx >= 0.60 and cy >= 0.82:
            return True
        if tl in ("burn!", "tap to burn", "taptoburn", "cancel") and 0.44 <= cx <= 0.65 and cy >= 0.82:
            return True
        # 3. 普通战斗左上角波次 "1/3"、"2/3"、"3/3"（被结算遮罩压暗时已被 min_brightness 过滤）
        if any(wv in t for wv in ("1/3", "2/3", "3/3", "1/2", "2/2", "1/1")) and cx <= 0.22 and cy <= 0.24:
            return True

    # 4. 右上角纯白色战斗暂停双竖杠图标 "||"（迷宫与普通战斗共有，结算/弹窗时变暗为 0）
    roi_pause = img[int(h * 0.020) : int(h * 0.075), int(w * 0.955) : int(w * 0.990)]
    if roi_pause.size > 0:
        hsv_p = cv2.cvtColor(roi_pause, cv2.COLOR_BGR2HSV)
        white_ratio = float(((hsv_p[:, :, 1] < 30) & (hsv_p[:, :, 2] > 215)).mean())
        if 0.14 <= white_ratio <= 0.42:
            return True

    # 5. 左上角迷宫士气绿框（小地图展开时约在 y=0.18..0.24，收起时约在 y=0.01..0.06）
    for ry1, ry2 in ((0.185, 0.232), (0.008, 0.052)):
        roi = img[int(h * ry1) : int(h * ry2), int(w * 0.090) : int(w * 0.172)]
        if roi.size > 0:
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            olive = (
                (hsv[:, :, 0] >= 35)
                & (hsv[:, :, 0] <= 65)
                & (hsv[:, :, 1] >= 90)
                & (hsv[:, :, 2] >= 45)
                & (hsv[:, :, 2] <= 145)
            )
            if float(olive.mean()) >= 0.45:
                return True

    return False
