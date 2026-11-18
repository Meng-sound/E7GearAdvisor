"""强力版「布里克强攻」战斗控制器：observe → decide 状态机 + 模板匹配。

核心规则：
  1. 道中优先级：AoE > 主动S2 > S1；非 AoE 的大招 S3 默认扣住。
  2. Boss 带小弟：单击 S1 后点小弟；同一目标连续 2 次伤害没死换第二个，
     第二个再 1 次没死就直接转火 Boss。残血小弟（≤1/3）只交 S1，AoE 例外。
  3. 烧魂只打 Boss：小弟清空（Boss 单挑）后才点亮 Burn!；屏幕上没有 Burn! 按钮时
     连点 2 次仍无 Cancel 会自动改为直接交技能。能否烧魂只看按钮，不按角色名拦截。
  4. 罪戾的安洁莉卡（奶妈）：Boss 回合开局优先交 S3 全队加伤害提速。
  5. 角色知识表：指挥官萝里娜没有主动 S2（S2 是被动图标，点了没反应），
     因此绝不点她的 S2 槽。（「灵魂不足」只是神兽提示，不作为判据）
  6. 防呆：同一个技能槽连点 3 次画面毫无变化 → 判定该槽点不动，立刻改走平A/退出烧魂，
     绝不再对着无效按钮无限连点（旧版曾因此卡在「烧魂S2」直到 12 次自动暂停）。
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from core import OcrItem, runtime_root

ROOT = runtime_root()
TEMPLATE_DIR = ROOT / "templates"

# 模板基准分辨率
BASE_1883 = (1883, 1059)
BASE_1666 = (1666, 937)

BURN_BTN_POS = (0.545, 0.905)
AUTO_BTN_POS = (0.881, 0.047)
SKILL_POS: dict[int, tuple[float, float]] = {
    1: (0.800, 0.917),
    2: (0.878, 0.917),
    3: (0.955, 0.917),
}
_SLOT_BY_POS: dict[tuple[float, float], int] = {pos: slot for slot, pos in SKILL_POS.items()}


def detect_head_hp_bars(img) -> tuple:
    """头顶血条：徽章定起点 + 固定外框槽宽列投影，返回 (ally_ratios, enemy_ratios)。"""
    import cv2 as _cv2
    import numpy as _np

    h, w = img.shape[:2]
    if h < 80 or w < 80:
        return [], []

    hsv = _cv2.cvtColor(img, _cv2.COLOR_BGR2HSV)
    h_ch, s_ch, v_ch = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]

    alive = (
        ((h_ch >= 18) & (h_ch <= 92) & (s_ch >= 80) & (v_ch >= 95))
        | (((h_ch <= 17) | (h_ch >= 170)) & (s_ch >= 115) & (v_ch >= 110))
    ).astype(_np.uint8) * 255
    kernel = _cv2.getStructuringElement(_cv2.MORPH_RECT, (7, 1))
    bridged = _cv2.morphologyEx(alive, _cv2.MORPH_CLOSE, kernel)
    num, _labels, stats, _cents = _cv2.connectedComponentsWithStats(bridged, 8)

    min_bw = max(3, int(w * 0.005))
    max_bw = int(w * 0.085)
    max_bh = max(4, int(h * 0.022))

    segs = []
    for i in range(1, num):
        x, y, bw, bh, area = [int(v) for v in stats[i]]
        if y < int(h * 0.12) or y > int(h * 0.65):
            continue
        if bh < 2 or bh > max_bh or bw < min_bw or bw > max_bw:
            continue
        if area < bw * bh * 0.30:
            continue
        segs.append([x, y, bw, bh])

    segs.sort(key=lambda sg: (sg[1] // 6, sg[0]))
    merged = []
    for seg in segs:
        x, y, bw, bh = seg
        if merged and abs(y - merged[-1][1]) <= 3 and (x - (merged[-1][0] + merged[-1][2])) <= int(w * 0.015):
            prev = merged[-1]
            prev[2] = max(prev[0] + prev[2], x + bw) - prev[0]
            prev[3] = max(prev[3], bh)
        else:
            merged.append(seg)

    ally, enemy = [], []
    ally_full_w = max(12.0, w * 0.0425)
    enemy_full_w = max(12.0, w * 0.0380)

    for x, y, bw, bh in merged:
        bx0 = max(0, x - int(w * 0.024))
        by0 = max(0, y - int(h * 0.008))
        by1 = min(h, y + bh + int(h * 0.012))
        badge_s = s_ch[by0:by1, bx0:x]
        badge_v = v_ch[by0:by1, bx0:x]
        if badge_s.size == 0 or int(((badge_s >= 75) & (badge_v >= 75)).sum()) < 10:
            continue

        is_enemy = x >= int(w * 0.46)
        if not is_enemy:
            far_bx0 = max(0, x - int(w * 0.045))
            far_h = h_ch[by0:by1, far_bx0:x]
            far_s = s_ch[by0:by1, far_bx0:x]
            red_ball = int(((far_s >= 110) & ((far_h <= 12) | (far_h >= 168))).sum())
            purple_gold = int(
                ((far_s >= 80) & (((far_h >= 115) & (far_h <= 165)) | ((far_h >= 15) & (far_h <= 35)))).sum()
            )
            if red_ball > purple_gold * 1.5 and x >= int(w * 0.38):
                is_enemy = True

        std_w = enemy_full_w if is_enemy else ally_full_w
        scan_x1 = min(w, x + int(round(std_w * 1.12)))
        strip_alive = bridged[y: y + bh, x:scan_x1] > 0
        if strip_alive.size == 0:
            continue
        col_alive = strip_alive.mean(axis=0) >= 0.35
        idxs = _np.where(col_alive)[0]
        if idxs.size == 0:
            continue
        span_px = float(idxs[-1] - idxs[0] + 1)
        active_px = float(col_alive.sum())
        eff_px = span_px if (active_px / max(1.0, span_px)) >= 0.65 else active_px
        ratio = float(_np.clip(eff_px / std_w, 0.02, 1.0))
        (enemy if is_enemy else ally).append(round(ratio, 3))

    return ally, enemy


def slot_for_pos(pos) -> int | None:
    """按 x 坐标判断这是第几个技能槽（忽略 y：小窗口技能行更靠下，y 会变）。"""
    try:
        x = float(pos[0])
    except (TypeError, ValueError, IndexError):
        return None
    for slot, (sx, _sy) in SKILL_POS.items():
        if abs(sx - x) <= 0.02:
            return slot
    return None

def map_skill_slots_by_x(icon_xs) -> dict:
    """根据底部亮技能图标 x 列表生成本帧局部槽位映射（不修改全局 SKILL_POS）。"""
    xs = sorted(round(float(x), 4) for x in icon_xs)
    if len(xs) >= 3:
        xs = xs[-3:]
        return {1: xs[0], 2: xs[1], 3: xs[2]}
    if len(xs) == 2:
        return {1: xs[0], 2: xs[1]}
    if len(xs) == 1:
        return {1: xs[0]}
    return {slot: pos[0] for slot, pos in SKILL_POS.items()}


_LAST_SLOT_Y = 0.0
_STD_SLOT_XS = (0.799, 0.878, 0.955)


def detect_lit_skill_xs(img) -> list:
    """金色选中描边定锚 + 三槽网格门控：不在场返回 []，在场返回 2~3 个槽位中心 x。"""
    global _LAST_SLOT_Y
    import cv2 as _cv2
    import numpy as _np

    h, w = img.shape[:2]
    if h < 80 or w < 80:
        return []

    above = img[int(h * 0.740): int(h * 0.815), int(w * 0.760): int(w * 0.990)]
    if above.size > 0:
        ah = _cv2.cvtColor(above, _cv2.COLOR_BGR2HSV)
        gold_above = (ah[:, :, 0] >= 8) & (ah[:, :, 0] <= 34) & (ah[:, :, 1] >= 90) & (ah[:, :, 2] >= 150)
        if float(gold_above.mean()) >= 0.28:
            return []

    y0, y1 = int(h * 0.835), int(h * 0.985)
    x0, x1 = int(w * 0.755), int(w * 0.995)
    strip = img[y0:y1, x0:x1]
    if strip.size == 0:
        return []

    hsv = _cv2.cvtColor(strip, _cv2.COLOR_BGR2HSV)
    h_ch, s_ch, v_ch = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    gold = (h_ch >= 8) & (h_ch <= 34) & (s_ch >= 88) & (v_ch >= 150)
    cyan = (h_ch >= 85) & (h_ch <= 130) & (s_ch >= 90) & (v_ch >= 160)
    halo = gold | cyan

    sh = y1 - y0
    top_band = slice(0, max(1, int(sh * 0.32)))
    bot_band = slice(min(sh - 1, int(sh * 0.68)), sh)

    selected_slot = None
    best = 0.0
    yc = 0.914 if h >= 900 else 0.910

    for idx, scx in enumerate(_STD_SLOT_XS, start=1):
        sx0 = max(0, int(w * (scx - 0.038)) - x0)
        sx1 = min(x1 - x0, int(w * (scx + 0.038)) - x0)
        if sx1 <= sx0 + 4:
            continue
        sub = halo[:, sx0:sx1]
        top_r = float(sub[top_band, :].mean())
        bot_r = float(sub[bot_band, :].mean())
        tot_r = float(sub.mean())
        if top_r >= 0.055 and bot_r >= 0.045 and tot_r >= 0.055:
            score = top_r + bot_r + tot_r
            if score > best:
                best = score
                selected_slot = idx
                ys = _np.where(sub.mean(axis=1) >= 0.08)[0]
                if ys.size >= 4:
                    yc = float(_np.clip((y0 + 0.5 * float(ys[0] + ys[-1])) / h, 0.895, 0.955))

    if selected_slot is None:
        return []

    seam_x0 = max(0, int(w * 0.834) - x0)
    seam_x1 = min(x1 - x0, max(seam_x0 + 2, int(w * 0.843) - x0))
    seam_v = v_ch[int(sh * 0.25): int(sh * 0.75), seam_x0:seam_x1]
    if seam_v.size > 0 and float(_np.min(seam_v.mean(axis=0))) > 165.0:
        return []

    gray = _cv2.cvtColor(strip, _cv2.COLOR_BGR2GRAY)
    edges = _cv2.Canny(gray, 50, 130) > 0
    cy_local = int(round(yc * h)) - y0
    iy0 = max(0, cy_local - int(h * 0.042))
    iy1 = min(sh, cy_local + int(h * 0.042))

    present = []
    for idx, scx in enumerate(_STD_SLOT_XS, start=1):
        sx0 = max(0, int(w * (scx - 0.032)) - x0)
        sx1 = min(x1 - x0, int(w * (scx + 0.032)) - x0)
        if sx1 <= sx0 + 4 or iy1 <= iy0 + 4:
            continue
        if idx == selected_slot:
            cols = _np.where((v_ch[iy0:iy1, sx0:sx1] >= 100).mean(axis=0) >= 0.25)[0]
            cx = (x0 + sx0 + 0.5 * float(cols[0] + cols[-1])) / w if cols.size >= 4 else scx
            present.append(round(float(_np.clip(cx, scx - 0.012, scx + 0.012)), 4))
            continue
        bv = v_ch[iy0:iy1, sx0:sx1]
        bs = s_ch[iy0:iy1, sx0:sx1]
        be = edges[iy0:iy1, sx0:sx1]
        lit_ratio = float(((bv >= 105) & (bs >= 25)).mean())
        p75 = float(_np.percentile(bv, 75))
        std = float(bv.std())
        edge_d = float(be.mean())
        # 非选中槽必须真有图标纹理边缘，避免 2 槽英雄的 0.955 空地被亮度骗成第 3 槽
        has_icon_texture = std >= 18.0 and edge_d >= 0.058
        if has_icon_texture and (lit_ratio >= 0.22 or p75 >= 62.0):
            cols = _np.where((bv >= 85).mean(axis=0) >= 0.20)[0]
            cx = (x0 + sx0 + 0.5 * float(cols[0] + cols[-1])) / w if cols.size >= 4 else scx
            present.append(round(float(_np.clip(cx, scx - 0.012, scx + 0.012)), 4))

    if len(present) < 2:
        return []
    _LAST_SLOT_Y = round(yc, 4)
    return present


def _apply_local_skill_xs(plan, slot_xs, icon_y):
    """把本帧局部槽位 x 写进决策结果，不改全局 SKILL_POS。"""
    if not plan or not slot_xs:
        return plan
    ptype = plan.get("type")
    if ptype == "combat_click":
        slot = slot_for_pos(plan.get("pos"))
        if slot is not None and slot in slot_xs:
            plan = dict(plan)
            plan["pos"] = (slot_xs[slot], icon_y)
    elif ptype == "combat_sequence" and plan.get("steps"):
        steps = list(plan["steps"])
        first_pos, first_clicks = steps[0]
        slot = slot_for_pos(first_pos)
        if slot is not None and slot in slot_xs:
            steps[0] = ((slot_xs[slot], icon_y), first_clicks)
            plan = dict(plan)
            plan["steps"] = steps
    return plan




def _apply_pos_overrides() -> None:
    """从 rules.yaml 读按钮位置覆盖（窗口大小不同点不到时，用户可自己微调，不用改代码）。"""
    global BURN_BTN_POS, AUTO_BTN_POS
    try:
        import yaml

        from core import load_rules_cfg

        cfg = load_rules_cfg(ROOT / "rules.yaml")
        st = cfg.get("settings", {}) or {}
        sp = st.get("skill_pos")
        if isinstance(sp, (list, tuple)) and len(sp) == 3:
            for idx, pair in enumerate(sp, start=1):
                if isinstance(pair, (list, tuple)) and len(pair) == 2:
                    SKILL_POS[idx] = (float(pair[0]), float(pair[1]))
        bp = st.get("burn_pos")
        if isinstance(bp, (list, tuple)) and len(bp) == 2:
            BURN_BTN_POS = (float(bp[0]), float(bp[1]))
        ap = st.get("auto_pos")
        if isinstance(ap, (list, tuple)) and len(ap) == 2:
            AUTO_BTN_POS = (float(ap[0]), float(ap[1]))
        _SLOT_BY_POS.clear()
        _SLOT_BY_POS.update({pos: slot for slot, pos in SKILL_POS.items()})
    except Exception:  # noqa: BLE001
        pass


_apply_pos_overrides()

# 技能图标是「固定像素大小、贴右下角」排布：窗口越矮，图标相对越靠下。
# 1131x636 实测图标中心 y≈0.95；1819x1023 时 0.905 恰好命中图标上半部。
SKILL_Y_SMALL = 0.950
SKILL_Y_LARGE = 0.917

# ---------------- 角色知识表（OCR 名字包含任一别名即命中） ----------------
# 指挥官萝里娜：二技能是被动图标（没有技能按钮，点了毫无反应）。
# 旧版把她当成「被动S2」仍去点 S2 烧魂，点了 12 次没反应才自动暂停 —— 这里直接拉黑 S2。
# 注意：烧魂资格只看 Burn! 按钮，不存在按角色名禁止烧魂的名单。
HERO_NO_ACTIVE_S2: tuple[str, ...] = ("萝里娜", "萝丽娜", "萝莉娜", "罗里娜", "罗丽娜", "罗莉娜", "lorina")


def _hero_name_has(hero_name: str, aliases: tuple[str, ...]) -> bool:
    text = (hero_name or "").replace(" ", "").lower()
    return bool(text) and any(alias.lower() in text for alias in aliases)


def hero_has_active_s2(hero_name: str) -> bool:
    """该角色是否真的有「主动二技能」按钮（被动 S2 的角色点了没用）。"""
    return not _hero_name_has(hero_name, HERO_NO_ACTIVE_S2)


def hero_can_soulburn(hero_name: str) -> bool:
    """兼容旧调用：烧魂资格只由 Burn! 按钮决定，不再按角色名拦截。"""
    return True


def _load_png(path: Path, gray: bool = False) -> np.ndarray:
    flag = cv2.IMREAD_GRAYSCALE if gray else cv2.IMREAD_COLOR
    arr = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), flag)
    if arr is None:
        raise FileNotFoundError(f"缺少识别模板文件：{path}")
    return arr


_CLASS_TPL: np.ndarray | None = None


def _class_template() -> np.ndarray | None:
    """加载「辅助职业」小图标模板（灰度），用于名字右侧匹配。"""
    global _CLASS_TPL
    if _CLASS_TPL is None:
        f = TEMPLATE_DIR / "class_support.png"
        if f.exists():
            # 中文路径下 cv2.imread 会失败，必须用 fromfile + imdecode
            data = np.fromfile(str(f), dtype=np.uint8)
            _CLASS_TPL = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    return _CLASS_TPL


class CombatControllerBase:
    """强力版战斗控制器的公共底座：模板缩放、AUTO 检测、波次解析、战斗重置。"""

    def __init__(self) -> None:
        self._raw_templates: dict[str, tuple[np.ndarray, tuple[int, int]]] = {
            "mob_a": (_load_png(TEMPLATE_DIR / "mob_a_tag.png", gray=True), BASE_1883),
            "cancel": (_load_png(TEMPLATE_DIR / "cancel_burn.png", gray=True), BASE_1883),
            "crosshair": (_load_png(TEMPLATE_DIR / "auto_crosshair.png", gray=True), BASE_1666),
            "class_support": (_load_png(TEMPLATE_DIR / "class_support.png", gray=True), BASE_1883),
        }
        self._scaled_cache: dict[tuple[str, int, int], np.ndarray] = {}
        self.reset_battle()

    @staticmethod
    def _write(prefix: str, msg: str) -> None:
        try:
            from datetime import datetime as _dt

            from core import runtime_root

            d = runtime_root() / "debug"
            d.mkdir(parents=True, exist_ok=True)
            f = d / f"{prefix}_{_dt.now():%Y%m%d}.txt"
            with f.open("a", encoding="utf-8") as fp:
                fp.write(f"[{_dt.now():%H:%M:%S}] {msg}\n")
        except Exception:  # noqa: BLE001
            pass

    def _devlog(self, msg: str) -> None:
        """AI 日志：技术细节，写 debug\\AI战斗日志_YYYYMMDD.txt。"""
        self._write("AI战斗日志", msg)

    def _userlog(self, msg: str) -> None:
        """战斗解读：纯中文，写 debug\\战斗解读_YYYYMMDD.txt。"""
        self._write("战斗解读", msg)

    _TAG_CN = {"aoe": "群体", "heal": "治疗", "buff": "增益", "single": "单体", "passive": "被动", "unknown": "未识别"}

    def _short_user_line(self, obs, plan) -> str:
        """玩家极简日志：只显示「W2 敌3 · 萝里娜 → S3」。"""
        hero = obs.hero_name or "角色"
        n_min = len(getattr(obs, "minion_targets", ()) or ())
        n_bar = int(getattr(self, "_enemy_bar_count", 0) or 0)
        if obs.is_boss:
            enemy_tag = f"Boss+{n_min}" if n_min > 0 else "Boss"
        else:
            enemy_tag = f"敌{max(1, n_min, n_bar)}"
        ak = str(plan.get("action_key") or "")
        slot = slot_for_pos(plan.get("pos"))
        if plan.get("type") == "combat_sequence":
            act = "S1点小弟"
        elif "点亮烧魂" in ak:
            act = "点亮烧魂"
        elif "退出烧魂" in ak:
            act = "退出烧魂"
        elif "烧魂" in ak and slot:
            act = f"烧魂S{slot}"
        elif "治疗" in ak and slot:
            act = f"治疗S{slot}"
        elif "增益" in ak and slot:
            act = f"增益S{slot}"
        elif "AoE" in ak and slot:
            act = f"群体S{slot}"
        elif "转火" in ak:
            act = "S1转火Boss"
        elif slot:
            act = f"S{slot}"
        else:
            act = ak.replace("强攻-", "") or "等待"
        return f"W{obs.wave_index} {enemy_tag} · {hero} → {act}"

    def _explain(self, obs, plan) -> str:
        """把本帧决策翻译成纯中文一句话（与当前优先级一致）。"""
        try:
            hero = obs.hero_name or "角色"
            tags = load_skill_tags().get(hero) or {}
            parts = []
            for slot in (1, 2, 3):
                tag = get_slot_primary(tags, slot)
                if tag:
                    parts.append(f"S{slot}是{self._TAG_CN.get(tag, tag)}")
            skill_txt = "、".join(parts) if parts else "技能类型还没学会"
            n_enemy = max(
                len(getattr(obs, "minion_targets", ()) or ()), int(getattr(self, "_enemy_bar_count", 0) or 0)
            )
            enemy_txt = "只剩 Boss" if (obs.is_boss and n_enemy == 0) else f"敌方 {n_enemy} 个"
            ak = str(plan.get("action_key") or "")
            if "治疗" in ak:
                why = "有队友血量偏低，先治疗"
            elif "增益" in ak:
                why = "先上增益，之后输出更稳"
            elif "烧魂" in ak:
                why = "点亮烧魂，用强化技能打高伤"
            elif "AoE" in ak or "群" in str(plan.get("desc", "")):
                why = "敌人较多，用群体技能清场"
            elif "S3" in ak:
                why = "大招已就绪，按优先级直接放"
            elif "S2" in ak:
                why = "S2 就绪，优先于平A"
            elif "转火" in ak:
                why = "小兵打不死，转火 Boss"
            elif "小弟" in ak:
                why = "先清小兵"
            elif "S1" in ak or "兜底" in ak:
                why = "没有更合适的技能，先平A"
            else:
                why = "按当前优先级出招"
            return f"第{obs.wave_index}波 · {enemy_txt} · {hero}：{skill_txt} → {why}"
        except Exception as exc:  # noqa: BLE001
            return f"（决策解析失败：{exc}）"

    def _snapshot_line(self, obs, plan, lit_xs) -> str:
        """拼一行现场：波次/角色/血量/技能就绪/敌人/烧魂/分类/决策。"""
        ally = tuple(getattr(self, "_ally_hp_ratios", ()) or ())
        ally_txt = ("/".join(f"{float(x):.2f}" for x in ally)) if ally else "? "
        mins = tuple(getattr(obs, "minion_hp_ratios", ()) or ())
        min_txt = ("/".join(f"{float(x):.2f}" for x in mins)) if mins else ("Boss单挑" if obs.is_boss else "无")
        hero = obs.hero_name or "?"
        ctx = f"W{obs.wave_index} {hero} | 我[{ally_txt}] 敌[{min_txt}]"
        flags = f"S1=√ S2={'√' if getattr(obs, 's2_ready', False) else '×'} S3={'√' if obs.s3_ready else '×'} burn={'ON' if obs.burn_toggled_on else 'off'}"
        _cn = {"aoe": "群攻", "single": "单体", "heal": "治疗", "buff": "增益", "passive": "被动", "unknown": "未识别"}
        _learned = (load_skill_tags().get(hero) or {})
        tags = []
        for slot in (1, 2, 3):
            raw = _learned.get(str(slot)) or _learned.get(slot)
            if raw:
                tags.append(f"S{slot}:[{_cn.get(raw, raw)}]")
            else:
                tags.append(f"S{slot}:[未学]")
        tag_txt = " ".join(tags)
        lit = "/".join(f"{x:.3f}" for x in lit_xs) if lit_xs else "无"
        act = f"{plan.get('action_key') or plan.get('type')} @{plan.get('pos')} x{plan.get('clicks', 1)}"
        return f"{ctx} | {flags} | {tag_txt} | 亮图标[{lit}] → {act}"

    def _init_skill_observer(self) -> None:
        """技能效果观察器：区分 verified_heal / verified_buff / pending_nd 三档。"""
        self._cast_hero: str | None = None
        self._cast_slot: int = 0
        self._cast_time: float = 0.0
        self._cast_hp_snapshot: tuple = ()
        self._cast_ally_hp: tuple = ()
        self._aoe_slots: set = set()
        self.verified_heal: set = set()
        self._heal_slots = self.verified_heal
        self.verified_buff: set = set()
        self.pending_nd: set = set()
        self._non_damage_slots: dict = {}
        self._single_slots: set = set()
        self._non_damage_order: dict = {}
        self._cast_attempts: dict = {}

    def reset_battle(self) -> None:
        """进入新关卡或结算退出时重置战斗内状态。"""
        self.last_auto_cancel_time = 0.0

    # -------------------- 模板缩放与底层视觉检测 --------------------
    def _tmpl(self, name: str, w: int, h: int) -> np.ndarray:
        key = (name, w, h)
        cached = self._scaled_cache.get(key)
        if cached is not None:
            return cached
        raw, (bw, bh) = self._raw_templates[name]
        # 等比缩放：宽高用同一个系数，避免非 16:9 窗口把图标压扁/拉长导致匹配失败
        scale = min(w / bw, h / bh)
        tw = max(4, int(round(raw.shape[1] * scale)))
        th = max(4, int(round(raw.shape[0] * scale)))
        interp = cv2.INTER_AREA if tw < raw.shape[1] else cv2.INTER_LINEAR
        scaled = cv2.resize(raw, (tw, th), interpolation=interp)
        self._scaled_cache[key] = scaled
        return scaled

    def is_combat_auto_on(self, img: np.ndarray) -> bool:
        """检测战斗中是否开启了系统 AUTO（右下角自动锁定准星 [⊕] 模板判定）。"""
        h, w = img.shape[:2]
        tmpl = self._tmpl("crosshair", w, h)
        roi = cv2.cvtColor(
            img[int(h * 0.735) : int(h * 0.845), int(w * 0.925) : int(w * 0.996)],
            cv2.COLOR_BGR2GRAY,
        )
        if roi.shape[0] < tmpl.shape[0] or roi.shape[1] < tmpl.shape[1]:
            return False
        score = float(cv2.matchTemplate(roi, tmpl, cv2.TM_CCOEFF_NORMED).max())
        return score >= 0.72

    def _parse_wave(self, items: list[OcrItem], w: int, h: int) -> str | None:
        for it in items:
            cx, cy = it.center[0] / w, it.center[1] / h
            if cx <= 0.22 and cy <= 0.24:
                m = re.search(r"([1-3]/[1-3])", it.text)
                if m:
                    return m.group(1)
        return None


# 预计算 64x64 技能框几何掩码：区分【主动方形 S2】与【被动十字架形 S2】
_YY64, _XX64 = np.mgrid[0:64, 0:64]
_DC64 = np.minimum(
    np.minimum(np.hypot(_XX64, _YY64), np.hypot(63 - _XX64, _YY64)),
    np.minimum(np.hypot(_XX64, 63 - _YY64), np.hypot(63 - _XX64, 63 - _YY64)),
)
# 四个圆角对角缺口区域（避开最左侧 S1 金圈溢出与右下角灵魂火苗）
_PASSIVE_VOID_MASK = (_DC64 >= 5.0) & (_DC64 <= 14.5) & (_XX64 >= 7) & ~((_XX64 >= 44) & (_YY64 >= 44))
# 被动十字架顶部银色横框高光区
_PASSIVE_TOP_BAR_MASK = (_YY64 >= 1) & (_YY64 <= 4) & (_XX64 >= 20) & (_XX64 <= 44)


@dataclass
class BriegTurnObservation:
    wave_str: str | None
    wave_index: int
    is_boss: bool
    minion_targets: list[tuple[float, float]]
    has_active_s2: bool
    s2_ready: bool
    s3_ready: bool
    burn_toggled_on: bool
    burn_slot: int | None
    can_soulburn: bool
    souls: int | None
    skill_bar_ready: bool
    hero_name: str
    hero_sig: np.ndarray
    is_support_class: bool = False
    s2_slot_lit: bool = False
    # 与 minion_targets 同序的小弟血条比例（0.0~1.0），供决策层执行残血技能限制。
    minion_hp_ratios: tuple[float, ...] = ()


class BriegSimpleCombatController(CombatControllerBase):
    """通用/布里克强攻手动控制器（不绑定具体英雄名字，严格按底层 3 条规则精控）：

    1. 道中优先级：AoE > 主动S2 > S1；非 AoE 的大招 S3 默认扣住，不再按波次交 S3。
    2. Boss 带小弟时单击 S1 后点小弟；同一目标连续 2 次伤害没死换第二个，
       第二个再 1 次没死就直接双 S1 转火 Boss。残血小弟（≤1/3）只交 S1，AoE 例外。
       不点 Cancel（点技能不会烧魂），直接按正常出招点技能即可。
    3. 烧魂只打 Boss：仅当小弟清空（Boss 单挑）时才点亮 Burn! 释放烧魂技能；
       屏幕上没有 Burn! 按钮时（如大招后的额外回合）连点 2 次仍无 Cancel 会自动改为直接交技能。
       能否烧魂只看 Burn! 按钮，不按角色名拦截。
    4. 罪戾的安洁莉卡（奶妈）：Boss 回合开局优先交 S3 全队加伤害提速。
    5. 角色知识表：指挥官萝里娜没有主动 S2 → 永不点 S2 槽；
       另外「灵魂不足」/ 技能冷却中 的槽位一律不进烧魂候选，避免对着点不动的按钮空点。
    6. 无效槽位防呆：同一技能槽连点 3 次画面毫无变化 → 拉黑该槽，改走 Cancel 退出烧魂 / 平A / 交回主循环。
    """

    def reset_battle(self) -> None:
        super().reset_battle()
        # 跨帧战斗状态（上一波次、Boss 标记）
        self.current_wave: str | None = None
        self.wave_index: int = 1
        self.is_boss_wave: bool = False
        self.suppress_burn_until_turn_end: bool = False
        self.burn_suppress_sig: np.ndarray | None = None
        self.burn_suppress_time: float = 0.0
        # 「没按钮就交技能」防呆：记录点亮 Burn! 的尝试，连点后仍无 Cancel 说明按钮不存在
        self.burn_light_sig: np.ndarray | None = None
        self.burn_light_time: float = 0.0
        self.burn_light_attempts: int = 0
        self.passive_s2_heroes: set[str] = set()
        self.skill_blocked: dict[tuple[str, int], float] = {}  # (角色, 槽位) -> 解禁时间  # 试过点不动的角色（S2 是被动装饰）
        self._icon_y: float = SKILL_Y_LARGE  # 技能图标行 y（observe 时按窗口高度自适应）
        # 无效技能槽防呆：同一槽位连点多次画面无变化 → 记入 dead_slots，本回合不再点它
        self.dead_slots: set[int] = set()
        self.burn_cancel_attempted: bool = False
        self.last_action_key: str = ""
        self.last_action_sig: np.ndarray | None = None
        self.last_action_time: float = 0.0
        self.same_action_count: int = 0
        self._init_skill_observer()
        self.is_learning_skills: bool = False
        self._learned_heroes_this_battle: set = set()
        self.fallback_count: int = 0
        self.last_fallback_key: str = ""
        self.turn_guard_sig: np.ndarray | None = None
        self.turn_guard_time: float = 0.0
        # Boss 小弟集火状态：同一目标连续两次伤害仍未消失 → 换第二个；
        # 第二个再打一次仍未消失 → 直接转火 Boss（不再二次点小弟）。
        self._minion_attack_target: tuple[float, float] | None = None
        self._minion_attack_count: int = 0
        self._minion_attack_phase: int = 1
        self._minion_force_boss: bool = False

    @staticmethod
    def is_s2_active_skill(img: np.ndarray) -> bool:
        """通过 S2 图标外框几何特征区分「主动圆角方形」与「被动内凹十字架形」。

        主动方形在四角缺口区域充满边框/技能底图，而被动手十字架四角内凹留空且顶部有亮银横条。
        """
        h, w = img.shape[:2]
        box = img[int(h * 0.863) : int(h * 0.981), int(w * 0.8475) : int(w * 0.9165)]
        if box.size == 0:
            return False
        g = cv2.cvtColor(cv2.resize(box, (64, 64), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        void_v = float(g[_PASSIVE_VOID_MASK].mean())
        bar_v = float(g[_PASSIVE_TOP_BAR_MASK].mean())
        return (void_v / max(1.0, bar_v)) >= 0.58

    def _heal_slot_if_needed(self, obs: BriegTurnObservation, now: float = 0.0) -> int | None:
        """任一我方 < 50% 时：先查 verified_heal，再对辅助职业分级冷启动。"""
        ratios = [float(r) for r in (getattr(self, "_ally_hp_ratios", ()) or ()) if r is not None]
        if not ratios:
            return None
        min_hp = min(ratios)
        if min_hp >= 0.5:
            return None

        def _usable(slot: int) -> bool:
            if (obs.hero_name, slot) in getattr(self, "_passive_slots", set()):
                return False
            if slot in self.dead_slots:
                return False
            until = self.skill_blocked.get((obs.hero_name, slot))
            return until is None or now >= until

        s2_ok = (
            bool(getattr(obs, "s2_ready", False))
            and (getattr(self, "_two_slot_layout", False) or hero_has_active_s2(obs.hero_name))
            and obs.hero_name not in self.passive_s2_heroes
            and _usable(2)
        )
        ready = {3: bool(obs.s3_ready) and _usable(3), 2: s2_ok, 1: _usable(1)}

        for slot in (3, 2, 1):
            if ready[slot] and (obs.hero_name, slot) in getattr(self, "verified_heal", set()):
                return slot

        # 第二顺位：带 heal 副标签的复合技能（攻击附带治疗队友）
        for slot in (3, 2, 1):
            if ready[slot] and (obs.hero_name, slot) in getattr(self, "_sub_heal_slots", set()):
                return slot

        if not getattr(obs, "is_support_class", False):
            return None

        vetoed = getattr(self, "verified_buff", set()) | getattr(self, "_aoe_slots", set())
        low_count = sum(1 for r in ratios if r < 0.5)
        is_critical = (min_hp < 0.35) or (low_count >= 2)
        if is_critical or not obs.has_active_s2:
            cold_order = (3, 2)
        else:
            cold_order = (2, 3) if obs.is_boss else (2,)
        for slot in cold_order:
            if ready[slot] and (obs.hero_name, slot) not in vetoed:
                return slot
        return None

    def _non_damage_slot_for(self, obs) -> int | None:
        """该角色已学到的非伤害技能中，当前就绪、排序最靠前的那个槽位。"""
        order = getattr(self, "_non_damage_order", {})
        if not order:
            return None
        ready = {
            1: 1 not in self.dead_slots,
            2: bool(getattr(obs, "s2_ready", False)) and (getattr(self, "_two_slot_layout", False) or hero_has_active_s2(obs.hero_name))
               and obs.hero_name not in self.passive_s2_heroes and 2 not in self.dead_slots,
            3: bool(obs.s3_ready) and 3 not in self.dead_slots,
        }
        for _s in (1, 2, 3):
            if (obs.hero_name, _s) in getattr(self, "_passive_slots", set()):
                ready[_s] = False
        cand = [
            (-slot, slot)
            for (hero, slot), rank in order.items()
            if hero == obs.hero_name and slot in ready and ready[slot]
        ]
        if not cand:
            return None
        cand.sort()
        return int(cand[0][1])

    def _is_aoe(self, hero: str = "", slot: int | None = None) -> bool:
        """该英雄的该技能是否为群攻。

        第一批先留接口并恒返回 False；第二批接入「一次技能后 3 个以上小弟血条同时下降」
        的群攻识别后，这里再返回真实结果。参数保留 hero/slot 供后续按角色与槽位标记。
        """
        return bool(slot is not None and (hero, int(slot)) in getattr(self, "_aoe_slots", set()))

    def _minion_has_low_hp(self, obs: BriegTurnObservation) -> bool:
        """当前集火小弟（或场上小弟）是否处于血条 ≤ 1/3 的残血状态。"""
        if getattr(self, "_minion_force_boss", False):
            return False
        ratios = getattr(obs, "minion_hp_ratios", ()) or ()
        if self._minion_attack_phase == 2 and self._minion_attack_target is not None:
            for idx, pt in enumerate(obs.minion_targets):
                if idx < len(ratios) and self._nearest_minion(self._minion_attack_target, [pt]) is not None:
                    try:
                        return float(ratios[idx]) <= (1.0 / 3.0 + 1e-6)
                    except (TypeError, ValueError):
                        return False
        for hp in ratios:
            try:
                if float(hp) <= (1.0 / 3.0 + 1e-6):
                    return True
            except (TypeError, ValueError):
                continue
        return False

    def _ready_aoe_slot(self, obs: BriegTurnObservation, s2_available: bool) -> int | None:
        """返回当前就绪的最高优先级群体技能槽位；没有则返回 None。"""
        until_s3 = self.skill_blocked.get((obs.hero_name, 3))
        s3_blocked = until_s3 is not None and self.turn_guard_time < until_s3
        ready_by_slot = {
            1: 1 not in self.dead_slots,
            2: s2_available and 2 not in self.dead_slots,
            3: obs.s3_ready and 3 not in self.dead_slots and not s3_blocked,
        }
        for slot in (3, 2, 1):
            if ready_by_slot[slot] and self._is_aoe(obs.hero_name, slot):
                return slot
        return None

    @staticmethod
    def _nearest_minion(
        target: tuple[float, float], targets: list[tuple[float, float]]
    ) -> tuple[float, float] | None:
        """在小弟坐标列表里找与锁定目标最接近的一项（识别误差容差 0.06）。"""
        best: tuple[float, float] | None = None
        best_dist = 0.06
        for candidate in targets:
            try:
                dist = max(abs(float(candidate[0]) - float(target[0])), abs(float(candidate[1]) - float(target[1])))
            except (TypeError, ValueError, IndexError):
                continue
            if dist <= best_dist:
                best_dist = dist
                best = candidate
        return best

    def _next_minion_attack(
        self, obs: BriegTurnObservation
    ) -> tuple[tuple[float, float] | None, bool]:
        """选择本次 S1 的小弟目标，并推进「两刀换人、第二人一刀转 Boss」状态。

        返回 ``(目标坐标, 是否已转火 Boss)``。目标坐标为空且第二项为 True 时，
        表示双击 S1 让游戏自动索敌 Boss。小弟血条为空但 [A] 标记仍在时，
        该目标仍留在 ``obs.minion_targets`` 中，因此会继续打，不因空血动画提前换人。
        """
        targets = list(obs.minion_targets)
        if not targets:
            self._minion_attack_target = None
            self._minion_attack_count = 0
            self._minion_attack_phase = 1
            self._minion_force_boss = False
            return None, False

        if self._minion_force_boss:
            return None, True

        current: tuple[float, float] | None = None
        if self._minion_attack_target is not None:
            current = self._nearest_minion(self._minion_attack_target, targets)
        if current is None:
            if self._minion_attack_phase == 2:
                # 第二个小弟已被击杀 → 直接转火 Boss，不再回头打卡血的第一小弟。
                self._minion_force_boss = True
                return None, True
            # 上一个目标已消失（死亡/离场）→ 新目标从「第一个」重新计数。
            self._minion_attack_target = None
            self._minion_attack_count = 0
            self._minion_attack_phase = 1

        if self._minion_attack_target is None:
            self._minion_attack_target = targets[0]
            current = targets[0]

        if self._minion_attack_phase == 1 and self._minion_attack_count >= 2:
            # 第一目标连续两次伤害仍未消失，换列表中的第二个目标。
            second = next(
                (t for t in targets if self._nearest_minion(t, [self._minion_attack_target]) is None),
                None,
            )
            if second is None:
                self._minion_force_boss = True
                return None, True
            self._minion_attack_target = second
            current = second
            self._minion_attack_count = 0
            self._minion_attack_phase = 2
        elif self._minion_attack_phase == 2 and self._minion_attack_count >= 1:
            # 第二目标只给一刀；仍未消失就直接打 Boss。
            self._minion_force_boss = True
            return None, True

        self._minion_attack_target = current
        self._minion_attack_count += 1
        return current, False

    def _detect_boss_and_minions(
        self, img: np.ndarray, items: list[OcrItem]
    ) -> tuple[bool, list[tuple[float, float]], tuple[float, ...]]:
        """识别是否 Boss 波次（顶部 Lv. 大血条），并提取所有战场上带 [A] 血条的小弟可点击坐标。"""
        h, w = img.shape[:2]
        boss_ocr = any(
            "lv." in it.text.lower() and 0.42 <= it.center[0] / w <= 0.74 and it.center[1] / h <= 0.08
            for it in items
        )
        t_a = self._tmpl("mob_a", w, h)
        roi_boss = cv2.cvtColor(
            img[int(h * 0.04) : int(h * 0.17), int(w * 0.45) : int(w * 0.72)],
            cv2.COLOR_BGR2GRAY,
        )
        boss_tag = False
        if roi_boss.shape[0] >= t_a.shape[0] and roi_boss.shape[1] >= t_a.shape[1]:
            boss_tag = float(cv2.matchTemplate(roi_boss, t_a, cv2.TM_CCOEFF_NORMED).max()) >= 0.72
        boss_now = boss_ocr or boss_tag

        # Boss 血条固定在顶部 y<0.18；场上小弟小血条右端 [A] 均落在 y=[0.20, 0.78], x=[0.48, 0.99]
        roi_mobs = cv2.cvtColor(
            img[int(h * 0.20) : int(h * 0.78), int(w * 0.48) : int(w * 0.99)],
            cv2.COLOR_BGR2GRAY,
        )
        raw_pts: list[tuple[int, int]] = []
        if roi_mobs.shape[0] >= t_a.shape[0] and roi_mobs.shape[1] >= t_a.shape[1]:
            res = cv2.matchTemplate(roi_mobs, t_a, cv2.TM_CCOEFF_NORMED)
            ys, xs = np.where(res >= 0.70)
            min_dx = max(12, int(w * 0.015))
            min_dy = max(10, int(h * 0.016))
            for y, x in sorted(zip(ys, xs), key=lambda p: -float(res[p[0], p[1]])):
                if not any(abs(x - px) < min_dx and abs(y - py) < min_dy for py, px in raw_pts):
                    raw_pts.append((y, x))

        # 计算每个小弟血条填充比例，优先集火残血（同血量优先前排左侧）确保逐一击破
        ranked: list[tuple[int, float, float, tuple[float, float]]] = []
        for y, x in raw_pts:
            ax = 0.48 + (x + t_a.shape[1] * 0.5) / w
            ay = 0.20 + (y + t_a.shape[0] * 0.5) / h
            hx1 = max(0, int(w * (ax - 0.055)))
            hx2 = max(hx1 + 1, int(w * (ax - 0.008)))
            hy1 = max(0, int(h * (ay - 0.010)))
            hy2 = min(h, max(hy1 + 1, int(h * (ay + 0.006))))
            hp_crop = cv2.cvtColor(img[hy1:hy2, hx1:hx2], cv2.COLOR_BGR2HSV)
            # 敌方小弟血条为亮绿色(H=35..85)或残血橙红(H<=15/H>=168)
            hp_alive = (
                ((hp_crop[:, :, 0] >= 35) & (hp_crop[:, :, 0] <= 88))
                | (hp_crop[:, :, 0] <= 15)
                | (hp_crop[:, :, 0] >= 168)
            ) & (hp_crop[:, :, 1] >= 75) & (hp_crop[:, :, 2] >= 75)
            hp_pct = float(hp_alive.mean()) if hp_alive.size > 0 else 1.0
            hp_bucket = int(round(hp_pct * 5))  # 0~5 档残血优先
            tx = float(round(min(0.96, max(0.46, ax - 0.032)), 3))
            ty = float(round(min(0.76, max(0.28, ay + 0.115)), 3))
            ranked.append((hp_bucket, ax, hp_pct, (tx, ty)))

        ranked.sort(key=lambda item: (item[0], item[1]))
        targets = [pt for _, _, _, pt in ranked]
        hp_ratios = tuple(round(max(0.0, min(1.0, hp)), 4) for _, _, hp, _ in ranked)
        return boss_now, targets, hp_ratios

    def observe_brieg(self, img: np.ndarray, items: list[OcrItem]) -> BriegTurnObservation | None:
        h, w = img.shape[:2]
        wave_str = self._parse_wave(items, w, h)
        if wave_str and wave_str != self.current_wave:
            prev_num = int(self.current_wave[0]) if self.current_wave else 0
            new_num = int(wave_str[0])
            if new_num < prev_num:
                self.reset_battle()
            self.current_wave = wave_str
            self.wave_index = new_num
            self.is_boss_wave = False

        # 窗口高度 < 900 时技能条更靠下（见 SKILL_Y_SMALL 注释）
        self._icon_y = SKILL_Y_SMALL if img.shape[0] < 900 else SKILL_Y_LARGE

        # 若画面有迷宫跑图右下角 "Skill" 文字，绝不进入战斗技能控制
        if any(
            "skill" in it.text.strip().lower() and it.center[0] / w >= 0.78 and it.center[1] / h >= 0.80
            for it in items
        ):
            return None

        # 1. 是否点开了 Burn!（蓝色 Cancel / 模板）
        burn_toggled = any(
            ("cancel" in it.text.strip().lower() and 0.44 <= it.center[0] / w <= 0.65 and it.center[1] / h >= 0.84)
            or "灵魂燃烧效果" in it.text
            for it in items
        )
        if not burn_toggled:
            t_can = self._tmpl("cancel", w, h)
            roi_can = cv2.cvtColor(img[int(h * 0.86): int(h * 0.97), int(w * 0.45): int(w * 0.63)], cv2.COLOR_BGR2GRAY)
            if roi_can.shape[0] >= t_can.shape[0] and roi_can.shape[1] >= t_can.shape[1]:
                burn_toggled = float(cv2.matchTemplate(roi_can, t_can, cv2.TM_CCOEFF_NORMED).max()) >= 0.74

        # 2. 技能栏在场硬门控
        lit_xs = detect_lit_skill_xs(img)
        sliding_cd = any("回合" in it.text and it.center[0] / w > 0.966 and it.center[1] / h >= 0.86 for it in items)
        if (len(lit_xs) not in (2, 3) or sliding_cd) and not burn_toggled:
            return None

        skill_bar_ready = True
        if _LAST_SLOT_Y and 0.88 <= _LAST_SLOT_Y <= 0.96:
            self._icon_y = _LAST_SLOT_Y

        # 2.5 名字解析：全图 OCR -> 局部放大补读 -> S1 指纹 + 模糊对齐
        raw_hero_name = ""
        hero_box = None
        for it in items:
            cx, cy = it.center[0] / w, it.center[1] / h
            if 0.14 <= cx <= 0.42 and 0.855 <= cy <= 0.945:
                cand = _clean_ocr_hero_name(it.text)
                if cand:
                    raw_hero_name = cand
                    try:
                        hero_box = tuple(int(v) for v in it.box)
                    except Exception:  # noqa: BLE001
                        hero_box = None
                    break

        if not raw_hero_name and getattr(self, "ocr", None) is not None:
            nx0, nx1 = int(w * 0.16), int(w * 0.35)
            ny0, ny1 = int(h * 0.86), int(h * 0.93)
            name_crop = img[ny0:ny1, nx0:nx1]
            if name_crop.size > 0:
                name_up = cv2.resize(name_crop, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
                try:
                    for sit in self.ocr.read(name_up, min_score=0.32, min_brightness=35.0, include_dim=True):
                        cand = _clean_ocr_hero_name(sit.text)
                        if cand:
                            raw_hero_name = cand
                            bx1, by1, bx2, by2 = sit.box
                            hero_box = (nx0 + bx1 // 2, ny0 + by1 // 2, nx0 + bx2 // 2, ny0 + by2 // 2)
                            break
                except Exception:  # noqa: BLE001
                    pass

        s1_crop = crop_s1_icon(img, lit_xs=lit_xs, icon_y=self._icon_y)
        hero_name = resolve_hero_identity(raw_hero_name, s1_crop)

        _h_entry = load_skill_tags().get(hero_name)
        if isinstance(_h_entry, dict) and _h_entry.pop("_form_changed", False):
            self._learned_heroes_this_battle.discard(hero_name)

        # 辅助职业图标
        is_support = False
        tpl_cls = _class_template()
        if tpl_cls is not None and hero_box is not None:
            try:
                _l, _t, _r, _b = hero_box
                yc_box = (_t + _b) / 2
                x0 = max(0, _r + 2)
                x1 = min(w, _r + int(w * 0.13))
                y0 = max(0, int(yc_box - h * 0.040))
                y1 = min(h, int(yc_box + h * 0.040))
                if x1 - x0 > 10 and y1 - y0 > 10:
                    roi_cls = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
                    best = 0.0
                    for sc in (0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.25):
                        tw = max(6, int(tpl_cls.shape[1] * sc))
                        th = max(6, int(tpl_cls.shape[0] * sc))
                        if tw >= roi_cls.shape[1] or th >= roi_cls.shape[0]:
                            continue
                        t = cv2.resize(tpl_cls, (tw, th), interpolation=cv2.INTER_AREA)
                        best = max(best, float(cv2.matchTemplate(roi_cls, t, cv2.TM_CCOEFF_NORMED).max()))
                    is_support = best >= 0.70
            except Exception:  # noqa: BLE001
                is_support = False

        hero_no_s2 = (not hero_has_active_s2(hero_name)) or (hero_name in self.passive_s2_heroes)

        # 3. 识别 Boss 与小弟
        boss_now, minion_targets, minion_hp_ratios = self._detect_boss_and_minions(img, items)
        if boss_now:
            self.is_boss_wave = True

        # 4. 三槽就绪：冷却字 + 去白字亮度/饱和度 + 灰区局部放大 OCR
        s2_cd = None
        s3_cd = None if len(lit_xs) >= 3 or burn_toggled else 99
        for it in items:
            cx, cy = it.center[0] / w, it.center[1] / h
            if cy < 0.84 or "回合" not in it.text:
                continue
            m = re.search(r"(\d+)", it.text)
            cd_val = int(m.group(1)) if m else 1
            if 0.835 <= cx <= 0.916:
                s2_cd = cd_val
            elif 0.916 < cx <= 1.0:
                s3_cd = cd_val

        yc = self._icon_y
        iy0, iy1 = max(0, int(h * (yc - 0.035))), min(h, int(h * (yc + 0.035)))

        def _slot_metrics(scx):
            ix0, ix1 = max(0, int(w * (scx - 0.025))), min(w, int(w * (scx + 0.025)))
            crop = img[iy0:iy1, ix0:ix1]
            if crop.size == 0:
                return 0.0, 0.0, False
            chsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
            sc, vc = chsv[:, :, 1], chsv[:, :, 2]
            nw = ~((sc < 35) & (vc > 190))
            vv = vc[nw] if np.any(nw) else vc.ravel()
            sv = sc[nw] if np.any(nw) else sc.ravel()
            p80 = float(np.percentile(vv, 80)) if vv.size else 0.0
            ms = float(sv.mean()) if sv.size else 0.0
            hx0, hx1 = max(0, int(w * (scx - 0.035))), min(w, int(w * (scx + 0.035)))
            top = img[max(0, int(h * (yc - 0.062))): max(1, int(h * (yc - 0.036))), hx0:hx1]
            bot = img[min(h - 1, int(h * (yc + 0.036))): min(h, int(h * (yc + 0.062))), hx0:hx1]
            has_gold = False
            if top.size > 0 and bot.size > 0:
                th = cv2.cvtColor(np.vstack([top, bot]), cv2.COLOR_BGR2HSV)
                gr = float(((th[:, :, 0] >= 8) & (th[:, :, 0] <= 34) & (th[:, :, 1] >= 88) & (th[:, :, 2] >= 150)).mean())
                has_gold = gr >= 0.12
            return p80, ms, has_gold

        def _zoom_has_cd(scx):
            eng = getattr(self, "ocr", None)
            if eng is None:
                return False
            zx0, zx1 = max(0, int(w * (scx - 0.034))), min(w, int(w * (scx + 0.034)))
            zy0, zy1 = max(0, int(h * (yc - 0.045))), min(h, int(h * (yc + 0.045)))
            sub = img[zy0:zy1, zx0:zx1]
            if sub.size == 0:
                return False
            up = cv2.resize(sub, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
            try:
                got = eng.read(up, min_score=0.35, min_brightness=0.0, include_dim=True)
                return any("回合" in it.text or bool(re.search(r"[1-9]\s*回", it.text)) for it in got)
            except Exception:  # noqa: BLE001
                return False

        v1, _s1_sat, _g1 = _slot_metrics(_STD_SLOT_XS[0])
        v2, s2_sat, g2 = _slot_metrics(_STD_SLOT_XS[1])
        v3, s3_sat, g3 = _slot_metrics(_STD_SLOT_XS[2])

        _learned_s2 = get_slot_primary(load_skill_tags().get(hero_name) or {}, 2)
        if _learned_s2 == "passive":
            has_active_s2 = False
        elif _learned_s2 in ("aoe", "heal", "buff", "single"):
            has_active_s2 = not hero_no_s2
        else:
            has_active_s2 = (not hero_no_s2) and self.is_s2_active_skill(img)

        if has_active_s2 and s2_cd is None and (85.0 <= v2 < 125.0) and not g2:
            if _zoom_has_cd(_STD_SLOT_XS[1]):
                s2_cd = 1
        # 硬校验：本帧必须真的检出第 3 槽（2 槽布局时 0.955 是空的地面）
        slot3_exists = len(lit_xs) >= 3 and any(abs(x - _STD_SLOT_XS[2]) <= 0.025 for x in lit_xs)
        if not slot3_exists and not burn_toggled:
            s3_cd = 99
        elif s3_cd is None and (85.0 <= v3 < 125.0) and not g3:
            if _zoom_has_cd(_STD_SLOT_XS[2]):
                s3_cd = 1

        s2_ready = has_active_s2 and (s2_cd is None) and (g2 or (v2 >= 115.0 and s2_sat >= 28.0))
        s3_ready = slot3_exists and (s3_cd is None) and (g3 or (v3 >= 110.0 and s3_sat >= 25.0))

        # 烧魂槽位必须真实可点：S1 恒有；S2 需主动且不在冷却；S3 需不在冷却
        burn_candidates = [(1, v1)]
        if has_active_s2 and s2_cd is None:
            burn_candidates.append((2, v2))
        if s3_cd is None:
            burn_candidates.append((3, v3))
        usable = [kv for kv in burn_candidates if kv[1] >= 90.0]
        burn_slot = max(usable, key=lambda kv: kv[1])[0] if (burn_toggled and usable) else None

        # 5. 检测 Burn! / Tap to burn 是否亮起（灵魂点数不再计算：灵魂不足只是神兽提示）
        souls: int | None = None

        flames_roi = cv2.cvtColor(
            img[int(h * 0.850) : int(h * 0.955), int(w * 0.375) : int(w * 0.480)],
            cv2.COLOR_BGR2HSV,
        )
        flame_lit = float(
            ((flames_roi[:, :, 0] >= 88) & (flames_roi[:, :, 0] <= 124) & (flames_roi[:, :, 1] >= 115) & (flames_roi[:, :, 2] >= 170)).mean()
        ) >= 0.012

        burn_ocr = any(
            it.text.strip().lower() in ("burn!", "tap to burn", "taptoburn")
            and 0.44 <= it.center[0] / w <= 0.65
            and it.center[1] / h >= 0.82
            for it in items
        )
        banner_hsv = cv2.cvtColor(
            img[int(h * 0.855) : int(h * 0.955), int(w * 0.495) : int(w * 0.610)],
            cv2.COLOR_BGR2HSV,
        )
        banner_soft_cyan = float(
            ((banner_hsv[:, :, 0] >= 82) & (banner_hsv[:, :, 0] <= 150) & (banner_hsv[:, :, 1] >= 75) & (banner_hsv[:, :, 2] >= 42)).mean()
        )
        # 能否烧魂只看「Burn! 按钮是否在闪」；灵魂点数不是判据
        # 能否烧魂只看 Burn! 按钮是否出现/闪烁，不再用角色知识表拦截。
        can_soulburn = burn_ocr or banner_soft_cyan >= 0.25

        # 头像/血条指纹（区分是否仍在同一回合内）
        sig_crop = cv2.resize(
            cv2.cvtColor(img[int(h * 0.86) : int(h * 0.97), int(w * 0.20) : int(w * 0.36)], cv2.COLOR_BGR2GRAY),
            (32, 16),
            interpolation=cv2.INTER_AREA,
        )

        return BriegTurnObservation(
            wave_str=self.current_wave,
            wave_index=self.wave_index,
            is_boss=self.is_boss_wave,
            minion_targets=minion_targets,
            minion_hp_ratios=minion_hp_ratios,
            has_active_s2=has_active_s2,
            s2_ready=s2_ready,
            s3_ready=s3_ready,
            burn_toggled_on=burn_toggled,
            is_support_class=is_support,
            s2_slot_lit=(v2 >= 120.0),
            burn_slot=burn_slot,
            can_soulburn=can_soulburn,
            souls=souls,
            skill_bar_ready=skill_bar_ready,
            hero_name=hero_name,
            hero_sig=sig_crop,
        )

    # ---------- 回合切换 / 无效技能槽防呆 ----------
    def bind_runtime(self, win, ocr) -> None:
        """注入 GameWindow 与 Ocr，供长按学习技能弹窗用。"""
        self.win = win
        self.ocr = ocr

    def _sync_hero_skill_tags(self, hero: str, tags: dict | None = None) -> None:
        """把 primary 与副标签同步到运行期集合。"""
        if not hero or hero == "我方英雄":
            return
        all_tags = tags if tags is not None else load_skill_tags()
        hero_tags = all_tags.get(hero) or {}
        self._passive_slots = getattr(self, "_passive_slots", set())
        self._sub_heal_slots = getattr(self, "_sub_heal_slots", set())
        self._burn_aoe_slots = getattr(self, "_burn_aoe_slots", set())
        self._non_damage_order = getattr(self, "_non_damage_order", {})

        for slot in (1, 2, 3):
            key = (hero, slot)
            self._aoe_slots.discard(key)
            self.verified_heal.discard(key)
            self.verified_buff.discard(key)
            self._single_slots.discard(key)
            self._passive_slots.discard(key)
            self._sub_heal_slots.discard(key)
            self._burn_aoe_slots.discard(key)
            self._non_damage_order.pop(key, None)
            primary = get_slot_primary(hero_tags, slot)
            detail = get_slot_detail(hero_tags, slot)
            sub = detail.get("tags") or {}
            if primary == "aoe":
                self._aoe_slots.add(key)
            elif primary == "heal":
                self.verified_heal.add(key)
            elif primary == "buff":
                self.verified_buff.add(key)
                self._non_damage_order[key] = slot
            elif primary == "single":
                self._single_slots.add(key)
            elif primary == "passive":
                self._passive_slots.add(key)
            if primary != "heal" and float(sub.get("heal", 0.0)) >= 0.75:
                self._sub_heal_slots.add(key)
            if float(sub.get("burn_aoe", 0.0)) >= 0.80:
                self._burn_aoe_slots.add(key)

    def _save_unknown_sample(self, hero: str, slot: int, main_txt: str, burn_txt: str, ev: str) -> None:
        """把判不出来的弹窗原文追加到 debug\\待补样本.txt，方便后续补关键词。"""
        try:
            from datetime import datetime as _dt

            from core import runtime_root

            d = runtime_root() / "debug"
            d.mkdir(parents=True, exist_ok=True)
            f = d / "待补样本.txt"
            with f.open("a", encoding="utf-8") as fp:
                fp.write(
                    f"[{_dt.now():%Y-%m-%d %H:%M:%S}] {hero} S{slot} | ev={ev} | "
                    f"main={main_txt[:120]} | burn={burn_txt[:60]}\n"
                )
        except Exception:  # noqa: BLE001
            pass

    def _learn_ready(self, obs, lit_xs) -> bool:
        """技能栏就绪 + 名字有效 + 连续两帧同英雄，才允许长按学习。"""
        try:
            hero = (obs.hero_name or "").strip()
            if not hero or hero == "我方英雄" or not getattr(obs, "skill_bar_ready", False):
                return False
            sig = tuple(round(float(x), 2) for x in lit_xs)
            prev = getattr(self, "_learn_prev", None)
            self._learn_prev = (sig, hero)
            return prev is not None and prev[1] == hero and (len(sig) in (2, 3) or prev[0] == sig)
        except Exception:  # noqa: BLE001
            return False

    def _missing_tags(self, obs) -> list:
        hero = (obs.hero_name or "").strip()
        if not hero or hero in ("我傘英雄", "我方英雄"):
            return []
        hero_tags = load_skill_tags().get(hero) or {}
        return [s for s in (1, 2, 3) if get_slot_primary(hero_tags, s) in (None, "", "unknown")]

    def _maybe_learn_skills(self, obs, lit_xs, now: float = 0.0) -> str:
        """逐槽长按学习。返回 'learned' / 'wait' / 'degrade'。"""
        if now <= 0.0:
            now = time.time()
        hero = (obs.hero_name or "").strip()
        if not hero or hero == "我方英雄" or obs.burn_toggled_on or not getattr(obs, "skill_bar_ready", False):
            return "degrade"

        retry = getattr(self, "_learn_retry_after", None)
        if retry is None:
            self._learn_retry_after = {}
            retry = self._learn_retry_after
        if now < float(retry.get(hero, 0.0)):
            return "degrade"

        tags = load_skill_tags()
        hero_tags = tags.setdefault(hero, {})
        missing = [s for s in (1, 2, 3) if get_slot_primary(hero_tags, s) in (None, "", "unknown")]
        if not missing:
            self._learned_heroes_this_battle.add(hero)
            self._sync_hero_skill_tags(hero, tags)
            return "degrade"

        if getattr(obs, "wave_index", 1) >= 2:
            return "degrade"  # 第 2 波起不再学习，保证输出节奏

        win = getattr(self, "win", None)
        ocr = getattr(self, "ocr", None)
        if win is None or ocr is None:
            return "degrade"

        wait_hero, wait_t0 = getattr(self, "_learn_wait_state", ("", 0.0))
        if wait_hero != hero or (now - wait_t0) > 8.0:
            wait_t0 = now
            self._learn_wait_state = (hero, wait_t0)

        if not self._learn_ready(obs, lit_xs):
            if (now - wait_t0) < 1.2:
                return "wait"
            retry[hero] = now + 3.5
            self._devlog(f"[技能学习] {hero} 画面未稳定超 1.2s → 本回合先出招，下回合再学")
            return "degrade"

        self.is_learning_skills = True
        t0 = time.time()
        any_ok = False
        try:
            icon_y = getattr(self, "_icon_y", SKILL_POS[1][1])

            def _read_popup(slot: int, hold: float) -> tuple:
                # 先点一下左下空白，确保上一个弹窗已关闭
                try:
                    win.click_ratio(0.28, 0.92, clicks=1, quick=True)
                    time.sleep(0.12)
                except Exception:  # noqa: BLE001
                    pass
                win.press_start_ratio(SKILL_POS[slot][0], icon_y, jitter=2)
                time.sleep(hold)
                img_pop = win.capture()
                win.press_end()
                time.sleep(0.18)
                t_main, t_burn = extract_skill_popup_texts(img_pop, ocr, slot=slot)
                return t_main, t_burn

            def _looks_like_popup(t_main: str, t_burn: str) -> bool:
                blob = f"{t_main}{t_burn}"
                if len(blob) < 8:
                    return False
                if any(bad in blob for bad in ("Hits!", "召唤了", "玩家", "灵魂不足")):
                    return False
                if any(k in blob for k in ("获得灵魂", "冷却时间", "强化技能", "灵魂燃烧", "获得专注力")):
                    return True
                return len(t_main) >= 10 and any(
                    k in t_main
                    for k in ("回合", "战斗开始", "攻击", "生命值", "速攻值", "效果", "提升", "恢复", "我军", "敌人", "死亡时")
                )

            for slot in missing:
                if time.time() - t0 > 4.0:
                    self._devlog(f"[技能学习] {hero} 超 4s → 剩余槽位下回合继续")
                    break

                main_txt, burn_txt = _read_popup(slot, 0.55)
                if not _looks_like_popup(main_txt, burn_txt):
                    # 弹窗没出来：加长按住时间重试一次
                    main_txt, burn_txt = _read_popup(slot, 0.85)
                if not _looks_like_popup(main_txt, burn_txt):
                    self._devlog(f"[技能学习] {hero} S{slot} 弹窗未出现，跳过（原文: {main_txt[:30]}）")
                    time.sleep(0.15)
                    continue

                info = classify_skill_popup(main_txt, burn_txt)
                if info["primary"] != "unknown":
                    any_ok = True
                else:
                    self._save_unknown_sample(hero, slot, main_txt, burn_txt, info.get("ev", ""))
                set_slot_skill_info(hero_tags, slot, info)
                save_skill_tags(tags)
                self._devlog(
                    f"[技能学习] {hero} S{slot} -> {info['primary']} tags={info['tags']} "
                    f"| 证据: {info['ev']} | 原文({len(main_txt)}字): {main_txt[:45]}"
                )
                time.sleep(0.22)

            self._sync_hero_skill_tags(hero, tags)
            left = [s for s in (1, 2, 3) if get_slot_primary(hero_tags, s) in (None, "", "unknown")]
            # 不论是否学全，本场不再重复学习（防死循环拖慢节奏）
            self._learned_heroes_this_battle.add(hero)
            if not left:
                return "learned"
            return "learned" if any_ok else "degrade"
        except Exception as exc:  # noqa: BLE001
            self._devlog(f"[技能学习] 异常降级：{exc}")
            try:
                win.press_end()
            except Exception:  # noqa: BLE001
                pass
            retry[hero] = time.time() + 4.0
            return "degrade"
        finally:
            self.is_learning_skills = False

    def _refresh_turn_guard(self, obs: BriegTurnObservation, now: float) -> None:
        """换人或超过 6 秒才算新回合：清空「本回合点不动」的技能槽记忆。"""
        if self.turn_guard_sig is None:
            self.turn_guard_sig = obs.hero_sig.copy()
            self.turn_guard_time = now
            return
        diff = float(np.abs(obs.hero_sig.astype(np.int16) - self.turn_guard_sig.astype(np.int16)).mean())
        if (now - self.turn_guard_time) > 15.0 or (
            obs.wave_str is not None
            and obs.wave_str != getattr(self, "_last_guard_wave", obs.wave_str)
            and getattr(obs, "wave_index", 1) == 1
        ):
            self.passive_s2_heroes.clear()
            self.skill_blocked.clear()
        self._last_guard_wave = getattr(obs, "wave_str", None)
        if diff >= 9.0 or (now - self.turn_guard_time) > 6.0:
            self.dead_slots.clear()
            self.burn_cancel_attempted = False
            self.same_action_count = 0
            self.fallback_count = 0
            self.last_fallback_key = ""
            self.last_action_key = ""
            self.last_action_sig = None
            self.turn_guard_sig = obs.hero_sig.copy()
        self.turn_guard_time = now

    def _fallback_plan(self, obs: BriegTurnObservation, now: float, reason: str) -> dict:
        """技能槽确定点不动时的兜底：先退出烧魂高亮，再退回平A，最后交回主循环判定。"""
        plan = self._build_fallback(obs, now, reason)
        key = str(plan.get("action_key", plan.get("type", "")))
        self.fallback_count = self.fallback_count + 1 if key == self.last_fallback_key else 1
        self.last_fallback_key = key
        if self.fallback_count > 3:
            return {
                "type": "combat_wait",
                "desc": f"⏳ {obs.hero_name} · {reason} → 等主循环",
            }
        return plan

    def _build_fallback(self, obs: BriegTurnObservation, now: float, reason: str) -> dict:
        if obs.burn_toggled_on and not self.burn_cancel_attempted:
            self.burn_cancel_attempted = True
            self.suppress_burn_until_turn_end = True
            self.burn_suppress_sig = obs.hero_sig
            self.burn_suppress_time = now
            self.burn_light_attempts = 0
            self.burn_light_sig = None
            return {
                "type": "combat_click",
                "action_key": "强攻-退出烧魂",
                "pos": BURN_BTN_POS,
                "clicks": 1,
                "fast_followup": True,
                "desc": f"↩ {obs.hero_name} · {reason} → 退出烧魂",
            }
        if 1 not in self.dead_slots:
            if obs.minion_targets:
                target = obs.minion_targets[0]
                return {
                    "type": "combat_sequence",
                    "action_key": "强攻-兜底点杀小弟",
                    "steps": [((SKILL_POS[1][0], self._icon_y), 1), (target, 1)],
                    "step_gap": 0.13,
                    "desc": f"🛟 {obs.hero_name} · {reason} → S1",
                }
            return {
                "type": "combat_click",
                "action_key": "强攻-兜底S1",
                "pos": (SKILL_POS[1][0], self._icon_y),
                "clicks": 2,
                "fast_followup": False,
                "desc": f"🛟 {obs.hero_name} · {reason} → S1",
            }
        return {
            "type": "combat_wait",
            "desc": f"⏳ {obs.hero_name} · {reason} → 交回主循环",
        }

    def _apply_skill_block(self, plan: dict, obs: BriegTurnObservation, now: float) -> dict:
        """该角色的这个技能刚被判定「放不出」（多半冷却中）→ 本次改平A，别空点。"""
        if not plan or plan.get("type") != "combat_click":
            return plan
        slot = slot_for_pos(plan.get("pos"))
        if slot is None or slot == 1:
            return plan
        until = self.skill_blocked.get((obs.hero_name, slot))
        if until is None or now >= until:
            return plan
        return {
            "type": "combat_click",
            "action_key": f"强攻-S{slot}冷却改平A",
            "pos": (SKILL_POS[1][0], self._icon_y),
            "clicks": 2,
            "fast_followup": False,
            "desc": f"⚔ {obs.hero_name} · S{slot} 冷却 → S1",
        }

    def _guard_dead_slot(self, plan: dict, obs: BriegTurnObservation, now: float) -> dict:
        """同一技能槽连点多次画面毫无变化 → 才判该槽点不动并改走兜底（默认 12 次，宁可多重复）。"""
        if not plan or plan.get("type") != "combat_click":
            return plan
        slot = slot_for_pos(plan.get("pos"))
        if slot is None:
            return plan
        diff = 999.0
        if self.last_action_sig is not None:
            diff = float(np.abs(obs.hero_sig.astype(np.int16) - self.last_action_sig.astype(np.int16)).mean())
        # 血量按 10% 分档，避免呼吸/粒子导致的 0.001 级抖动重置连点计数
        hp_snapshot = (
            tuple(int(round(float(r) * 10)) for r in (getattr(obs, "minion_hp_ratios", ()) or ())),
            len(getattr(obs, "minion_targets", ()) or ()),
        )
        hp_unchanged = (slot in (2, 3)) or (hp_snapshot == getattr(self, "_last_hp_snapshot", None))
        s2_still_lit = (slot != 2) or bool(
            getattr(obs, "s2_slot_lit", False) or getattr(obs, "s2_ready", False)
        )
        same_action = (
            plan.get("action_key") == self.last_action_key
            and diff < 9.0
            and hp_unchanged
            and s2_still_lit
            and (now - self.last_action_time) <= 6.0
        )
        self.same_action_count = self.same_action_count + 1 if same_action else 1
        self.last_action_key = str(plan.get("action_key", ""))
        self.last_action_sig = obs.hero_sig.copy()
        self._last_hp_snapshot = hp_snapshot
        self.last_action_time = now
        if slot in self.dead_slots:
            return self._fallback_plan(obs, now, f"S{slot} 本回合已判定点不动")
        if self.same_action_count >= (3 if slot in (2, 3) else 12):
            self.dead_slots.add(slot)
            if slot == 2 and s2_still_lit:
                self.passive_s2_heroes.add(obs.hero_name)
            # 记住这个角色的这个技能暂时放不出（多半是冷却中），20 秒内不再尝试
            self.skill_blocked[(obs.hero_name, slot)] = now + 20.0
            return self._fallback_plan(obs, now, f"S{slot} 连点 {self.same_action_count} 次画面无变化")
        self.fallback_count = 0
        self.last_fallback_key = ""
        return plan

    def _click_skill(
        self,
        slot: int,
        action_key: str,
        desc: str,
        *,
        clicks: int = 2,
        fast_followup: bool = False,
    ) -> dict:
        return {
            "type": "combat_click",
            "action_key": action_key,
            "pos": (SKILL_POS[slot][0], self._icon_y),
            "clicks": clicks,
            "fast_followup": fast_followup,
            "desc": desc,
        }

    def _many_high_one_low(self, obs) -> bool:
        """全局例外：只有 1 个残血、且 >50% 血的敌人 >= 2 → 按正常优先级出招。"""
        ratios = [float(r) for r in (getattr(obs, "minion_hp_ratios", ()) or ()) if r is not None]
        low_n = sum(1 for r in ratios if r <= (1.0 / 3.0 + 1e-6))
        high_n = sum(1 for r in ratios if r > 0.5)
        return low_n == 1 and high_n >= 2

    def _s3_usable(self, obs) -> bool:
        """S3 视觉就绪且未被判死/非被动即可释放（unknown 未学也按视觉就绪放）。"""
        if not obs.s3_ready or 3 in self.dead_slots:
            return False
        if (obs.hero_name, 3) in getattr(self, "_passive_slots", set()):
            return False
        until = self.skill_blocked.get((obs.hero_name, 3))
        return until is None or self.turn_guard_time >= until

    def _plan_non_boss(
        self,
        obs: BriegTurnObservation,
        s2_available: bool,
        trial_s2: bool,
        wave_tag: str,
    ) -> dict:
        """道中优先级：AoE > S2 > S1；非 AoE 的 S3 一律扣住。"""
        aoe_slot = self._ready_aoe_slot(obs, s2_available)
        # 大招是群攻时：小兵 >= 3 才交，否则扣住留着
        _enemy_n = max(len(getattr(obs, "minion_targets", ()) or ()), int(getattr(self, "_enemy_bar_count", 0) or 0))
        if aoe_slot == 3 and _enemy_n < 3:
            aoe_slot = None
        if aoe_slot is not None:
            return self._click_skill(
                aoe_slot,
                f"强攻-波次{obs.wave_index}-AoE-S{aoe_slot}",
                f"⚔ {obs.hero_name} · 波次{wave_tag} → 群体 S{aoe_slot}",
                fast_followup=(aoe_slot == 2),
            )
        if s2_available or trial_s2:
            return self._click_skill(
                2,
                f"强攻-波次{obs.wave_index}-S2",
                f"⚔ {obs.hero_name} · 波次{wave_tag} → S2",
            )
        # 道中不再扣住单体大招：S3 就绪就按优先级放（AoE 已在上面处理）
        if self._s3_usable(obs):
            return self._click_skill(
                3,
                f"强攻-波次{obs.wave_index}-S3",
                f"⚔ {obs.hero_name} · 波次{wave_tag} → S3",
            )
        return self._click_skill(
            1,
            f"强攻-波次{obs.wave_index}-S1",
            f"⚔ {obs.hero_name} · 波次{wave_tag} → S1",
        )

    def _plan_minion_s1(self, obs: BriegTurnObservation) -> dict:
        """单击 S1 后点小弟；两次没死换第二个，第二个一次没死则双 S1 打 Boss。"""
        target, force_boss = self._next_minion_attack(obs)
        if force_boss:
            return self._click_skill(
                1,
                "强攻-Boss战转火Boss",
                f"🎯 {obs.hero_name} · Boss+周围x{len(obs.minion_targets)} → 转火 Boss",
            )
        if target is None:
            # 理论上不会走到：调用方只在有 [A] 小弟目标时进入；保底回到双击 S1。
            return self._click_skill(
                1,
                "强攻-Boss战S1",
                f"⚔ {obs.hero_name} · Boss → S1",
            )
        return {
            "type": "combat_sequence",
            "action_key": "强攻-Boss战点杀小弟",
            "steps": [((SKILL_POS[1][0], self._icon_y), 1), (target, 1)],
            "step_gap": 0.13,
            "desc": f"🎯 {obs.hero_name} · Boss+周围x{len(obs.minion_targets)} → S1 点小弟",
        }

    def _plan_boss_minions(
        self,
        obs: BriegTurnObservation,
        s2_available: bool,
    ) -> dict:
        """Boss 仍带小弟时的技能与集火决策。"""
        aoe_slot = self._ready_aoe_slot(obs, s2_available)
        if aoe_slot is not None:
            return self._click_skill(
                aoe_slot,
                f"强攻-Boss残血AoE-S{aoe_slot}",
                f"💠 {obs.hero_name} · 群体 S{aoe_slot}",
                fast_followup=(aoe_slot == 2),
            )

        if self._s3_usable(obs):
            return self._click_skill(
                3,
                "强攻-小弟期S3",
                f"💥 {obs.hero_name} · Boss+小弟 → S3",
            )
        if s2_available:
            return self._click_skill(
                2,
                f"强攻-小弟期主动S2",
                f"🛡 {obs.hero_name} · Boss+小弟 → S2",
                fast_followup=True,
            )
        return self._plan_minion_s1(obs)

    def _plan_boss_solo(
        self,
        obs: BriegTurnObservation,
        now: float,
        s2_available: bool,
        *,
        allow_burn: bool = True,
    ) -> dict:
        """Boss 单挑：能烧魂先点 Burn!，否则 S2 → S3 → S1。"""
        if allow_burn and obs.can_soulburn and not self.suppress_burn_until_turn_end:
            same_hero = self.burn_light_sig is not None and self._sig_diff(obs, self.burn_light_sig) < 9.0
            self.burn_light_attempts = (
                self.burn_light_attempts + 1 if same_hero and (now - self.burn_light_time) < 2.5 else 1
            )
            self.burn_light_sig = obs.hero_sig
            self.burn_light_time = now
            return {
                "type": "combat_click",
                "action_key": "强攻-Boss点亮烧魂",
                "pos": BURN_BTN_POS,
                "clicks": 1,
                "fast_followup": True,
                "desc": f"🔥 {obs.hero_name} · Boss → Burn 烧魂",
            }
        if s2_available:
            return self._click_skill(
                2,
                "强攻-Boss主动S2",
                f"🛡 {obs.hero_name} · Boss → S2 套盾",
                fast_followup=True,
            )
        if self._s3_usable(obs):
            return self._click_skill(
                3,
                "强攻-Boss单挑S3",
                f"💥 {obs.hero_name} · Boss → S3",
            )
        return self._click_skill(
            1,
            "强攻-Boss战S1",
            f"⚔ {obs.hero_name} · Boss → S1",
        )

    def _plan_turn(self, obs: BriegTurnObservation, now: float) -> dict:
        """按规则给出本回合动作（不含无效槽位防呆）。"""
        primary_minion = obs.minion_targets[0] if obs.minion_targets else None
        _now = now

        if primary_minion is None:
            # 小弟清空后立刻释放集火状态，供下一波/下一战重新计数。
            self._minion_attack_target = None
            self._minion_attack_count = 0
            self._minion_attack_phase = 1
            self._minion_force_boss = False


        def _blocked(slot: int) -> bool:
            if (obs.hero_name, slot) in getattr(self, "_passive_slots", set()):
                return True
            until = self.skill_blocked.get((obs.hero_name, slot))
            if until is not None and _now < until:
                return True
            return False

        _s2_tag = get_slot_primary(load_skill_tags().get(obs.hero_name) or {}, 2)
        s2_learned_active = _s2_tag in ("aoe", "heal", "buff", "single")
        s2_available = (
            (obs.s2_ready or (s2_learned_active and getattr(obs, "s2_slot_lit", False)))
            and (s2_learned_active or getattr(self, "_two_slot_layout", False) or hero_has_active_s2(obs.hero_name))
            and obs.hero_name not in self.passive_s2_heroes
            and not _blocked(2)
        )
        # S2 几何判不准时，槽位亮着先试点；角色知识表仍禁止被动 S2 角色试点。
        trial_s2 = (
            (not obs.has_active_s2)
            and obs.s2_slot_lit
            and (getattr(self, "_two_slot_layout", False) or hero_has_active_s2(obs.hero_name))
            and (obs.hero_name not in self.passive_s2_heroes)
            and not _blocked(2)
        )
        wave_tag = obs.wave_str or f"{obs.wave_index}/?"

        # ---- 情况一：已经点开了 Burn!（显示蓝色 Cancel） ----
        if obs.burn_toggled_on:
            bslot = obs.burn_slot
            burn_usable = (
                bslot in SKILL_POS
                and bslot not in self.dead_slots
                and not _blocked(bslot)
                and (
                    bslot != 2
                    or (
                        obs.has_active_s2
                        and (getattr(self, "_two_slot_layout", False) or hero_has_active_s2(obs.hero_name))
                        and obs.hero_name not in self.passive_s2_heroes
                    )
                )
            )
            is_burn_aoe = burn_usable and (obs.hero_name, bslot) in getattr(self, "_burn_aoe_slots", set())
            _enemy_cnt = max(len(obs.minion_targets), int(getattr(self, "_enemy_bar_count", 0) or 0))
            if is_burn_aoe and (obs.is_boss or _enemy_cnt >= 2):
                self.suppress_burn_until_turn_end = False
                self.burn_light_attempts = 0
                self.burn_light_sig = None
                return self._click_skill(
                    int(bslot),
                    f"强攻-烧魂群攻S{bslot}",
                    f"🔥 {obs.hero_name} · 烧魂群攻 → S{bslot}",
                    fast_followup=(bslot == 2),
                )
            # 不烧魂场景：非 Boss / Boss 仍有小弟 / 当前没有真实可点的烧魂槽。
            # 不点 Cancel，直接走普通出招；点击技能本身不会触发烧魂。
            if (not obs.is_boss) or primary_minion is not None or not burn_usable:
                self.suppress_burn_until_turn_end = True
                self.burn_suppress_sig = obs.hero_sig
                self.burn_suppress_time = now
                self.burn_light_attempts = 0
                self.burn_light_sig = None
                if not obs.is_boss:
                    return self._plan_non_boss(obs, s2_available, trial_s2, wave_tag)
                if primary_minion is not None:
                    return self._plan_boss_minions(obs, s2_available)
                return self._plan_boss_solo(obs, now, s2_available, allow_burn=False)
            # Boss 单挑且烧魂槽真实可点 → 双击释放烧魂技能。
            self.suppress_burn_until_turn_end = False
            self.burn_light_attempts = 0
            self.burn_light_sig = None
            return self._click_skill(
                int(bslot),
                f"强攻-烧魂S{bslot}",
                f"🔥 {obs.hero_name} · 仅Boss → 烧魂 S{bslot}",
                fast_followup=(bslot == 2),
            )

        # ---- 情况二：尚未遇到 Boss（1/3、2/3 等道中波次） ----
        if not obs.is_boss:
            # 普通道中不盲目试点未知 S2（十字被动也可能亮槽）；只放几何确认过的主动 S2。
            # 已点开 Burn! 的分支仍保留一次试点兜底，避免历史行为丢功能。
            return self._plan_non_boss(obs, s2_available, False, wave_tag)

        # ---- 情况三：Boss 波次 ----
        if primary_minion is not None:
            return self._plan_boss_minions(obs, s2_available)
        return self._plan_boss_solo(obs, now, s2_available)

    @staticmethod
    def _sig_diff(obs: BriegTurnObservation, sig: np.ndarray | None) -> float:
        if sig is None:
            return 999.0
        return float(np.abs(obs.hero_sig.astype(np.int16) - sig.astype(np.int16)).mean())

    def decide_from_observation(self, obs: BriegTurnObservation, now: float) -> dict:
        """纯策略决策函数（同时供实机主循环与离线单元测试直接校验）。"""
        if not obs.skill_bar_ready:
            self.suppress_burn_until_turn_end = False
            self.burn_suppress_sig = None
            return {"type": "combat_wait", "desc": f"等待 {obs.hero_name} 技能栏就绪"}

        self._refresh_turn_guard(obs, now)

        # 若切到下一名英雄或超过 3.5 秒进入新回合，自动解除本回合的 S3 烧魂屏蔽
        if self.suppress_burn_until_turn_end:
            sig_diff = self._sig_diff(obs, self.burn_suppress_sig)
            if sig_diff >= 9.0 or (now - self.burn_suppress_time) > 3.5:
                self.suppress_burn_until_turn_end = False
                self.burn_suppress_sig = None

        # ---- 防呆：屏幕上根本没有 Burn! 按钮时（例如大招后的额外回合），连点两次仍无 Cancel 就交技能 ----
        sig_diff = self._sig_diff(obs, self.burn_light_sig)
        if (
            not obs.burn_toggled_on
            and self.burn_light_sig is not None
            and sig_diff < 9.0
            and (now - self.burn_light_time) < 2.5
        ):
            if self.burn_light_attempts >= 2:
                self.suppress_burn_until_turn_end = True
        elif sig_diff >= 9.0 or (now - self.burn_light_time) >= 2.5:
            self.burn_light_attempts = 0
            self.burn_light_sig = None

        heal_slot = self._heal_slot_if_needed(obs, now)
        if heal_slot is not None:
            _burn_tag = (load_skill_tags().get(obs.hero_name) or {}).get(str(obs.burn_slot or 0), "")
            _burn_ok = _burn_tag not in ("buff", "passive")
            if obs.burn_toggled_on and _burn_ok:
                # 已点亮 Burn!：无视常规烧魂限制，直接放治疗（支持烧魂治疗）
                self.suppress_burn_until_turn_end = False
                self.burn_light_attempts = 0
                plan = self._click_skill(
                    heal_slot,
                    f"强攻-烧魂治疗S{heal_slot}",
                    f"🔥💚 {obs.hero_name} · 队友残血 → 烧魂治疗 S{heal_slot}",
                    fast_followup=(heal_slot == 2),
                )
            elif obs.can_soulburn and not self.suppress_burn_until_turn_end:
                same_hero = False
                try:
                    if self.burn_light_sig is not None:
                        same_hero = float(
                            np.abs(obs.hero_sig.astype(np.int16) - self.burn_light_sig.astype(np.int16)).mean()
                        ) < 9.0
                except Exception:  # noqa: BLE001
                    same_hero = False
                self.burn_light_attempts = (
                    self.burn_light_attempts + 1 if same_hero and (now - self.burn_light_time) < 2.5 else 1
                )
                self.burn_light_sig = obs.hero_sig
                self.burn_light_time = now
                if self.burn_light_attempts >= 2:
                    # 两次点不出 Cancel（灵魂不足/额外回合）→ 本回合不再尝试烧魂
                    self.suppress_burn_until_turn_end = True
                    plan = self._click_skill(
                        heal_slot,
                        f"强攻-治疗S{heal_slot}",
                        f"💚 {obs.hero_name} · 队友残血 → 治疗 S{heal_slot}",
                        fast_followup=(heal_slot == 2),
                    )
                else:
                    plan = {
                        "type": "combat_click",
                        "action_key": "强攻-治疗点亮烧魂",
                        "pos": BURN_BTN_POS,
                        "clicks": 1,
                        "fast_followup": True,
                        "desc": f"🔥 {obs.hero_name} · 队友残血 → 先点 Burn! 准备治疗 S{heal_slot}",
                    }
            else:
                plan = self._click_skill(
                    heal_slot,
                    f"强攻-治疗S{heal_slot}",
                    f"💚 {obs.hero_name} · 队友残血 → 治疗 S{heal_slot}",
                    fast_followup=(heal_slot == 2),
                )
        else:
            nd_slot = self._non_damage_slot_for(obs)
            if nd_slot is not None:
                plan = self._click_skill(
                    nd_slot,
                    f"强攻-增益S{nd_slot}",
                    f"✨ {obs.hero_name} · 非伤害技能优先 → S{nd_slot}",
                    fast_followup=(nd_slot == 2),
                )
            else:
                plan = self._plan_turn(obs, now)
        plan = self._apply_skill_block(plan, obs, now) if plan else plan

        # 补丁 3/4 的局部坐标重映射暂停启用（会改变既有决策坐标，待单独调优）
        return self._guard_dead_slot(plan, obs, now)

    def decide(self, img: np.ndarray, items: list[OcrItem], now: float | None = None) -> dict | None:
        if now is None:
            now = time.time()

        # 1. 若战斗中系统 AUTO 开启（右下角有 [⊕] 准星），立即单击关闭
        if self.is_combat_auto_on(img):
            if now - self.last_auto_cancel_time < 1.2:
                return {"type": "combat_wait", "desc": "等待 AUTO 关闭生效"}
            self.last_auto_cancel_time = now
            return {
                "type": "combat_click",
                "action_key": "强攻-关闭AUTO",
                "pos": AUTO_BTN_POS,
                "clicks": 1,
                "fast_followup": True,
                "desc": "🎯 系统 AUTO 已开 → 自动关闭",
            }

        try:
            _ally, _enemy = detect_head_hp_bars(img)
            # 头顶血条识别尚不稳定（会混入 UI 元素），只用左下角精确数字血量触发治疗
            _ally = []
            for _it in items:
                _cx, _cy = _it.center[0] / w, _it.center[1] / h
                if 0.16 <= _cx <= 0.38 and 0.92 <= _cy <= 0.99 and "/" in _it.text:
                    _m = re.search(r"(\d{2,6})\s*/\s*(\d{2,6})", _it.text)
                    if _m:
                        _cur, _max = int(_m.group(1)), int(_m.group(2))
                        if _max > 0:
                            _r = round(min(1.0, max(0.01, _cur / _max)), 3)
                            if not any(abs(_r - a) <= 0.06 for a in _ally):
                                _ally.append(_r)
                        break
            self._ally_hp_ratios = tuple(_ally)
            self._enemy_bar_count = len(_enemy)
        except Exception:
            pass
        lit_xs = detect_lit_skill_xs(img)
        if getattr(self, "_cast_hero", None) and not lit_xs:
            self._bar_hidden_seen = True  # 技能栏消失 = 动画在播，之后才允许归类
        self._frame_slot_xs = map_skill_slots_by_x(lit_xs) if len(lit_xs) in (2, 3) else None
        icon_y = getattr(self, "_icon_y", SKILL_POS[1][1])
        _det_y = globals().get("_LAST_SLOT_Y", 0.0)
        if _det_y and 0.70 < _det_y < 0.99:
            icon_y = _det_y
            self._icon_y = _det_y

        obs = self.observe_brieg(img, items)
        if obs is None:
            self.suppress_burn_until_turn_end = False
            self.burn_suppress_sig = None
            self._frame_slot_xs = None
            self._last_hero_name = ""
            # 技能栏不在场 → 敌方回合/动画，清空名字并返回
            return None

        # 只有「什么都没判出就绪」时才按 2 槽布局修正，避免噪点误判
        self._two_slot_layout = False

        # ② 名字兜底：本帧读不到就沿用上一帧的有效名字（不要退回"我方英雄"）
        try:
            _cur_s1 = compute_s1_dhash(crop_s1_icon(img, lit_xs=lit_xs, icon_y=icon_y))
            _hn = (obs.hero_name or "").strip()
            if _hn and _hn != "我方英雄":
                self._last_hero_name = _hn
                self._last_s1_hash = _cur_s1
            elif (
                getattr(self, "_last_hero_name", "")
                and _cur_s1
                and getattr(self, "_last_s1_hash", "")
                and dhash_distance(_cur_s1, self._last_s1_hash) <= 6
            ):
                obs.hero_name = self._last_hero_name
            else:
                self._last_hero_name = ""
                self._last_s1_hash = _cur_s1
        except Exception:  # noqa: BLE001
            pass
        self._sync_hero_skill_tags(obs.hero_name)
        _missing = self._missing_tags(obs)
        if _missing and not obs.burn_toggled_on and getattr(self, "win", None) is not None:
            _state = self._maybe_learn_skills(obs, lit_xs, now=now)
            if _state == "learned":
                self._frame_slot_xs = None
                return {"type": "combat_wait", "desc": f"📖 {obs.hero_name} · 学习完成，准备出招"}
            if _state == "wait":
                self._frame_slot_xs = None
                return {"type": "combat_wait", "desc": f"⏳ {obs.hero_name} · 等画面稳定后学习"}
            # degrade：学不到就先打，不卡死

        slot_xs = self._frame_slot_xs
        try:
            plan = self.decide_from_observation(obs, now)
        finally:
            self._frame_slot_xs = None

        # ① 用本帧检测到的图标 x 重映射点击位置（2 槽/3 槽布局都可能偏移）
        try:
            if plan and slot_xs:
                _slot = slot_for_pos(plan.get("pos")) if plan.get("type") == "combat_click" else None
                if _slot == 3 and 3 not in slot_xs:
                    plan = self._click_skill(1, "强攻-空槽降级S1", f"⚔ {obs.hero_name} → S1")
                plan = _apply_local_skill_xs(plan, slot_xs, icon_y)
        except Exception:  # noqa: BLE001
            pass

        try:
            if plan:
                short_line = self._short_user_line(obs, plan)
                if plan.get("type") in ("combat_click", "combat_sequence"):
                    plan = dict(plan)
                    plan["desc"] = short_line
                self._devlog(f"{self._snapshot_line(obs, plan, lit_xs)} | 原因: {self._explain(obs, plan)}")
                self._userlog(short_line)
        except Exception:  # noqa: BLE001
            pass

        _now2 = now
        if (
            plan.get("type") == "combat_wait"
            and lit_xs
            and getattr(obs, "hero_name", None)
            and (_now2 - float(getattr(self, "_last_fallback_time", 0.0))) >= 2.0
        ):
            self._last_fallback_time = _now2
            return {
                "type": "combat_click",
                "action_key": "强攻-兜底最右亮图标",
                "pos": (SKILL_POS[1][0], icon_y),
                "clicks": 2,
                "fast_followup": False,
                "desc": f"🛟 {obs.hero_name} · 未判出就绪 → 双击 S1 安全平A",
            }
        return plan


# ==================== A. 弹窗文本提取（锚点列定位 + 锚点校验 + 整图回退） ====================
_RE_PURE_NUM_NOISE = re.compile(
    r"^(?:Lv\.?|Max|MAX|TAG|\d+|\+\d+|-\d+|\d+/\d+|\d+%|\d+\.\d+%?|[\s\+\-%/\.,:：☆⭐★\(\)（）\?？<>])+$",
    re.IGNORECASE,
)
_RE_ENHANCE_ROW = re.compile(
    r"(?:^[+\-±]\s*[1-7]\b|伤害量提升\s*\d|效果发生率提升\s*\d|恢复量[^\w]{0,4}提升\s*\d|"
    r"速攻值提升(?:量提升)?\s*\d|冷却时间减少\s*\d|复活时生命值提升\s*\d|攻击力提升\s*\d+(?:\.\d+)?%)"
)
_UI_NOISE_WORDS = ("强化技能", "強化技能", "升级", "刻印记忆", "觉醒", "传送英雄", "额外效果", "搜索")


def _strip_debug_red_boxes(img):
    if img is None or getattr(img, "size", 0) == 0:
        return img
    red = (img[:, :, 2] > 180) & (img[:, :, 1] < 45) & (img[:, :, 0] < 45)
    if not red.any():
        return img
    out = img.copy()
    out[red] = (38, 34, 30)
    return out


def _build_fallback_sections(norm_items, h: int):
    """回退提取：不限列宽，仅截断烧魂段与强化列表。"""
    y_enhance = int(h * 0.92)
    y_burn = None
    for it, t in norm_items:
        cy = it.center[1] / max(1, h)
        if ("强化技能" in t or "強化技能" in t) and len(t) <= 8 and 0.30 <= cy <= 0.92:
            y_enhance = min(y_enhance, it.box[1])
        elif _RE_ENHANCE_ROW.search(t) and cy >= 0.42:
            y_enhance = min(y_enhance, it.box[1])
    for it, t in norm_items:
        cy = it.center[1] / max(1, h)
        if ("灵魂燃烧效果" in t or "灵魂燃烧" in t) and 0.25 <= cy <= 0.85 and it.box[1] < y_enhance:
            y_burn = it.box[1] if y_burn is None else min(y_burn, it.box[1])
    y_main_bottom = min(y_burn, y_enhance) if y_burn is not None else y_enhance
    main_boxes, burn_boxes = [], []
    for it, t in norm_items:
        cy_px = (it.box[1] + it.box[3]) * 0.5
        if any(bad in t for bad in _UI_NOISE_WORDS) or _RE_ENHANCE_ROW.search(t):
            continue
        if int(h * 0.10) <= cy_px < y_main_bottom:
            main_boxes.append((it, t))
        elif y_burn is not None and y_burn <= cy_px < y_enhance:
            burn_boxes.append((it, t))
    main_boxes.sort(key=lambda pr: (pr[0].box[1] // 16, pr[0].box[0]))
    burn_boxes.sort(key=lambda pr: (pr[0].box[1] // 16, pr[0].box[0]))
    return "".join(t for _, t in main_boxes), "".join(t for _, t in burn_boxes)


def extract_popup_sections_from_items(items, w: int, h: int):
    """锚点列定位 + 锚点校验 + 全域回退。"""
    from core import to_simplified

    if not items or w <= 0 or h <= 0:
        return "", ""
    norm = []
    for it in items:
        t = "".join(to_simplified(it.text).split())
        if not t or _RE_PURE_NUM_NOISE.fullmatch(t):
            continue
        norm.append((it, t))
    if not norm:
        return "", ""

    fb_main, fb_burn = _build_fallback_sections(norm, h)
    if w < h * 0.9:
        return fb_main, fb_burn

    x_left = None
    header_y = None
    y_enhance = int(h * 0.92)
    y_burn = None

    for it, t in norm:
        cx, cy = it.center[0] / w, it.center[1] / h
        if any(k in t for k in ("获得灵魂", "得灵魂", "获得专注力", "冷却时间")) and 0.12 <= cy <= 0.80 and cx >= 0.22:
            if header_y is None or it.box[1] < header_y:
                header_y = it.box[1]
                x_left = max(0, it.box[0] - int(0.065 * w))

    for it, t in norm:
        cx, cy = it.center[0] / w, it.center[1] / h
        if ("强化技能" in t or "強化技能" in t) and len(t) <= 8 and 0.22 <= cx <= 0.92 and 0.30 <= cy <= 0.92:
            if x_left is not None and abs(it.box[0] - x_left) > int(0.14 * w):
                continue
            if it.box[1] < y_enhance:
                y_enhance = it.box[1]
                x_left = it.box[0]

    for it, t in norm:
        cx, cy = it.center[0] / w, it.center[1] / h
        if ("灵魂燃烧效果" in t or "灵魂燃烧" in t) and 0.22 <= cx <= 0.92 and 0.25 <= cy <= 0.86:
            if x_left is not None and abs(it.box[0] - x_left) > int(0.14 * w):
                continue
            if it.box[1] < y_enhance:
                y_burn = it.box[1] if y_burn is None else min(y_burn, it.box[1])
                if x_left is None:
                    x_left = it.box[0]

    if x_left is not None:
        for it, t in norm:
            if it.center[1] / h >= 0.42 and _RE_ENHANCE_ROW.search(t):
                if x_left - int(0.04 * w) <= it.box[0] <= x_left + int(0.26 * w):
                    y_enhance = min(y_enhance, it.box[1])

    if x_left is None:
        return fb_main, fb_burn

    col_x0 = max(0, x_left - int(0.035 * w))
    col_x1_start = min(w, x_left + int(0.25 * w))
    col_x1_end = min(w, x_left + int(0.32 * w))
    y_top = max(0, header_y - int(0.09 * h)) if header_y is not None else int(0.10 * h)
    y_main_bottom = min(y_burn, y_enhance) if y_burn is not None else y_enhance

    main_boxes, burn_boxes = [], []
    for it, t in norm:
        x1, y1, x2, y2 = it.box
        cy = (y1 + y2) * 0.5
        if not (col_x0 <= x1 <= col_x1_start and x2 <= col_x1_end):
            continue
        if any(bad in t for bad in _UI_NOISE_WORDS):
            continue
        if y_top <= cy < y_main_bottom:
            main_boxes.append((it, t))
        elif y_burn is not None and y_burn <= cy < y_enhance:
            burn_boxes.append((it, t))

    main_boxes.sort(key=lambda pr: (pr[0].box[1] // 16, pr[0].box[0]))
    burn_boxes.sort(key=lambda pr: (pr[0].box[1] // 16, pr[0].box[0]))
    main_text = "".join(t for _, t in main_boxes)
    burn_text = "".join(t for _, t in burn_boxes)

    corrupted = ("强化技能" in main_text) or bool(_RE_ENHANCE_ROW.search(main_text))
    soul_lost = (not _RE_SOUL_GAIN.search(main_text)) and bool(_RE_SOUL_GAIN.search(fb_main))
    if corrupted or len(main_text) < 10 or soul_lost:
        return fb_main, (burn_text or fb_burn)
    return main_text, burn_text


def extract_skill_popup_texts(img, ocr, slot=None):
    """三遍识别：宽 ROI → 整图 → 去红框图。"""
    import numpy as np

    if img is None or getattr(img, "size", 0) == 0 or ocr is None:
        return "", ""
    h, w = img.shape[:2]

    def _run_roi(src_img):
        if w < h * 0.9:
            items = ocr.read(src_img, min_score=0.38, min_brightness=0.0, include_dim=True)
            return extract_popup_sections_from_items(items, w, h)
        x0 = int(w * (0.36 if slot in (1, 2, 3) else 0.20))
        x1 = int(w * 0.96)
        y0, y1 = int(h * 0.10), int(h * 0.94)
        roi = np.ascontiguousarray(src_img[y0:y1, x0:x1])
        raw = ocr.read(roi, min_score=0.38, min_brightness=0.0, include_dim=True)
        shifted = [
            OcrItem(
                text=it.text,
                score=it.score,
                box=(it.box[0] + x0, it.box[1] + y0, it.box[2] + x0, it.box[3] + y0),
                brightness=it.brightness,
            )
            for it in raw
        ]
        return extract_popup_sections_from_items(shifted, w, h)

    main_txt, burn_txt = _run_roi(img)
    if len(main_txt) >= 10 and _RE_SOUL_GAIN.search(main_txt) and "全体敌人" in main_txt:
        return main_txt, burn_txt

    if len(main_txt) < 10 or not _RE_SOUL_GAIN.search(main_txt):
        full = ocr.read(img, min_score=0.35, min_brightness=0.0, include_dim=True)
        m2, b2 = extract_popup_sections_from_items(full, w, h)
        if (_RE_SOUL_GAIN.search(m2) and not _RE_SOUL_GAIN.search(main_txt)) or len(m2) > len(main_txt):
            main_txt, burn_txt = m2, (b2 or burn_txt)

    red = (img[:, :, 2] > 180) & (img[:, :, 1] < 45) & (img[:, :, 0] < 45)
    if np.any(red) and ("全体敌人" not in main_txt or not _RE_SOUL_GAIN.search(main_txt)):
        clean = _strip_debug_red_boxes(img)
        m3, b3 = _run_roi(clean)
        if (
            ("全体敌人" in m3 and "全体敌人" not in main_txt)
            or (_RE_SOUL_GAIN.search(m3) and not _RE_SOUL_GAIN.search(main_txt))
            or len(m3) > len(main_txt)
        ):
            main_txt, burn_txt = m3, (b3 or burn_txt)

    return main_txt, burn_txt


# ==================== B. 分类器（无灵魂回退攻击词 > 攻击定主类 > 附加记副标） ====================
_RE_SOUL_GAIN = re.compile(r"(获得灵魂|得灵魂|灵魂\s*[123一二三]\s*点)")
_RE_HEADER_META = re.compile(
    r"(获得灵魂\s*\d*\s*点?|得灵魂\s*\d*\s*点?|获得专注力\s*\d*\s*点?|冷却时间\s*\d*\s*回合?|冷却时)"
)
_RE_NEG_ATK_MASK = re.compile(
    r"(非攻击类技能|受到攻击|每次攻击时|基本技能发动攻击|基本技能攻击|技能伤害无效|不会触发夹攻|攻击力提升|攻击力降低|攻击力最高的)"
)
_RE_AOE_SKILL = re.compile(
    r"(攻击全体敌人|对全体敌人[^。]{0,20}攻击|攻击[^，。]{0,6}全体敌人|包含目标在内的\s*[23两三]\s*人|攻击[^，。]{0,6}[23两三][名个]敌人)"
)
_RE_ATK_SKILL = re.compile(
    r"(攻击[^，。]{0,8}(?:敌人|目标)|对敌人[^。]{0,22}攻击|穿透[^，。]{0,8}攻击|用[^，。]{1,9}(?:攻击|上击|打击|斩击|刺击|射击)|造成[^，。]{0,8}额外伤害)"
)
_RE_ALLY_HEAL = re.compile(
    r"((?:我军|全体|目标|人员|最低)[^，。]{0,16}(?:恢复|回复)[^，。]{0,8}生命|使[^，。]{0,10}等比(?:恢复|回复)生命)"
)
_RE_SELF_HEAL = re.compile(r"(部分伤害量作为生命值(?:恢复|回复)|自身[^，。]{0,10}(?:恢复|回复)[^，。]{0,8}生命)")
_RE_BUFF_EFFECT = re.compile(
    r"((?:我军|自身|目标|全体)[^，。]{0,14}(?:获得|提升|防护罩|免疫|魄力|无敌|不死|额外回合|复制|夹攻)|解除[^，。]{0,10}弱化效果)"
)


def classify_skill_popup(main_text: str, burn_text: str = "") -> dict:
    """多标签分类：{"primary","tags","ev"}。"""
    from core import to_simplified

    raw_main = "".join(to_simplified(str(main_text or "")).split())
    raw_burn = "".join(to_simplified(str(burn_text or "")).split())

    for cut_kw in ("强化技能", "強化技能", "升级刻印", "刻印记忆"):
        if cut_kw in raw_main:
            raw_main = raw_main.split(cut_kw, 1)[0]
        if cut_kw in raw_burn:
            raw_burn = raw_burn.split(cut_kw, 1)[0]
    if not raw_burn and "灵魂燃烧效果" in raw_main:
        raw_main, raw_burn = raw_main.split("灵魂燃烧效果", 1)

    if len(raw_main) < 6:
        return {"primary": "unknown", "tags": {}, "ev": "OCR文本过短"}

    body = _RE_HEADER_META.sub("", raw_main)
    masked = _RE_NEG_ATK_MASK.sub("", body)
    m_aoe = _RE_AOE_SKILL.search(masked)
    m_atk = _RE_ATK_SKILL.search(masked)

    soul_m = _RE_SOUL_GAIN.search(raw_main)
    if not soul_m:
        if m_aoe:
            return {"primary": "aoe", "tags": {"aoe": 0.85}, "ev": f"无灵魂但含群攻词:{m_aoe.group(0)}"}
        if m_atk:
            return {"primary": "single", "tags": {"single": 0.85}, "ev": f"无灵魂但含攻击词:{m_atk.group(0)}"}
        return {"primary": "passive", "tags": {"passive": 1.0}, "ev": f"无获得灵魂({raw_main[:24]})"}

    tags, ev, primary = {}, [soul_m.group(0)], ""

    if m_aoe:
        primary = "aoe"
        hit = m_aoe.group(0)
        if "全体敌人" in hit:
            tags["aoe"] = 0.95
        else:
            tags["aoe"] = 0.85
            tags["single"] = 0.70
        ev.append(hit)
    elif m_atk:
        primary = "single"
        tags["single"] = 0.95
        ev.append(m_atk.group(0))

    m_ally = _RE_ALLY_HEAL.search(body)
    m_self = _RE_SELF_HEAL.search(body)
    if m_ally:
        if not primary:
            primary, tags["heal"] = "heal", 0.95
        else:
            tags["heal"] = 0.80
        ev.append(m_ally.group(0))
    elif m_self:
        if not primary:
            primary, tags["heal"] = "heal", 0.85
        else:
            tags["self_heal"] = 0.65
        ev.append(m_self.group(0))

    m_buff = _RE_BUFF_EFFECT.search(body)
    if m_buff:
        if not primary:
            primary, tags["buff"] = "buff", 0.95
        else:
            tags["buff"] = 0.65
        ev.append(m_buff.group(0))

    if not primary:
        if "敌人" in masked or "目标" in masked:
            primary, tags["single"] = "single", 0.70
            ev.append("含灵魂与敌方目标")
        elif any(w in body for w in ("获得", "提升", "复制", "额外回合", "免疫", "防护罩")):
            primary, tags["buff"] = "buff", 0.75
            ev.append("含灵魂+增益词")
        elif "伤害" in body:
            primary, tags["single"] = "single", 0.70
            ev.append("含灵魂+伤害词")
        else:
            return {"primary": "unknown", "tags": {}, "ev": f"未命中特征({body[:24]})"}

    if raw_burn:
        if "全体敌人" in raw_burn:
            tags["burn_aoe"] = 0.95
            ev.append("烧魂:攻击全体敌人")
        if "恢复" in raw_burn or "回复" in raw_burn:
            tags["burn_heal"] = 0.95
            ev.append("烧魂:恢复生命")
        if "额外回合" in raw_burn:
            tags["burn_extra"] = 0.90
            ev.append("烧魂:额外回合")

    return {"primary": primary, "tags": tags, "ev": " | ".join(ev)}


def classify_skill_desc(text: str) -> str:
    """兼容旧接口：只返回主标签。"""
    return str(classify_skill_popup(text).get("primary", "unknown"))


# ==================== C. 标签存储 + S1指纹 + 多形态(_forms) + 身份解析 ====================
_TAGS_CACHE: dict = {}
KNOWN_MONSTER_NAMES = {
    "红焰蝎子", "流浪谋士", "岩穴狮鹫", "叹狮鹫", "流浪格斗家", "红色半月野熊", "我方英雄", "我傘英雄",
}
_HERO_TRAILING_NOISE = set("婴♀♂☆⭐★①②③④⑤1234567890.·-—_ ")


def _tags_file():
    from pathlib import Path as _P

    try:
        from core import user_data_dir

        return user_data_dir() / "skill_tags.json"
    except Exception:  # noqa: BLE001
        return _P("skill_tags.json")


TAGS_VERSION = 4


def crop_s1_icon(img, lit_xs=None, icon_y=None):
    """按本帧第 1 槽中心裁剪 S1 图标核心区（内缩，避开金环与魂火）。"""
    if img is None or getattr(img, "size", 0) == 0:
        return None
    h, w = img.shape[:2]
    if h < 80 or w < 80:
        return None
    s1_x = float(lit_xs[0]) if (lit_xs and len(lit_xs) >= 1) else float(_STD_SLOT_XS[0])
    s1_y = float(icon_y) if icon_y else float(_LAST_SLOT_Y or SKILL_POS[1][1])
    x1 = max(0, int(round(w * (s1_x - 0.022))))
    x2 = min(w, int(round(w * (s1_x + 0.022))))
    y1 = max(0, int(round(h * (s1_y - 0.034))))
    y2 = min(h, int(round(h * (s1_y + 0.034))))
    if x2 <= x1 + 4 or y2 <= y1 + 4:
        return None
    return img[y1:y2, x1:x2]


def compute_s1_dhash(s1_img) -> str:
    """S1 图标核心块 -> 64-bit dHash（16 位十六进制）。"""
    if s1_img is None or getattr(s1_img, "size", 0) == 0:
        return ""
    gray = cv2.cvtColor(s1_img, cv2.COLOR_BGR2GRAY) if s1_img.ndim == 3 else s1_img
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    diff = (small[:, 1:] > small[:, :-1]).ravel()
    val = 0
    for bit in diff:
        val = (val << 1) | int(bool(bit))
    return f"{val:016x}"


def dhash_distance(h1: str, h2: str) -> int:
    if not h1 or not h2 or len(h1) != 16 or len(h2) != 16:
        return 64
    try:
        return (int(h1, 16) ^ int(h2, 16)).bit_count()
    except ValueError:
        return 64


def _edit_distance_le1(a: str, b: str) -> bool:
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        return sum(1 for ca, cb in zip(a, b) if ca != cb) <= 1
    short, long_s = (a, b) if la < lb else (b, a)
    i = j = diff = 0
    while i < len(short) and j < len(long_s):
        if short[i] == long_s[j]:
            i += 1
            j += 1
        else:
            diff += 1
            if diff > 1:
                return False
            j += 1
    return True


def _clean_ocr_hero_name(raw_name: str) -> str:
    """清洗 OCR 名字：繁转简、去空白、去尾部图标误识。"""
    from core import to_simplified

    s2 = "".join(to_simplified(str(raw_name or "")).split())
    while len(s2) > 2 and s2[-1] in _HERO_TRAILING_NOISE:
        s2 = s2[:-1]
    if not s2 or s2 in KNOWN_MONSTER_NAMES or len(s2) < 2:
        return ""
    if re.fullmatch(r"[\d/\+\-%\.\sA-Za-z]+", s2):
        return ""
    return s2


def get_slot_primary(hero_tags: dict, slot: int):
    if not isinstance(hero_tags, dict):
        return None
    raw = hero_tags.get(str(slot)) or hero_tags.get(slot)
    if isinstance(raw, dict):
        return raw.get("primary")
    return str(raw) if raw else None


def get_slot_detail(hero_tags: dict, slot: int) -> dict:
    if not isinstance(hero_tags, dict):
        return {}
    raw = hero_tags.get(str(slot)) or hero_tags.get(slot)
    if isinstance(raw, dict):
        return raw
    details = hero_tags.get("_detail")
    if isinstance(details, dict):
        d = details.get(str(slot)) or details.get(slot)
        if isinstance(d, dict):
            return d
    pv = str(raw) if raw else ""
    return {"primary": pv, "tags": {pv: 1.0} if pv else {}, "ev": ""}


def _sync_current_form_snapshot(hero_tags: dict) -> None:
    cur = str(hero_tags.get("_s1_hash") or "")
    if not cur:
        return
    if not any(get_slot_primary(hero_tags, x) not in (None, "", "unknown") for x in (1, 2, 3)):
        return
    entry = hero_tags.setdefault("_forms", {}).setdefault(cur, {})
    for x in ("1", "2", "3"):
        if x in hero_tags:
            entry[x] = hero_tags[x]
    if isinstance(hero_tags.get("_detail"), dict):
        entry["_detail"] = {k: dict(v) for k, v in hero_tags["_detail"].items() if isinstance(v, dict)}


def _activate_or_switch_form(hero_tags: dict, s1_hash: str) -> bool:
    if not s1_hash or not isinstance(hero_tags, dict):
        return False
    dirty = False
    if "_aliases" not in hero_tags:
        hero_tags["_aliases"] = []
        dirty = True
    old_hash = str(hero_tags.get("_s1_hash") or "")
    forms = hero_tags.setdefault("_forms", {})
    if not old_hash:
        hero_tags["_s1_hash"] = s1_hash
        _sync_current_form_snapshot(hero_tags)
        return True

    best_key = None
    best_dist = dhash_distance(s1_hash, old_hash)
    if best_dist <= 10:
        best_key = old_hash
    for f_hash in list(forms.keys()):
        d = dhash_distance(s1_hash, f_hash)
        if d < best_dist:
            best_dist = d
            best_key = f_hash

    if best_key is not None and best_dist <= 10:
        if best_key != old_hash and best_key in forms:
            _sync_current_form_snapshot(hero_tags)
            target = forms[best_key]
            for x in ("1", "2", "3"):
                hero_tags[x] = target.get(x, "unknown")
            if isinstance(target.get("_detail"), dict):
                hero_tags["_detail"] = {k: dict(v) for k, v in target["_detail"].items()}
            hero_tags["_s1_hash"] = best_key
            dirty = True
        return dirty

    if best_dist > 14:
        _sync_current_form_snapshot(hero_tags)
        hero_tags["_s1_hash"] = s1_hash
        for x in ("1", "2", "3"):
            hero_tags[x] = "unknown"
        hero_tags["_detail"] = {}
        hero_tags["_form_changed"] = True
        return True
    return dirty


def resolve_hero_identity(ocr_name: str, s1_img=None) -> str:
    """三级身份解析：精确 -> 别名/前缀/编辑距离<=1 -> S1 dHash 兜底。"""
    tags = load_skill_tags()
    s1_hash = compute_s1_dhash(s1_img)
    raw_trimmed = "".join(str(ocr_name or "").split())
    clean_name = _clean_ocr_hero_name(raw_trimmed)
    matched = None
    dirty = False

    if clean_name and clean_name in tags:
        matched = clean_name

    if matched is None and clean_name:
        for known, data in list(tags.items()):
            if not isinstance(data, dict) or known in KNOWN_MONSTER_NAMES:
                continue
            aliases = data.get("_aliases") or []
            if clean_name in aliases or raw_trimmed in aliases:
                matched = known
                break
            if len(clean_name) >= 3 and len(known) >= 3 and (
                clean_name.startswith(known) or known.startswith(clean_name)
            ):
                matched = known
                break
            if len(clean_name) >= 3 and _edit_distance_le1(clean_name, known):
                matched = known
                break
        if matched is not None and clean_name != matched:
            al = tags[matched].setdefault("_aliases", [])
            if clean_name not in al:
                al.append(clean_name)
                dirty = True

    if matched is None and s1_hash:
        best_hero, best_d = None, 64
        for known, data in list(tags.items()):
            if not isinstance(data, dict) or known in KNOWN_MONSTER_NAMES:
                continue
            cands = [str(data.get("_s1_hash") or "")] + list((data.get("_forms") or {}).keys())
            for ch in cands:
                d = dhash_distance(s1_hash, ch)
                if d < best_d:
                    best_d, best_hero = d, known
        limit = 10 if not clean_name else 4
        if best_hero is not None and best_d <= limit:
            matched = best_hero

    if matched is not None:
        entry = tags.setdefault(matched, {})
        if _activate_or_switch_form(entry, s1_hash):
            dirty = True
        if dirty:
            save_skill_tags(tags)
        return matched

    if clean_name:
        entry = tags.setdefault(clean_name, {"_s1_hash": s1_hash, "_aliases": [], "_forms": {}})
        if s1_hash and not entry.get("_s1_hash"):
            entry["_s1_hash"] = s1_hash
        save_skill_tags(tags)
        return clean_name

    return "我方英雄"


def set_slot_skill_info(hero_tags: dict, slot: int, info) -> None:
    key = str(slot)
    if isinstance(info, str):
        hero_tags[key] = info
    else:
        primary = str(info.get("primary") or "unknown")
        hero_tags[key] = primary
        hero_tags.setdefault("_detail", {})[key] = {
            "primary": primary,
            "tags": dict(info.get("tags") or {}),
            "ev": str(info.get("ev") or ""),
        }
    _sync_current_form_snapshot(hero_tags)


def load_skill_tags() -> dict:
    global _TAGS_CACHE
    if _TAGS_CACHE:
        return _TAGS_CACHE
    try:
        import json as _json

        f = _tags_file()
        if f.exists():
            data = _json.loads(f.read_text(encoding="utf-8")) or {}
            if int(data.get("_v", 0)) < TAGS_VERSION:
                _TAGS_CACHE = {}
                return _TAGS_CACHE
            raw = data.get("heroes") if isinstance(data.get("heroes"), dict) else data
            cleaned = {}
            for name, val in raw.items():
                if not isinstance(val, dict) or name in KNOWN_MONSTER_NAMES:
                    continue
                val.setdefault("_s1_hash", "")
                val.setdefault("_aliases", [])
                val.setdefault("_forms", {})
                _sync_current_form_snapshot(val)
                cleaned[name] = val
            _TAGS_CACHE = cleaned
    except Exception:  # noqa: BLE001
        _TAGS_CACHE = {}
    return _TAGS_CACHE


def save_skill_tags(tags: dict | None = None) -> None:
    global _TAGS_CACHE
    if tags is not None:
        _TAGS_CACHE = tags
    try:
        import json as _json

        for m in list(KNOWN_MONSTER_NAMES):
            _TAGS_CACHE.pop(m, None)
        f = _tags_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        payload = {"_v": TAGS_VERSION, "heroes": _TAGS_CACHE}
        f.write_text(_json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
