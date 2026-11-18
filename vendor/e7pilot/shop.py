"""第七史诗（Steam 简中版）秘密商店自动刷新购买书签程序。

功能：
  1. 启动时交互设置【剩余天空石停止线】（例如剩余 <= 2000 颗时自动停止并响铃提示）。
  2. 自动上下浏览完整 6 格商店货架：
       - 遇未购买(1/1)的「圣约书签」「神秘奖牌」(或「神秘书签」)自动点击购买并二次确认；
       - 自动跳过已购买(0/1)条目与普通装备/英雄/友情点；
       - 顶部扫完后自动上滑底部查看第 5~6 栏商品；
       - 若金币不足/天空石达到设定下限/弹出充值画面，立即安全停止并三声提示音。
热键：F8 暂停/继续    F10 退出脚本
"""
from __future__ import annotations

import ctypes
import re
import sys
import time
import winsound
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

import stats as stats_db

from core import (
    open_game_window,
    to_simplified,
    GameWindow,
    InputBlockedError,
    Ocr,
    OcrItem,
    cursor_control_probe,
    find_game_window,
    is_admin,
    is_low_integrity,
    process_parent_info,
    process_privilege_summary,
    read_click_mode,
    runtime_root,
    write_startup_diag,
)

ROOT = runtime_root()
VK_F8, VK_F10 = 0x77, 0x79

REFRESH_BTN_POS = (0.210, 0.916)
REFRESH_CONFIRM_POS = (0.584, 0.638)
REFRESH_CANCEL_POS = (0.416, 0.639)
BUY_CONFIRM_POS = (0.638, 0.708)
BUY_CANCEL_POS = (0.376, 0.706)
SHOP_DRAG_FROM = (0.62, 0.78)
SHOP_DRAG_TO = (0.62, 0.22)
# 扫描用滑动序列：商店一页 6 件（可见 4 件 + 第 5 件半截），一次滑 2.5 行即可全覆盖。
# 需要更保险时可再加一步，例如：(((0.62, 0.80), (0.62, 0.34)), ((0.62, 0.78), (0.62, 0.55)))
# 扫描停靠点：顶部不动 → 中部(半屏) → 底部(到底)
SHOP_STOP_DRAGS = (
    None,                                # 停靠点 1：不滑动，直接扫顶部
    ((0.62, 0.80), (0.62, 0.34)),        # 停靠点 2：一趟滑到底（到底后无半截行）
)
SHOP_BOTTOM_RESCAN_DRAG = ((0.62, 0.62), (0.62, 0.42))  # 底部补扫：小滑一点，把半截行顶上来
SHOP_SECOND_PASS = False
SHOP_REFRESH_COST = 3      # 每次刷新消耗的天空石                              # 刷新前再全页扫一遍（防漏）
SHOP_STABLE_FRAMES = 2                               # 连续稳定帧数（稳定后才判定）
SHOP_ICON_CONFIRM = 0.80                             # 图标模板确认阈值
SHOP_SCROLL_STEPS = (((0.62, 0.80), (0.62, 0.34)),)  # 兼容旧引用
SHOP_DRAG_DURATION = 0.12   # 滑动更快
SHOP_DRAG_STEPS = 8

COVENANT_NAMES = ("圣约书签", "书签")
MYSTIC_NAMES = ("神秘奖牌", "神秘书签", "神秘奖", "奖牌")
ALL_BOOKMARK_NAMES = COVENANT_NAMES + MYSTIC_NAMES

INSUFFICIENT_KEYWORDS = ("金币不足", "黄金不足", "天空石不足", "货币不足", "行动力不足", "充值", "礼包")


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def norm(s: str) -> str:
    return to_simplified("".join(s.split()))


def ensure_utf8_console(title: str) -> None:
    try:
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleTitleW(title)
    except Exception:  # noqa: BLE001
        pass
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass


def try_elevate() -> bool:
    """若非管理员，自动弹出 Windows UAC 提权；Low 进程里 runas 仍是 Low，故不做无意义重启。"""
    if is_admin() or "--no-elevate" in sys.argv or "--elevated" in sys.argv:
        return False
    script = str(Path(__file__).resolve())
    extra_args = " ".join(f'"{a}"' for a in sys.argv[1:])
    py_flags = ("-s " if sys.flags.no_user_site else "") + ("-E " if sys.flags.ignore_environment else "")
    params = f'{py_flags}"{script}" --elevated {extra_args}'.strip()
    ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, str(ROOT), 1)
    if int(ret) <= 32:
        print(f"⚠ 自动提权失败（code={int(ret)}），将按当前权限继续（可能无法控制鼠标）", flush=True)
        return False
    return True


_LAST_TOPBAR_GOLD: int | None = None


def extract_skystones(img: np.ndarray, ocr: Ocr, require_bright: bool = True) -> int | None:
    """识别顶栏天空石，并顺带用 2 倍放大顶栏刷新 _LAST_TOPBAR_GOLD（绕开双帧并集缓存）。"""
    global _LAST_TOPBAR_GOLD
    h, w = img.shape[:2]
    if h <= 0 or w <= 0:
        return None

    band = img[int(h * 0.010): int(h * 0.090), int(w * 0.35): int(w * 0.99)]
    if band.size == 0:
        return None
    if require_bright and int(band.max()) < 200:
        return None

    up = cv2.resize(band, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    items = ocr.read(up, min_score=0.40, min_brightness=45.0)
    bw = up.shape[1]
    nums: list[tuple[float, str]] = []
    for it in items:
        t = it.text.strip().replace(" ", "")
        if re.fullmatch(r"[\d,]{3,12}", t):
            nums.append((it.center[0], t))
    if nums:
        nums.sort()
        for cx_u, t_u in nums:
            if (cx_u / max(1, bw)) < 0.56:
                try:
                    g_val = int(t_u.replace(",", ""))
                    if g_val >= 10000:
                        _LAST_TOPBAR_GOLD = g_val
                        break
                except ValueError:
                    pass
        try:
            val = int(nums[-1][1].replace(",", ""))
        except ValueError:
            val = 0
        if 1 <= val <= 999999:
            return val
    return None


_SHOP_ICONS: dict[str, "np.ndarray"] = {}


def _load_shop_icons() -> dict:
    """加载书签/奖牌图标模板（必须用 fromfile，中文路径下 imread 会失败）。"""
    global _SHOP_ICONS
    if _SHOP_ICONS:
        return _SHOP_ICONS
    for name, kind in (("shop_covenant.png", "圣约书签"), ("shop_mystic.png", "神秘奖牌")):
        p = Path(__file__).parent / "templates" / name
        if p.exists():
            data = np.fromfile(str(p), dtype=np.uint8)
            img = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
            if img is not None:
                _SHOP_ICONS[kind] = img
    return _SHOP_ICONS


def _fuzzy_kind(text: str) -> str | None:
    """模糊匹配书签/奖牌名称（容忍 OCR 错字、拆字、繁简）。"""
    import difflib

    t = norm(text).replace(" ", "")
    if not t:
        return None
    targets = {"圣约书签": ("圣", "约", "书", "签"), "神秘奖牌": ("神", "秘", "奖", "牌")}
    for kind, chars in targets.items():
        hit = sum(1 for c in chars if c in t)
        if hit >= 3:
            return kind
        if hit >= 2 and difflib.SequenceMatcher(None, t, kind).ratio() >= 0.5:
            return kind
        if difflib.SequenceMatcher(None, t, kind).ratio() >= 0.66:
            return kind
    # 常见错字/繁体
    if ("书" in t and "签" in t) or ("約" in t and "書" in t):
        return "圣约书签"
    if ("奖" in t and "牌" in t) or ("獎" in t and "牌" in t) or "神祕" in t:
        return "神秘奖牌"
    return None


def _icon_kind_at(img: "np.ndarray", cy: float) -> str | None:
    """在某一行的图标位置做模板匹配，返回命中的商品类型（用于文字识别失败时兜底确认）。"""
    icons = _load_shop_icons()
    if not icons:
        return None
    h, w = img.shape[:2]
    y1 = max(0, int(h * (cy - 0.055)))
    y2 = min(h, int(h * (cy + 0.055)))
    x1 = max(0, int(w * 0.385))
    x2 = min(w, int(w * 0.520))
    roi = cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    if roi.size == 0:
        return None
    best_kind, best_score = None, 0.0
    for kind, tpl in icons.items():
        for sc in (0.7, 0.85, 1.0, 1.15, 1.3):
            tw, th = int(tpl.shape[1] * sc), int(tpl.shape[0] * sc)
            if tw > roi.shape[1] or th > roi.shape[0]:
                continue
            res = cv2.matchTemplate(roi, cv2.resize(tpl, (tw, th)), cv2.TM_CCOEFF_NORMED)
            _, mx, _, _ = cv2.minMaxLoc(res)
            if mx > best_score:
                best_kind, best_score = kind, float(mx)
    return best_kind if best_score >= SHOP_ICON_CONFIRM else None


def top_row_looks_cut(items: list[OcrItem], w: int, h: int) -> bool:
    """顶部是否有「被切掉一半」的商品行：有购买按钮，但上方读不到完整商品名。"""
    tops = [
        it
        for it in items
        if norm(it.text) == "购买" and 0.85 <= it.center[0] / w <= 0.99 and it.center[1] / h < 0.17
    ]
    if not tops:
        return False
    for btn in tops:
        by = btn.center[1] / h
        # 按钮上方 0.06 范围内，是否有"像商品名"的文字（2 字以上、非装备/价格/可购买）
        has_name = False
        for it in items:
            t = norm(it.text)
            cy = it.center[1] / h
            if not (by - 0.075 <= cy < by - 0.005):
                continue
            if len(t) < 2 or t.isdigit():
                continue
            if any(k in t for k in ("装备", "可购买", "购买", "货币", "1/1", "0/1")):
                continue
            if "," in t:
                continue
            has_name = True
            break
        if not has_name:
            return True
    return False


BOOKMARK_FRAGMENT_CHARS = set("圣约书签神秘奖牌")

CUT_BTN_Y_HARD = 0.132      # 购买按钮 y ≤ 此值 → 商品名必被顶边切掉
CUT_BTN_Y_SOFT = 0.170      # 疑似区上限
INTACT_TEXT_Y_MIN = 0.102   # 首行文字中心 y ≥ 此值 → 完整未切
LAYOUT_SETTLE_SHIFT = 0.006 # 两帧按钮位移小于此值视为静止
POST_PULL_SETTLE_SEC = 0.22 # 下滑后内置停顿


def top_row_looks_cut_geometric(items: list[OcrItem], w: int, h: int, exclude_ys: list[float]) -> float | None:
    """返回"被切顶行"的购买按钮 y；未切返回 None。判据全部基于几何，不看文字是否合法。"""
    top_btns = [
        it.center[1] / h
        for it in items
        if norm(it.text) == "购买"
        and 0.85 <= it.center[0] / w <= 0.99
        and it.center[1] / h < CUT_BTN_Y_SOFT
        and not any(abs(it.center[1] / h - ey) < 0.025 for ey in exclude_ys)
    ]
    if not top_btns:
        return None
    btn_y = min(top_btns)

    if btn_y <= CUT_BTN_Y_HARD:
        return btn_y

    paired = [
        (norm(it.text), it.center[0] / w, it.center[1] / h)
        for it in items
        if 0.38 <= it.center[0] / w <= 0.82 and -0.015 <= (btn_y - it.center[1] / h) <= 0.075
    ]
    if not paired:
        return btn_y

    for text, _cx, cy in paired:
        has_bm_char = any(ch in BOOKMARK_FRAGMENT_CHARS for ch in text)
        if cy < INTACT_TEXT_Y_MIN or (cy < 0.118 and has_bm_char):
            return btn_y
    return None


def top_row_is_intact(items: list[OcrItem], w: int, h: int) -> bool:
    """顶行是否完整（按钮位置正常且左侧有完整文字）。用于锁定首行、避免误滑。"""
    for it in items:
        if norm(it.text) != "购买" or not (0.85 <= it.center[0] / w <= 0.99):
            continue
        by = it.center[1] / h
        if by < CUT_BTN_Y_HARD or by > 0.25:
            continue
        for other in items:
            t = norm(other.text)
            if not (0.38 <= other.center[0] / w <= 0.82):
                continue
            if not (-0.015 <= (by - other.center[1] / h) <= 0.075):
                continue
            if len(t) < 2 or t.isdigit():
                continue
            if other.center[1] / h >= INTACT_TEXT_Y_MIN:
                return True
    return False


def find_blocked_bookmarks(items: list[OcrItem], w: int, h: int) -> list[str]:
    """找出"文字是书签、但同一行没有可点购买按钮"的行（多半是第一行被顶部挡住）。"""
    buy_buttons = [
        it
        for it in items
        if (norm(it.text) == "购买" or norm(it.text).endswith("购买"))
        and 0.85 <= it.center[0] / w <= 0.99
        and 0.05 <= it.center[1] / h <= 0.97
    ]
    blocked: list[str] = []
    for it in items:
        t = norm(it.text)
        cx, cy = it.center[0] / w, it.center[1] / h
        if not (0.40 <= cx <= 0.92 and 0.05 <= cy <= 0.30):
            continue
        kind = None
        if any(k in t for k in COVENANT_NAMES):
            kind = "圣约书签"
        elif any(k in t for k in MYSTIC_NAMES):
            kind = "神秘奖牌"
        else:
            kind = _fuzzy_kind(t)
        if kind is None:
            continue
        matched = False
        for btn in buy_buttons:
            dy = btn.center[1] / h - cy
            if -0.015 <= dy <= 0.068:
                matched = True
                break
        if not matched:
            blocked.append(kind)
    return blocked


def _is_buy_btn_lit_green(img: np.ndarray, buy_ry: float) -> bool:
    """购买按钮是否为可买的亮绿/高亮状态（已售罄为深灰）。"""
    h, w = img.shape[:2]
    y1 = max(0, int(h * (buy_ry - 0.024)))
    y2 = min(h, int(h * (buy_ry + 0.024)))
    x1 = max(0, int(w * 0.845))
    x2 = min(w, int(w * 0.965))
    roi = img[y1:y2, x1:x2]
    if roi.size == 0:
        return False
    v_p95 = float(np.percentile(roi.max(axis=2), 95))
    if v_p95 < 175.0:
        return False
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    green_px = (hsv[:, :, 0] >= 32) & (hsv[:, :, 0] <= 92) & (hsv[:, :, 1] >= 65) & (hsv[:, :, 2] >= 100)
    return float(green_px.mean()) >= 0.12 or v_p95 >= 210.0


def find_unbought_bookmark(
    img: np.ndarray,
    items: list[OcrItem],
    exclude_ys: list[float] | None = None,
):
    """查找第一个可买书签：排除 0/1 售罄行、本停靠点已买行、按钮未亮绿的格子。"""
    h, w = img.shape[:2]
    excl = exclude_ys or []
    buy_buttons = [
        it
        for it in items
        if (norm(it.text) == "购买" or norm(it.text).endswith("购买"))
        and 0.85 <= it.center[0] / w <= 0.99
        and 0.05 <= it.center[1] / h <= 0.97
    ]
    sold_out_rows = [
        it.center[1] / h for it in items if "0/1" in norm(it.text) and 0.80 <= it.center[0] / w <= 0.99
    ]

    candidates = sorted(items, key=lambda it: it.center[1])
    for it in candidates:
        t = norm(it.text)
        cx, cy = it.center[0] / w, it.center[1] / h
        if not (0.40 <= cx <= 0.92 and 0.06 <= cy <= 0.985):
            continue

        if any(k in t for k in COVENANT_NAMES):
            kind = "圣约书签"
        elif any(k in t for k in MYSTIC_NAMES):
            kind = "神秘奖牌"
        else:
            kind = _fuzzy_kind(t)
        if kind is None:
            continue

        matched_btn = None
        best_dy = 999.0
        for btn in buy_buttons:
            bx, by = btn.center[0] / w, btn.center[1] / h
            dy = by - cy
            if -0.015 <= dy <= 0.068 and abs(dy - 0.032) < best_dy:
                best_dy = abs(dy - 0.032)
                matched_btn = (bx, by)
        if matched_btn is None:
            continue

        buy_rx, buy_ry = matched_btn
        if any(abs(sy - buy_ry) <= 0.035 for sy in sold_out_rows):
            continue
        if any(abs(ey - buy_ry) <= 0.045 for ey in excl):
            continue
        if not _is_buy_btn_lit_green(img, buy_ry):
            continue

        price = 0
        for it2 in items:
            pxx, pyy = it2.center[0] / w, it2.center[1] / h
            if 0.84 <= pxx <= 0.985 and abs(pyy - buy_ry) <= 0.045:
                digits = norm(it2.text).replace(",", "")
                if digits.isdigit():
                    price = int(digits)
                    break
        if price <= 0:
            price = 280000 if kind == "神秘奖牌" else 184000
        return kind, (round(buy_rx, 3), round(buy_ry, 3)), price

    for btn in buy_buttons:
        by = btn.center[1] / h
        if any(abs(sy - by) <= 0.035 for sy in sold_out_rows):
            continue
        if any(abs(ey - by) <= 0.045 for ey in excl):
            continue
        kind = _icon_kind_at(img, by)
        if kind is None or not _is_buy_btn_lit_green(img, by):
            continue
        return kind, (round(btn.center[0] / w, 3), round(by, 3)), (280000 if kind == "神秘奖牌" else 184000)

    return None


class SecretShopController:
    """秘密商店单页/跨帧决策状态机（纯逻辑可被离线单测与实机主循环共同复用）。"""

    def __init__(self, stop_skystones: int, ocr: Ocr) -> None:
        self.stop_skystones = max(0, int(stop_skystones))
        self.ocr = ocr
        self.last_skystones: int | None = None
        self.pending_jump_val: int | None = None
        self.skystone_below_streak: int = 0

        self.scroll_count: int = 0  # 本页已上滑次数
        self.stop_idx: int = 0      # 当前扫描停靠点（0=顶部,1=中部,2=底部）
        self.pass_idx: int = 0      # 当前是第几遍全页扫描（0=第一遍,1=二次确认）
        self.spent_skystones: int = 0   # 累计消耗天空石
        self.spent_gold: int = 0        # 累计消耗金币
        self.pending_price: int = 0     # 本次待购买商品价格
        self.pending_item_kind: str | None = None
        self.counted_this_popup: bool = False
        self.pending_buy_pt: tuple[float, float] | None = None
        self.last_counted_pt: tuple[float, float] | None = None
        self.bought_ys_at_stop: list[float] = []
        self.refresh_count: int = 0
        self.bought_covenant: int = 0
        self.bought_mystic: int = 0
        self.modal_recheck_count: int = 0  # 弹窗淡入/低亮度连续复核计数

    def _update_skystones(self, img: np.ndarray) -> int | None:
        val = extract_skystones(img, self.ocr, require_bright=True)
        if val is None:
            return self.last_skystones

        if self.last_skystones is None:
            self.last_skystones = val
            self.pending_jump_val = None
        elif val > self.last_skystones + 200:
            # 商店内天空石只会慢慢减少，突然变大说明识别串行了（例如把金币读成天空石）
            self.pending_jump_val = val
            return self.last_skystones
        elif abs(val - self.last_skystones) <= 30:
            # 正常单次消耗 3 颗（或刚进入商店波动），直接采信
            self.last_skystones = val
            self.pending_jump_val = None
        else:
            # 异常大跳变（防单帧粒子遮挡千位/万位导致误停）：连续两帧读到接近值才采信
            if self.pending_jump_val is not None and abs(val - self.pending_jump_val) <= 6:
                self.last_skystones = val
                self.pending_jump_val = None
            else:
                self.pending_jump_val = val
                return self.last_skystones

        if self.last_skystones <= self.stop_skystones:
            self.skystone_below_streak += 1
        else:
            self.skystone_below_streak = 0
        return self.last_skystones

    def _check_modal_fade_or_refresh(
        self, img: np.ndarray, items: list[OcrItem], w: int, h: int, prev_recheck: int
    ) -> str | dict | None:
        """弹窗淡入或整屏 OCR 漏标题兜底：低亮度扫描弹窗正文，连续复核确认后放行刷新，购买弹窗绝不误点。"""
        has_modal_btns = any(
            norm(it.text) in ("取消", "确认", "购买")
            and 0.25 <= it.center[0] / w <= 0.78
            and 0.55 <= it.center[1] / h <= 0.80
            for it in items
        )
        if not has_modal_btns:
            return None
        modal_crop = img[int(h * 0.26) : int(h * 0.58), int(w * 0.28) : int(w * 0.72)]
        if modal_crop.size <= 0:
            return None
        modal_text = norm(
            "".join(it.text for it in self.ocr.read(modal_crop, min_score=0.45, min_brightness=30.0))
        )
        for kw in INSUFFICIENT_KEYWORDS:
            if kw in modal_text:
                return {
                    "type": "stop_error",
                    "reason": f"检测到「{kw}」，为安全保护账号资源已自动停止！",
                }
        has_buy_kw = any(k in modal_text for k in ("购买商品", "确定要购买"))
        has_buy_btn = any(
            norm(it.text) == "购买"
            and 0.25 <= it.center[0] / w <= 0.78
            and 0.55 <= it.center[1] / h <= 0.80
            for it in items
        )
        has_confirm_btn = any(
            norm(it.text) == "确认"
            and 0.50 <= it.center[0] / w <= 0.72
            and 0.55 <= it.center[1] / h <= 0.72
            for it in items
        )
        has_cancel_btn = any(
            norm(it.text) == "取消"
            and 0.30 <= it.center[0] / w <= 0.50
            and 0.55 <= it.center[1] / h <= 0.72
            for it in items
        )
        is_refresh_modal = (
            not has_buy_kw
            and not has_buy_btn
            and (
                (
                    ("立即更新吗" in modal_text or ("消耗天空石" in modal_text and "立即更新" in modal_text))
                    and (has_confirm_btn or has_cancel_btn)
                )
                or (
                    has_confirm_btn
                    and any(k in modal_text for k in ("立即更新", "消耗天空石"))
                )
            )
        )
        if is_refresh_modal and prev_recheck >= 2:
            return "CONFIRM_REFRESH"
        if any(k in modal_text for k in ("立即更新", "消耗天空石", "购买商品", "确定要购买")):
            self.modal_recheck_count = prev_recheck + 1
            return {
                "type": "recheck",
                "wait_after": 0.18,
                "desc": "⏳ 确认弹窗淡入中，等待弹窗完全就绪...",
            }
        return None

    def analyze(self, img: np.ndarray, items: list[OcrItem]) -> dict:
        prev_modal_recheck = self.modal_recheck_count
        self.modal_recheck_count = 0
        h, w = img.shape[:2]
        all_text = norm("".join(it.text for it in items))

        # 1. 金币不足 / 天空石不足 / 充值弹窗安全拦截
        for kw in INSUFFICIENT_KEYWORDS:
            if kw in all_text:
                return {
                    "type": "stop_error",
                    "reason": f"检测到「{kw}」，为安全保护账号资源已自动停止！",
                }

        # 2. 处理「购买商品」二次确认弹窗
        if "购买商品" in all_text or "确定要购买该商品" in all_text:
            popup_item: str | None = None
            for it in items:
                cx, cy = it.center[0] / w, it.center[1] / h
                if 0.35 <= cx <= 0.72 and 0.35 <= cy <= 0.60:
                    t = norm(it.text)
                    if any(k in t for k in COVENANT_NAMES):
                        popup_item = "圣约书签"
                        break
                    if any(k in t for k in MYSTIC_NAMES):
                        popup_item = "神秘奖牌"
                        break

            if popup_item is not None:
                confirm_pt = BUY_CONFIRM_POS
                for it in items:
                    if norm(it.text) == "购买" and 0.55 <= it.center[0] / w <= 0.76 and 0.63 <= it.center[1] / h <= 0.78:
                        confirm_pt = (round(it.center[0] / w, 3), round(it.center[1] / h, 3))
                        break
                if not self.counted_this_popup:
                    if popup_item == "圣约书签":
                        self.bought_covenant += 1
                    else:
                        self.bought_mystic += 1
                    self.spent_gold += int(self.pending_price or 0)
                    default_p = 280000 if popup_item == "神秘奖牌" else 184000
                    actual_p = int(self.pending_price or 0) or default_p
                    self.last_counted_item = popup_item
                    self.last_counted_price = actual_p
                    self.last_counted_pt = self.pending_buy_pt
                    if self.pending_buy_pt is not None:
                        self.bought_ys_at_stop.append(float(self.pending_buy_pt[1]))
                    # 不在这里写统计：等余额验证通过后再记（避免取消/未生效也计数）
                    self.pending_price = 0
                    self.counted_this_popup = True
                self.pending_item_kind = None
                return {
                    "type": "click_ratio",
                    "action_key": "确认购买书签",
                    "pos": confirm_pt,
                    "wait_after": 0.55,
                    "desc": f"💰 确认购买【{popup_item}】（累计：圣约 x{self.bought_covenant}，神秘 x{self.bought_mystic}）",
                }

            # 安全兜底：万一弹窗不是书签，绝不购买 -> 点取消
            cancel_pt = BUY_CANCEL_POS
            for it in items:
                if norm(it.text) == "取消" and 0.25 <= it.center[0] / w <= 0.48 and 0.63 <= it.center[1] / h <= 0.78:
                    cancel_pt = (round(it.center[0] / w, 3), round(it.center[1] / h, 3))
                    break
            return {
                "type": "click_ratio",
                "action_key": "取消误点商品",
                "pos": cancel_pt,
                "wait_after": 0.35,
                "desc": "🛡 购买确认弹窗内未识别到目标书签 → 自动点击「取消」",
            }

        self.counted_this_popup = False

        # 3. 处理「要消耗天空石立即更新吗？」确认弹窗（整屏漏标题时允许在连续复核后由裁剪区兜底确认）
        refresh_from_all = "立即更新吗" in all_text or ("消耗天空石" in all_text and "立即更新" in all_text)
        refresh_from_crop = False
        if not refresh_from_all:
            modal_decision = self._check_modal_fade_or_refresh(img, items, w, h, prev_modal_recheck)
            if modal_decision == "CONFIRM_REFRESH":
                refresh_from_crop = True
                all_text = "立即更新吗"
            elif isinstance(modal_decision, dict):
                return modal_decision
        if "立即更新吗" in all_text or ("消耗天空石" in all_text and "立即更新" in all_text):
            if self.skystone_below_streak >= 1 and self.last_skystones is not None and self.last_skystones <= self.stop_skystones:
                cancel_pt = REFRESH_CANCEL_POS
                for it in items:
                    if norm(it.text) == "取消" and 0.30 <= it.center[0] / w <= 0.50 and 0.55 <= it.center[1] / h <= 0.72:
                        cancel_pt = (round(it.center[0] / w, 3), round(it.center[1] / h, 3))
                        break
                return {
                    "type": "cancel_and_done",
                    "pos": cancel_pt,
                    "reason": f"当前剩余天空石 {self.last_skystones:,} 颗，已达设定停止线（≤ {self.stop_skystones:,} 颗）！",
                }

            ok_pt = REFRESH_CONFIRM_POS
            for it in items:
                if norm(it.text) == "确认" and 0.50 <= it.center[0] / w <= 0.72 and 0.55 <= it.center[1] / h <= 0.72:
                    ok_pt = (round(it.center[0] / w, 3), round(it.center[1] / h, 3))
                    break
            self.scroll_count = 0
            self.stop_idx = 0
            self.pass_idx = 0
            self.bought_ys_at_stop.clear()
            self.refresh_count += 1
            return {
                "type": "click_ratio",
                "action_key": "确认刷新商店",
                "pos": ok_pt,
                "wait_after": 0.40,
                "desc": f"🔄 确认消耗 3 天空石刷新商店（第 {self.refresh_count} 次刷新）{'（弹窗裁剪兜底）' if refresh_from_crop else ''}",
            }

        # 4. 弹窗淡入动画期兜底（确认/取消已出现但标题文字尚在渐显，低亮度扫描弹窗正文防误停/防漏警）
        has_modal_btns = any(
            norm(it.text) in ("取消", "确认", "购买") and 0.25 <= it.center[0] / w <= 0.78 and 0.55 <= it.center[1] / h <= 0.80
            for it in items
        )
        if has_modal_btns:
            modal_crop = img[int(h * 0.26) : int(h * 0.58), int(w * 0.28) : int(w * 0.72)]
            if modal_crop.size > 0:
                modal_text = norm("".join(it.text for it in self.ocr.read(modal_crop, min_score=0.45, min_brightness=30.0)))
                for kw in INSUFFICIENT_KEYWORDS:
                    if kw in modal_text:
                        return {
                            "type": "stop_error",
                            "reason": f"检测到「{kw}」，为安全保护账号资源已自动停止！",
                        }
                if any(k in modal_text for k in ("立即更新", "消耗天空石", "购买商品", "确定要购买")):
                    return {
                        "type": "recheck",
                        "wait_after": 0.18,
                        "desc": "⏳ 确认弹窗淡入中，等待弹窗完全就绪...",
                    }

        # 5. 断线重连提示自动重试
        if ("点击重试" in all_text or "重试" in all_text) and any(
            k in all_text for k in ("网络", "连接", "超时", "断开", "重新")
        ):
            for it in items:
                if "重试" in norm(it.text):
                    return {
                        "type": "click_ratio",
                        "action_key": "网络重试",
                        "pos": (round(it.center[0] / w, 3), round(it.center[1] / h, 3)),
                        "wait_after": 0.55,
                        "desc": f"🌐 网络波动弹窗 → 点击「{it.text}」",
                    }

        # 5. 校验当前处于「秘密商店」主页面
        in_shop = ("秘密商店" in all_text) or any(
            "立即更新" in norm(it.text) and it.center[0] / w <= 0.35 and it.center[1] / h >= 0.82
            for it in items
        )
        if not in_shop:
            return {
                "type": "wait_shop",
                "desc": "未识别到「秘密商店」界面（请在游戏里打开秘密商店界面）",
            }

        # 6. 读取当前明亮画面顶栏天空石（不受弹窗遮罩影响）
        stones = self._update_skystones(img)
        stone_tag = f"{stones:,}" if stones is not None else "未知"

        # 7. 扫描当前页面是否存在未购买的「圣约书签」或「神秘奖牌」
        found = find_unbought_bookmark(img, items, exclude_ys=self.bought_ys_at_stop)
        if found is not None:
            kind, buy_pt, price = found
            self.pending_item_kind = kind
            self.pending_price = price
            self.pending_buy_pt = buy_pt
            return {
                "type": "click_ratio",
                "action_key": f"购买{kind}",
                "pos": buy_pt,
                "wait_after": 0.28,
                "desc": f"✨ 发现未购买的【{kind}】！点击购买按钮 {buy_pt}（剩余天空石 {stone_tag}）",
            }

        # 8. 停靠点扫描：顶部 → 中部 → 底部；到底后如需二次确认先回顶部再扫一遍
        if self.stop_idx < len(SHOP_STOP_DRAGS) - 1:
            self.stop_idx += 1
            self.bought_ys_at_stop.clear()
            drag = SHOP_STOP_DRAGS[self.stop_idx]
            self.scroll_count += 1
            return {
                "type": "drag_ratio",
                "action_key": "上滑秘密商店",
                "from": drag[0],
                "to": drag[1],
                "duration": SHOP_DRAG_DURATION,
                "steps": SHOP_DRAG_STEPS,
                "wait_after": 0.30,
                "desc": (
                    f"📜 停靠点 {self.stop_idx + 1}/{len(SHOP_STOP_DRAGS)}"
                    f"（第 {self.pass_idx + 1} 遍扫描，剩余天空石 {stone_tag}）"
                ),
            }

        if SHOP_SECOND_PASS and self.pass_idx == 0:
            # 二次确认只补底部：半截行最容易漏，轻轻顶上来再扫一次即可（省时间）
            self.pass_idx = 1
            drag = SHOP_BOTTOM_RESCAN_DRAG
            return {
                "type": "drag_ratio",
                "action_key": "底部补扫",
                "from": drag[0],
                "to": drag[1],
                "duration": SHOP_DRAG_DURATION,
                "steps": SHOP_DRAG_STEPS,
                "wait_after": 0.30,
                "desc": f"🔁 底部补扫：把半截行顶上来再确认一次（剩余天空石 {stone_tag}）",
            }

        # 注意：扫描状态只在真正刷新后重置（见确认刷新分支），否则会反复重扫

        # 9. 本页全 6 栏均已扫描/买完，检查是否达到用户设定的剩余天空石下限
        if self.skystone_below_streak >= 2 and self.last_skystones is not None:
            return {
                "type": "done",
                "reason": (
                    f"当前剩余天空石 {self.last_skystones:,} 颗，已到达您设定的停止线"
                    f"（剩余 ≤ {self.stop_skystones:,} 颗）！"
                ),
            }

        # 10. 尚未到达停止线 -> 点击左下角「立即更新」（若最后差几颗还没双帧确认再刷前，若已 <= 下限但 streak==1，先多采一帧确认而不是盲目刷新！）
        if self.skystone_below_streak == 1:
            return {
                "type": "recheck",
                "wait_after": 0.20,
                "desc": f"🔍 检测到天空石 {stone_tag} 已接近停止线 ≤ {self.stop_skystones:,}，再次复核确认...",
            }

        refresh_pt = REFRESH_BTN_POS
        for it in items:
            if "立即更新" in norm(it.text) and it.center[0] / w <= 0.35 and it.center[1] / h >= 0.82:
                refresh_pt = (round(it.center[0] / w, 3), round(it.center[1] / h, 3))
                break
        self.spent_skystones += SHOP_REFRESH_COST

        return {
            "type": "click_ratio",
            "action_key": "点击立即更新",
            "pos": refresh_pt,
            "wait_after": 0.28,
            "desc": f"🔄 本页 6 栏无漏网书签（剩余天空石 {stone_tag} / 停止线 {self.stop_skystones:,}）→ 点击「立即更新」",
        }


class ShopBot:
    def __init__(self, win: GameWindow, ocr: Ocr, stop_skystones: int) -> None:
        self.win = win
        self.ocr = ocr
        self.ctrl = SecretShopController(stop_skystones, ocr)
        self.inspected_gear: set[str] = set()   # 已检查的 85 装备（名称|价格）
        self.bought_gear: set[str] = set()      # 已购买的红装（防重复）
        self.gear_cfg = self._load_gear_cfg()
        # 顶部切行补救状态（Gemini 设计）
        self._btn_ys_prev: list[float] = []
        self._stable_layout = 0
        self._pull_down_count = 0
        self._top_row_resolved = False
        self._skipped_top_ys: list[float] = []
        self._bought_rows_y: list[float] = []
        self._last_refresh_seen = -1
        # 余额与验证
        self.gold: int | None = None
        self.sky: int | None = None
        self._bal_prev: tuple[int | None, int | None] | None = None
        self._pending: dict | None = None       # 待验证的动作
        self._pre_refresh_sig: np.ndarray | None = None  # 刷新前商品图标区缩略指纹
        self.start_gold: int | None = None
        self.start_sky: int | None = None
        self.paused = False
        self._key_state = {VK_F8: False, VK_F10: False}
        self._next_sleep = 0.18
        self.last_action_key = ""
        self.repeat_count = 0
        self.recheck_count = 0
        self.last_action_small: np.ndarray | None = None
        self.not_in_shop_since: float | None = None
        self._last_drag_sig: np.ndarray | None = None
        self._prev_small: np.ndarray | None = None
        self._stable_hits: int = 0
        self._last_items: list[OcrItem] | None = None

    @staticmethod
    def _union_items(a: list[OcrItem], b: list[OcrItem], tol: float = 0.02) -> list[OcrItem]:
        """两帧 OCR 结果取并集：同位置（容差内）只保留一条，其余合并。"""
        out: list[OcrItem] = list(a)
        for it in b:
            same = False
            for old in out:
                if (
                    abs(it.center[0] - old.center[0]) <= tol * 1600
                    and abs(it.center[1] - old.center[1]) <= tol * 900
                ):
                    same = True
                    break
            if not same:
                out.append(it)
        return out

    def _pressed(self, vk: int) -> bool:
        down = bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
        was = self._key_state[vk]
        self._key_state[vk] = down
        return down and not was

    def poll_hotkeys(self) -> bool:
        if self._pressed(VK_F10):
            log("⏹ 收到 F10 热键，正在退出秘密商店刷新程序。")
            return False
        if self._pressed(VK_F8):
            self.paused = not self.paused
            if self.paused:
                log("⏸ 已手动暂停（再按一次 F8 继续，按 F10 退出）")
            else:
                log("▶ 继续自动刷新秘密商店！")
                self.repeat_count = 0
                self.recheck_count = 0
                self.ctrl.modal_recheck_count = 0
                self.last_action_small = None
                self.not_in_shop_since = None
        return True

    def _stop_reason(self) -> str | None:
        """金币/天空石停止线判定（模式来自 rules.yaml：shop_stop_mode）。"""
        try:
            from core import load_rules_cfg

            st = (load_rules_cfg().get("settings") or {})
            stop_gold = int(st.get("shop_stop_gold", 1000000) or 0)
            mode = str(st.get("shop_stop_mode", "sky") or "sky")
        except Exception:  # noqa: BLE001
            stop_gold, mode = 1000000, "sky"
        sky = getattr(self.ctrl, "last_skystones", None)
        gold = self.gold
        stop_sky = getattr(self.ctrl, "stop_skystones", 0)
        sky_hit = sky is not None and sky <= stop_sky
        gold_hit = gold is not None and gold <= stop_gold
        if mode == "gold":
            return f"金币 {gold:,} ≤ {stop_gold:,}" if gold_hit else None
        if mode == "either":
            if sky_hit:
                return f"天空石 {sky:,} ≤ {stop_sky:,}"
            if gold_hit:
                return f"金币 {gold:,} ≤ {stop_gold:,}"
            return None
        return f"天空石 {sky:,} ≤ {stop_sky:,}" if sky_hit else None

    @staticmethod
    def _beep_alert() -> None:
        for freq in (1000, 1300, 1000):
            try:
                winsound.Beep(freq, 220)
            except Exception:  # noqa: BLE001
                pass

    def _audit(self, img, note: str, save_image: bool = True) -> None:
        """购买审计：把发现/购买瞬间的截图和记录写入 debug/shop/，方便事后核对有没有漏买。"""
        try:
            d = ROOT / "debug" / "shop"
            d.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            if save_image and img is not None:
                cv2.imwrite(str(d / f"{ts}_{int(time.time() * 1000) % 1000:03d}.png"), img)
            with open(d / "购物记录.log", "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {note}\n")
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _load_gear_cfg() -> dict:
        try:
            from core import load_rules_cfg

            st = (load_rules_cfg(ROOT / "rules.yaml").get("settings") or {})
            return {
                "enabled": bool(st.get("gear_auto_buy", False)),
                "score27": bool(st.get("gear_cond_score27", False)),
                "speed3": bool(st.get("gear_cond_speed3", False)),
                "combo": bool(st.get("gear_cond_combo", False)),
                "price": int(st.get("gear_price", 1400000)),
            }
        except Exception:  # noqa: BLE001
            return {"enabled": False, "score27": False, "speed3": False, "combo": False, "price": 1400000}

    def _gold_now(self, items) -> int | None:
        """从顶栏读金币（金币在钻石左边）。"""
        for it in items:
            t = "".join(str(it.text).split())
            if not t.replace(",", "").isdigit() or len(t) < 6:
                continue
            cx, cy = it.center
            # 顶栏区域、位置偏左（金币）
            if cy < 0.09 * 1023 and 0.50 <= cx / 1819 <= 0.70:
                return int(t.replace(",", ""))
        return None

    def _gear_meets(self, info: dict) -> bool:
        cfg = self.gear_cfg
        if not cfg["enabled"]:
            return False
        checks = []
        if cfg["score27"]:
            checks.append((info.get("score") or 0) >= 27)
        if cfg["speed3"]:
            checks.append((info.get("speed") or 0) >= 3)
        if cfg["combo"]:
            checks.append(bool(info.get("critdmg")) and bool(info.get("crit")) and (info.get("speed") or 0) > 0)
        return bool(checks) and any(checks)

    def _buy_gear(self, cand: dict, info: dict, items, img) -> None:
        """点「购买」→ 确认弹窗 → 购买；只认配置价格与传说品质。"""
        price = int(cand.get("price") or 0)
        if price != int(self.gear_cfg["price"]):
            log(f"💤 红装「{cand['name']}」价格 {price:,} ≠ {self.gear_cfg['price']:,}，跳过")
            return
        if (info.get("quality") or "") != "传说":
            log(f"💤 红装「{cand['name']}」品质识别为「{info.get('quality')}」，跳过")
            return
        gold = self._gold_now(items)
        if gold is not None and gold < price:
            log(f"💤 金币不足（{gold:,} < {price:,}），跳过「{cand['name']}」")
            return
        # 找该行的「购买」按钮
        buy_pt = None
        for it in items:
            if "".join(str(it.text).split()) != "购买":
                continue
            if it.center[0] / 1819 < 0.85:
                continue
            if abs(it.center[1] - int(cand["y"] * 1023)) > 60:
                continue
            buy_pt = (it.center[0] / 1819, it.center[1] / 1023)
            break
        if buy_pt is None:
            log(f"⚠ 没找到「购买」按钮，跳过「{cand['name']}」")
            return

        win = self.win
        win.click_ratio(*buy_pt, clicks=1)
        time.sleep(0.35)
        frame = win.capture("auto")
        popup = self.ocr.read(frame, 0.5)
        pop_text = "".join("".join(str(i.text).split()) for i in popup)
        if "确定要购买" not in pop_text and "购买商品" not in pop_text:
            log(f"⚠ 「{cand['name']}」没有出现购买确认弹窗 → 放弃")
            return
        if cand["name"] not in pop_text:
            log(f"⚠ 弹窗商品名与预期不符（{pop_text[:30]}）→ 取消")
            for i in popup:
                if "".join(str(i.text).split()) == "取消":
                    win.click_ratio(i.center[0] / 1819, i.center[1] / 1023, clicks=1)
                    break
            return
        # 弹窗里点「购买」
        for i in popup:
            if "".join(str(i.text).split()) == "购买" and i.center[0] / 1819 > 0.55:
                win.click_ratio(i.center[0] / 1819, i.center[1] / 1023, clicks=1)
                break
        time.sleep(0.45)
        self.bought_gear.add(f"{cand['name']}|{price}")
        log(
            f"🛒 已购买红装「{cand['name']}」分数={info.get('score')} 速度={info.get('speed')} "
            f"暴击={info.get('crit')} 暴伤={info.get('critdmg')} 价格={price:,}"
        )
        try:
            stats_db.log_event(
                "gear_buy",
                name=cand["name"],
                quality=info.get("quality"),
                score=info.get("score"),
                speed=info.get("speed"),
                crit=info.get("crit"),
                critdmg=info.get("critdmg"),
                price=price,
            )
        except Exception:  # noqa: BLE001
            pass

    # ---------- 余额读取与动作验证 ----------
    @staticmethod
    def _parse_balances(items, img) -> tuple[int | None, int | None]:
        """从顶栏读 (金币, 天空石)。金币在左、天空石在右。"""
        h, w = img.shape[:2]
        gold = sky = None
        for it in items:
            t = "".join(str(it.text).split())
            if not t.replace(",", "").isdigit():
                continue
            cx, cy = it.center[0] / w, it.center[1] / h
            if cy > 0.10:
                continue
            if 0.50 <= cx < 0.685:
                gold = int(t.replace(",", ""))
            elif 0.685 <= cx <= 0.80:
                sky = int(t.replace(",", ""))
        return gold, sky

    @staticmethod
    def _shelf_sig(img: np.ndarray) -> np.ndarray:
        """按比例坐标提取商品图标区（x:0.385~0.520, y:0.14~0.82）的 16x32 缩略灰度指纹。"""
        h, w = img.shape[:2]
        roi = img[int(h * 0.14): int(h * 0.82), int(w * 0.385): int(w * 0.520)]
        if roi.size == 0:
            return np.zeros((32, 16), dtype=np.int16)
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        return cv2.resize(gray, (16, 32), interpolation=cv2.INTER_AREA).astype(np.int16)

    @staticmethod
    def _in_refresh_popup(items, img: np.ndarray) -> bool:
        """判断是否仍处于确认刷新弹窗（含遮罩压暗顶栏判定）。"""
        h, w = img.shape[:2]
        band = img[int(h * 0.010): int(h * 0.090), int(w * 0.35): int(w * 0.99)]
        if band.size > 0 and int(band.max()) < 200:
            return True
        all_text = norm("".join(it.text for it in items))
        if "立即更新吗" in all_text or ("消耗天空石" in all_text and "立即更新" in all_text):
            return True
        return any(
            norm(it.text) in ("取消", "确认")
            and 0.25 <= it.center[0] / w <= 0.78
            and 0.55 <= it.center[1] / h <= 0.80
            for it in items
        )

    def _track_balances(self, items, img) -> None:
        """优先用 2 倍放大顶栏直读金币与天空石（不走双帧并集缓存）。"""
        raw_gold, raw_sky = self._parse_balances(items, img)
        prev_gold, prev_sky = self._bal_prev if self._bal_prev else (None, None)

        if self._pending is not None:
            cur_sky = extract_skystones(img, self.ocr, require_bright=True)
            if cur_sky is not None and getattr(self.ctrl, "last_skystones", None) is not None:
                if abs(cur_sky - self.ctrl.last_skystones) <= 30:
                    self.ctrl.last_skystones = cur_sky

        if _LAST_TOPBAR_GOLD is not None:
            self.gold = _LAST_TOPBAR_GOLD
        elif raw_gold is not None and (raw_gold == prev_gold or self._pending is not None):
            self.gold = raw_gold

        if getattr(self.ctrl, "last_skystones", None) is not None:
            self.sky = int(self.ctrl.last_skystones)
        elif raw_sky is not None and raw_sky == prev_sky:
            self.sky = raw_sky

        self._bal_prev = (raw_gold, raw_sky)
        if self.start_gold is None and self.gold is not None:
            self.start_gold = self.gold
        if self.start_sky is None and self.sky is not None:
            self.start_sky = self.sky
        self._check_pending(items, img)

    def _check_pending(self, items=None, img=None) -> None:
        """验证上一笔动作：购买支持「金币减少」或「货架变灰/售罄」双通道。"""
        p = self._pending
        if not p:
            return
        now = time.time()
        ok = False
        if p["kind"] == "refresh":
            before = p.get("sky_before")
            if before is None or self.sky is None:
                try:
                    stats_db.log_event("refresh", sky=int(SHOP_REFRESH_COST), unverified=True)
                except Exception:  # noqa: BLE001
                    pass
                self._pending = None
                return
            if (before - 6) <= self.sky <= (before - 1):
                ok = True
        elif p["kind"] == "buy":
            before = p.get("gold_before")
            _it = p.get("item") or "圣约书签"
            _price = int(p.get("price") or 0) or (280000 if _it == "神秘奖牌" else 184000)

            if before is not None and self.gold is not None and self.gold < int(before) - 1000:
                ok = True

            if not ok and img is not None and items is not None:
                all_txt = norm("".join(i.text for i in items))
                in_buy_popup = ("购买商品" in all_txt) or ("确定要购买" in all_txt)
                has_err = any(kw in all_txt for kw in INSUFFICIENT_KEYWORDS)
                in_shop_main = ("秘密商店" in all_txt) or any("立即更新" in norm(i.text) for i in items)
                if in_shop_main and not in_buy_popup and not has_err:
                    buy_pt = p.get("buy_pt")
                    if buy_pt is not None and not _is_buy_btn_lit_green(img, float(buy_pt[1])):
                        ok = True
                    if not ok and find_unbought_bookmark(img, items, exclude_ys=[]) is None:
                        ok = True

            if not ok and (before is None or self.gold is None) and now >= p["deadline"]:
                ok = True

        if ok:
            if p["kind"] == "buy":
                _it2 = p.get("item") or "圣约书签"
                _pr2 = int(p.get("price") or 0) or (280000 if _it2 == "神秘奖牌" else 184000)
                if p.get("gold_before") is not None and self.gold == p.get("gold_before"):
                    self.gold = max(0, int(self.gold) - _pr2)
                try:
                    stats_db.log_event(
                        "buy",
                        item=_it2,
                        qty=(50 if _it2 == "神秘奖牌" else 5),
                        gold=_pr2,
                    )
                except Exception:  # noqa: BLE001
                    pass
            elif p["kind"] == "refresh":
                try:
                    stats_db.log_event("refresh", sky=int(SHOP_REFRESH_COST))
                except Exception:  # noqa: BLE001
                    pass
            self._pending = None
            return

        if now < p["deadline"]:
            return

        if p["kind"] == "refresh" and img is not None and items is not None:
            prev_sig = p.get("shelf_sig")
            if prev_sig is not None and not self._in_refresh_popup(items, img):
                cur_sig = self._shelf_sig(img)
                if float(np.abs(cur_sig - prev_sig).mean()) >= 6.0:
                    self.ctrl.spent_skystones = max(0, self.ctrl.spent_skystones - int(SHOP_REFRESH_COST))
                    try:
                        stats_db.log_event("refresh", sky=0, free=True)
                    except Exception:  # noqa: BLE001
                        pass
                    self._pending = None
                    log("🎁 不在确认弹窗且商品区指纹已变化（天空石未变）→ 按免费刷新放行")
                    return

        self._pending = None
        if p["kind"] == "refresh":
            self.ctrl.refresh_count = max(0, self.ctrl.refresh_count - 1)
            self.ctrl.spent_skystones = max(0, self.ctrl.spent_skystones - int(SHOP_REFRESH_COST))
        else:
            if p.get("item") == "圣约书签":
                self.ctrl.bought_covenant = max(0, self.ctrl.bought_covenant - 1)
            else:
                self.ctrl.bought_mystic = max(0, self.ctrl.bought_mystic - 1)
            self.ctrl.spent_gold = max(0, self.ctrl.spent_gold - int(p.get("price") or 0))
            if getattr(self.ctrl, "bought_ys_at_stop", None):
                self.ctrl.bought_ys_at_stop.pop()
        self.paused = True
        log("=" * 64)
        log(
            f"⚠ 账目验证失败：{'刷新' if p['kind'] == 'refresh' else '购买'}后状态未变化 → "
            f"已回滚计数并暂停（金币 {self.gold} / 天空石 {self.sky}，F8 继续）"
        )
        log("=" * 64)
        self._beep_alert()

    def _arm_pending(self, kind: str, **kw) -> None:
        self._pending = {
            "kind": kind,
            "deadline": time.time() + 4.0,
            "gold_before": self.gold,
            "sky_before": self.sky,
            **kw,
        }

    def _reconcile(self) -> bool:
        """用起始/结束余额差校验累计消耗；不一致 → 暂停并说明（返回 False）。"""
        problems: list[str] = []
        if self.start_gold is not None and self.gold is not None:
            actual = self.start_gold - self.gold
            if actual != int(self.ctrl.spent_gold):
                problems.append(f"金币：余额差 {actual:,} ≠ 累计记录 {int(self.ctrl.spent_gold):,}")
        if self.start_sky is not None and self.sky is not None:
            actual = self.start_sky - self.sky
            if actual != int(self.ctrl.spent_skystones):
                problems.append(f"天空石：余额差 {actual:,} ≠ 累计记录 {int(self.ctrl.spent_skystones):,}")
        if not problems:
            return True
        self.paused = True
        log("=" * 64)
        log("⚠ 账目核对不一致（可能有一次操作没被正确计数）：")
        for x in problems:
            log(f"   · {x}")
        log("   已暂停，请人工确认后再按【F8】继续，或按【F10】退出。")
        log("=" * 64)
        self._beep_alert()
        return False

    def _save_shop_debug(self, img, items, tag: str) -> str:
        try:
            import cv2 as _cv2

            d = ROOT / "debug" / "shop"
            d.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%m%d_%H%M%S")
            _cv2.imencode(".png", img)[1].tofile(str(d / f"{stamp}_{tag}.png"))
            h, w = img.shape[:2]
            lines = [f"{it.text}\t{it.score:.2f}\t({it.center[0]/w:.3f},{it.center[1]/h:.3f})" for it in items]
            (d / f"{stamp}_{tag}.txt").write_text("\n".join(lines), encoding="utf-8")
            return f"{stamp}_{tag}.png"
        except Exception:  # noqa: BLE001
            return ""

    def _recover_cut_row(self, items, img) -> bool:
        """顶部被切/被挡的行：先向下轻滑露出再买；两次仍不行 → 存图 + 拉黑跳过。

        只在「即将刷新」时调用，保证"先买能买的，再补救"。
        """
        w, h = img.shape[1], img.shape[0]

        # 换页重置
        if self.ctrl.refresh_count != self._last_refresh_seen:
            self._last_refresh_seen = self.ctrl.refresh_count
            self._pull_down_count = 0
            self._top_row_resolved = False
            self._skipped_top_ys = []
            self._bought_rows_y = []
            self._btn_ys_prev = []
            self._stable_layout = 0

        # Step 0：布局是否静止（比较「购买」按钮 y 位移）
        curr = sorted(
            it.center[1] / h
            for it in items
            if norm(it.text) == "购买" and 0.85 <= it.center[0] / w <= 0.99
        )
        if curr and self._btn_ys_prev and len(curr) == len(self._btn_ys_prev):
            shift = max(abs(a - b) for a, b in zip(curr, self._btn_ys_prev))
            self._stable_layout = self._stable_layout + 1 if shift <= LAYOUT_SETTLE_SHIFT else 1
        else:
            self._stable_layout = 1 if curr else 0
        self._btn_ys_prev = curr

        # Step 2：顶行完整（普通商品）→ 锁定，之后不再为它下滑
        if not self._top_row_resolved and top_row_is_intact(items, w, h):
            self._top_row_resolved = True

        # Guard 3：必须已静止 2 帧
        if self._stable_layout < 2:
            return False

        blocked = find_blocked_bookmarks(items, w, h)
        cut_y = None
        if not self._top_row_resolved:
            cut_y = top_row_looks_cut_geometric(items, w, h, self._skipped_top_ys)
        if not blocked and cut_y is None:
            return False

        suspect = cut_y if cut_y is not None else 0.15

        # Step 5：超过 2 次仍不行 → 存图 + 拉黑 + 允许刷新
        if self._pull_down_count >= 2:
            name = self._save_shop_debug(img, items, "cut_skip")
            self._skipped_top_ys.append(float(suspect))
            self._top_row_resolved = True
            log(
                f"⚠ 顶部商品行连续 2 次下滑仍无法完整显示 → 已存图 debug\\shop\\{name or '(失败)'}，"
                "本页跳过该行"
            )
            return False

        # Step 5：向下轻滑（内容下移，把被切的行拉下来）
        self._pull_down_count += 1
        self._bought_rows_y.clear()
        log(f"🖱 顶部商品行被遮挡 → 向下轻滑露出（第 {self._pull_down_count} 次）")
        self.win.drag_ratio(0.62, 0.25, 0.62, 0.38, duration=0.28, steps=14)
        time.sleep(POST_PULL_SETTLE_SEC)
        self._btn_ys_prev = []
        self._stable_layout = 0
        self._last_items = None
        self._stable_hits = 0
        self._next_sleep = 0.05
        return True

    def _inspect_gear(self, items, img) -> None:
        """长按查看 85 装备详情并记录样本（P1：不购买）。"""
        import gear as gear_mod

        text_all = "".join(("".join(str(it.text).split())) for it in items)
        if any(k in text_all for k in ("立即更新吗", "确定要购买", "购买商品")):
            return
        cands = gear_mod.find_candidates(items, img.shape[1], img.shape[0])
        if not cands:
            return
        for cand in cands:
            key = f"{cand['name']}|{cand['price']}"
            if key in self.inspected_gear:
                continue
            if len(self.inspected_gear) > 300:
                self.inspected_gear.clear()
            info = gear_mod.inspect(self.win, self.ocr, cand)
            self.inspected_gear.add(key)
            if not info:
                log(f"🔎 85装备「{cand['name']}」长按后没抓到详情，跳过")
                return
            sample = gear_mod.save_sample(info["frame"], cand["name"])
            log(
                f"🔎 85装备「{cand['name']}」品质={info.get('quality') or '?'} "
                f"分数={info.get('score')} 速度={info.get('speed')} "
                f"暴击={info.get('crit')} 暴伤={info.get('critdmg')} 价格={cand['price']:,}"
                + (f"（样本 {sample.name}）" if sample else "")
            )
            try:
                stats_db.log_event(
                    "gear",
                    name=cand["name"],
                    quality=info.get("quality"),
                    score=info.get("score"),
                    speed=info.get("speed"),
                    crit=info.get("crit"),
                    critdmg=info.get("critdmg"),
                    price=cand["price"],
                )
            except Exception:  # noqa: BLE001
                pass
            # 满足勾选条件 → 自动购买（价格/品质/金币三重保护）
            if self._gear_meets(info) and f"{cand['name']}|{cand['price']}" not in self.bought_gear:
                log(f"🎯 红装「{cand['name']}」满足勾选条件 → 尝试购买")
                self._buy_gear(cand, info, items, img)
            return

    def _print_summary(self, headline: str) -> None:
        stones = self.ctrl.last_skystones
        stone_s = f"{stones:,} 颗" if stones is not None else "未知"
        log("=" * 64)
        log(f"🎉 {headline}")
        self._audit(None, f"结束统计：刷新 {self.ctrl.refresh_count} 次，圣约 +{self.ctrl.bought_covenant}，神秘 +{self.ctrl.bought_mystic}", save_image=False)
        log(
            f"📊 本次战果统计：共刷新 {self.ctrl.refresh_count} 次 | "
            f"圣约书签 +{self.ctrl.bought_covenant} 组 | "
            f"神秘奖牌 +{self.ctrl.bought_mystic} 组"
        )
        log(
            f"💎 消耗天空石 {self.ctrl.spent_skystones:,} 颗 | "
            f"💰 消耗金币 {self.ctrl.spent_gold:,} | "
            f"当前剩余天空石：{stone_s}"
        )
        self._audit(
            None,
            f"结束统计：刷新 {self.ctrl.refresh_count} 次，圣约 +{self.ctrl.bought_covenant}，"
            f"神秘 +{self.ctrl.bought_mystic}，消耗天空石 {self.ctrl.spent_skystones}，"
            f"消耗金币 {self.ctrl.spent_gold}",
            save_image=False,
        )
        log("=" * 64)
        self._beep_alert()

    def step(self) -> bool:
        _reason = self._stop_reason()
        if _reason and self._pending is None:
            log("=" * 64)
            log(f"🛑 达到停止线（{_reason}）→ 已暂停，F8 可继续")
            log("=" * 64)
            self.paused = True
            self._beep_alert()
            return True
        """执行单步；返回 False 表示已达成目标停止并准备退出。"""
        if not self.win.is_alive():
            hwnd = find_game_window()
            if not hwnd:
                self.paused = True
                log("⚠ 游戏窗口已关闭，重新打开并进入秘密商店后按 F8 继续")
                self._beep_alert()
                return True
            self.win.hwnd = hwnd

        self._next_sleep = 0.18
        img = self.win.capture("auto")
        if float(img.mean()) < 2.0:
            return True

        small = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (64, 36)).astype(np.int16)
        diff = 999.0 if self._prev_small is None else float(np.abs(small - self._prev_small).mean())
        self._prev_small = small

        # ① 稳定等待：画面在动（滚动动画/刷新）先不做判定，省掉固定等待时间
        if diff > 3.5:
            self._stable_hits = 0
            self._last_items = None
            self._next_sleep = 0.12
            return True
        self._stable_hits += 1

        items = self.ocr.read(img, min_score=0.55)
        # ② 双帧并集：连续稳定 2 帧后，把两帧文本合并再判定（任一帧读到就算）
        if self._stable_hits >= 2 and self._last_items is not None:
            items = self._union_items(self._last_items, items)
        self._last_items = items

        # 上一轮拖拽后画面几乎没变 -> 说明后台拖拽没生效，改用滚轮兜底
        if self._last_drag_sig is not None:
            if float(np.abs(small - self._last_drag_sig).mean()) < 1.5:
                log("⚠ 拖拽后画面没有变化（后台拖拽可能失效）→ 用滚轮兜底滚动")
                try:
                    self.win.wheel(0.62, 0.55, 6)
                except Exception:  # noqa: BLE001
                    pass
            self._last_drag_sig = None
        # ②' 余额双帧确认 + 待验证动作检查
        try:
            self._track_balances(items, img)
        except Exception:  # noqa: BLE001
            pass
        if self.paused:
            return True

        # ③ 红装观察：仅在「自动购买极品红装」勾选时才长按看详情（未勾选完全不碰装备）
        if self.gear_cfg.get("enabled"):
            try:
                self._inspect_gear(items, img)
            except Exception:  # noqa: BLE001
                pass

        dec = self.ctrl.analyze(img, items)
        if (
            isinstance(dec, dict)
            and "立即更新" in str(dec.get("action_key") or "")
            and self._pending
            and self._pending.get("kind") == "buy"
        ):
            self._next_sleep = 0.22
            return True
        dtype = dec["type"]

        # 即将刷新前：若顶部还有被切/被挡的行，先向下轻滑补救（优先买，其次补救）
        _ak = dec.get("action_key")
        _at_top_stop = getattr(self.ctrl, "stop_idx", 0) == 0
        if _ak == "点击立即更新" or (_ak == "上滑秘密商店" and _at_top_stop):
            try:
                if self._recover_cut_row(items, img):
                    return True
            except Exception:  # noqa: BLE001
                pass

        if dtype == "done":
            if not self._reconcile():
                return True
            self._print_summary(dec["reason"])
            return False

        if dtype == "cancel_and_done":
            log(f"🖱 点击「取消」并停止刷新：{dec['reason']}")
            self.win.click_ratio(*dec["pos"], clicks=1)
            time.sleep(0.25)
            self._print_summary(dec["reason"])
            return False

        if dtype == "stop_error":
            self.paused = True
            log("=" * 64)
            log(f"⚠ 自动暂停：{dec['reason']}")
            log(
                f"📊 当前进度：刷新 {self.ctrl.refresh_count} 次 | "
                f"圣约书签 +{self.ctrl.bought_covenant} | 神秘奖牌 +{self.ctrl.bought_mystic}"
            )
            log("👉 处理完后可按【F8】继续，或按【F10】退出！")
            log("=" * 64)
            self._beep_alert()
            return True

        if dtype == "wait_shop":
            self.recheck_count = 0
            now = time.time()
            if self.not_in_shop_since is None:
                self.not_in_shop_since = now
                log(f"⏳ {dec['desc']}")
            elif now - self.not_in_shop_since > 20.0:
                self.paused = True
                log("⚠ 20 秒未进入秘密商店 → 已暂停（F8 继续）")
                self._beep_alert()
            self._next_sleep = 0.60
            return True

        self.not_in_shop_since = None

        if dtype == "recheck":
            self.recheck_count += 1
            if self.recheck_count >= 15:
                self.paused = True
                self.recheck_count = 0
                self.ctrl.modal_recheck_count = 0
                log("⚠ 连续 15 次等待确认弹窗/状态仍未就绪，已自动暂停！请检查游戏画面后按 F8 继续。")
                self._beep_alert()
                return True
            log(dec["desc"])
            self._next_sleep = float(dec.get("wait_after", 0.20))
            return True

        self.recheck_count = 0
        action_key = dec.get("action_key", dtype)
        changed = (
            self.last_action_small is None
            or float(np.abs(small - self.last_action_small).mean()) > 4.0
        )
        if action_key == self.last_action_key and not changed:
            self.repeat_count += 1
        else:
            self.last_action_key = action_key
            self.repeat_count = 1

        if self.repeat_count >= 10:
            self.paused = True
            log(f"⚠ 「{action_key}」连续执行 {self.repeat_count} 次画面无变化，已自动暂停！请检查窗口是否被遮挡后按 F8 继续。")
            self._beep_alert()
            return True

        self.last_action_small = small.copy()
        self._next_sleep = float(dec.get("wait_after", 0.35))
        log(dec["desc"])

        # 购买审计：发现目标（点击购买前）、确认购买、确认刷新 都留档
        if action_key.startswith("购买"):
            self._audit(img, f"发现目标 → 点击 {action_key}")
        elif action_key == "确认购买书签":
            self._audit(img, f"确认购买 → {dec['desc']}")
        elif action_key == "确认刷新商店":
            self._audit(None, f"刷新商店（第 {self.ctrl.refresh_count} 次）", save_image=False)
        if dtype == "drag_ratio":
            rx1, ry1 = dec["from"]
            rx2, ry2 = dec["to"]
            self._last_drag_sig = small.copy()
            self.win.drag_ratio(
                rx1, ry1, rx2, ry2,
                duration=float(dec.get("duration", 0.24)),
                steps=int(dec.get("steps", 14)),
            )
        elif dtype == "click_ratio":
            # 取消购买弹窗：这次点击不会产生购买，撤销待验证，避免误判「购买后余额未变」
            if "自动点击「取消」" in str(dec.get("desc", "")) or "点击「取消」" in str(dec.get("desc", "")):
                self._pending = None
                # 取消购买：把弹窗出现时预加的内存计数回滚掉
                if getattr(self.ctrl, "counted_this_popup", False):
                    if getattr(self.ctrl, "last_counted_item", None) == "神秘奖牌":
                        self.ctrl.bought_mystic = max(0, self.ctrl.bought_mystic - 1)
                    else:
                        self.ctrl.bought_covenant = max(0, self.ctrl.bought_covenant - 1)
                    self.ctrl.spent_gold = max(0, self.ctrl.spent_gold - int(getattr(self.ctrl, "last_counted_price", 0) or 0))
                    self.ctrl.counted_this_popup = False
            if action_key == "点击立即更新":
                self._pre_refresh_sig = self._shelf_sig(img)
            rx, ry = dec["pos"]
            self.win.click_ratio(rx, ry, clicks=1)
            # 关键动作登记验证：刷新扣 3 天空石 / 购买扣价格金币
            if action_key == "确认刷新商店":
                self._last_items = None
                self._stable_hits = 0
                self._arm_pending("refresh", shelf_sig=self._pre_refresh_sig)
            elif action_key == "确认购买书签":
                item = getattr(self.ctrl, "last_counted_item", None)
                price = int(getattr(self.ctrl, "last_counted_price", 0) or 0)
                buy_pt = getattr(self.ctrl, "last_counted_pt", None)
                self._last_items = None
                self._stable_hits = 0
                if item:
                    # price=0（OCR 没读到价格）也要登记校验：用金币「有任何减少」兜底
                    self._arm_pending("buy", item=item, price=max(0, price), buy_pt=buy_pt)
        return True

    def run(self) -> bool:
        """运行商店刷新循环。返回 True=达成目标正常结束；False=用户 F10 退出或异常中断。"""
        completed = False
        print("=" * 68)
        print("  第七史诗（Steam 简中版）秘密商店自动刷书签助手")
        print("  购买目标：圣约书签 + 神秘奖牌（神秘书签）")
        print(f"  停止条件：剩余天空石 ≤ {self.ctrl.stop_skystones:,} 颗时自动停止并响铃")
        print("  快捷键：【F8】暂停 / 继续      【F10】退出程序")
        print("  提示：运行期间请勿最小化或遮挡游戏窗口，尽量不要动鼠标")
        print("=" * 68)
        try:
            stats_db.log_event("session")
        except Exception:  # noqa: BLE001
            pass
        log(f"🛡 进程权限：{process_privilege_summary()}  鼠标自检：{cursor_control_probe()}  {process_parent_info()}")
        write_startup_diag(ROOT)
        while True:
            if not self.poll_hotkeys():
                break
            if self.paused:
                time.sleep(0.1)
                continue
            if self.win.is_alive() and self.win.is_minimized():
                time.sleep(1.0)
                continue
            try:
                keep_going = self.step()
            except InputBlockedError as e:
                log("=" * 58)
                log(f"❌ 无法模拟鼠标：{e}")
                log("👉 解决：关闭本窗口，直接双击文件夹里的 .bat 启动；")
                log("   不要从 AI 助手/沙箱/受限终端中启动，也不要锁屏或用远程桌面。")
                log("=" * 58)
                self._beep_alert()
                return False
            except Exception as e:  # noqa: BLE001
                log(f"⚠ 本轮识别出现异常（将自动重试）：{e!r}")
                keep_going = True
                self._next_sleep = 0.5
            if not keep_going:
                completed = True
                break
            end = time.time() + self._next_sleep
            while time.time() < end:
                if not self.poll_hotkeys():
                    return False
                time.sleep(0.05)
        return completed


def _prompt_stop_skystones(current_stones: int | None) -> int:
    # 支持命令行 --stop 2000 非交互参数
    if "--stop" in sys.argv:
        idx = sys.argv.index("--stop")
        if idx + 1 < len(sys.argv):
            val = int(re.sub(r"[,，\s]", "", sys.argv[idx + 1]))
            if val >= 0:
                return val

    print()
    print("=" * 68)
    print("  💎 设置「秘密商店刷新」天空石停止线")
    if current_stones is not None:
        print(f"  当前识别到账号剩余天空石：{current_stones:,} 颗")
    else:
        print("  提示：请确保游戏里已经打开【秘密商店】界面")
    print()
    print("  👉 请输入你想刷到【天空石还剩多少颗】时自动停止（直接填数字）：")
    print("     例如账号里现在有 10,000 颗，只想留 2,000 颗保底：输入 2000 回车即可")
    print("     （每刷新 1 次消耗 3 颗天空石，到剩余 ≤ 你填的数字时自动停止）")
    print("=" * 68)
    while True:
        raw = input("请输入停止刷新的【剩余天空石数字】：").strip()
        cleaned = re.sub(r"[,，\s]", "", raw)
        if not cleaned.isdigit():
            print("❌ 请输入纯数字，例如：2000")
            continue
        target = int(cleaned)
        if current_stones is not None and target >= current_stones:
            ans = input(
                f"⚠ 注意：当前剩余只有 {current_stones:,} 颗，已经 ≤ 你输入的 {target:,} 颗（启动后会直接停止）。\n"
                f"   确认使用 {target:,} 吗？按 Y 确认，按 N 重新输入："
            ).strip().lower()
            if ans not in ("y", "yes", "是"):
                continue
        if current_stones is not None and target < current_stones:
            approx_spend = current_stones - target
            approx_refreshes = approx_spend // 3
            print(
                f"✅ 已设定：刷到剩余 ≤ {target:,} 颗停止（预计花费约 {approx_spend:,} 颗，约 {approx_refreshes:,} 次刷新）"
            )
        else:
            print(f"✅ 已设定：刷到剩余 ≤ {target:,} 颗停止")
        return target


def run_shop_flow(elevated_window: bool = False) -> int:
    ensure_utf8_console("第七史诗 秘密商店自动刷书签 [F8 暂停/继续 | F10 退出]")
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
    log("正在加载离线 OCR 文字识别模型，请稍候（约 1~3 秒）...")
    ocr = Ocr()
    log("✅ 模型加载完成！")

    sample = win.capture("auto")
    current_stones = extract_skystones(sample, ocr, require_bright=True)
    stop_skystones = _prompt_stop_skystones(current_stones)

    bot = ShopBot(win, ocr, stop_skystones)
    if current_stones is not None:
        bot.ctrl.last_skystones = current_stones
    bot.run()
    if elevated_window:
        input("\n刷新已结束，按回车键关闭窗口...")
    return 0


def main() -> int:
    ensure_utf8_console("第七史诗 秘密商店自动刷书签 [F8 暂停/继续 | F10 退出]")
    if try_elevate():
        return 0
    elevated_window = "--elevated" in sys.argv
    try:
        return run_shop_flow(elevated_window=elevated_window)
    except SystemExit as e:
        if e.code not in (0, None):
            print(f"\n{e}\n", flush=True)
            if elevated_window:
                input("按回车键关闭窗口...")
            return 1
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"\n❌ 程序发生未预期错误：{e!r}\n", flush=True)
        if elevated_window:
            input("按回车键关闭窗口...")
        return 1


if __name__ == "__main__":
    sys.exit(main())
