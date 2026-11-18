"""红装（85 传说）识别：列表定位候选 → 长按看详情 → 解析属性 → 记录样本。

P1 阶段只识别和记录，不做购买决策。
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import cv2
import numpy as np

from core import OcrItem, runtime_root, user_data_dir

PRICE_RE = re.compile(r"^[\d,]{3,}$")
NUM_RE = re.compile(r"(\d+(?:\.\d+)?)")
QUALITY_WORDS = ("传说", "英雄", "史诗", "稀有", "普通")
STAT_LABELS = ("装备分数", "速度", "暴击伤害", "暴击率", "暴击", "攻击力", "防御力", "生命值", "效果命中", "命中")


def _norm(s: str) -> str:
    return "".join(str(s).split())


def _by_y(items: list[OcrItem], y: float, tol: float = 0.03) -> list[OcrItem]:
    return [it for it in items if abs(it.center[1] - y) <= tol * 1000]


def find_candidates(items: list[OcrItem], w: int, h: int) -> list[dict]:
    """从商店列表 OCR 里找「85 + 装备」的行（返回比例坐标）。"""
    out: list[dict] = []
    levels = [it for it in items if _norm(it.text) in ("85", "8s", "8S")]
    for lv in levels:
        y = lv.center[1]
        row = _by_y(items, y, 0.035)
        has_gear = any("装备" in _norm(it.text) for it in row)
        if not has_gear:
            continue
        price = None
        price_x = 1e9
        for it in row:
            t = _norm(it.text)
            if PRICE_RE.match(t) and it.center[0] > lv.center[0]:
                price = int(t.replace(",", ""))
                price_x = it.center[0]
        # 名称：垂直范围放宽（名称比「85」低约 40px），水平在等级右侧、价格左侧
        name_cands = []
        for it in items:
            t = _norm(it.text)
            if abs(it.center[1] - y) > 0.075 * 1000:
                continue
            if not (lv.center[0] + 10 < it.center[0] < price_x):
                continue
            if len(t) < 2 or PRICE_RE.match(t):
                continue
            if any(k in t for k in ("装备", "可购买", "购买", "85")):
                continue
            name_cands.append(it)
        name = ""
        if name_cands:
            name_cands.sort(key=lambda it: len(_norm(it.text)), reverse=True)
            name = _norm(name_cands[0].text)
        if not name:
            continue
        out.append(
            {
                "level": 85,
                "name": name,
                "price": price or 0,
                # 图标中心：等级文字右下一点（换算成比例）
                "x": (lv.center[0] + int(w * 0.013)) / max(1, w),
                "y": (lv.center[1] + int(h * 0.020)) / max(1, h),
            }
        )
    return out


def _num(items: list[OcrItem], label: str, exclude: tuple[str, ...] = ()) -> float | None:
    """找 label 右侧同一行的第一个数字（含 exclude 词的行跳过）。"""
    for it in items:
        t = _norm(it.text)
        if label not in t:
            continue
        if any(x in t for x in exclude):
            continue
        y = it.center[1]
        best: tuple[float, float] | None = None
        for other in items:
            if other is it:
                continue
            if abs(other.center[1] - y) > 18:
                continue
            if other.center[0] <= it.center[0]:
                continue
            m = NUM_RE.search(_norm(other.text))
            if m and (best is None or other.center[0] < best[0]):
                best = (other.center[0], float(m.group(1)))
        if best:
            return best[1]
    return None


def parse_detail(items: list[OcrItem]) -> dict:
    """解析详情面板：品质 / 分数 / 速度 / 暴击 / 暴伤 等。"""
    quality = ""
    for it in items:
        t = _norm(it.text)
        for q in QUALITY_WORDS:
            if t.startswith(q) or q in t:
                quality = q
                break
        if quality:
            break
    return {
        "quality": quality,
        "score": _num(items, "装备分数"),
        "speed": _num(items, "速度"),
        "crit": _num(items, "暴击", exclude=("伤害",)),
        "critdmg": _num(items, "暴击伤害"),
        "atk": _num(items, "攻击力"),
        "def": _num(items, "防御力"),
        "hp": _num(items, "生命值"),
    }


def legendary_ratio(img: np.ndarray, xr: float, yr: float) -> tuple[float, float]:
    """返回图标框的 (红色占比, 紫色占比)。红装≈红0.24~0.56/紫0.00；紫装≈红0.00/紫0.27~0.31。"""
    h, w = img.shape[:2]
    cx, cy = int(w * xr), int(h * yr)
    half = max(10, int(w * 0.0209))
    crop = img[max(0, cy - half) : min(h, cy + half), max(0, cx - half) : min(w, cx + half)]
    if crop.size == 0:
        return 0.0, 0.0
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    H, S, V = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    sat = (S > 80) & (V > 60)
    red = float((sat & ((H <= 10) | (H >= 170))).mean())
    purple = float((sat & (H >= 135) & (H <= 165)).mean())
    return red, purple


def is_legendary(img: np.ndarray, xr: float, yr: float) -> bool:
    """是否传说（红装）：红占比高且紫占比低。"""
    red, purple = legendary_ratio(img, xr, yr)
    return red >= 0.15 and purple < 0.06


def save_sample(frame: np.ndarray, name: str) -> Path | None:
    try:
        d = user_data_dir() / "gear"
        d.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        safe = re.sub(r"[^\w\u4e00-\u9fff]+", "_", name)[:24] or "gear"
        p = d / f"{ts}_{safe}.png"
        cv2.imencode(".png", frame)[1].tofile(str(p))
        return p
    except Exception:  # noqa: BLE001
        return None


def inspect(win, ocr, cand: dict, hold: float = 0.45) -> dict | None:
    """长按装备图标 → 抓图 → 松开 → 解析详情。"""
    try:
        win.press_start_ratio(cand["x"], cand["y"])
    except Exception:  # noqa: BLE001
        return None
    try:
        time.sleep(hold)
        frame = win.capture("auto")
    except Exception:  # noqa: BLE001
        frame = None
    finally:
        try:
            win.press_end()
        except Exception:  # noqa: BLE001
            pass
    if frame is None or float(frame.mean()) < 2.0:
        return None
    items = ocr.read(frame, 0.45)
    info = parse_detail(items)
    info["frame"] = frame
    info["texts"] = [_norm(i.text) for i in items]
    return info
