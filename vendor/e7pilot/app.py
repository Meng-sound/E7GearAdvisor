"""E7Pilot —— 图形界面（GUI）与命令行分发入口。

GUI：直接双击 E7Pilot.exe（或 python app.py）
CLI：E7Pilot.exe --run main.py --auto     （GUI 内部就是用这个起子进程）
     E7Pilot.exe --version
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

import prts

# PyInstaller windowed 模式没有控制台，stdout/stderr 可能为 None
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

# 必须在创建任何 Tk 窗口之前声明 DPI 感知，否则 150% 缩放下窗口会被系统压小
try:
    import ctypes as _ct

    try:
        _ct.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:  # noqa: BLE001
        _ct.windll.user32.SetProcessDPIAware()
except Exception:  # noqa: BLE001
    pass

try:
    from version import APP_NAME, BUILD_DATE, VERSION
except Exception:  # noqa: BLE001
    APP_NAME, VERSION, BUILD_DATE = "E7Pilot", "1.0.0", ""

MODES = [
    ("auto", "原版推图", "官方自动推图"),
    ("brieg", "手操烧魂", "自动识别战斗逻辑"),
    ("shop", "秘密商店", "自动刷新购买"),
    ("chain", "商店+推图", "字面意思，秘密商店达标自动推主线"),
    ("theater", "月光剧场", "自动观影"),
]


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def bundle_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).parent))


def prepare_env() -> Path:
    """把规则/模板/资源放到工作目录，并把 E7_ROOT 指向它（打包后也能读写 debug）。"""
    work = app_dir()
    (work / "debug").mkdir(exist_ok=True)
    for name in ("rules.yaml",):
        src, dst = bundle_dir() / name, work / name
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)
    for name in ("templates",):
        src, dst = bundle_dir() / name, work / name
        if src.exists() and not dst.exists():
            shutil.copytree(src, dst)
    os.environ["E7_ROOT"] = str(work)
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    return work


def run_cli(argv: list[str]) -> int:
    """子进程入口：argv = ["main.py", "--auto", ...] 或 ["shop.py", ...]。"""
    if not argv:
        return 2
    target, rest = argv[0], argv[1:]
    sys.argv = [target, *rest]
    if target == "probe.py":
        import probe

        return probe.main()
    if target == "shop.py":
        import shop

        return shop.run_shop_flow()
    if target == "equip_scan.py":
        import equip_scan

        return equip_scan.main()
    import main

    return main.main()


# ---------------------------------------------------------------- GUI
def dual_client_warning_decision(
    *,
    warned: bool,
    noshow: bool,
    pip_enabled: bool,
    steam_hwnd: int | None,
    emu_hwnds: list[int],
) -> tuple[bool, bool]:
    """双客户端提示的纯决策逻辑（便于离线测试）。

    条件：画中画开启 + 同时检测到 MuMu 模拟器与 Steam 版第七史诗 + 本次运行未勾选「不再提示」。
    返回 (是否弹窗, 新的 warned 状态)；条件不满足时 warned 复位（下次满足会重新弹）。
    """
    if noshow or not pip_enabled:
        return False, False
    active = bool(steam_hwnd) and bool(emu_hwnds)
    if not active:
        return False, False
    if warned:
        return False, True
    return True, True


def run_gui() -> int:
    import tkinter as tk
    from tkinter import messagebox, ttk

    work = prepare_env()

    class App(tk.Tk):
        def __init__(self) -> None:
            super().__init__()
            self.title(f"{APP_NAME}  v{VERSION}")
            # 整体放大：1.35 缩放 + 默认字体 12 号（默认 9 号太小）
            try:
                # 跟随系统 DPI（已声明 per-monitor 感知，Tk 会自动算缩放）
                import tkinter.font as _tkfont

                for _name, _size in (
                    ("TkDefaultFont", 11),
                    ("TkTextFont", 11),
                    ("TkMenuFont", 11),
                    ("TkHeadingFont", 11),
                    ("TkTooltipFont", 11),
                ):
                    try:
                        _tkfont.nametofont(_name).configure(size=_size)
                    except Exception:  # noqa: BLE001
                        pass
            except Exception:  # noqa: BLE001
                pass

            self.geometry("1200x930")
            self.minsize(1000, 760)
            self.work = work
            self.proc: subprocess.Popen | None = None

            style = prts.setup_dark_style(self)
            prts.enable_dark_titlebar(self)

            # 顶部
            top = ttk.Frame(self, padding=(12, 10, 12, 4))
            top.pack(fill="x")
            self.banner = prts.HazardBanner(
                self, "本软件永久免费；若你是付费购买，请申请退款并举报卖家。"
            )
            self.banner.pack(fill="x", padx=12, pady=(8, 2))
            ttk.Label(top, text=f"{APP_NAME}", font=(prts.FONT_UI, 20)).pack(side="left")
            ttk.Label(top, text=f"SYS.VER // {VERSION}", style="Sub.TLabel", font=("Consolas", 9)).pack(side="left", padx=(10, 0))
            ttk.Button(top, text="ℹ 关于", command=self.show_about).pack(side="right")
            self.theme_btn = ttk.Button(top, text=("☀ 日间" if prts.MODE["name"] == "dark" else "☾ 夜间"), command=self.toggle_theme)
            self.theme_btn.pack(side="right", padx=(0, 8))
            ttk.Button(top, text="❤ 支持作者", command=self.open_donate).pack(side="right", padx=(0, 8))
            ttk.Button(top, text="📜 日志", command=self.toggle_log).pack(side="right", padx=(0, 8))
            self.update_btn = ttk.Button(top, text="🔄 检查更新", command=self.check_update_click)
            self.update_btn.pack(side="right", padx=(0, 8))
            ttk.Button(top, text="目录", command=self.open_dir).pack(side="right", padx=8)

            # 功能按钮
            box = ttk.LabelFrame(self, text="选择功能（先打开游戏并进入对应界面）", padding=10)
            box.pack(fill="x", padx=12, pady=6)

            # 红装自动购买配置（rules.yaml -> settings.gear_*）
            self._cfg_gear = {
                "enabled": False,
                "score27": False,
                "speed3": False,
                "combo": False,
                "price": 1400000,
            }
            try:
                from core import load_rules_cfg as _load_cfg

                _gs = (_load_cfg().get("settings") or {})
                self._cfg_gear = {
                    "enabled": bool(_gs.get("gear_auto_buy", False)),
                    "score27": bool(_gs.get("gear_cond_score27", False)),
                    "speed3": bool(_gs.get("gear_cond_speed3", False)),
                    "combo": bool(_gs.get("gear_cond_combo", False)),
                    "price": int(_gs.get("gear_price", 1400000)),
                }
            except Exception:  # noqa: BLE001
                pass

            # 画中画配置（rules.yaml -> settings.pip_*）
            self._cfg_pip = {"enabled": False, "width": 1080, "fps": 30}
            try:
                import yaml as _yaml

                from core import runtime_root as _rr

                _c = _yaml.safe_load((_rr() / "rules.yaml").read_text(encoding="utf-8")) or {}
                _s = _c.get("settings") or {}
                self._cfg_pip = {
                    "enabled": bool(_s.get("pip_enabled", False)),
                    "width": int(_s.get("pip_width", 1080)),
                    "fps": float(_s.get("pip_fps", 30)),
                }
            except Exception:  # noqa: BLE001
                pass

            self.mode_var = tk.StringVar(value="brieg")
            grid = tk.Frame(box, bg=prts.C["bg"])
            grid.pack(fill="x")
            for i, (key, title, desc) in enumerate(MODES):
                r, c = divmod(i, 3)
                tile = prts.PrtsTile(
                    grid, f"{i + 1:02d}", key, title, desc, self.mode_var, self._on_mode_change
                )
                tile.grid(
                    row=r, column=c, sticky="ew",
                    padx=(0 if c == 0 else 8, 0), pady=(0 if r == 0 else 8, 0),
                )
                grid.columnconfigure(c, weight=1, uniform="tile")

            # 参数
            params = ttk.Frame(self, padding=(12, 0))
            params.pack(fill="x")
            self.stop_stones = tk.StringVar(value="2000")
            self.keep_gold = tk.StringVar(value="1000000")
            ttk.Label(params, text="保留金币：").pack(side="left")
            ttk.Entry(params, textvariable=self.keep_gold, width=12).pack(side="left")
            ttk.Label(params, text="（5 号用，50 万/张票）", foreground="#888").pack(side="left", padx=2)

            # 停止条件（①天空石 ②金币 ③模式）
            stopbar = ttk.Frame(self, padding=(12, 4))
            stopbar.pack(fill="x")
            try:
                _st2 = load_rules_cfg().get("settings") or {}
            except Exception:  # noqa: BLE001
                _st2 = {}
            self.stop_gold = tk.StringVar(value=str((_st2.get("shop_stop_gold", 1000000))))
            self.stop_mode = tk.StringVar(value=str(_st2.get("shop_stop_mode", "sky")))
            ttk.Label(stopbar, text="① 天空石停止线").pack(side="left")
            self.stone_entry = ttk.Entry(stopbar, textvariable=self.stop_stones, width=10)
            self.stone_entry.pack(side="left", padx=(4, 18))
            ttk.Label(stopbar, text="② 金币停止线").pack(side="left")
            self.gold_entry = ttk.Entry(stopbar, textvariable=self.stop_gold, width=12)
            self.gold_entry.pack(side="left", padx=(4, 18))
            ttk.Label(stopbar, text="③ 停止条件").pack(side="left")
            for _val, _txt in (("sky", "天空石"), ("gold", "金币"), ("either", "任一")):
                ttk.Radiobutton(
                    stopbar, text=_txt, value=_val, variable=self.stop_mode,
                    command=self._on_stop_mode_change,
                ).pack(side="left", padx=(6, 0))
            self._sync_stop_state()

            # 游戏窗口尺寸（锁定到标定过的比例，识别最稳）
            wbar = ttk.Frame(self, padding=(12, 0))
            wbar.pack(fill="x")
            self.win_w = tk.StringVar(value="1819")
            self.win_h = tk.StringVar(value="1023")
            ttk.Label(wbar, text="游戏窗口：").pack(side="left")
            ttk.Entry(wbar, textvariable=self.win_w, width=6).pack(side="left")
            ttk.Label(wbar, text="×").pack(side="left", padx=2)
            ttk.Entry(wbar, textvariable=self.win_h, width=6).pack(side="left")
            ttk.Button(wbar, text="📐 应用尺寸", command=self._apply_window_size).pack(side="left", padx=8)
            ttk.Label(
                wbar, text="（推荐 1819×1023，识别最稳；点一次会自动居中）", foreground="#888"
            ).pack(side="left")


            # 画中画：始终置顶的小窗，实时看游戏画面
            pbar = ttk.Frame(self, padding=(12, 6))
            pbar.pack(fill="x")
            self.pip_on = tk.BooleanVar(value=self._cfg_pip["enabled"])
            self.pip_width = tk.StringVar(value=str(self._cfg_pip["width"]))
            self.pip_fps = tk.StringVar(value=str(int(self._cfg_pip.get("fps", 30))))
            ttk.Checkbutton(
                pbar, text="画中画（置顶小窗看画面）", variable=self.pip_on, command=self._apply_pip
            ).pack(side="left")
            ttk.Label(pbar, text="宽度").pack(side="left", padx=(12, 4))
            ttk.Entry(pbar, textvariable=self.pip_width, width=6).pack(side="left")
            ttk.Label(pbar, text="帧率").pack(side="left", padx=(12, 4))
            ttk.Entry(pbar, textvariable=self.pip_fps, width=5).pack(side="left")
            ttk.Button(pbar, text="应用", command=self._apply_pip).pack(side="left", padx=6)
            ttk.Label(pbar, text="（DWM 合成，几乎不占 CPU）", foreground="#888").pack(side="left")

            # 实时统计（读 debug/统计.jsonl，买一次更新一次）
            sbar = ttk.Frame(self, padding=(12, 2))
            sbar.pack(fill="x")
            self.stats_line = tk.StringVar(value="")
            self._equip_noshow = False
            # 先摆右侧按钮，再让卡片占用剩余宽度，否则按钮会被挤出窗口
            self._gear_analysis_win = None
            ttk.Button(sbar, text="📊 统计", command=self.open_stats).pack(side="right")
            ttk.Button(sbar, text="🎽 红装记录", command=self.open_gear_log).pack(side="right", padx=(0, 8))
            ttk.Button(sbar, text="🔍 装备扫描", command=self.start_equip_scan).pack(side="right", padx=(0, 8))
            ttk.Button(sbar, text="📈 装备分析", command=self._open_gear_analysis).pack(side="right", padx=(0, 6))
            self.stat_cards = prts.StatCards(sbar)
            self.stat_cards.pack(side="left", fill="x", expand=True)

            # 红装自动购买
            gbar = ttk.Frame(self, padding=(12, 2))
            gbar.pack(fill="x")
            lbar = ttk.Frame(self, padding=(12, 4))
            lbar.pack(fill="x")
            tbar = ttk.Frame(self, padding=(12, 4))
            tbar.pack(fill="x")
            self.gear_on = tk.BooleanVar(value=self._cfg_gear["enabled"])
            ttk.Checkbutton(
                gbar, text="自动购买极品红装（85 传说）", variable=self.gear_on, command=self._apply_gear
            ).pack(side="left")
            ttk.Button(gbar, text="详情", command=self.open_gear_detail).pack(side="left", padx=8)
            try:
                _ls = bool((load_rules_cfg().get("settings") or {}).get("low_spec_mode", False))
            except Exception:  # noqa: BLE001
                _ls = False
            self.low_spec_on = tk.BooleanVar(value=_ls)
            ttk.Checkbutton(
                lbar, text="低配降载（推图 / 商店 / 剧场推荐；手操烧魂请勿勾选）",
                variable=self.low_spec_on, command=self._save_low_spec,
            ).pack(side="left", padx=(16, 4))
            self.ghost_on = tk.BooleanVar(value=False)
            ttk.Checkbutton(
                lbar, text="幽灵窗口（点击无效）",
                variable=self.ghost_on, command=self._toggle_ghost,
            ).pack(side="left", padx=(16, 4))
            self.timer_on = tk.BooleanVar(value=False)
            self.timer_min = tk.StringVar(value="120")
            self.close_game_on = tk.BooleanVar(value=False)
            self.shutdown_on = tk.BooleanVar(value=False)
            ttk.Checkbutton(tbar, text="定时停止", variable=self.timer_on).pack(side="left")
            ttk.Entry(tbar, textvariable=self.timer_min, width=6).pack(side="left", padx=(4, 2))
            ttk.Label(tbar, text="分钟").pack(side="left", padx=(0, 14))
            try:
                _st = load_rules_cfg().get("settings") or {}
            except Exception:  # noqa: BLE001
                _st = {}

            ttk.Checkbutton(tbar, text="到点关闭游戏", variable=self.close_game_on).pack(side="left")
            ttk.Checkbutton(tbar, text="到点关机", variable=self.shutdown_on).pack(side="left", padx=(14, 0))

            # 控制
            ctrl = ttk.Frame(self, padding=(12, 8))
            ctrl.pack(fill="x")
            self.action_bar = prts.DualActionBar(ctrl, self.start, self.stop)
            self.action_bar.pack(side="left")
            self.btn_start = prts.BarHandle(self.action_bar, "start")
            self.btn_stop = prts.BarHandle(self.action_bar, "stop")
            self.btn_start.state(["!disabled"])
            self.status = tk.StringVar(value="就绪")
            self.led = prts.StatusLed(ctrl)
            self.led.pack(side="left", padx=16)
            self.status.trace_add("write", lambda *_: self.led.set_status(self.status.get()))
            ttk.Label(
                ctrl, text="运行后：F8 暂停/继续，F10 退出（全局热键）", foreground="#888"
            ).pack(side="right")

            # 日志（默认收起，点右上角「📜 日志」展开；同时写入 debug/运行日志_*.txt）
            self.logbox = ttk.LabelFrame(self, text="运行日志", padding=6)
            self.log_visible = False
            self.log = tk.Text(
                self.logbox, height=24, wrap="none", bg="#101418", fg="#d7e0d7",
                insertbackground="#d7e0d7", font=("Consolas", 9),
            )
            sb = ttk.Scrollbar(self.logbox, command=self.log.yview)
            self.log.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            self.log.pack(side="left", fill="both", expand=True)

            ttk.Label(
                self,
                text="开源免费 · PolyForm Noncommercial 1.0.0 · 禁止商用/倒卖",
                style="Sub.TLabel",
            ).pack(fill="x", padx=12, pady=(0, 8))

            self._pip = None
            try:
                from pipwin import PiPWindow

                self._pip = PiPWindow(self, width=self._cfg_pip["width"], fps=self._cfg_pip.get("fps", 30))
                if self.pip_on.get():
                    self._pip.start()
            except Exception:  # noqa: BLE001
                self._pip = None

            # 画中画双客户端提示（11-14）：开了画中画时，MuMu 与 Steam 版第七史诗同时运行则提醒退出 Steam 版
            self._dual_warned = False
            self._dual_noshow = False
            self._dual_after = None

            self._update_info: dict | None = None
            self._stats_after = self.after(1000, self._tick_stats)
            self.after(1500, self._auto_check)
            self.after(4000, self._poll_dual_clients)

            self.protocol("WM_DELETE_WINDOW", self.on_close)
            self.bind_all("<Control-Shift-D>", lambda _e: self.open_devlog())
            self.bind_all("<Control-Shift-A>", lambda _e: self._switch_devlog("ai"))
            self._on_mode_change()
            self.after(2500, self._auto_fit_window)
            self._start_capture_hotkey()

        # ---------- 交互 ----------
        def _on_mode_change(self) -> None:
            mode = self.mode_var.get()
            st = "normal" if mode in ("shop", "chain") else "disabled"
            self.stop_entry_state = st

        def _auto_fit_window(self) -> None:
            """程序启动后自动把游戏窗口调成标定尺寸（找不到窗口或模拟器模式就静默跳过）。"""
            try:
                from core import EMULATOR_INFO, find_game_window

                if find_game_window() and not EMULATOR_INFO:
                    self._apply_window_size()
            except Exception:  # noqa: BLE001
                pass

        def _start_capture_hotkey(self) -> None:
            """F9 全局截屏：把当前游戏画面存到 debug\\probe，文件名带时间戳。"""
            import threading
            import time as _t

            try:
                import ctypes

                import cv2
                import numpy as np

                from core import GameWindow, find_game_window, runtime_root

                user32 = ctypes.windll.user32
            except Exception:  # noqa: BLE001
                return

            def _loop() -> None:
                prev = False
                while True:
                    try:
                        down = bool(user32.GetAsyncKeyState(0x78) & 0x8000)  # VK_F9
                        if down and not prev:
                            hwnd = find_game_window()
                            if hwnd:
                                win = GameWindow(hwnd)
                                img = win.capture()
                                if img is not None:
                                    d = runtime_root() / "debug" / "probe"
                                    d.mkdir(parents=True, exist_ok=True)
                                    f = d / f"shot_{_t.strftime('%m%d_%H%M%S')}.png"
                                    ok, buf = cv2.imencode(".png", img)
                                    if ok:
                                        buf.tofile(str(f))
                        prev = down
                    except Exception:  # noqa: BLE001
                        prev = False
                    _t.sleep(0.05)

            threading.Thread(target=_loop, daemon=True).start()

        def _apply_window_size(self) -> None:
            """把游戏窗口客户区调整到用户指定尺寸（默认 1819x1023，标定过的比例）。"""
            try:
                from core import EMULATOR_INFO, find_game_window, resize_game_window

                w = int(float(self.win_w.get()))
                h = int(float(self.win_h.get()))
                if not (800 <= w <= 3840 and 600 <= h <= 2160):
                    self.status.set("尺寸超出范围")
                    return
                hwnd = find_game_window()
                if not hwnd:
                    self.status.set("没找到游戏窗口")
                    return
                if EMULATOR_INFO:
                    self.status.set("模拟器模式：不改窗口尺寸")
                    return
                got = resize_game_window(hwnd, w, h)
                self.status.set(f"窗口已设为 {got[0]}×{got[1]}" if got else "尺寸设置失败")
                if getattr(self, "ghost_on", None) and self.ghost_on.get():
                    import ghostwin

                    ok2, msg2 = ghostwin.enable(hwnd)
                    if not ok2:
                        self.ghost_on.set(False)
                        self.status.set(f"幽灵窗口：{msg2}")
            except Exception as exc:  # noqa: BLE001
                self.status.set(f"尺寸设置失败：{exc}")
                pass

        def _apply_pip(self) -> None:
            on = bool(self.pip_on.get())
            try:
                width = int(float(self.pip_width.get()))
            except Exception:  # noqa: BLE001
                width = 1080
            width = max(240, min(1600, width))
            try:
                fps = float(self.pip_fps.get())
            except Exception:  # noqa: BLE001
                fps = 30.0
            fps = max(1.0, min(30.0, fps))
            if self._pip is not None:
                self._pip.set_width(width)
                self._pip.set_fps(fps)
                if on and not self._pip.enabled:
                    self._pip.start()
                elif not on and self._pip.enabled:
                    self._pip.stop()
            self._save_pip_cfg(on, width, fps)

        def _save_pip_cfg(self, enabled: bool, width: int, fps: float = 30.0) -> None:
            try:
                import yaml

                from core import runtime_root

                path = runtime_root() / "rules.yaml"
                cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                st = cfg.setdefault("settings", {})
                st["pip_enabled"] = bool(enabled)
                st["pip_width"] = int(width)
                st["pip_fps"] = float(fps)
                path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass

        def _poll_dual_clients(self) -> None:
            """每 5 秒只读检测一次双客户端状态（不碰游戏、不影响自动化子进程）。"""
            try:
                self._check_dual_clients()
            except Exception:  # noqa: BLE001
                pass
            try:
                self._dual_after = self.after(5000, self._poll_dual_clients)
            except Exception:  # noqa: BLE001
                self._dual_after = None

        def _check_dual_clients(self) -> None:
            pip = getattr(self, "_pip", None)
            pip_enabled = bool(pip is not None and getattr(pip, "enabled", False))
            steam_hwnd = None
            emu_hwnds: list[int] = []
            if pip_enabled:
                try:
                    from pipwin import detect_dual_clients

                    steam_hwnd, emu_hwnds = detect_dual_clients()
                except Exception:  # noqa: BLE001
                    steam_hwnd, emu_hwnds = None, []
            show, self._dual_warned = dual_client_warning_decision(
                warned=bool(getattr(self, "_dual_warned", False)),
                noshow=bool(getattr(self, "_dual_noshow", False)),
                pip_enabled=pip_enabled,
                steam_hwnd=steam_hwnd,
                emu_hwnds=emu_hwnds,
            )
            if show:
                self._show_dual_client_warning()

        def _show_dual_client_warning(self) -> None:
            win = tk.Toplevel(self)
            win.title("提示")
            win.attributes("-topmost", True)
            win.resizable(False, False)
            body = ttk.Frame(win, padding=16)
            body.pack(fill="both", expand=True)
            ttk.Label(
                body,
                text="请退出steam版第七史诗以保证模拟器画中画能正常抓取!",
                wraplength=420,
                justify="left",
            ).pack(anchor="w")
            no_show = tk.BooleanVar(value=False)
            ttk.Checkbutton(body, text="本次运行不再提示", variable=no_show).pack(anchor="w", pady=(12, 0))

            def _close() -> None:
                if bool(no_show.get()):
                    self._dual_noshow = True
                try:
                    win.destroy()
                except Exception:  # noqa: BLE001
                    pass

            ttk.Button(body, text="确定", width=10, command=_close).pack(anchor="e", pady=(12, 0))
            win.protocol("WM_DELETE_WINDOW", _close)
            try:
                self.update_idletasks()
                x = self.winfo_rootx() + max(0, (self.winfo_width() - 480) // 2)
                y = self.winfo_rooty() + max(0, (self.winfo_height() - 220) // 2)
                win.geometry(f"+{x}+{y}")
            except Exception:  # noqa: BLE001
                pass

        def _apply_gear(self) -> None:
            self._save_gear_cfg(enabled=bool(self.gear_on.get()), **{
                "score27": self._cfg_gear["score27"],
                "speed3": self._cfg_gear["speed3"],
                "combo": self._cfg_gear["combo"],
            })

        def _save_gear_cfg(self, enabled: bool | None = None, score27=None, speed3=None, combo=None) -> None:
            try:
                import yaml

                from core import runtime_root

                path = runtime_root() / "rules.yaml"
                cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                st = cfg.setdefault("settings", {})
                if enabled is not None:
                    st["gear_auto_buy"] = bool(enabled)
                    self._cfg_gear["enabled"] = bool(enabled)
                if score27 is not None:
                    st["gear_cond_score27"] = bool(score27)
                    self._cfg_gear["score27"] = bool(score27)
                if speed3 is not None:
                    st["gear_cond_speed3"] = bool(speed3)
                    self._cfg_gear["speed3"] = bool(speed3)
                if combo is not None:
                    st["gear_cond_combo"] = bool(combo)
                    self._cfg_gear["combo"] = bool(combo)
                path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass

        def open_gear_detail(self) -> None:
            win = tk.Toplevel(self)
            win.title("红装购买条件")
            win.geometry("420x300")
            ttk.Label(win, text="满足任一勾选条件即购买：", padding=8).pack(anchor="w")
            v1 = tk.BooleanVar(value=self._cfg_gear["score27"])
            v2 = tk.BooleanVar(value=self._cfg_gear["speed3"])
            v3 = tk.BooleanVar(value=self._cfg_gear["combo"])
            ttk.Checkbutton(win, text="装备分数 ≥ 27", variable=v1).pack(anchor="w", padx=24)
            ttk.Checkbutton(win, text="速度 ≥ 3", variable=v2).pack(anchor="w", padx=24)
            ttk.Checkbutton(win, text="同时拥有「暴击伤害 / 暴击 / 速度」三条词条", variable=v3).pack(anchor="w", padx=24)
            ttk.Label(win, text="价格只认 1,400,000 金币", padding=8).pack(anchor="w")
            ttk.Label(
                win,
                text="说明：只对 85 级「传说（红）」装备生效；\n识别不确定时一律不买。",
                foreground="#666",
                padding=(24, 0),
            ).pack(anchor="w")

            def save() -> None:
                self._save_gear_cfg(score27=v1.get(), speed3=v2.get(), combo=v3.get())
                win.destroy()

            ttk.Button(win, text="保存", command=save).pack(pady=12)

        def _tick_stats(self) -> None:
            try:
                import stats as stats_mod

                t = stats_mod.session_totals(stats_mod.load_events())
                self.stats_line.set(
                    f"圣约 +{t['covenant']:,} | 神秘 +{t['mystic']:,} | "
                    f"天空石 -{t['sky']:,} | 金币 -{t['gold']:,} | 刷新 {t['refresh']} 次"
                )
                self.stat_cards.update_values(t)
            except Exception:  # noqa: BLE001
                pass
            try:
                self._stats_after = self.after(1000, self._tick_stats)
            except Exception:  # noqa: BLE001
                pass

        def start_equip_scan(self) -> None:
            """装备扫描（P1）：与自动化互斥；先弹准备引导，再用子进程跑 equip_scan.py。"""
            if self.proc and self.proc.poll() is None:
                messagebox.showinfo("提示", "请先停止当前运行中的功能，再开始装备扫描。", parent=self)
                return

            if not self._equip_noshow:
                dlg = tk.Toplevel(self)
                dlg.title("准备开始扫描")
                dlg.attributes("-topmost", True)
                dlg.resizable(False, False)
                dlg.grab_set()
                body = ttk.Frame(dlg, padding=16)
                body.pack(fill="both", expand=True)
                ttk.Label(
                    body,
                    text=(
                        "请先在游戏内打开装备背包，并在「全部」列表点选「最大强化」排序（降序）。\n"
                        "确认后开始扫描，只扫描 +15 装备，其余自动跳过。"
                    ),
                    wraplength=400,
                    justify="left",
                ).pack(anchor="w")
                noshow_var = tk.BooleanVar(value=False)
                ttk.Checkbutton(body, text="本次登录不再提醒", variable=noshow_var).pack(anchor="w", pady=(10, 0))
                confirmed = {"ok": False}

                def _go() -> None:
                    if noshow_var.get():
                        self._equip_noshow = True
                    confirmed["ok"] = True
                    dlg.destroy()

                btns = ttk.Frame(body)
                btns.pack(anchor="e", pady=(12, 0))
                ttk.Button(btns, text="取消", command=dlg.destroy).pack(side="left", padx=(0, 8))
                ttk.Button(btns, text="确认开始扫描", command=_go).pack(side="left")
                self.wait_window(dlg)
                if not confirmed["ok"]:
                    return

            self.log.delete("1.0", "end")
            self.status.set("装备扫描中…（F8 暂停 / F10 停止）")
            self.btn_start.state(["disabled"])
            self.btn_stop.state(["!disabled"])
            env = os.environ.copy()
            env.setdefault("PYTHONIOENCODING", "utf-8")
            cmd = (
                [sys.executable, "--run", "equip_scan.py"]
                if getattr(sys, "frozen", False)
                else [sys.executable, "equip_scan.py"]
            )
            try:
                self.proc = subprocess.Popen(
                    cmd, cwd=str(self.work), env=env,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace",
                )
            except Exception as exc:  # noqa: BLE001
                self._finish(f"启动失败：{exc}")
                messagebox.showerror("启动失败", str(exc))
                return
            threading.Thread(target=self._pump, daemon=True).start()

        def open_gear_log(self) -> None:
            try:
                from gear_ui import GearWindow

                GearWindow(self)
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("红装记录", f"打不开红装记录：{exc}")

        def open_stats(self) -> None:
            try:
                from stats_ui import StatsWindow

                StatsWindow(self)
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("统计窗口", f"打不开统计窗口：{exc}")

        def _open_gear_analysis(self) -> None:
            win = getattr(self, "_gear_analysis_win", None)
            if win is not None:
                try:
                    if win.winfo_exists():
                        win.deiconify()
                        win.lift()
                        win.focus_force()
                        return
                except Exception:  # noqa: BLE001
                    self._gear_analysis_win = None
            err_title = "装备分析看板"
            err_tpl = "打不开装备分析窗口：{exc}"
            try:
                from gear_analysis_ui import UI_TEXTS, GearAnalysisWindow

                err_title = UI_TEXTS["title"]
                err_tpl = UI_TEXTS["open_error"]
                self._gear_analysis_win = GearAnalysisWindow(self)
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror(err_title, err_tpl.format(exc=exc), parent=self)

        def open_donate(self) -> None:
            """打开项目主页（README 底部有微信赞赏码，完全自愿）。"""
            try:
                from version import DONATE_URL

                webbrowser.open(DONATE_URL)
            except Exception:  # noqa: BLE001
                pass

        def open_dir(self) -> None:
            try:
                os.startfile(str(self.work))  # noqa: S606
            except Exception:  # noqa: BLE001
                pass

        def _auto_check(self) -> None:
            threading.Thread(target=self._do_check, args=(True,), daemon=True).start()

        def _do_check(self, silent: bool) -> None:
            try:
                from updater import check_update

                info = check_update()
            except Exception:  # noqa: BLE001
                info = None
            self.after(0, lambda: self._on_update_result(info, silent))

        def _on_update_result(self, info: dict | None, silent: bool) -> None:
            if info:
                self._update_info = info
                self.update_btn.configure(text=f"🆕 新版本 v{info['version']}")
                if not silent:
                    msg = f"发现新版本 v{info['version']}" + (f"\n\n{info['notes']}" if info.get("notes") else "")
                    if messagebox.askyesno("发现新版本", msg + "\n\n现在打开下载页吗？"):
                        webbrowser.open(info["download"])
            elif not silent:
                self.update_btn.configure(text="🔄 检查更新")
                messagebox.showinfo("检查更新", f"当前已是最新版本 v{VERSION}。")

        def check_update_click(self) -> None:
            if self._update_info:
                # 多源：挑第一个可用的下载地址（都不可用时用第一个，浏览器自己处理）
                urls = self._update_info.get("downloads") or [self._update_info.get("download")]
                target = urls[0]
                try:
                    from updater import pick_download_url

                    target = pick_download_url([u for u in urls if u])
                except Exception:  # noqa: BLE001
                    pass
                webbrowser.open(target)
                return
            self.update_btn.configure(text="🔄 检查中…")
            threading.Thread(target=self._do_check, args=(False,), daemon=True).start()

        def toggle_theme(self) -> None:
            """浅色（构成主义）/ 夜间深色 切换"""
            name = "dark" if prts.MODE["name"] == "light" else "light"
            prts.set_theme(name)
            prts.enable_dark_titlebar(self, dark=(name == "dark"))
            self.theme_btn.configure(text="☀ 日间" if name == "dark" else "☾ 夜间")
            try:
                self.banner._render()
                self.stat_cards.retint()
                self.led._paint(self.status.get())
                self.log.configure(bg=prts.C["log_bg"], fg=prts.C["ink"], insertbackground=prts.C["ink"])
            except Exception:  # noqa: BLE001
                pass

        def toggle_log(self) -> None:
            if self.log_visible:
                self.logbox.pack_forget()
                self.geometry("1200x780")
            else:
                self.logbox.pack(fill="both", expand=True, padx=12, pady=(0, 12))
                self.geometry("1200x980")
            self.log_visible = not self.log_visible

        def show_about(self) -> None:
            win = tk.Toplevel(self)
            win.title("关于")
            win.geometry("580x400")
            win.transient(self)
            ttk.Label(
                win, text=f"{APP_NAME}  v{VERSION}", font=("Microsoft YaHei UI", 14, "bold")
            ).pack(pady=(18, 6))
            ttk.Label(
                win,
                text=(
                    "许可证：PolyForm Noncommercial 1.0.0\n"
                    "允许个人使用、修改与非营利分享；禁止任何商业使用。\n\n"
                    "实现方式：窗口截图 + 离线 OCR + 模拟鼠标点击。\n"
                    "不读取游戏内存、不修改游戏文件、不绕过反作弊。\n\n"
                    "仅供学习交流，使用风险自负。\n\n"
                    f"构建日期：{BUILD_DATE}"
                ),
                justify="left",
            ).pack(pady=14, padx=22, anchor="w")
            ttk.Button(win, text="关闭", command=win.destroy).pack(side="bottom", pady=12)

        def _build_args(self, mode: str) -> list[str]:
            if mode == "shop":
                return ["shop.py", "--stop", self._num(self.stop_stones.get(), "2000")]
            if mode == "chain":
                return ["main.py", "--chain", "--stop", self._num(self.stop_stones.get(), "2000")]
            if mode == "theater":
                return ["main.py", "--theater", "--keep-gold", self._num(self.keep_gold.get(), "1000000")]
            flag = "--auto" if mode == "auto" else "--brieg"
            return ["main.py", flag]

        @staticmethod
        def _num(value: str, default: str) -> str:
            v = "".join(ch for ch in value if ch.isdigit())
            return v or default

        # ---------- 进程 ----------
        def start(self) -> None:
            if self.proc and self.proc.poll() is None:
                return
            mode = self.mode_var.get()
            args = self._build_args(mode) + ["--no-elevate"]
            self.log.delete("1.0", "end")
            try:
                debug_dir = self.work / "debug"
                debug_dir.mkdir(exist_ok=True)
                self._logpath = debug_dir / f"运行日志_{time.strftime('%Y%m%d_%H%M%S')}.txt"
                self._logfh = open(self._logpath, "w", encoding="utf-8", buffering=1)
                # 让主窗口对屏幕抓图隐身（WDA_EXCLUDEFROMCAPTURE），避免黑场回退时拍到自己
                try:
                    import ctypes as _ct

                    _hwnd = _ct.windll.user32.GetParent(self.winfo_id()) or self.winfo_id()
                    _ct.windll.user32.SetWindowDisplayAffinity(_hwnd, 0x00000011)
                except Exception:  # noqa: BLE001
                    pass
            except Exception:  # noqa: BLE001
                self._logfh = None
                self._logpath = None
            self.log.insert(
                "end",
                "本软件免费开源（PolyForm Noncommercial 1.0.0）：禁止商用/倒卖；"
                "如你是付费购买，请申请退款并举报卖家。\n",
            )
            self.status.set("运行中…（请勿最小化游戏窗口）")
            try:
                from datetime import datetime as _dt

                from core import runtime_root as _rr

                _d = _rr() / "debug"
                _d.mkdir(parents=True, exist_ok=True)
                _tag = _dt.now().strftime("%Y%m%d")
                _sep = f"===== 新一局 {_dt.now():%H:%M:%S} ====="
                for _prefix in ("AI战斗日志", "战斗解读"):
                    _f = _d / f"{_prefix}_{_tag}.txt"
                    with _f.open("a", encoding="utf-8") as _fp:
                        _fp.write(_sep + "\n")
            except Exception:  # noqa: BLE001
                pass
            try:
                self._apply_window_size()
            except Exception:  # noqa: BLE001
                pass
            try:
                if getattr(self, "timer_on", None) and self.timer_on.get():
                    self._schedule_timer()
            except Exception:  # noqa: BLE001
                pass
            try:
                if getattr(self, "ghost_on", None) and self.ghost_on.get():
                    from core import find_game_window
                    import ghostwin

                    ok, msg = ghostwin.enable(find_game_window() or 0)
                    if not ok:
                        self.ghost_on.set(False)
                        self.status.set(f"幽灵窗口未开启：{msg}")
            except Exception as exc:  # noqa: BLE001
                self.status.set(f"幽灵窗口异常：{exc}")
            self.btn_start.state(["disabled"])
            self.btn_stop.state(["!disabled"])
            env = os.environ.copy()
            env.setdefault("PYTHONIOENCODING", "utf-8")
            try:
                env["E7PILOT_LOW_SPEC"] = "1" if getattr(self, "low_spec_on", None) and self.low_spec_on.get() else "0"
            except Exception:  # noqa: BLE001
                pass
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, "--run", *args]
            else:
                cmd = [sys.executable, *args]
            try:
                self.proc = subprocess.Popen(
                    cmd, cwd=str(self.work), env=env,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace",
                )
            except Exception as e:  # noqa: BLE001
                self._finish(f"启动失败：{e}")
                messagebox.showerror("启动失败", str(e))
                return
            threading.Thread(target=self._pump, daemon=True).start()

        def _pump(self) -> None:
            assert self.proc is not None and self.proc.stdout is not None
            for line in self.proc.stdout:
                self._append(line.rstrip("\n"))
            code = self.proc.wait()
            self._finish(f"已结束（退出码 {code}）")

        def _toggle_ghost(self) -> None:
            """勾选立刻生效（不要求脚本已启动），并总是给出状态反馈。"""
            try:
                import ghostwin
                from core import find_game_window

                hwnd = find_game_window() or 0
                if not self.ghost_on.get():
                    ghostwin.disable(hwnd)
                    self.status.set("幽灵窗口：已关闭")
                    return
                if not hwnd:
                    self.ghost_on.set(False)
                    self.status.set("幽灵窗口：没找到游戏窗口")
                    return
                ok, msg = ghostwin.enable(hwnd)
                if not ok:
                    self.ghost_on.set(False)
                self.status.set(f"幽灵窗口：{msg}")
            except Exception as exc:  # noqa: BLE001
                self.ghost_on.set(False)
                self.status.set(f"幽灵窗口异常：{exc}")

        def _schedule_timer(self) -> None:
            """按「定时停止」设置调度；分钟数非法则不启用。"""
            self._cancel_timer()
            try:
                minutes = float(self.timer_min.get().strip())
            except Exception:  # noqa: BLE001
                self.status.set("定时间隔无效")
                return
            if minutes <= 0:
                return
            if getattr(self, "shutdown_on", None) and self.shutdown_on.get():
                if not messagebox.askyesno("确认", f"将在 {minutes:.0f} 分钟后关机，继续？", parent=self):
                    self.shutdown_on.set(False)
                    return
            self._timer_job = self.after(int(minutes * 60000), self._timer_fire)

        def _cancel_timer(self) -> None:
            job = getattr(self, "_timer_job", None)
            if job:
                try:
                    self.after_cancel(job)
                except Exception:  # noqa: BLE001
                    pass
            self._timer_job = None

        def _timer_fire(self) -> None:
            self._timer_job = None
            try:
                self.stop()
            except Exception:  # noqa: BLE001
                pass
            try:
                if getattr(self, "close_game_on", None) and self.close_game_on.get():
                    from core import find_game_window

                    hwnd = find_game_window()
                    if hwnd:
                        import win32con
                        import win32gui

                        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                        self.status.set("定时到：已请求关闭游戏")
            except Exception:  # noqa: BLE001
                pass
            if getattr(self, "shutdown_on", None) and self.shutdown_on.get():
                self._countdown_shutdown()

        def _countdown_shutdown(self) -> None:
            """60 秒倒计时关机，可取消。"""
            win = tk.Toplevel(self)
            win.title("即将关机")
            win.geometry("360x150")
            win.attributes("-topmost", True)
            lab = ttk.Label(win, text="", font=("Microsoft YaHei UI", 12, "bold"))
            lab.pack(pady=18)
            state = {"n": 60, "job": None}

            def cancel() -> None:
                if state["job"]:
                    try:
                        self.after_cancel(state["job"])
                    except Exception:  # noqa: BLE001
                        pass
                try:
                    import subprocess

                    subprocess.run(["shutdown", "/a"], creationflags=0x08000000, check=False)
                except Exception:  # noqa: BLE001
                    pass
                win.destroy()

            def tick() -> None:
                if state["n"] <= 0:
                    try:
                        import subprocess

                        subprocess.run(["shutdown", "/s", "/t", "0"], creationflags=0x08000000, check=False)
                    except Exception:  # noqa: BLE001
                        pass
                    win.destroy()
                    return
                lab.configure(text=f"{state['n']} 秒后关机")
                state["n"] -= 1
                state["job"] = self.after(1000, tick)

            ttk.Button(win, text="取消关机", command=cancel).pack()
            win.protocol("WM_DELETE_WINDOW", cancel)
            tick()

        def _switch_devlog(self, kind: str) -> None:
            """切换实时日志：user=中文解读，ai=AI 日志。"""
            self._devlog_kind = kind
            if getattr(self, "_devlog_win", None) is not None:
                try:
                    self._devlog_win.destroy()
                except Exception:  # noqa: BLE001
                    pass
                self._devlog_win = None
                self.open_devlog()

        def open_devlog(self) -> None:
            """隐藏的开发者日志窗口（Ctrl+Shift+D）：实时 tail 战斗决策文件。"""
            if getattr(self, "_devlog_win", None) is not None:
                try:
                    self._devlog_win.lift()
                    return
                except Exception:  # noqa: BLE001
                    self._devlog_win = None

            from datetime import datetime as _dt

            win = tk.Toplevel(self)
            win.title("开发者日志（勿外传）")
            win.geometry("760x420+0+0")
            win.attributes("-topmost", False)
            win.update_idletasks()
            try:
                import ctypes as _ct

                _h = _ct.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
                _ct.windll.user32.SetWindowDisplayAffinity(_h, 0x00000011)
            except Exception:  # noqa: BLE001
                pass
            txt = tk.Text(win, wrap="none", bg="#101216", fg="#D8DEE9", font=("Consolas", 10))
            txt.pack(fill="both", expand=True)
            self._devlog_win = win
            state = {"pos": -1, "path": None}

            def _path() -> Path:
                from core import runtime_root

                name = getattr(self, "_devlog_kind", "user")
                prefix = "AI战斗日志" if name == "ai" else "战斗解读"
                return runtime_root() / "debug" / f"{prefix}_{_dt.now():%Y%m%d}.txt"

            def _tick() -> None:
                if not win.winfo_exists():
                    self._devlog_win = None
                    return
                try:
                    f = _path()
                    if state["path"] != str(f):
                        state["path"] = str(f)
                        state["pos"] = f.stat().st_size if f.exists() else 0
                        txt.delete("1.0", "end")
                    if f.exists():
                        with f.open("r", encoding="utf-8", errors="ignore") as fp:
                            fp.seek(state["pos"])
                            chunk = fp.read()
                            state["pos"] = fp.tell()
                        if chunk:
                            txt.insert("end", chunk)
                            txt.see("end")
                except Exception:  # noqa: BLE001
                    pass
                self.after(500, _tick)

            _tick()

        def _sync_stop_state(self) -> None:
            """按停止条件禁用无关输入框：天空石/金币互斥，任一都可填。"""
            mode = self.stop_mode.get()
            try:
                self.stone_entry.configure(state=("disabled" if mode == "gold" else "normal"))
                self.gold_entry.configure(state=("disabled" if mode == "sky" else "normal"))
            except Exception:  # noqa: BLE001
                pass

        def _on_stop_mode_change(self) -> None:
            self._sync_stop_state()
            self._save_stop_cfg()

        def _save_stop_cfg(self) -> None:
            """保存金币停止线与停止模式到 rules.yaml。"""
            try:
                import yaml as _yaml

                from core import runtime_root as _rr

                p = _rr() / "rules.yaml"
                raw = _yaml.safe_load(p.read_text(encoding="utf-8")) or {}
                st = raw.setdefault("settings", {})
                try:
                    st["stop_skystones"] = max(0, int(self.stop_stones.get().strip() or 0))
                except Exception:  # noqa: BLE001
                    st["stop_skystones"] = 2000
                try:
                    st["shop_stop_gold"] = max(0, int(self.stop_gold.get().strip() or 0))
                except Exception:  # noqa: BLE001
                    st["shop_stop_gold"] = 1000000
                st["shop_stop_mode"] = self.stop_mode.get() or "sky"
                p.write_text(_yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
                self.status.set(f"停止条件已保存：{st['shop_stop_mode']} / 金币 {st['shop_stop_gold']:,}")
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("停止条件", f"保存失败：{exc}")

        def _save_low_spec(self) -> None:
            """低配模式写入 rules.yaml（下次启动仍生效）。"""
            try:
                import yaml as _yaml

                from core import runtime_root as _rr

                p = _rr() / "rules.yaml"
                raw = _yaml.safe_load(p.read_text(encoding="utf-8")) or {}
                raw.setdefault("settings", {})["low_spec_mode"] = bool(self.low_spec_on.get())
                p.write_text(_yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
                self.status.set("低配模式已保存（重启脚本生效）")
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("低配模式", f"保存失败：{exc}")

        def _append(self, text: str) -> None:
            self.log.insert("end", text + "\n")
            # 挂机久了日志会无限增长：超过 800 行裁掉最旧的 300 行
            try:
                if int(self.log.index("end-1c").split(".")[0]) > 800:
                    self.log.delete("1.0", "300.0")
            except Exception:  # noqa: BLE001
                pass
            if self.log_visible:
                self.log.see("end")
            if getattr(self, "_logfh", None):
                try:
                    self._logfh.write(text + "\n")
                    self._logfh.flush()
                except Exception:  # noqa: BLE001
                    pass

        def _finish(self, msg: str) -> None:
            if getattr(self, "_logfh", None):
                try:
                    self._logfh.close()
                except Exception:  # noqa: BLE001
                    pass
                self._logfh = None
            self.status.set(msg)
            self.btn_start.state(["!disabled"])
            self.btn_stop.state(["disabled"])

        def stop(self) -> None:
            try:
                import ghostwin
                from core import find_game_window

                ghostwin.disable(find_game_window() or 0)
                if getattr(self, "ghost_on", None):
                    self.ghost_on.set(False)
            except Exception:  # noqa: BLE001
                pass
            if self.proc and self.proc.poll() is None:
                try:
                    self.proc.terminate()
                except Exception:  # noqa: BLE001
                    pass
                self.status.set("已停止")
            try:
                self._cancel_timer()
            except Exception:  # noqa: BLE001
                pass
            try:
                import ghostwin

                ghostwin.disable()
            except Exception:  # noqa: BLE001
                pass

        def on_close(self) -> None:
            try:
                import ghostwin

                ghostwin.disable()
            except Exception:  # noqa: BLE001
                pass
            try:
                if self._pip is not None:
                    self._pip.stop()
            except Exception:  # noqa: BLE001
                pass
            try:
                if self._dual_after is not None:
                    self.after_cancel(self._dual_after)
                    self._dual_after = None
            except Exception:  # noqa: BLE001
                pass
            self.stop()
            self.destroy()

    App().mainloop()
    return 0


def main() -> int:
    if "--ghost-watch" in sys.argv:
        # 看门狗子进程：主进程退出后还原窗口样式
        try:
            i = sys.argv.index("--ghost-watch")
            import ghostwin

            ghostwin.run_watchdog(int(sys.argv[i + 1]), int(sys.argv[i + 2]), int(sys.argv[i + 3]))
        except Exception:  # noqa: BLE001
            pass
        return 0
    if "--check-update" in sys.argv:
        from updater import check_update

        info = check_update()
        print(json.dumps(info, ensure_ascii=False) if info else "已是最新版本")
        return 0 if not info else 10
    if "--version" in sys.argv or "-V" in sys.argv:
        print(f"{APP_NAME} v{VERSION} ({BUILD_DATE})")
        print("License: PolyForm Noncommercial 1.0.0（禁止商用/倒卖）")
        return 0
    if "--run" in sys.argv:
        i = sys.argv.index("--run")
        return run_cli(sys.argv[i + 1 :])
    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
