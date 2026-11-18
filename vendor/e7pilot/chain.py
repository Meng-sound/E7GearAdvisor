"""秘密商店刷书签 → 关闭商店 → 大厅 → 主线地图 → 强力版布里克强攻 自动串联流程。

过渡流程依据 debug/probe/大厅文件/ 的实机截图（2026-11-08，1641x923 客户端）标定：
  1. 商店界面：点击左上角「‹」返回箭头（≈0.035, 0.052）关闭秘密商店，回到大厅；
  2. 大厅界面：右侧竖排菜单点击「Episode」文字（≈0.924, 0.259），直接进入上次的主线地图；
  3. 地图界面：识别到「准备战斗」即交给强力版布里克强攻自动接管（编队/进行任务/战斗）。
中间会出现 1~2 帧黑屏或加载画面（OCR 为空），流程会自动跳过等待。
"""
from __future__ import annotations

import ctypes
import re
import time
from pathlib import Path

import cv2
import numpy as np
import yaml

from core import GameWindow, InputBlockedError, Ocr, find_game_window, is_admin, read_click_mode, runtime_root, open_game_window, load_rules_cfg
from main import Bot, norm
from shop import (
    ShopBot,
    _prompt_stop_skystones,
    ensure_utf8_console,
    extract_skystones,
    log,
)

ROOT = runtime_root()

# ---------- 实机截图标定（客户端比例坐标） ----------
SHOP_BACK_POS = (0.035, 0.052)    # 秘密商店左上角「‹」返回箭头
EPISODE_BTN_POS = (0.924, 0.259)  # 大厅右侧竖排菜单「Episode」

VK_F10 = 0x79


def join_text(items) -> str:
    """把 OCR 结果拼成一个无空白字符串，用于状态判断。"""
    return "".join(norm(it.text) for it in items)


def classify_text(text: str) -> str:
    """根据 OCR 文本判断当前处于过渡流程的哪一屏：shop / lobby / map / loading。"""
    if "立即更新" in text or ("秘密商店" in text and "购买" in text):
        return "shop"
    if "准备战斗" in text or "进行任务" in text or re.search(r"第\d+章", text):
        return "map"
    if "Episode" in text and ("圣域" in text or "支线故事" in text):
        return "lobby"
    return "loading"


def _find_exact(items, target: str):
    for it in items:
        if norm(it.text) == target:
            return it
    return None


def _beep(times: int = 3) -> None:
    import winsound

    for freq in (1000, 1300, 1000)[:times]:
        try:
            winsound.Beep(freq, 220)
        except Exception:  # noqa: BLE001
            pass


def _save_pause_shot(img: np.ndarray) -> None:
    try:
        d = ROOT / "debug" / "paused"
        d.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(d / f"{time.strftime('%m%d_%H%M%S')}.png"), img)
        log("📸 当前画面已保存到 debug/paused/，可发给 AI 校正过渡规则")
    except Exception:  # noqa: BLE001
        pass


def transition_to_story(win: GameWindow, ocr: Ocr, timeout: float = 90.0) -> bool:
    """从秘密商店过渡到主线地图。成功返回 True；超时/卡住返回 False（响铃并留档）。"""
    log("=" * 64)
    log("🔀 商店完成 → 关闭商店 → 大厅 → 主线")
    log("=" * 64)
    deadline = time.time() + timeout
    back_tries = 0
    episode_tries = 0
    last_img: np.ndarray | None = None
    last_state = "loading"

    while time.time() < deadline:
        if not win.is_alive():
            hwnd = find_game_window()
            if not hwnd:
                log("⚠ 游戏窗口已关闭，过渡中止。")
                return False
            win.hwnd = hwnd
        img = win.capture("auto")
        if float(img.mean()) < 2.0:  # 加载黑屏
            time.sleep(0.4)
            continue
        last_img = img
        items = ocr.read(img, min_score=0.55)
        state = classify_text(join_text(items))
        last_state = state

        if state == "map":
            log("✅ 已到达主线地图，强力版布里克强攻即将接管！")
            return True

        if state == "shop":
            back_tries += 1
            if back_tries > 6:
                break
            log(f"🔚 点击左上角返回箭头关闭「秘密商店」（第 {back_tries} 次）")
            win.click_ratio(*SHOP_BACK_POS, clicks=1)
            time.sleep(1.2)
            continue

        if state == "lobby":
            episode_tries += 1
            if episode_tries > 6:
                break
            ep = _find_exact(items, "Episode")
            if ep is not None:
                w, h = win.client_size()
                pos = (ep.center[0] / w, ep.center[1] / h)
                log(f"🚪 大厅已就绪，点击「Episode」进入主线（第 {episode_tries} 次）")
            else:
                pos = EPISODE_BTN_POS
                log(f"🚪 大厅已就绪，按标定位置点击「Episode」（第 {episode_tries} 次）")
            win.click_ratio(pos[0], pos[1], clicks=1)
            time.sleep(2.5)
            continue

        time.sleep(0.5)  # loading / 未知过渡帧

    log("=" * 64)
    log(f"⚠ 自动过渡未完成（最后识别状态：{last_state}）。")
    log("=" * 64)
    if last_img is not None:
        _save_pause_shot(last_img)
    _beep()
    return False


def _wait_manual_map(win: GameWindow, ocr: Ocr, timeout: float = 180.0) -> bool:
    """过渡失败后的兜底：等用户手动进入主线地图，检测到「准备战斗」后自动继续。"""
    log("⏳ 请手动点进主线地图，程序检测到「准备战斗」后会自动继续（3 分钟内，F10 可退出）")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if ctypes.windll.user32.GetAsyncKeyState(VK_F10) & 0x8000:
            log("⏹ 收到 F10，退出串联流程。")
            return False
        if not win.is_alive():
            return False
        img = win.capture("auto")
        if float(img.mean()) >= 2.0:
            items = ocr.read(img, min_score=0.55)
            if classify_text(join_text(items)) == "map":
                log("✅ 检测到主线地图，继续执行第二阶段！")
                return True
        time.sleep(1.0)
    log("⚠ 等待手动进入主线超时，程序退出。")
    return False


def run_chain_flow(elevated_window: bool = False) -> int:
    """串联主流程：商店刷书签 → 过渡 → 强力版布里克强攻过剧情。"""
    ensure_utf8_console("第七史诗 商店→主线 自动串联 [F8 暂停/继续 | F10 退出]")
    if not is_admin():
        log("⚠ 提示：当前未授予管理员权限。若游戏内自动点击无反应，请重新双击启动并在弹窗点「是」。")

    win = open_game_window(read_click_mode())
    if win is None:
        raise SystemExit(
            "❌ 未找到《第七史诗》游戏窗口！\n"
            "请确认：1. 游戏已从 Steam 启动，或 MuMu 模拟器已进入游戏；"
            "2. 游戏处于窗口模式且没有最小化，并打开秘密商店。"
        )
    if win.is_minimized():
        log("检测到游戏窗口处于最小化状态，正在恢复窗口...")
        win.activate()
    log(f"✅ 已连接游戏窗口，画面尺寸 {win.client_size()}")

    print("=" * 68)
    print("  第七史诗（Steam 简中版）自动串联助手")
    print("  阶段 1：秘密商店自动刷书签（圣约书签 + 神秘奖牌）")
    print("  阶段 2：关闭商店 → 返回大厅 → 打开主线 → 强力版布里克强攻自动过剧情")
    print("  快捷键：【F8】暂停 / 继续      【F10】退出程序")
    print("  提示：请先在游戏里打开【秘密商店】界面，再运行本程序")
    print("=" * 68)

    log("正在加载离线 OCR 文字识别模型，请稍候（约 1~3 秒）...")
    ocr = Ocr()
    log("✅ 模型加载完成！")

    sample = win.capture("auto")
    current_stones = extract_skystones(sample, ocr, require_bright=True)
    stop_skystones = _prompt_stop_skystones(current_stones)

    bot = ShopBot(win, ocr, stop_skystones)
    if current_stones is not None:
        bot.ctrl.last_skystones = current_stones
    completed = bot.run()
    if not completed:
        log("⏹ 商店阶段被中断（F10 退出或异常），不再进入剧情阶段。")
        return 0

    if not transition_to_story(win, ocr):
        if not _wait_manual_map(win, ocr):
            return 1

    try:
        log("🎬 第二阶段开始：强力版「布里克强攻」自动过剧情！")
        cfg = load_rules_cfg(ROOT / "rules.yaml")
        Bot(cfg, mode_override="brieg").run()
    except InputBlockedError as e:
        log("=" * 58)
        log(f"❌ 无法模拟鼠标：{e}")
        log("=" * 58)
        _beep()
        return 1

    if elevated_window:
        input("\n全部完成，按回车键关闭窗口...")
    return 0
