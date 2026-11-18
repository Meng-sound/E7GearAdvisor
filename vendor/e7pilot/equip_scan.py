"""第七史诗（Steam 简中版）背包装备扫描 P1（只读扫描全部 +15 装备并聚合统计）。

热键：F8 暂停/继续    F10 退出扫描
设计：+15 徽章模板+红色门限 → 网格点击卡片 → 右侧详情面板 OCR → 截断行锚点翻页
只读：只点击左侧装备卡片，绝不点右侧/顶部任何功能按钮。
"""
from __future__ import annotations

import ctypes
import json
import re
import sys
import time
import winsound
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from core import (
    Ocr,
    OcrItem,
    is_admin,
    open_game_window,
    read_click_mode,
    runtime_root,
    to_simplified,
)

ROOT = runtime_root()
VK_F8, VK_F10 = 0x77, 0x79

# 1819x1023 基准下的几何比例（真实网格：列距 140.7px、行距 189px；右侧面板徽章已排除）
GRID_X_MAX = 0.660
GRID_Y_MIN = 0.020   # 检测从屏幕最上方开始：翻页多滑一行时，顶部被顶出去的行也能被发现（用于布局校验/回调）
PANEL_X_MIN = 0.665
COL0_CENTER_X = 0.1668
COL_PITCH = 0.0773
ROW0_CENTER_Y = 0.2209
ROW_PITCH = 0.1847
BOTTOM_CUT_Y = 0.855
CARD_CLICK_DX = -38.0 / 1819.0
CARD_CLICK_DY = 66.0 / 1023.0
CLICK_HOLD = 0.14   # E7 界面按钮需 0.13~0.18s 才识别；远低于长按 0.3s 弹详情阈值

QUALITIES = ("异界传说", "传说", "英雄", "稀有", "高级", "普通")
PARTS = ("武器", "头盔", "铠甲", "项链", "戒指", "鞋子")
PERCENT_AMBIGUOUS_STATS = ("攻击力", "防御力", "生命值")
# 这些属性永远是百分比（主属性/副属性都一样）：OCR 漏掉 % 时直接按百分比兜底，避免装备分数暴跌
MUST_PERCENT_STATS = ("暴击率", "暴击伤害", "效果命中", "效果抗性")

# 占位草稿阈值，供后续按玩家需求调整（P1 只做区分统计，不产出雷达）
DRAFT_THRESHOLDS = {
    "speed_ge_1": 15,
    "speed_ge_2": 20,
    "score_ge_1": 90,
    "score_ge_2": 100,
}


def _setup_console_encoding() -> None:
    """打包成 exe 后子进程 stdout 可能是 GBK（与 main.py/shop.py 同样处理），
    直接 print emoji 会抛 UnicodeEncodeError 导致整个脚本崩掉 → 统一切到 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def log(msg: str) -> None:
    line = f"[{datetime.now():%H:%M:%S}] {msg}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        # 极端兜底：输出流仍不是 UTF-8 时，直接把 UTF-8 字节写到底层缓冲，绝不因日志崩脚本
        try:
            sys.stdout.buffer.write((line + "\n").encode("utf-8", "replace"))
            sys.stdout.flush()
        except Exception:  # noqa: BLE001
            pass


def norm(s: str) -> str:
    return to_simplified("".join(str(s).split()))


def load_plus15_template() -> np.ndarray:
    # 优先工作目录 templates/（GUI 首次启动会把模板拷到 exe 旁）；
    # 兼容"旧版本覆盖升级"导致 templates 目录已存在但缺新模板的情况 → 回退打包内置目录。
    cands = [ROOT / "templates" / "badge_plus15.png"]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        cands.append(Path(meipass) / "templates" / "badge_plus15.png")
    p = next((c for c in cands if c.exists()), cands[0])
    if not p.exists():
        raise FileNotFoundError(f"缺少模板文件：{p}")
    tmpl = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if tmpl is None:
        raise RuntimeError(f"无法读取模板：{p}")
    return tmpl


def detect_plus15_badges(
    img: np.ndarray,
    tmpl: np.ndarray,
    tmpl_thresh: float = 0.66,
    red_thresh: float = 0.25,
) -> list[list[dict]]:
    """检测左侧背包网格内的 +15 徽章，按行聚类并从左到右排序。

    阈值说明：背包默认选中态 [0,0] 的黄框 / 角色头像遮挡会让个别徽章匹配分降到 0.67~0.70，
    因此阈值取 0.66；橙色 +12/+10 与蓝色图标由红色像素门限（red_thresh）过滤。
    返回: [[{"cx": rx, "cy": ry, "col": 0..6, "score": s, "red": r}, ...], ...]
    """
    h, w = img.shape[:2]
    if h < 100 or w < 100:
        return []

    rx_max = int(w * GRID_X_MAX)
    ry_min = int(h * GRID_Y_MIN)
    roi = img[ry_min:, :rx_max]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    scale = w / 1819.0
    tw = max(12, int(round(tmpl.shape[1] * scale)))
    th = max(10, int(round(tmpl.shape[0] * scale)))
    if tw >= gray.shape[1] or th >= gray.shape[0]:
        return []
    t_scaled = cv2.resize(tmpl, (tw, th), interpolation=cv2.INTER_AREA)

    res = cv2.matchTemplate(gray, t_scaled, cv2.TM_CCOEFF_NORMED)
    ys, xs = np.where(res >= tmpl_thresh)
    if ys.size == 0:
        return []

    hsv_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    red_mask = (
        ((hsv_roi[:, :, 0] <= 10) | (hsv_roi[:, :, 0] >= 170))
        & (hsv_roi[:, :, 1] >= 120)
        & (hsv_roi[:, :, 2] >= 120)
    )

    cands = sorted(
        [(float(res[y, x]), int(x), int(y)) for y, x in zip(ys, xs)],
        reverse=True,
    )
    nms_dx = int(w * 0.045)
    nms_dy = int(h * 0.080)
    kept: list[dict] = []
    for score, x, y in cands:
        cx_abs = x + tw * 0.5
        cy_abs = ry_min + y + th * 0.5
        if any(abs(cx_abs - k["cx_px"]) < nms_dx and abs(cy_abs - k["cy_px"]) < nms_dy for k in kept):
            continue
        red_ratio = float(red_mask[y : y + th, x : x + tw].mean())
        if red_ratio < red_thresh:
            continue
        cx_r = cx_abs / w
        cy_r = cy_abs / h
        col = int(round((cx_r - COL0_CENTER_X) / COL_PITCH))
        kept.append({
            "cx": round(cx_r, 4),
            "cy": round(cy_r, 4),
            "cx_px": cx_abs,
            "cy_px": cy_abs,
            "col": max(0, min(6, col)),
            "score": round(score, 3),
            "red": round(red_ratio, 3),
        })

    if not kept:
        return []

    kept.sort(key=lambda d: d["cy"])
    rows: list[list[dict]] = []
    for item in kept:
        if not rows or abs(item["cy"] - rows[-1][0]["cy"]) > 0.045:
            rows.append([item])
        else:
            rows[-1].append(item)
    for row in rows:
        row.sort(key=lambda d: d["cx"])
    return rows


def badge_to_click_ratio(bx: float, by: float) -> tuple[float, float]:
    """徽章中心归一化坐标 → 卡片安全单击坐标（限定在左侧网格内）。"""
    cx = max(0.05, min(0.64, bx + CARD_CLICK_DX))
    cy = max(0.18, min(0.97, by + CARD_CLICK_DY))
    return (round(cx, 4), round(cy, 4))


def _parse_stat_value(raw: str) -> tuple[float | int | None, bool]:
    t = norm(raw).replace(",", "").strip()
    is_pct = t.endswith("%")
    if is_pct:
        t = t[:-1]
    if not re.fullmatch(r"\d+(?:\.\d+)?", t):
        return None, is_pct
    val: float | int = float(t) if "." in t else int(t)
    return val, is_pct


def _stat_key(label: str, is_pct: bool) -> str:
    if label in PERCENT_AMBIGUOUS_STATS and is_pct:
        return f"{label}%"
    return label


def _pair_row_stats(items: list[OcrItem], w: int, h: int, y_lo: float, y_hi: float) -> list[dict]:
    labels: list[tuple[float, str]] = []
    values: list[tuple[float, str]] = []
    for it in items:
        cx, cy = it.center[0] / w, it.center[1] / h
        if not (y_lo <= cy <= y_hi):
            continue
        t = norm(it.text)
        if not t:
            continue
        if cx < 0.85:
            labels.append((cy, t))
        else:
            values.append((cy, t))

    labels.sort(key=lambda x: x[0])
    used = [False] * len(values)
    out: list[dict] = []
    for ly, ltxt in labels:
        best_idx = -1
        best_dy = 0.018
        for idx, (vy, _vtxt) in enumerate(values):
            if used[idx]:
                continue
            dy = abs(vy - ly)
            if dy <= best_dy:
                best_dy = dy
                best_idx = idx
        if best_idx < 0:
            continue
        used[best_idx] = True
        val, is_pct = _parse_stat_value(values[best_idx][1])
        if val is None:
            continue
        pct_inferred = False
        if ltxt in MUST_PERCENT_STATS and not is_pct:
            # 暴击率/暴击伤害/效果命中/效果抗性必然是百分比：OCR 漏 % 时兜底，避免分数暴跌
            is_pct = True
            pct_inferred = True
        out.append({
            "type": ltxt,
            "key": _stat_key(ltxt, is_pct),
            "value": val,
            "is_percent": is_pct,
            "pct_inferred": pct_inferred,
        })
    return out


def parse_right_panel(
    items: list[OcrItem], w: int, h: int, diag: dict | None = None
) -> dict | None:
    """解析右侧详情面板 OCR 结果；非 +15 或被长按弹窗遮挡时返回 None。"""
    panel = [
        it for it in items
        if it.center[0] / w >= PANEL_X_MIN and 0.18 <= it.center[1] / h <= 0.97
    ]
    if not panel:
        if diag is not None:
            diag["reason"] = "panel_empty"
        return None

    # 校验面板内是否确实显示 +15
    has_plus15 = any(
        "+15" in norm(it.text) and 0.72 <= it.center[0] / w <= 0.77 and 0.22 <= it.center[1] / h <= 0.28
        for it in panel
    )
    if not has_plus15:
        if diag is not None:
            diag["reason"] = "no_plus15"
        return None

    # 防误长按详情大窗遮挡：大窗遮住面板左侧时「装备分数」标签会缺失
    has_score_label = any(
        "装备分数" in norm(it.text) and it.center[0] / w >= PANEL_X_MIN and 0.64 <= it.center[1] / h <= 0.70
        for it in panel
    )
    if not has_score_label:
        if diag is not None:
            diag["reason"] = "no_score_label"
        return None

    # 等级
    level: int | None = None
    for it in panel:
        cx, cy = it.center[0] / w, it.center[1] / h
        if 0.68 <= cx <= 0.73 and 0.24 <= cy <= 0.28:
            t = norm(it.text)
            if t.isdigit():
                level = int(t)
                break
    if level is None:
        # 兜底：等级数字偶尔会被 OCR 与 +15 徽章粘连/漏读，放宽搜索区域再取一次（排除 +15 的 15）
        for it in sorted(panel, key=lambda i: i.center[1]):
            cx, cy = it.center[0] / w, it.center[1] / h
            if not (0.66 <= cx <= 0.78 and 0.23 <= cy <= 0.29):
                continue
            t = norm(it.text).replace("+", "")
            m = re.fullmatch(r"(\d{2,3})", t)
            if m and m.group(1) not in ("15",):
                level = int(m.group(1))
                break

    # 品质 + 部位（支持换行拼接，如「异界传说铠」+「甲」）
    qp_tokens = sorted(
        [
            (round(it.center[1] / h, 2), it.center[0] / w, norm(it.text))
            for it in panel
            if 0.75 <= it.center[0] / w <= 0.90 and 0.24 <= it.center[1] / h <= 0.29
        ]
    )
    qp_text = "".join(t for _, _, t in qp_tokens)
    quality = next((q for q in QUALITIES if q in qp_text), None)
    part = next((p for p in PARTS if p in qp_text), None)

    # 装备名称（位于品质+部位下方、简介上方）
    name_tokens = sorted(
        [
            (it.center[1] / h, it.center[0] / w, norm(it.text))
            for it in panel
            if 0.75 <= it.center[0] / w <= 0.96 and 0.288 <= it.center[1] / h <= 0.345
        ]
    )
    name = "".join(t for _, _, t in name_tokens)

    # 主属性 / 副属性
    mains = _pair_row_stats(panel, w, h, 0.455, 0.495)
    subs = _pair_row_stats(panel, w, h, 0.505, 0.648)
    if not mains or not subs:
        if diag is not None:
            diag["reason"] = f"no_mains_or_subs(m={len(mains)},s={len(subs)})"
        return None

    # 装备分数
    score: int | None = None
    for it in panel:
        cx, cy = it.center[0] / w, it.center[1] / h
        if cx >= 0.88 and 0.650 <= cy <= 0.695:
            t = norm(it.text)
            if t.isdigit():
                score = int(t)
                break
    if score is None:
        if diag is not None:
            diag["reason"] = "no_score_value"
        return None
    if diag is not None:
        diag["reason"] = "ok"

    # 套装
    set_info: dict | None = None
    for it in panel:
        cx, cy = it.center[0] / w, it.center[1] / h
        if 0.70 <= cx <= 0.92 and 0.755 <= cy <= 0.820:
            m = re.search(r"(.+?套装)\s*[（(]\s*(\d+)\s*/\s*(\d+)\s*[)）]", norm(it.text))
            if m:
                set_info = {
                    "name": m.group(1),
                    "pieces": int(m.group(2)),
                    "required": int(m.group(3)),
                }
                break

    equipped = any("解除配戴" in norm(it.text) and it.center[1] / h >= 0.90 for it in panel)
    return {
        "plus": 15,
        "level": level,
        "quality": quality,
        "part": part,
        "name": name,
        "main_stat": mains[0],
        "substats": subs,
        "score": score,
        "set": set_info,
        "equipped": equipped,
        "locked": None,  # P1 暂空：缺未锁定图标对照样本后再补
    }


def aggregate_stats(gears: list[dict]) -> dict:
    """按全属性区分统计与派生统计（初版不含雷达）。"""
    by_part: dict[str, int] = {}
    by_quality: dict[str, int] = {}
    by_level: dict[str, int] = {}
    by_set: dict[str, int] = {}
    substat_values: dict[str, list[float | int]] = {}
    scores: list[int] = []
    double_crit = 0
    speed_ge_1 = 0
    speed_ge_2 = 0
    score_ge_1 = 0
    score_ge_2 = 0

    for g in gears:
        part = g.get("part") or "未知"
        qual = g.get("quality") or "未知"
        lvl = str(g.get("level") or "未知")
        sname = (g.get("set") or {}).get("name") or "未知"
        by_part[part] = by_part.get(part, 0) + 1
        by_quality[qual] = by_quality.get(qual, 0) + 1
        by_level[lvl] = by_level.get(lvl, 0) + 1
        by_set[sname] = by_set.get(sname, 0) + 1

        sc = g.get("score")
        if isinstance(sc, (int, float)):
            scores.append(int(sc))
            if sc >= DRAFT_THRESHOLDS["score_ge_1"]:
                score_ge_1 += 1
            if sc >= DRAFT_THRESHOLDS["score_ge_2"]:
                score_ge_2 += 1

        keys_present: dict[str, float | int] = {}
        for sub in g.get("substats") or []:
            k = sub["key"]
            v = sub["value"]
            substat_values.setdefault(k, []).append(v)
            keys_present[k] = v

        if "暴击率" in keys_present and "暴击伤害" in keys_present:
            double_crit += 1
        spd = keys_present.get("速度", 0)
        if spd >= DRAFT_THRESHOLDS["speed_ge_1"]:
            speed_ge_1 += 1
        if spd >= DRAFT_THRESHOLDS["speed_ge_2"]:
            speed_ge_2 += 1

    substat_summary = {
        k: {
            "count": len(vals),
            "min": min(vals),
            "max": max(vals),
            "avg": round(sum(vals) / len(vals), 2),
            "values": vals,
        }
        for k, vals in sorted(substat_values.items())
    }
    return {
        "total_plus15": len(gears),
        "by_part": by_part,
        "by_quality": by_quality,
        "by_level": by_level,
        "by_set": by_set,
        "score_summary": (
            {"min": min(scores), "max": max(scores), "avg": round(sum(scores) / len(scores), 2)}
            if scores else {}
        ),
        "substat_stats": substat_summary,
        "derived": {
            "draft_thresholds": DRAFT_THRESHOLDS,
            "double_crit": double_crit,
            f"speed_ge_{DRAFT_THRESHOLDS['speed_ge_1']}": speed_ge_1,
            f"speed_ge_{DRAFT_THRESHOLDS['speed_ge_2']}": speed_ge_2,
            f"score_ge_{DRAFT_THRESHOLDS['score_ge_1']}": score_ge_1,
            f"score_ge_{DRAFT_THRESHOLDS['score_ge_2']}": score_ge_2,
        },
    }


def _grid_sig(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    roi = img[int(h * 0.185) : int(h * 0.98), int(w * 0.115) : int(w * 0.650)]
    return cv2.resize(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY), (48, 64), interpolation=cv2.INTER_AREA).astype(np.int16)


def _panel_sig(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    roi = img[int(h * 0.22) : int(h * 0.83), int(w * 0.67) : int(w * 0.98)]
    return cv2.resize(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY), (32, 64), interpolation=cv2.INTER_AREA).astype(np.int16)


def _gold_mask(bgr: np.ndarray) -> np.ndarray:
    """选中金框像素掩码（兼顾亮白金核心与暖黄外晕，排除纯白数字与红/蓝/灰底）。"""
    if bgr.size == 0:
        return np.zeros((0, 0), dtype=bool)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    b = bgr[:, :, 0].astype(np.int16)
    g = bgr[:, :, 1].astype(np.int16)
    r = bgr[:, :, 2].astype(np.int16)
    return (
        (hsv[:, :, 0] >= 18)
        & (hsv[:, :, 0] <= 42)
        & (hsv[:, :, 1] >= 28)
        & (hsv[:, :, 2] >= 140)
        & ((np.minimum(r, g) - b) >= 18)
    )


GOLD_CARD_DX = -35.5 / 1819.0
GOLD_CARD_DY = 72.0 / 1023.0
GOLD_CARD_HALF_W = 0.0368
GOLD_CARD_HALF_H = 0.0840


def score_gold_border(img: np.ndarray, bx_r: float, by_r: float) -> tuple[float, int]:
    """评估某张卡片外沿 4 条边框的金框得分，返回 (均值占比, 命中边数)。

    几何按实机 1819x1023 标定（同日实测：选中卡 4 条边占比 0.34~0.44、未选中 0.00）；
    采样避开左上角等级数字、右上角 +15 徽章与右下角部位图标。
    """
    h, w = img.shape[:2]
    cx = (bx_r + GOLD_CARD_DX) * w
    cy = (by_r + GOLD_CARD_DY) * h
    hw = GOLD_CARD_HALF_W * w
    hh = GOLD_CARD_HALF_H * h
    x_l, x_r = int(cx - hw), int(cx + hw)
    y_t, y_b = int(cy - hh), int(cy + hh)
    ins = 12
    patches = (
        img[max(0, y_t - 1): max(1, y_t + 5), max(0, x_l + ins): max(1, x_r - ins)],       # 顶边
        img[max(0, y_b - 4): min(h, y_b + 2), max(0, x_l + ins): max(1, x_r - ins)],       # 底边
        img[max(0, y_t + 16): max(1, y_b - 16), max(0, x_l - 1): max(1, x_l + 5)],         # 左边
        img[max(0, y_t + 16): max(1, y_b - 16), max(0, x_r - 4): min(w, x_r + 2)],         # 右边
    )
    ratios = [float(_gold_mask(p).mean()) for p in patches if p.size]
    if not ratios:
        return 0.0, 0
    hits = sum(1 for v in ratios if v >= 0.14)
    top3 = sorted(ratios, reverse=True)[:3]
    return round(sum(top3) / len(top3), 4), hits


def _is_gold_hit(score: float, hits: int) -> bool:
    return (hits >= 3 and score >= 0.20) or (hits >= 2 and score >= 0.26)


def find_gold_badge_in_rows(
    img: np.ndarray,
    rows: list[list[dict]],
    target_col: int | None = None,
) -> tuple[dict | None, float, int]:
    """在已检出的 +15 徽章行中定位带金框的卡片。"""
    best_b: dict | None = None
    best_score = 0.0
    best_hits = 0
    for row in rows:
        for b in row:
            if target_col is not None and abs(b["col"] - target_col) > 1:
                continue
            sc, hits = score_gold_border(img, b["cx"], b["cy"])
            bonus = 0.02 if (target_col is not None and b["col"] == target_col) else 0.0
            if (hits > best_hits) or (hits == best_hits and (sc + bonus) > best_score):
                best_b, best_score, best_hits = b, sc, hits
    if best_b is not None and _is_gold_hit(best_score, best_hits):
        return best_b, best_score, best_hits
    return None, best_score, best_hits


def find_gold_in_column(img: np.ndarray, col: int) -> tuple[float | None, float]:
    """徽章被顶边裁掉时的单列兜底：沿目标列找金框底边，反推出估算徽章 y。"""
    h, w = img.shape[:2]
    cx_c = (COL0_CENTER_X + col * COL_PITCH) + GOLD_CARD_DX
    cx_px = cx_c * w
    hw = GOLD_CARD_HALF_W * w
    hh = GOLD_CARD_HALF_H * h
    x1 = max(0, int(cx_px - hw - 6))
    x2 = min(w, int(cx_px + hw + 6))
    y1, y2 = int(h * 0.175), int(h * 0.990)
    if x2 - x1 < 20 or y2 - y1 < 30:
        return None, 0.0
    gm = _gold_mask(img[y1:y2, x1:x2]).astype(np.float32)
    cw = gm.shape[1]
    bot_profile = gm[:, int(cw * 0.15): int(cw * 0.85)].mean(axis=1)
    k = min(9, len(bot_profile))
    smooth = np.convolve(bot_profile, np.ones(k, dtype=np.float32) / k, mode="same")
    idx = int(np.argmax(smooth))
    peak = float(smooth[idx])
    if peak < 0.22:
        return None, peak
    y_bot_px = y1 + idx
    y_bot = y_bot_px / h
    # 用左右两条竖边做双门控（按实机卡片外沿 ± 6px 采样），防止单行黄图标误触发
    ry1 = max(y1, int(y_bot_px - 2 * hh + 12))
    ry2 = max(ry1 + 5, int(y_bot_px - 12))
    left_s = float(_gold_mask(img[ry1:ry2, max(0, int(cx_px - hw - 6)):int(cx_px - hw + 1)]).mean())
    right_s = float(_gold_mask(img[ry1:ry2, int(cx_px + hw - 1):min(w, int(cx_px + hw + 6))]).mean())
    if left_s < 0.14 or right_s < 0.14:
        return None, peak
    est_badge_cy = y_bot - GOLD_CARD_HALF_H - GOLD_CARD_DY
    return round(est_badge_cy, 4), round(peak, 3)


def _plan_gold_scroll_step(
    y_curr: float | None,
    gain: float | None,
) -> tuple[str, float, float, float, float]:
    """根据金框当前 y（None=滑出顶部视野）规划下一步小步慢拖。"""
    if y_curr is None:
        rem_down = 0.23
        g = gain or 1.0
        drag_dy = min(0.24, max(0.08, (rem_down / g) * 0.90))
        dur = max(0.26, drag_dy * 1023.0 / 450.0)
        return ("down", 0.30, round(0.30 + drag_dy, 4), round(drag_dy, 4), round(dur, 3))
    if 0.205 <= y_curr <= 0.238:
        return ("aligned", 0.0, 0.0, 0.0, 0.0)
    if y_curr < 0.205:
        # 略过头：小步向下拉回
        rem_down = max(0.03, ROW0_CENTER_Y - y_curr)
        g = gain or 1.0
        drag_dy = min(0.16, max(0.03, (rem_down / g) * 0.90))
        dur = max(0.26, drag_dy * 1023.0 / 450.0)
        return ("down", 0.30, round(0.30 + drag_dy, 4), round(drag_dy, 4), round(dur, 3))
    # 已接近目标但偏下（0.238~0.265）：只做很小的一步上推，避免把底部行挤出屏幕
    rem_up = y_curr - ROW0_CENTER_Y
    if rem_up < 0.05:
        drag_dy = 0.05
        dur = 0.32
    else:
        if gain is None:
            drag_dy = min(0.24, max(0.06, rem_up * 0.85))
        else:
            desired = min(0.32, rem_up)
            drag_dy = min(0.34, max(0.05, (desired / gain) * 0.90))
        dur = max(0.32, drag_dy * 1023.0 / 520.0)
    return ("up", 0.80, round(0.80 - drag_dy, 4), round(drag_dy, 4), round(dur, 3))


class EquipScanner:
    def __init__(self, win, ocr: Ocr) -> None:
        self.win = win
        self.ocr = ocr
        self.tmpl = load_plus15_template()
        self.paused = False
        self._key_state = {VK_F8: False, VK_F10: False}
        self.gears: list[dict] = []
        self.stop_reason = "completed"
        self._last_identity: tuple | None = None
        self._scroll_gain: float | None = None
        self._ocr_log_path: Path | None = None
        self._qc = {
            "total": 0, "level_missing": 0, "part_missing": 0, "name_empty": 0,
            "set_missing": 0, "sub_missing": 0, "pct_inferred": 0, "score_missing": 0,
        }

    def _pressed(self, vk: int) -> bool:
        down = bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
        was = self._key_state[vk]
        self._key_state[vk] = down
        return down and not was

    def poll_hotkeys(self) -> bool:
        if self._pressed(VK_F10):
            self.stop_reason = "user_f10"
            log("⏹ 收到 F10 热键，停止装备扫描。")
            return False
        if self._pressed(VK_F8):
            self.paused = not self.paused
            log("⏸ 已暂停扫描（F8 继续 / F10 退出）" if self.paused else "▶ 继续扫描")
        return True

    def _wait_hotkeys(self, sec: float) -> bool:
        end = time.time() + sec
        while time.time() < end:
            if not self.poll_hotkeys():
                return False
            if self.paused:
                time.sleep(0.1)
                end += 0.1
                continue
            time.sleep(0.05)
        return True

    def _wait_stable(self, timeout: float = 1.2) -> np.ndarray | None:
        prev = None
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.poll_hotkeys():
                return None
            img = self.win.capture("auto")
            sig = _grid_sig(img)
            if prev is not None and float(np.abs(sig - prev).mean()) < 1.5:
                return img
            prev = sig
            time.sleep(0.08)
        return self.win.capture("auto")

    def _check_bag_screen(self, items: list[OcrItem], w: int, h: int) -> tuple[bool, str | None]:
        all_txt = "".join(norm(it.text) for it in items)
        in_bag = any("背包" in norm(it.text) and it.center[0] / w < 0.16 and it.center[1] / h < 0.10 for it in items)
        if not in_bag:
            return False, None
        bag_count = None
        for it in items:
            if it.center[0] / w >= 0.65 and it.center[1] / h <= 0.18:
                m = re.fullmatch(r"\d+/\d+", norm(it.text))
                if m:
                    bag_count = m.group(0)
                    break
        if "最大强化" not in all_txt:
            log("⚠ 提示：右侧未检测到「最大强化」排序，请确认已按「最大强化」排序。")
        return True, bag_count

    @staticmethod
    def _identity(parsed: dict) -> tuple:
        """装备内容指纹：用于判断面板是否真的切换到了下一件（同款武器面板极其相似，不能用图像 diff）。"""
        subs = tuple(sorted((s["key"], str(s["value"])) for s in parsed.get("substats") or []))
        main = parsed.get("main_stat") or {}
        return (
            parsed.get("name"),
            parsed.get("level"),
            parsed.get("quality"),
            parsed.get("part"),
            parsed.get("score"),
            main.get("key"),
            str(main.get("value")),
            subs,
        )

    def _save_fail_frame(self, img: np.ndarray, tag: str) -> None:
        try:
            d = ROOT / "debug"
            d.mkdir(parents=True, exist_ok=True)
            p = d / f"equip_{tag}_{datetime.now():%m%d_%H%M%S}.png"
            cv2.imencode(".png", img)[1].tofile(str(p))
        except Exception:  # noqa: BLE001
            pass

    def _finalize_parsed(
        self,
        parsed: dict,
        badge: dict,
        page: int,
        row_idx: int,
        items: list[OcrItem],
        w: int,
        h: int,
        ident: tuple,
    ) -> dict:
        """统一写入位置/序号并记录 OCR 日志，避免多路径重复。"""
        self._last_identity = ident
        parsed["page"] = page
        parsed["row"] = row_idx
        parsed["col"] = badge["col"]
        parsed["id"] = len(self.gears) + 1   # 先给 id，日志里才不会显示 #None（主循环随后会写同值）
        self._log_item_ocr(parsed, badge, items, w, h)
        return parsed

    def _detect_missing_r1c1_badge(self, img: np.ndarray, first_row: list[dict]) -> dict | None:
        """P1 首行从 C2 起时，放宽模板阈值（红占比仍严格 >=0.25）复查同行的 R1C1 徽章。"""
        if not first_row or first_row[0]["col"] < 1:
            return None
        row_y = first_row[0]["cy"]
        for row in detect_plus15_badges(img, self.tmpl, tmpl_thresh=0.58, red_thresh=0.25):
            for b in row:
                if b["col"] == 0 and abs(b["cy"] - row_y) <= 0.045:
                    return b
        return None

    def _ocr_right_panel(self, img: np.ndarray) -> list[OcrItem]:
        """仅裁切右侧详情面板做 OCR，避免全屏大图缩放导致副属性数字被粘连合并。"""
        h, w = img.shape[:2]
        x0 = max(0, int(w * (PANEL_X_MIN - 0.01)))
        y0 = max(0, int(h * 0.17))
        y1 = min(h, int(h * 0.98))
        crop = img[y0:y1, x0:w]
        items = self.ocr.read(crop, 0.50)
        return [
            OcrItem(
                it.text,
                it.score,
                (it.box[0] + x0, it.box[1] + y0, it.box[2] + x0, it.box[3] + y0),
                it.brightness,
            )
            for it in items
        ]

    def _try_read_initial_c1(self, img: np.ndarray, badge: dict) -> tuple[dict | None, str]:
        """P1R1C1 若已自带选中金框，直接读取当前右侧面板，避免首击干扰。"""
        try:
            h, w = img.shape[:2]
            g_sc, g_hits = score_gold_border(img, badge["cx"], badge["cy"])
            if not _is_gold_hit(g_sc, g_hits):
                return None, f"no_gold(sc={g_sc:.2f},hits={g_hits})"
            items = self._ocr_right_panel(img)
            diag: dict = {}
            parsed = parse_right_panel(items, w, h, diag=diag)
            if parsed is None:
                return None, f"panel_{diag.get('reason', 'unknown')}"
            ident = self._identity(parsed)
            if self._last_identity is not None and ident == self._last_identity:
                return None, "same_ident"
            return self._finalize_parsed(parsed, badge, 0, 0, items, w, h, ident), "ok"
        except Exception as exc:  # noqa: BLE001
            return None, f"err:{exc.__class__.__name__}"

    def _log_c1_fail_diag(
        self,
        badge: dict,
        pre_img: np.ndarray | None,
        pre_reason: str,
        attempts: list[tuple[np.ndarray, list[OcrItem], tuple[float, float], str]],
    ) -> None:
        """仅在 P1R1C1 最终失败时保存现场截图与诊断摘要，正常扫描零输出。"""
        try:
            if pre_img is not None:
                self._save_fail_frame(pre_img, "p1_r1c1_pre")
            if attempts:
                self._save_fail_frame(attempts[-1][0], "p1_r1c1_fail")
            pw_ok = "n/a"
            try:
                pw_ok = str(bool(self.win._is_valid_pw_frame(self.win._capture_printwindow())))
            except Exception:  # noqa: BLE001
                pass
            reasons = ",".join(f"a{i}:{r}" for i, (_im, _it, _xy, r) in enumerate(attempts)) or "none"
            clicks = ",".join(f"a{i}:({xy[0]:.4f},{xy[1]:.4f})" for i, (_im, _it, xy, _r) in enumerate(attempts)) or "none"
            line = (
                f"🩺 [C1诊断] pre={pre_reason} attempts=[{reasons}] click_mode={getattr(self.win, 'click_mode', '?')} "
                f"pw_ok={pw_ok} badge=({badge['cx']:.4f},{badge['cy']:.4f},sc={badge.get('score')},red={badge.get('red')}) "
                f"clicks=[{clicks}]"
            )
            log(line)
            if self._ocr_log_path is not None:
                with self._ocr_log_path.open("a", encoding="utf-8") as fp:
                    fp.write(line + "\n")
                    if attempts:
                        last_img, last_items, _xy, _r = attempts[-1]
                        lh, lw = last_img.shape[:2]
                        raw = " | ".join(
                            f"({it.center[0]/lw:.3f},{it.center[1]/lh:.3f}){norm(it.text)}"
                            for it in sorted(last_items, key=lambda i: (i.center[1], i.center[0]))
                            if it.center[0] / lw >= PANEL_X_MIN
                        )
                        fp.write(f"    C1_FAIL_PANEL_OCR: {raw}\n")
        except Exception:  # noqa: BLE001
            pass

    def _click_and_read(
        self,
        badge: dict,
        page: int,
        row_idx: int,
        initial_img: np.ndarray | None = None,
    ) -> dict | None:
        """点击卡片 → 等面板刷新 → OCR 解析；用金框或内容变化确认点击生效（不漏同款双胞胎）。"""
        is_c1 = page == 0 and row_idx == 0 and badge.get("col") == 0
        pre_reason = "skipped"
        if is_c1 and initial_img is not None:
            pre_parsed, pre_reason = self._try_read_initial_c1(initial_img, badge)
            if pre_parsed is not None:
                return pre_parsed

        cx, cy = badge_to_click_ratio(badge["cx"], badge["cy"])
        prev_ident = self._last_identity
        parsed: dict | None = None
        gold_on_card = False
        items: list[OcrItem] = []
        w = h = 0
        ident: tuple = ()
        cx_offsets = (0.0, 0.012, 0.006)
        c1_attempts: list[tuple[np.ndarray, list[OcrItem], tuple[float, float], str]] = []

        for attempt in range(3 if is_c1 else 2):
            cx_now = min(0.64, cx + cx_offsets[attempt])
            self.win.click_ratio(cx_now, cy, jitter=2, clicks=1, hold=CLICK_HOLD)
            time.sleep(0.65 if (is_c1 and attempt >= 1) else 0.45)
            img = self.win.capture("auto")
            h, w = img.shape[:2]
            items = self._ocr_right_panel(img)
            diag: dict | None = {} if is_c1 else None
            parsed = parse_right_panel(items, w, h, diag=diag)
            if parsed is None:
                if is_c1:
                    c1_attempts.append((img, items, (cx_now, cy), str((diag or {}).get("reason", "unknown"))))
                continue
            ident = self._identity(parsed)
            g_score, g_hits = score_gold_border(img, badge["cx"], badge["cy"])
            gold_on_card = _is_gold_hit(g_score, g_hits)
            if ident != prev_ident or gold_on_card:
                break
            if is_c1:
                c1_attempts.append((img, items, (cx_now, cy), "same_ident_no_gold"))

        if parsed is None or (prev_ident is not None and ident == prev_ident and not gold_on_card):
            if is_c1:
                self._log_c1_fail_diag(badge, initial_img, pre_reason, c1_attempts)
            return None
        return self._finalize_parsed(parsed, badge, page, row_idx, items, w, h, ident)

















    @staticmethod
    def _fmt_stat(st: dict | None) -> str:
        if not st:
            return "?"
        return f"{st.get('key') or st.get('type')}={st.get('value')}{'%' if st.get('is_percent') else ''}"

    def _log_item_ocr(self, parsed: dict, badge: dict, items: list[OcrItem], w: int, h: int) -> None:
        """把每件装备的解析结果（含百分号）打到日志 + 记 OCR 自检计数，供玩家/维护者核对命中率。"""
        try:
            subs = parsed.get("substats") or []
            main = parsed.get("main_stat")
            setinfo = parsed.get("set") or {}
            line = (
                f"🧾 #{parsed.get('id')} [P{parsed['page'] + 1} R{parsed['row'] + 1}C{badge['col'] + 1}] "
                f"Lv{parsed.get('level')}/{parsed.get('quality')}/{parsed.get('part')} {parsed.get('name')} | "
                f"主 {self._fmt_stat(main)} | 副 " + " ".join(self._fmt_stat(s) for s in subs) +
                f" | 分{parsed.get('score')} | "
                f"{setinfo.get('name') or '?'}({setinfo.get('pieces')}/{setinfo.get('required')}) | "
                f"装{'是' if parsed.get('equipped') else '否'}"
            )
            log(line)
            qc = self._qc
            qc["total"] += 1
            if parsed.get("level") is None:
                qc["level_missing"] += 1
            if not parsed.get("part"):
                qc["part_missing"] += 1
            if not parsed.get("name"):
                qc["name_empty"] += 1
            if not parsed.get("set"):
                qc["set_missing"] += 1
            if parsed.get("score") is None:
                qc["score_missing"] += 1
            if len(subs) < 4:
                qc["sub_missing"] += 1
            qc["pct_inferred"] += sum(1 for s in subs if s.get("pct_inferred")) + (
                1 if main and main.get("pct_inferred") else 0
            )
            if self._ocr_log_path is not None:
                raw = " | ".join(
                    norm(it.text) for it in sorted(items, key=lambda i: (i.center[1], i.center[0]))
                    if it.center[0] / w >= PANEL_X_MIN
                )
                with self._ocr_log_path.open("a", encoding="utf-8") as fp:
                    fp.write(line + "\n")
                    fp.write(f"    RAW: {raw}\n")
        except Exception:  # noqa: BLE001
            pass

    def _scroll_to_gold_anchor(
        self, img_before: np.ndarray, gold_badge: dict
    ) -> tuple[bool, np.ndarray | None, float | None]:
        """以金色选中框为唯一锚点向上滑：目标停在顶行(0.221)，过头则向下回拉直到金框重现。

        返回: (是否触底/停, 最终画面, 金框当前所在行 y)。
        """
        img = img_before
        gold_col = int(gold_badge["col"])
        y_curr: float | None = float(gold_badge["cy"])
        down_streak = 0

        for step_idx in range(1, 9):
            direction, y_s, y_e, drag_dy, dur = _plan_gold_scroll_step(y_curr, self._scroll_gain)
            if direction == "aligned":
                return False, img, y_curr

            prev_sig = _grid_sig(img)
            steps = max(12, int(round(drag_dy * 60)))
            self.win.drag_ratio(0.398, y_s, 0.398, y_e, duration=dur, steps=steps, settle=0.28)
            time.sleep(0.16)
            next_img = self._wait_stable()
            if next_img is None:
                return True, None, None

            gdiff = float(np.abs(_grid_sig(next_img) - prev_sig).mean())
            if direction == "up" and gdiff < 1.8:
                log(f"📜 金框翻页 #{step_idx}: drag={drag_dy:.3f} → 列表已触底 (diff={gdiff:.2f})")
                return True, next_img, y_curr

            rows_now = detect_plus15_badges(next_img, self.tmpl)
            row_ys = [round(r[0]["cy"], 3) for r in rows_now]
            g_badge, g_score, g_hits = find_gold_badge_in_rows(next_img, rows_now, target_col=gold_col)
            y_new: float | None = None
            if g_badge is not None:
                y_new = float(g_badge["cy"])

            if direction == "up" and y_curr is not None and y_new is not None:
                moved = y_curr - y_new
                if drag_dy >= 0.08 and moved > 0.03:
                    step_gain = max(0.35, min(3.0, moved / drag_dy))
                    self._scroll_gain = (
                        step_gain if self._scroll_gain is None
                        else round(0.6 * self._scroll_gain + 0.4 * step_gain, 3)
                    )

            log(
                f"📜 金框翻页 #{step_idx}({direction}): drag={drag_dy:.3f} | "
                f"gold_y:{y_curr}→{y_new} (sc={g_score:.2f}, hits={g_hits}, gain={self._scroll_gain}) | 行={row_ys}"
            )
            img = next_img
            y_curr = y_new

            if y_curr is None:
                down_streak += 1
                if down_streak >= 3:
                    self.stop_reason = "gold_anchor_lost_after_rollback"
                    self._save_fail_frame(img, "gold_lost")
                    log("❌ 连续 3 次回滚仍未找回金框，安全停止防漏行（已存图）。")
                    return True, None, None
                continue
            down_streak = 0

            # 向上滑目标 Row0 [0.205,0.238]；若是回滚后重现，只要在 [0.205,0.400](Row0~1) 即直接停，零震荡
            if 0.205 <= y_curr <= (0.400 if direction == "down" else 0.238):
                return False, img, y_curr

        if y_curr is not None and 0.205 <= y_curr <= 0.500:
            return False, img, y_curr
        self.stop_reason = f"gold_align_failed(y={y_curr})"
        self._save_fail_frame(img, "gold_align_fail")
        log(f"⚠ 翻页 8 步后金框位置异常（y={y_curr}），安全停止防漏行。")
        return True, None, None

    def _ensure_next_rows(self, img: np.ndarray, gold_y: float | None) -> tuple[np.ndarray | None, float | None]:
        """翻页后确保「金框行下方」至少还有一行可见（对齐误差可能把下一行挤出屏幕）。

        若下方一个检测行都没有，则向下回拉约一个行距让下一行重新露出，并更新金框基准 y。
        """
        if gold_y is None:
            return img, gold_y
        rows = detect_plus15_badges(img, self.tmpl)
        if any(r[0]["cy"] > gold_y + 0.055 for r in rows):
            return img, gold_y
        max_y = max((r[0]["cy"] for r in rows), default=0.0)
        dy = max(0.04, min(0.16, 0.905 - max_y))
        dur = max(0.26, dy * 1023.0 / 450.0)
        steps = max(12, int(dy * 60))
        self.win.drag_ratio(0.398, 0.36, 0.398, round(0.36 + dy, 4), duration=dur, steps=steps, settle=0.28)
        time.sleep(0.16)
        img2 = self._wait_stable()
        if img2 is None:
            return None, gold_y
        rows2 = detect_plus15_badges(img2, self.tmpl)
        gb, _sc, _hits = find_gold_badge_in_rows(img2, rows2)
        new_gold = float(gb["cy"]) if gb is not None else gold_y
        log(f"📐 金框下方无行 → 向下回拉 dy={dy:.3f}，金框基准y={new_gold:.3f}")
        return img2, new_gold

    def _ensure_layout(self, img: np.ndarray) -> np.ndarray | None:
        """翻页后布局校验：顶部行 y 必须在 [0.195, 0.245]（多滑/少滑约一行时自动小步回调）。

        校验失败会安全停止（宁可停，也不静默漏掉一整行）。
        """
        for attempt in range(3):
            rows = detect_plus15_badges(img, self.tmpl)

            if not rows:
                return img  # 本页已无 +15 行，交给主循环判定结束
            top = rows[0][0]["cy"]
            if 0.195 <= top <= 0.245:
                if attempt > 0:
                    log(f"📐 布局校正完成 #{attempt}: top_y={top:.3f}")
                return img
            dy = max(0.05, min(0.30, abs(ROW0_CENTER_Y - top)))
            dur = max(0.24, dy * 1023.0 / 500.0)
            steps = max(12, int(round(dy * 60)))
            if top < ROW0_CENTER_Y:
                # 内容滑过了头 → 向下小步回拉
                self.win.drag_ratio(0.398, 0.34, 0.398, round(0.34 + dy, 4), duration=dur, steps=steps, settle=0.28)
            else:
                # 滑得不够 → 继续向上小步
                self.win.drag_ratio(0.398, 0.80, 0.398, round(0.80 - dy, 4), duration=dur, steps=steps, settle=0.28)
            time.sleep(0.16)
            img = self._wait_stable()
            if img is None:
                return None
            log(f"📐 布局校正 #{attempt+1}: top_y={top:.3f} 偏 {top - ROW0_CENTER_Y:+.3f} → 回调 dy={dy:.3f}")
        rows = detect_plus15_badges(img, self.tmpl)
        if rows and 0.195 <= rows[0][0]["cy"] <= 0.245:
            log(f"📐 布局校正完成: top_y={rows[0][0]['cy']:.3f}")
            return img
        self.stop_reason = "align_verify_failed"
        log("⚠ 翻页后布局校验失败（顶部行位置仍不对），安全停止防漏行。")
        return None

    def run(self) -> Path | None:
        img = self.win.capture("auto")
        h, w = img.shape[:2]
        items = self.ocr.read(img, 0.50)
        in_bag, bag_count = self._check_bag_screen(items, w, h)
        if not in_bag:
            self.stop_reason = "not_in_bag"
            log("❌ 未检测到装备背包界面，请先打开背包并切换到「全部」页签。")
            return self._save_report(bag_count)

        log(f"✅ 开始扫描背包 +15 装备（背包数量：{bag_count or '未知'}，分辨率：{w}×{h}）")
        try:
            d = ROOT / "debug"
            d.mkdir(parents=True, exist_ok=True)
            self._ocr_log_path = d / f"装备扫描_OCR详情_{datetime.now():%Y%m%d_%H%M%S}.txt"
            self._ocr_log_path.write_text(
                f"# E7Pilot 装备扫描 OCR 详情 {datetime.now().isoformat(timespec='seconds')} "
                f"res={w}x{h}\n"
                "# 每件装备：解析结果一行 + 右侧面板原始 OCR 一行（RAW）；可对照游戏核对命中率\n",
                encoding="utf-8",
            )
            log(f"🧪 OCR 详情日志：{self._ocr_log_path}")
        except Exception:  # noqa: BLE001
            self._ocr_log_path = None

        consecutive_parse_fail = 0
        page = 0
        total_pages_cap = 60
        gold_cut_y: float | None = None
        at_bottom = False

        while page < total_pages_cap:
            if not self.poll_hotkeys():
                break
            if self.paused:
                time.sleep(0.1)
                continue

            if page == 0:
                fixed = self._ensure_layout(img)
                if fixed is None:
                    break
                img = fixed

            rows = detect_plus15_badges(img, self.tmpl)

            if page == 0 and rows and rows[0][0]["col"] >= 1:
                extra_c1 = self._detect_missing_r1c1_badge(img, rows[0])
                if extra_c1 is not None:
                    rows[0].insert(0, extra_c1)
                    log(f"📐 R1C1 徽章低分兜底命中（score={extra_c1['score']:.3f}, red={extra_c1['red']:.3f}）")
                else:
                    log(f"🩺 [C1诊断] P1首行未检出R1C1(col=0)，首列=C{rows[0][0]['col']+1}，行y={rows[0][0]['cy']:.3f}")
                    self._save_fail_frame(img, "p1_no_c1")

            if rows:
                log(
                    f"📐 第 {page+1} 页布局: 行y={[round(r[0]['cy'], 3) for r in rows]} "
                    f"金框基准y={gold_cut_y}"
                )
            if page == 0 and not rows:
                self.stop_reason = "no_plus15_on_first_page"
                log("❌ 第 1 页未检测到任何 +15 装备（请确认已在「全部」页签按「最大强化」降序排序）。")
                break

            # 核心边界：只扫严格位于「上页最后金框行」下方的行（绝不漏行、也不重复该行及上方行）
            unscanned_rows = (
                rows if gold_cut_y is None
                else [r for r in rows if r[0]["cy"] > (gold_cut_y + 0.055)]
            )
            if at_bottom:
                scan_rows = unscanned_rows
                anchor_rows = []
            else:
                scan_rows = [r for r in unscanned_rows if r[0]["cy"] <= BOTTOM_CUT_Y]
                anchor_rows = [r for r in unscanned_rows if r[0]["cy"] > BOTTOM_CUT_Y]

            if not scan_rows and not anchor_rows:
                self.stop_reason = "reached_list_bottom" if at_bottom else "no_more_plus15"
                log("✅ 本页下方已无 +15 装备，扫描结束。")
                break

            for r_idx, row in enumerate(scan_rows):
                for badge in row:
                    if not self._wait_hotkeys(0.02):
                        return self._save_report(bag_count)
                    init_img = img if (page == 0 and r_idx == 0 and badge.get("col") == 0) else None
                    parsed = self._click_and_read(badge, page=page, row_idx=r_idx, initial_img=init_img)
                    if parsed is None:
                        consecutive_parse_fail += 1
                        log(f"⚠ 第 {page+1} 页第 {r_idx+1} 行第 {badge['col']+1} 列解析失败（{consecutive_parse_fail}/3）")
                        if consecutive_parse_fail >= 3:
                            self.stop_reason = "parse_failed_3x"
                            log("❌ 连续 3 次解析异常，安全停止（若游戏内弹出了装备详情大窗，请手动关闭后重试）。")
                            return self._save_report(bag_count)
                        continue
                    consecutive_parse_fail = 0
                    parsed["id"] = len(self.gears) + 1
                    self.gears.append(parsed)
                    log(
                        f"📦 #{parsed['id']} [P{page+1} R{r_idx+1}C{badge['col']+1}] "
                        f"{parsed['level']} {parsed['quality']}{parsed['part']} "
                        f"分={parsed['score']} 装={'是' if parsed['equipped'] else '否'}"
                    )

                cols = [b["col"] for b in row]
                if len(row) < 7:
                    if cols == list(range(len(cols))):
                        self.stop_reason = "partial_plus15_row_done"
                        log(f"✅ 第 {page+1} 页第 {r_idx+1} 行只有 {len(row)} 个 +15，已扫描到最后一个 +15，结束。")
                        return self._save_report(bag_count)
                    log(f"⚠ 第 {page+1} 页第 {r_idx+1} 行 +15 徽章不连续（列 {cols}），疑似漏检，继续扫描。")

            if at_bottom:
                self.stop_reason = "reached_list_bottom"
                log("✅ 列表已触底并扫描完毕，扫描完成。")
                break

            # 注意：即使本页没检测到「底部截断行」，也不代表没有更多行——
            # 可能是上一轮对齐误差把底部行挤出屏幕；继续按金框翻页即可（下方行会在翻页后露出来）。

            # 翻页前核实金框确实落在本页最后扫描卡片上（确保翻页基准唯一）
            last_badge = scan_rows[-1][-1]
            cur_img = self.win.capture("auto")
            gold_badge, g_sc, g_hits = find_gold_badge_in_rows(cur_img, [scan_rows[-1]], target_col=last_badge["col"])
            if gold_badge is None:
                cx_l, cy_l = badge_to_click_ratio(last_badge["cx"], last_badge["cy"])
                self.win.click_ratio(cx_l, cy_l, jitter=1, clicks=1, hold=CLICK_HOLD)
                time.sleep(0.28)
                cur_img = self.win.capture("auto")
                gold_badge, g_sc, g_hits = find_gold_badge_in_rows(cur_img, [scan_rows[-1]], target_col=last_badge["col"])
                if gold_badge is None:
                    self.stop_reason = "gold_missing_before_scroll"
                    self._save_fail_frame(cur_img, "gold_missing")
                    log(f"❌ 翻页前未能确认金框所在卡片（sc={g_sc:.2f}, hits={g_hits}），安全停止。")
                    break

            at_bottom, next_img, gold_cut_y = self._scroll_to_gold_anchor(cur_img, gold_badge)
            if next_img is None or gold_cut_y is None:
                break
            if not at_bottom:
                # 兜底：对齐误差可能把"下一行"挤出屏幕 → 向下回拉一点让它重新露出
                next_img, gold_cut_y = self._ensure_next_rows(next_img, gold_cut_y)
                if next_img is None or gold_cut_y is None:
                    break
            img = next_img
            page += 1

        return self._save_report(bag_count)

    def _save_report(self, bag_count: str | None) -> Path:
        out_dir = ROOT / "debug"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = out_dir / f"装备扫描_{stamp}.json"
        try:
            w, h = self.win.client_size()
        except Exception:  # noqa: BLE001
            w, h = 0, 0
        payload = {
            "meta": {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "resolution": [w, h],
                "bag_count": bag_count,
                "scanned_count": len(self.gears),
                "stop_reason": self.stop_reason,
                "ocr_log": str(self._ocr_log_path) if self._ocr_log_path else None,
            },
            "ocr_qc": dict(self._qc),
            "summary": aggregate_stats(self.gears),
            "items": self.gears,
        }
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        log("=" * 58)
        log(f"🎉 扫描结束（{self.stop_reason}），共记录 {len(self.gears)} 件 +15 装备")
        log(f"📄 结果已保存：{out_path}")
        qc = self._qc
        log(
            f"🧪 OCR 自检：共 {qc['total']} 件 | 缺等级 {qc['level_missing']} 缺部位 {qc['part_missing']} "
            f"空名称 {qc['name_empty']} 缺套装 {qc['set_missing']} 副属性<4 {qc['sub_missing']} "
            f"缺分数 {qc['score_missing']} | 百分号兜底 {qc['pct_inferred']} 次"
        )
        if self._ocr_log_path is not None:
            log(f"🧪 OCR 详情（逐件解析 + 原始OCR）：{self._ocr_log_path}")
        log("=" * 58)
        for freq in (1000, 1300):
            try:
                winsound.Beep(freq, 200)
            except Exception:  # noqa: BLE001
                pass
        return out_path


def main() -> int:
    _setup_console_encoding()
    if not is_admin():
        log("⚠ 提示：当前未授予管理员权限，若点击无反应请以管理员运行。")
    win = open_game_window(read_click_mode())
    if win is None:
        print("❌ 未找到《第七史诗》游戏窗口，请先打开 Steam 版游戏并进入装备背包。", flush=True)
        return 1
    if getattr(win, "hwnd", 0) == 0:
        print("⚠ P1 暂仅支持 Steam 窗口模式，模拟器坐标将在后续版本适配。", flush=True)
        return 1
    if win.is_minimized():
        win.activate()
    ocr = Ocr()
    EquipScanner(win, ocr).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
