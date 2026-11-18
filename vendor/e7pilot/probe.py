"""素材采集与诊断工具：自动截取游戏画面并标注识别结果到 debug/probe/ 文件夹。

当你遇到某个新弹窗、战败画面或未识别按钮时，双击 probe.bat（或 采集新界面_probe.bat）即可每 3 秒自动保存截图与文字供校正。
热键：F10 停止采集
"""
from __future__ import annotations

import argparse
import ctypes
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import win32gui
import yaml

from combat import BriegSimpleCombatController
from core import (
    GameWindow,
    Ocr,
    check_team_auto_switch,
    detect_quest_compass,
    find_game_window,
    has_battle_hud,
    has_labyrinth_hud,
    open_game_window,
    is_admin,
    runtime_root,
)
from main import Rule, analyze_frame, norm

ROOT = runtime_root()
OUT = ROOT / "debug" / "probe"
VK_F10 = 0x79


def ensure_utf8_console() -> None:
    try:
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleTitleW("第七史诗 新界面采集工具 [每3秒自动截图 | 按 F10 或关窗口结束]")
    except Exception:  # noqa: BLE001
        pass
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass


def try_elevate() -> bool:
    """若当前非管理员，自动弹出 Windows UAC 提权运行新窗口。"""
    if is_admin() or "--no-elevate" in sys.argv or "--elevated" in sys.argv:
        return False
    script = str(Path(__file__).resolve())
    py_flags = ("-s " if sys.flags.no_user_site else "") + ("-E " if sys.flags.ignore_environment else "")
    extra_args = " ".join(f'"{a}"' for a in sys.argv[1:])
    params = f'{py_flags}"{script}" --elevated {extra_args}'.strip()
    ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, str(ROOT), 1)
    return int(ret) > 32


def snap(
    win: GameWindow,
    ocr: Ocr,
    method: str,
    cfg: dict | None,
    count: int,
    combat_ctrl: BriegSimpleCombatController | None = None,
) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    img = win.capture(method)
    h, w = img.shape[:2]
    items = ocr.read(img, min_score=0.4, min_brightness=0)
    bright_items = ocr.read(img, min_score=0.55, min_brightness=95.0)
    stamp = datetime.now().strftime("%m%d_%H%M%S")

    vis = img.copy()
    for it in items:
        cv2.rectangle(vis, it.box[:2], it.box[2:], (0, 0, 255), 2)

    in_labyrinth = has_labyrinth_hud(img, bright_items)
    compass = detect_quest_compass(img) if in_labyrinth else None
    in_battle = has_battle_hud(img, bright_items)
    team_auto = check_team_auto_switch(img, bright_items)

    decision_str = "未加载规则"
    if cfg is not None:
        s = cfg.get("settings", {})
        rules = [Rule(**r) for r in cfg.get("rules", [])]
        g_forbid = [norm(x) for x in cfg.get("global_forbid", [])]
        max_len = int(s.get("default_max_len", 8))
        manual = bool(s.get("manual_combat", True))
        res = analyze_frame(
            img,
            bright_items,
            rules,
            g_forbid,
            max_len,
            enable_auto_check=bool(s.get("enable_auto_battle_check", True)),
            manual_combat=manual,
            combat_ctrl=combat_ctrl,
        )
        decision_str = f"{res['type']} -> {res.get('desc') or res.get('reason') or '无匹配规则'}"

    if compass is not None:
        _label, (rx, ry), _score = compass
        cv2.circle(vis, (int(w * rx), int(h * ry)), 28, (0, 255, 0), 3)

    cv2.imencode(".png", img)[1].tofile(str(OUT / f"shot_{stamp}.png"))
    cv2.imencode(".png", vis)[1].tofile(str(OUT / f"shot_{stamp}_ocr.png"))

    summary_lines = [
        f"window={w}x{h}  in_battle_hud={in_battle}  compass={compass}  team_auto={team_auto}",
        f"current_rule_decision={decision_str}",
    ]
    print(
        f"[第 {count} 张 | {stamp}] 窗口 {w}x{h} | 识别到 {len(items)} 段文字 | 当前判定：{decision_str}"
    )
    print(f"   ✅ 已保存到：debug\\probe\\shot_{stamp}.png")
    for it in items:
        cx, cy = it.center
        line = f"   [{it.score:.2f}] ({cx/w:.3f}, {cy/h:.3f}) {it.text!r}"
        print(line)
        summary_lines.append(line)

    (OUT / f"shot_{stamp}.txt").write_text("\n".join(summary_lines), encoding="utf-8")


def _run_probe() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=float, default=3.0)
    ap.add_argument("--once", action="store_true", help="只截一张图就退出")
    ap.add_argument("--method", default="auto", choices=["auto", "printwindow", "screen"])
    ap.add_argument("--elevated", action="store_true")
    ap.add_argument("--no-elevate", action="store_true")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    print("=" * 64)
    print("  📸 第七史诗 新界面素材采集工具 (Probe)")
    print(f"  图片自动保存目录：{OUT}")
    print("  使用方法：保持游戏在你想识别的界面，看到「✅ 已保存」后")
    print("            按【F10】键或直接点右上角 × 关闭窗口即可！")
    print("=" * 64)

    win = open_game_window("foreground")
    if win is None:
        print("\n❌ 未找到《第七史诗》窗口！请先从 Steam 启动游戏，或让 MuMu 模拟器进入游戏。")
        return 1
    if win.is_minimized():
        win.activate()
    _title = win32gui.GetWindowText(win.hwnd) if getattr(win, "hwnd", 0) else type(win).__name__
    print(f"✅ 已连接：{_title!r} 尺寸={win.client_size()}")
    print("正在加载离线 OCR 模型，请稍候（约 1~3 秒）...")
    ocr = Ocr()

    cfg = None
    cfg_path = ROOT / "rules.yaml"
    if cfg_path.exists():
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    combat_ctrl = BriegSimpleCombatController()

    print("✅ 开始自动截图采集！（每 3 秒保存一张，按 F10 停止）\n")

    count = 0
    try:
        while True:
            count += 1
            snap(win, ocr, args.method, cfg, count, combat_ctrl=combat_ctrl)
            if args.once or args.loop <= 0:
                break
            end = time.time() + args.loop
            while time.time() < end:
                if bool(ctypes.windll.user32.GetAsyncKeyState(VK_F10) & 0x8000):
                    print(f"\n⏹ 收到 F10，已停止采集！共保存 {count} 组截图到 debug\\probe 文件夹。")
                    return 0
                time.sleep(0.05)
    except KeyboardInterrupt:
        print(f"\n⏹ 已停止采集！共保存 {count} 组截图到 debug\\probe 文件夹。")
    return 0


def main() -> int:
    ensure_utf8_console()
    if try_elevate():
        return 0
    elevated_window = "--elevated" in sys.argv
    try:
        code = _run_probe()
        if elevated_window:
            input("\n按回车键关闭窗口...")
        return code
    except Exception as e:  # noqa: BLE001
        print(f"\n❌ 采集工具出错：{e!r}\n", flush=True)
        if elevated_window:
            input("按回车键关闭窗口...")
        return 1


if __name__ == "__main__":
    sys.exit(main())
