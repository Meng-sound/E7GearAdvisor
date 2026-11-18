"""月光剧场：自动观影模块。

流程（依据 debug/probe/电影院 实机截图标定）：
  1. 剧场大厅：点「入场」进入当前电影；
  2. 电影页：选一集可观看的剧集（未完成、未锁定）→ 点「进行观览」；
  3. 弹窗：缺票时「购买剧场门票」(50 万金币/张，尊重金币保留线) → 「使用剧场门票」点确认；
  4. 观影：剧情不能跳过，自动连点推进；进入剧情战斗时若系统 AUTO 未开则自动点开；
  5. 结算 CLEAR 点击继续；一集结束后回电影页继续下一集；
  6. 当前电影/季全部看完 → 返回大厅 → 横向滑动换片 → 继续。
"""
from __future__ import annotations

import ctypes
import random
import re
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import yaml

from combat import AUTO_BTN_POS, CombatControllerBase
from core import (
    load_rules_cfg,
    open_game_window,
    GameWindow,
    InputBlockedError,
    Ocr,
    find_game_window,
    has_battle_hud,
    is_admin,
    read_click_mode,
    runtime_root,
)
from main import norm

ROOT = runtime_root()
VK_F8, VK_F10 = 0x77, 0x79

SHOP_BACK_POS = (0.035, 0.052)   # 左上角「‹」返回
CENTER_CLICK = (0.500, 0.600)    # 剧情推进点击位置

# ---------------- unknown 场景细分（Gemini 方案） ----------------
THEATER_ACTIVE_STATES = {"story", "movie", "use_ticket"}
THEATER_SAFE_CLICK = (0.50, 0.22)   # 安全推进区：避开居中弹窗按钮与右上角控件
FRAME_DIFF_MOVING = 1.2             # 帧差 ≥ 此值 → 画面在动（过场/加载动画）
DARK_LUM = 12.0                     # 平均亮度 < 此值 → 纯黑转场
CENTER_STD_RICH = 15.0              # 中心纹理标准差 ≥ 此值 → 有内容（无字 CG）
FIRST_CLICK_DELAY = 6.0             # unknown 后多少秒开始试探点击
CLICK_INTERVAL = 5.0                # 两次试探点击间隔
MAX_PROBE_CLICKS = 3                # 单次 unknown 周期最多点几次
STATIC_PAUSE_SEC = 25.0             # 画面静止满这么久 → 判定真卡死
TOTAL_UNKNOWN_SEC = 40.0            # unknown 总时长上限（防加载动画无限转）

EPISODE_RE = re.compile(r"第(\d+)集")
SEASON_RE = re.compile(r"第(\d+)季")


def _join(items) -> str:
    return "".join(norm(it.text) for it in items)


def _log(msg: str) -> None:
    print(msg, flush=True)


def classify_state(items, text: str, has_battle: bool) -> str:
    """判断当前画面状态：battle / guide / buy_ticket / use_ticket / clear / movie / hall / story / popup / unknown。"""
    if has_battle:
        return "battle"
    # 观览指南弹窗（「月光剧场的故事无法跳过。是否要开始观览？」取消/确认）
    if "观览指南" in text or "是否要开始观览" in text or "是否开始观览" in text:
        return "guide"
    if "购买剧场门票" in text:
        return "buy_ticket"
    if "使用剧场门票" in text or "观览中无法跳过" in text:
        return "use_ticket"
    if "CLEAR" in text.upper():
        return "clear"
    if "月光剧场" in text and "进行观览" in text:
        return "movie"
    if "月光剧场" in text and "入场" in text:
        return "hall"
    if "月光剧场" not in text:
        if any("获得" in norm(it.text) for it in items):
            return "popup"
        if items:  # 剧情：隐藏 UI，只剩角色名/台词
            return "story"
    return "unknown"


def _parse_gold(items, w: int, h: int) -> int | None:
    for it in items:
        cx, cy = it.center[0] / w, it.center[1] / h
        if 0.55 <= cx <= 0.70 and cy <= 0.08:
            m = re.search(r"[\d,]{5,}", norm(it.text))
            if m:
                return int(m.group(0).replace(",", ""))
    return None


def _episode_status(items, w: int, h: int, cy: float) -> str:
    """判断某一集右侧状态：done / locked / timed / open / unknown。

    游戏里显示的四种状态：
      完成           -> done
      无法观览       -> locked
      N天后可观览    -> timed（用剧场门票可立即看）
      可观看/可观览  -> open（现在就能看，不用票）
    """
    for st in items:
        sx, sy = st.center[0] / w, st.center[1] / h
        if sx < 0.70 or abs(sy - cy) > 0.06:
            continue
        t = norm(st.text)
        if "天后" in t:
            return "timed"
        if "无法" in t:
            return "locked"
        if "完成" in t:
            return "done"
        if "可观看" in t or "可观览" in t or "可观" in t:
            return "open"
    return "unknown"


def pick_episode(items, w: int, h: int):
    """返回下一集 (集数, 点击x, 点击y, 状态)。

    只认「N天后可观览」——这是游戏标注的"下一集"（用剧场门票可立即观看）。
    找不到状态文字的剧集一律跳过：它很可能是被列表底边挡住了「完成」标签，
    绝不能当成可观看，否则会无限点已完成的那一集。
    """
    rows: list[tuple[int, float, float, str]] = []
    for it in items:
        m = EPISODE_RE.search(norm(it.text))
        cx, cy = it.center[0] / w, it.center[1] / h
        if not m or cx < 0.70:
            continue
        rows.append((int(m.group(1)), cx, cy, _episode_status(items, w, h, cy)))
    rows.sort(key=lambda r: r[0])
    open_rows = [r for r in rows if r[3] == "open"]
    if open_rows:
        return open_rows[0]
    timed_rows = [r for r in rows if r[3] == "timed"]
    return timed_rows[0] if timed_rows else None


def scan_episodes(items, w: int, h: int):
    """返回当前视野内所有剧集行 [(集数, x, y, 状态)]，状态为 done/locked/timed/unknown。"""
    rows = []
    for it in items:
        m = EPISODE_RE.search(norm(it.text))
        cx, cy = it.center[0] / w, it.center[1] / h
        if not m or cx < 0.70:
            continue
        rows.append((int(m.group(1)), cx, cy, _episode_status(items, w, h, cy)))
    rows.sort(key=lambda r: r[0])
    return rows


def season_tabs(items, w: int, h: int):
    """返回右侧季度标签 [(标签文字, y, x)]，按 y 排序。"""
    tabs = []
    for it in items:
        if not SEASON_RE.search(norm(it.text)):
            continue
        cx, cy = it.center[0] / w, it.center[1] / h
        if cx < 0.85:
            continue
        tabs.append((norm(it.text), cy, cx))
    tabs.sort(key=lambda t: t[1])
    return tabs


def selected_episode(items, w: int, h: int) -> int | None:
    """左下角详情面板当前选中的集数。"""
    for it in items:
        cx, cy = it.center[0] / w, it.center[1] / h
        if cx < 0.45 and 0.66 <= cy <= 0.84:
            m = EPISODE_RE.search(norm(it.text))
            if m:
                return int(m.group(1))
    return None


class TheaterBot:
    def __init__(self, win: GameWindow, ocr: Ocr, keep_gold: int, ticket_cost: int = 500000) -> None:
        self.win = win
        self.ocr = ocr
        self.keep_gold = keep_gold
        self.ticket_cost = ticket_cost
        self.paused = False
        self._key_state = {VK_F8: False, VK_F10: False}
        self._next_sleep = 0.15
        self.auto_ctrl = CombatControllerBase()
        self.last_auto_click = 0.0
        self.last_claim = 0.0
        self.last_story_click = 0.0
        self.last_center_click = 0.0
        self.episode_tries = 0
        self.season_tries = 0
        self.need_swipe = False
        self.last_swipe = 0.0
        self.films_done = 0
        self.unknown_since: float | None = None
        self.ep_status: dict[int, str] = {}
        self.season_seen: set[str] = set()
        self.scan_drags = 0
        self.need_scroll_top = False
        self.last_drag = 0.0
        self.last_ep_click: tuple[float, int] = (0.0, -1)
        # unknown 场景细分状态
        self._prev_gray = None
        self._last_valid_state: str | None = None
        self._unknown_since: float | None = None
        self._static_since: float | None = None
        self._probe_clicks = 0
        self._last_probe_click = 0.0
        self._unknown_dump: list[dict] = []
        self.last_gold: int | None = None
        # ---- 月光剧场专属节奏配置（由 rules.yaml 注入，不影响其它功能）----
        self.story_click_ms: float = 50.0     # 剧情连点的间隔（毫秒）
        self.story_hold_ms: tuple[float, float] = (0.060, 0.080)  # 每次按压时长（秒）
        self.story_burst: int = 12            # 每轮连点次数（之后重新 OCR 确认状态）
        self.action_gap: float = 0.30          # 同一按钮的最短间隔（防双击误触）
        self._story_bursts: int = 0            # 连续「剧情未推进」的轮数（用于自动加长按压）

    # ---------- 热键 ----------
    def _pressed(self, vk: int) -> bool:
        down = bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
        was = self._key_state[vk]
        self._key_state[vk] = down
        return down and not was

    def poll_hotkeys(self) -> bool:
        if self._pressed(VK_F10):
            _log("⏹ 收到 F10，退出电影院程序。")
            return False
        if self._pressed(VK_F8):
            self.paused = not self.paused
            _log("⏸ 已暂停（F8 继续 / F10 退出）" if self.paused else "▶ 继续自动观影！")
            self.unknown_since = None
        return True

    @staticmethod
    def _beep() -> None:
        import winsound

        for freq in (1000, 1300, 1000):
            try:
                winsound.Beep(freq, 220)
            except Exception:  # noqa: BLE001
                pass

    def pause(self, reason: str, img=None) -> None:
        self.paused = True
        _log("=" * 60)
        _log(f"⚠ 自动暂停：{reason}")
        _log("👉 处理完后按【F8】继续，或按【F10】退出。")
        _log("=" * 60)
        if img is not None:
            try:
                d = ROOT / "debug" / "paused"
                d.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(d / f"{time.strftime('%m%d_%H%M%S')}.png"), img)
                _log("📸 已保存 debug/paused/ 便于排查")
            except Exception:  # noqa: BLE001
                pass
        self._beep()

    def _click_text(self, items, w: int, h: int, keyword: str, fallback: tuple[float, float]) -> None:
        """优先点与按钮文字完全一致的条目，再退回包含匹配（排除长标题，如「购买剧场门票」）。"""
        exact = None
        loose = None
        for it in items:
            t = norm(it.text)
            if t == keyword:
                exact = it
                break
            if loose is None and keyword in t and len(t) <= len(keyword) + 6:
                loose = it
        target = exact or loose
        if target is not None:
            self.win.click_ratio(target.center[0] / w, target.center[1] / h, clicks=1)
        else:
            self.win.click_ratio(*fallback, clicks=1)

    def _drag_list(self, down: bool = True) -> None:
        """剧集列表翻页：从下往上拖=继续往下翻；从上往下拖=回到顶部。"""
        if down:
            self.win.drag_ratio(0.78, 0.80, 0.78, 0.38, duration=0.30)
        else:
            self.win.drag_ratio(0.78, 0.38, 0.78, 0.80, duration=0.30)

    # ---------- 单步 ----------
    def step(self) -> None:
        now = time.time()
        if not self.win.is_alive():
            hwnd = find_game_window()
            if not hwnd:
                self.pause("游戏窗口已关闭")
                return
            self.win.hwnd = hwnd

        img = self.win.capture("auto")
        if float(img.mean()) < 2.0:
            self._next_sleep = 0.15
            return
        h, w = img.shape[:2]
        items = self.ocr.read(img, min_score=0.55)
        self._last_items = items
        text = _join(items)
        has_battle = has_battle_hud(img, items)
        state = classify_state(items, text, has_battle)
        if state != "story":
            self._story_bursts = 0
        if state != "unknown":
            self._last_valid_state = state
            self._reset_unknown_tracking()
        self._next_sleep = 0.15
        # 每轮先记录金币余额（购买弹窗会遮挡金币栏，所以提前缓存）
        _g = _parse_gold(items, w, h)
        if _g is not None:
            self.last_gold = _g

        if state == "battle":
            if not self.auto_ctrl.is_combat_auto_on(img):
                if now - self.last_auto_click > 1.5:
                    _log("🔫 剧情战斗未开 AUTO → 点击开启自动战斗")
                    self.win.click_ratio(*AUTO_BTN_POS, clicks=1)
                    self.last_auto_click = now
            self._next_sleep = 0.20
            return

        if state == "buy_ticket":
            gold = _parse_gold(items, w, h) or self.last_gold
            if gold is None:
                self.pause("读不到金币余额（购买弹窗遮挡）→ 已暂停避免误买，请手动确认金币后按 F8", img)
                return
            if gold - self.ticket_cost < self.keep_gold:
                self.pause(
                    f"金币不足：当前 {gold:,}，买一张票 {self.ticket_cost:,} 后低于保留线 {self.keep_gold:,}",
                    img,
                )
                return
            _log(f"🎫 购买剧场门票（记录金币 {gold:,}）")
            self._click_text(items, w, h, "购买", (0.652, 0.818))
            self._next_sleep = 0.25
            return

        if state == "use_ticket":
            _log("🎟 使用剧场门票立即观览 → 确认")
            self._click_text(items, w, h, "确认", (0.580, 0.732))
            self._next_sleep = 0.30
            return

        if state == "guide":
            # 「观览指南」弹窗：确认后才开始播放，点「确认」
            if now - self.last_center_click > self.action_gap:
                _log("📖 观览指南弹窗 → 点击「确认」开始观览")
                self._click_text(items, w, h, "确认", (0.601, 0.735))
                self.last_center_click = now
            self._next_sleep = 0.25
            return

        if state == "clear":
            if now - self.last_center_click > self.action_gap:
                _log("🏁 CLEAR → 点击继续")
                self.win.click_ratio(*CENTER_CLICK, clicks=1)
                self.last_center_click = now
            self._next_sleep = 0.20
            return

        if state == "movie":
            self.unknown_since = None
            # 进入新片/换季后：先把剧集列表拖回顶部
            if self.need_scroll_top and now - self.last_drag > 0.35:
                _log("🖱 剧集列表拖回顶部")
                self._drag_list(down=False)
                self.need_scroll_top = False
                self.last_drag = now
                self._next_sleep = 0.25
                return

            rows = scan_episodes(items, w, h)
            for no, _x, _y, st in rows:
                if st != "unknown":
                    self.ep_status[no] = st

            # 可观看（不用票）优先，其次 N天后可观览（用票立即看）
            watchable = [r for r in rows if r[3] in ("open", "timed")]
            if watchable:
                ep_no, ex, ey, status = watchable[0]
                kind = "可观看" if status == "open" else "N天后可观览"
                if selected_episode(items, w, h) != ep_no:
                    _log(f"🎬 选择第 {ep_no} 集（{kind}）")
                    self.win.click_ratio(ex, ey, clicks=1)
                    self.last_ep_click = (now, ep_no)
                    self._next_sleep = 0.20
                    return
                _log(f"▶ 第 {ep_no} 集已选中（{kind}）→ 点击「进行观览」")
                self._click_text(items, w, h, "进行观览", (0.652, 0.923))
                self.ep_status = {}
                self.scan_drags = 0
                self.need_scroll_top = True
                self._next_sleep = 0.15
                return

            # 当前视野没有可看集 → 拖拽列表继续往下扫描（像翻神秘商店那样）
            if self.scan_drags < 2 and now - self.last_drag > 0.35:
                self.scan_drags += 1
                _log(f"🖱 剧集列表下滑扫描（第 {self.scan_drags} 次）")
                self._drag_list(down=True)
                self.last_drag = now
                self._next_sleep = 0.25
                return

            # 本季（当前标签）确实没有可看集 -> 切到还没检查过的季度标签
            tabs = season_tabs(items, w, h)
            unchecked = [t for t in tabs if t[0] not in self.season_seen]
            if unchecked:
                label, ty, tx = unchecked[0]
                _log(f"📺 本季无可看剧集（{len(self.ep_status)} 集）→ 切换「{label}」")
                self.win.click_ratio(tx, ty, clicks=1)
                self.season_seen.add(label)
                self.ep_status = {}
                self.scan_drags = 0
                self.need_scroll_top = True
                self._next_sleep = 0.30
                return

            _log("✅ 本片所有季度都已看过，没有可观看剧集 → 返回大厅换片")
            self.win.click_ratio(*SHOP_BACK_POS, clicks=1)
            self.need_swipe = True
            self.films_done += 1
            self.season_tries = 0
            self.ep_status = {}
            self.scan_drags = 0
            self.season_seen = set()
            self._next_sleep = 0.30
            return

        if state == "hall":
            self.unknown_since = None
            self.season_tries = 0
            if self.need_swipe and now - self.last_swipe > 0.6:
                _log(f"➡ 换片：滑动到下一场（已完成 {self.films_done} 部）")
                self.win.drag_ratio(0.75, 0.55, 0.25, 0.55)
                self.last_swipe = now
                self.need_swipe = False
                self._next_sleep = 0.45
                return
            _log("🚪 剧场大厅 → 点击「入场」")
            self._click_text(items, w, h, "入场", (0.891, 0.895))
            self.ep_status = {}
            self.season_seen = set()
            self.scan_drags = 0
            self.need_scroll_top = True
            self.season_tries = 0
            self._next_sleep = 0.45
            return

        if state == "story":
            self.unknown_since = None
            # 剧情推进：盲点（中间不 OCR），点满 burst 次后再抓帧确认状态
            hold = random.uniform(*self.story_hold_ms)
            for _ in range(max(1, int(self.story_burst))):
                if not self.poll_hotkeys() or self.paused:
                    break
                self.win.click_ratio(*CENTER_CLICK, clicks=1, hold=hold)
                self.last_story_click = time.time()
                time.sleep(max(0.0, self.story_click_ms / 1000.0))
            # 连续多轮仍是剧情 → 说明按压可能太短（Steam 版需要"按得实"），自动加长
            self._story_bursts += 1
            if self._story_bursts >= 3:
                self._story_bursts = 0
                lo, hi = self.story_hold_ms
                if hi < 0.15:
                    self.story_hold_ms = (min(0.13, lo + 0.03), min(0.17, hi + 0.05))
                    _log(
                        f"⏫ 剧情连点未推进 → 按压时长自动提高到 "
                        f"{self.story_hold_ms[0] * 1000:.0f}~{self.story_hold_ms[1] * 1000:.0f}ms"
                    )
            self._next_sleep = 0.02
            return

        if state == "popup":
            self._click_text(items, w, h, "确认", (0.5, 0.5))
            self._next_sleep = 0.20
            return

        # unknown：用图像指标细分（过场/无字CG/黑屏/真卡死）
        self._handle_unknown(img, now)
        self._next_sleep = 0.5

    # ---------- unknown 场景细分 ----------
    @staticmethod
    def _popup_border_like(gray) -> bool:
        """中心区域是否出现了「居中的矩形边框」（说明是 OCR 没认出来的弹窗）。"""
        try:
            roi = gray[40:140, 60:260]
            edges = cv2.Canny(roi, 60, 160)
            lines = cv2.HoughLinesP(
                edges, 1, np.pi / 180, threshold=40, minLineLength=60, maxLineGap=6
            )
            if lines is None:
                return False
            horiz = vert = 0
            for x1, y1, x2, y2 in lines[:, 0]:
                if abs(y2 - y1) <= 2 and abs(x2 - x1) >= 60:
                    horiz += 1
                elif abs(x2 - x1) <= 2 and abs(y2 - y1) >= 60:
                    vert += 1
            return horiz >= 2 and vert >= 2
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _visual_metrics(img, prev_gray):
        """缩到 320x180 灰度，算帧差 / 平均亮度 / 中心纹理标准差。"""
        small = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (320, 180))
        mean_lum = float(np.mean(small))
        center = small[45:135, 80:240]
        center_std = float(np.std(center))
        if prev_gray is None:
            diff = 0.0
        else:
            diff = float(np.mean(cv2.absdiff(small, prev_gray)))
        return small, diff, mean_lum, center_std

    def _reset_unknown_tracking(self) -> None:
        self._popup_blocked_logged = False
        self._unknown_since = None
        self._static_since = None
        self._probe_clicks = 0
        self._last_probe_click = 0.0
        self._unknown_dump.clear()

    def _dump_unknown(self, reason: str) -> None:
        try:
            stamp = time.strftime("%m%d_%H%M%S")
            d = ROOT / "debug" / f"unknown_dump_{stamp}"
            d.mkdir(parents=True, exist_ok=True)
            for i, rec in enumerate(self._unknown_dump):
                name = (
                    f"seq{i:02d}_t{rec['t']:.1f}s_static{rec['static']:.1f}s_"
                    f"diff{rec['diff']:.2f}_lum{rec['lum']:.0f}_std{rec['std']:.0f}.png"
                )
                cv2.imwrite(str(d / name), rec["img"])
            items = getattr(self, "_last_items", []) or []
            if items:
                h, w = self._unknown_dump[-1]["img"].shape[:2] if self._unknown_dump else (1, 1)
                lines = [
                    f"{it.text}\t{it.score:.2f}\t({it.center[0]/w:.3f},{it.center[1]/h:.3f})"
                    for it in items
                ]
                (d / "ocr_raw.txt").write_text("\n".join(lines), encoding="utf-8")
            _log(f"📸 unknown 诊断截图已保存：debug/unknown_dump_{stamp}/")
        except Exception:  # noqa: BLE001
            pass

    def _handle_unknown(self, img, now: float) -> None:
        small, diff, lum, cstd = self._visual_metrics(img, self._prev_gray)
        self._prev_gray = small

        if self._unknown_since is None:
            self._unknown_since = now
            self._static_since = now

        if diff >= FRAME_DIFF_MOVING:
            self._static_since = now

        total = now - self._unknown_since
        static = now - self._static_since

        if len(self._unknown_dump) < 10 and int(total * 10) % 30 == 0:
            self._unknown_dump.append(
                {"t": total, "static": static, "diff": diff, "lum": lum, "std": cstd, "img": img.copy()}
            )

        if static >= STATIC_PAUSE_SEC or total >= TOTAL_UNKNOWN_SEC:
            self._dump_unknown(f"static={static:.1f}s total={total:.1f}s")
            self.pause(
                f"连续未识别到剧场界面（静止 {static:.0f}s / 总 {total:.0f}s，"
                f"帧差 {diff:.1f} 亮度 {lum:.0f}），已保存诊断截图",
                img,
            )
            self._reset_unknown_tracking()
            return

        in_flow = self._last_valid_state in THEATER_ACTIVE_STATES
        if in_flow and static >= FIRST_CLICK_DELAY and self._probe_clicks < MAX_PROBE_CLICKS:
            if now - self._last_probe_click >= CLICK_INTERVAL:
                if lum >= DARK_LUM or static >= 12.0:
                    if self._popup_border_like(small):
                        # 疑似弹窗：绝不盲点，交给静止超时去暂停
                        if not getattr(self, "_popup_blocked_logged", False):
                            self._popup_blocked_logged = True
                            _log("🛑 画面疑似弹出未知弹窗（检测到居中边框）→ 暂停试探点击")
                        return
                    self.win.click_ratio(*THEATER_SAFE_CLICK, clicks=1)
                    self._probe_clicks += 1
                    self._last_probe_click = now
                    _log(
                        f"🖱 剧场画面静止 {static:.0f}s（亮度{lum:.0f} 纹理{cstd:.0f}）→ "
                        f"试探点击第 {self._probe_clicks}/{MAX_PROBE_CLICKS} 次"
                    )
        return

    def run(self) -> None:
        _log("=" * 68)
        _log("  第七史诗（Steam 简中版）月光剧场 自动观影助手")
        _log(f"  剧场门票：{self.ticket_cost:,} 金币/张；买票后保留金币 ≥ {self.keep_gold:,}")
        _log("  快捷键：【F8】暂停 / 继续      【F10】退出程序")
        _log("  提示：需要人已经进入「月光剧场」大厅界面；运行期间不要最小化游戏窗口")
        _log("=" * 68)
        while True:
            if not self.poll_hotkeys():
                break
            if self.paused:
                time.sleep(0.15)
                continue
            try:
                self.step()
            except InputBlockedError as e:
                _log("=" * 58)
                _log(f"❌ 无法模拟鼠标：{e}")
                _log("=" * 58)
                self._beep()
                return
            except Exception as e:  # noqa: BLE001
                _log(f"⚠ 本轮异常（自动重试）：{e!r}")
                self._next_sleep = 0.20
            end = time.time() + self._next_sleep
            while time.time() < end:
                if not self.poll_hotkeys():
                    return
                time.sleep(0.05)


def _prompt_keep_gold(current_gold: int | None, default: int) -> int:
    if "--keep-gold" in sys.argv:
        i = sys.argv.index("--keep-gold")
        if i + 1 < len(sys.argv):
            try:
                return max(0, int(re.sub(r"[,，\s]", "", sys.argv[i + 1])))
            except ValueError:
                pass
    print()
    print("=" * 68)
    print("  💰 设置「买票保留金币」下限")
    if current_gold is not None:
        print(f"  当前识别到金币：{current_gold:,}")
    print(f"  每张剧场门票 500,000 金币；买票后金币不得低于该下限（默认 {default:,}）")
    print("  直接回车用默认值，或输入数字（如 2000000）")
    print("=" * 68)
    while True:
        raw = input(f"请输入保留金币下限（默认 {default:,}）：").strip()
        if not raw:
            return default
        cleaned = re.sub(r"[,，\s]", "", raw)
        if cleaned.isdigit():
            return int(cleaned)
        print("❌ 请输入纯数字")


def run_theater_flow(elevated_window: bool = False) -> int:
    from shop import ensure_utf8_console

    ensure_utf8_console("第七史诗 月光剧场自动观影 [F8 暂停/继续 | F10 退出]")
    if not is_admin():
        _log("⚠ 提示：当前未授予管理员权限。若游戏内自动点击无反应，请重新双击启动并在弹窗点「是」。")

    win = open_game_window(read_click_mode())
    if win is None:
        raise SystemExit("❌ 未找到《第七史诗》游戏窗口！请先启动游戏（窗口模式或 MuMu 模拟器）并进入月光剧场。")
    if win.is_minimized():
        _log("检测到游戏窗口最小化，正在恢复...")
        win.activate()
    _log(f"✅ 已连接游戏窗口，画面尺寸 {win.client_size()}")

    cfg = {}
    try:
        cfg = load_rules_cfg(ROOT / "rules.yaml") or {}
    except Exception:  # noqa: BLE001
        pass
    st = cfg.get("settings", {}) or {}
    ticket_cost = int(st.get("theater_ticket_cost", 500000))
    default_keep = int(st.get("theater_keep_gold", 1000000))

    _log("正在加载离线 OCR 文字识别模型，请稍候（约 1~3 秒）...")
    ocr = Ocr()
    _log("✅ 模型加载完成！")

    sample = win.capture("auto")
    items = ocr.read(sample, 0.55)
    h, w = sample.shape[:2]
    gold = _parse_gold(items, w, h)
    keep_gold = _prompt_keep_gold(gold, default_keep)

    bot = TheaterBot(win, ocr, keep_gold, ticket_cost)
    # 节奏参数（只作用于月光剧场，缺省即内置默认值）
    try:
        bot.story_click_ms = float(st.get("theater_story_click_ms", bot.story_click_ms))
        bot.story_burst = int(st.get("theater_story_burst", bot.story_burst))
        bot.action_gap = float(st.get("theater_action_gap_ms", bot.action_gap * 1000)) / 1000.0
        _hold = st.get("theater_story_hold_ms")
        if isinstance(_hold, (list, tuple)) and len(_hold) == 2:
            bot.story_hold_ms = (float(_hold[0]) / 1000.0, float(_hold[1]) / 1000.0)
        _poll = st.get("theater_poll_ms")
        if _poll:
            bot.poll_ms = float(_poll) / 1000.0
    except Exception:  # noqa: BLE001
        pass
    bot.run()
    if elevated_window:
        input("\n观影结束，按回车键关闭窗口...")
    return 0
