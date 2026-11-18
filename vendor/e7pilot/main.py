"""第七史诗（Steam 简中版）自动推剧情 主程序。

热键：F8 暂停/继续    F10 退出脚本
"""
from __future__ import annotations

import ctypes
import sys
import time
import winsound
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import yaml

from combat import BriegSimpleCombatController
from diag_env import write_env_diag
from core import (
    to_simplified,
    GameWindow,
    blue_empty_pads,
    hero_plus_btn,
    find_empty_slot,
    InputBlockedError,
    Ocr,
    OcrItem,
    check_team_auto_switch,
    detect_quest_compass,
    find_game_window,
    find_single_compass_fallback,
    has_battle_hud,
    has_labyrinth_hud,
    is_admin,
    is_low_integrity,
    process_parent_info,
    process_privilege_summary,
    runtime_root,
    write_startup_diag,
    cursor_control_probe,
)

ROOT = runtime_root()
VK_F8, VK_F10 = 0x77, 0x79
STRIP_CHARS = "><»«›‹·•.。!！-—_~ "


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def dev_combat_log(msg: str) -> None:
    """开发者日志：战斗内部决策写文件，玩家看不到。"""
    if not msg:
        return
    try:
        from core import runtime_root

        d = runtime_root() / "debug"
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"战斗日志_{datetime.now():%Y%m%d}.txt"
        with f.open("a", encoding="utf-8") as fp:
            fp.write(f"[{datetime.now():%H:%M:%S}] {msg}\n")
    except Exception:  # noqa: BLE001
        pass


def norm(s: str) -> str:
    return to_simplified("".join(s.split()))


def clean_btn_text(s: str) -> str:
    return norm(s).strip(STRIP_CHARS)


@dataclass
class Rule:
    name: str
    keywords: list[str] = field(default_factory=list)
    action: str = "click"
    region: list[float] | None = None
    require_any: list[str] = field(default_factory=list)
    forbid: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    exact: bool = False
    max_len: int | None = None
    at: list[float] | None = None
    cooldown: float = 1.0
    last_fire: float = 0.0

    def find(self, items: list[OcrItem], w: int, h: int, default_max_len: int) -> OcrItem | None:
        max_len = self.max_len or default_max_len
        kw_norm = [clean_btn_text(k) if self.exact else norm(k) for k in self.keywords]
        excl_norm = [norm(x) for x in self.exclude]
        for it in items:
            raw = norm(it.text)
            t = clean_btn_text(it.text) if self.exact else raw
            if not t or len(t) > max_len:
                continue
            if excl_norm and any(ex in raw for ex in excl_norm):
                continue
            hit = (t in kw_norm) if self.exact else any(k in t for k in kw_norm)
            if not hit:
                continue
            if self.region:
                cx, cy = it.center
                x1, y1, x2, y2 = self.region
                if not (x1 <= cx / w <= x2 and y1 <= cy / h <= y2):
                    continue
            return it
        return None


def analyze_frame(
    img: np.ndarray,
    items: list[OcrItem],
    rules: list[Rule],
    global_forbid: list[str],
    default_max_len: int,
    enable_auto_check: bool = True,
    now: float | None = None,
    allow_dead_end_compass: bool = False,
    manual_combat: bool = False,
    combat_ctrl: BriegSimpleCombatController | None = None,
) -> dict:
    """对单帧图像与 OCR 结果做纯逻辑决策（同时供主循环与离线回放测试复用）。"""
    if now is None:
        now = time.time()
    h, w = img.shape[:2]
    all_text = norm("".join(it.text for it in items))
    in_battle = has_battle_hud(img, items)
    in_labyrinth = has_labyrinth_hud(img, items)

    # 0. 战斗暂停菜单（误触右上角 ‖ 或游戏弹出）：优先点「返回」关掉，别急着暂停
    _pause_markers = ("设置选项", "声音设置")   # 只有暂停菜单才有这两项，战斗失败页不会
    if any(any(mk in it.text for mk in _pause_markers) for it in items):
        back_btn = next(
            (it for it in items if it.text.strip() in ("返回", "继续", "继续战斗", "回到战斗")), None
        )
        if back_btn is not None:
            return {
                "type": "click_ratio",
                "rule": Rule(name="关闭战斗暂停菜单", cooldown=1.5),
                "pos": (back_btn.center[0] / w, back_btn.center[1] / h),
                "clicks": 1,
                "in_battle": True,
                "in_labyrinth": in_labyrinth,
                "is_aux_click": True,
                "desc": "↩ 检测到战斗暂停菜单 → 点击「返回」继续战斗",
            }
        return {
            "type": "key",
            "vk": 27,  # VK_ESCAPE
            "rule": Rule(name="关闭战斗暂停菜单(ESC)", cooldown=1.5),
            "in_battle": True,
            "desc": "↩ 检测到战斗暂停菜单（无返回按钮）→ 发送 ESC 关闭",
        }

    # 1. 优先检查所有暂停规则（打不过、没体力、满包）
    for rule in rules:
        if rule.action not in ("pause", "stop"):
            continue
        if rule.require_any and not any(norm(k) in all_text for k in rule.require_any):
            continue
        if rule.forbid and any(norm(k) in all_text for k in rule.forbid):
            continue
        target = rule.find(items, w, h, default_max_len)
        if target is not None:
            return {
                "type": "pause",
                "rule": rule,
                "reason": f"检测到「{target.text}」({rule.name})",
            }

    # 1.6 队伍未满弹窗：绝不确认，点取消回编队页补位
    _under_full = ("队伍未满", "未满员", "人数不足", "人员不足", "请先编队", "队伍不足")
    if any(k in all_text for k in _under_full):
        cancel_btn = next(
            (it for it in items if norm(it.text).strip("：: .。") in ("取消", "关闭", "返回")), None
        )
        if cancel_btn is not None:
            return {
                "type": "click_ratio",
                "rule": Rule(name="队伍未满→取消", cooldown=1.0),
                "pos": (cancel_btn.center[0] / w, cancel_btn.center[1] / h),
                "clicks": 1,
                "in_battle": False,
                "in_labyrinth": in_labyrinth,
                "is_aux_click": True,
                "desc": "↩ 队伍未满 → 点取消，回去补位",
            }

    # 2. 全局消费词拦截（单框高质量匹配 + 弱词弹窗/上下文双门控）
    _weak = ("消耗天空石", "花费天空石", "使用天空石", "天空石不足")
    _shop_words = ("立即更新", "秘密商店")
    _btn_words = ("确认", "确定", "取消", "购买")
    _stage_words = ("Episode", "EPISODE", "准备战斗", "可获得的奖励")

    has_shop_ctx = any(
        it.score >= 0.75 and any(w in norm(it.text) for w in _shop_words)
        for it in items
    )
    has_popup_btn = any(
        it.score >= 0.75
        and 0.20 <= it.center[0] / w <= 0.80
        and 0.25 <= it.center[1] / h <= 0.85
        and norm(it.text).strip("：: .。") in _btn_words
        for it in items
    )
    on_stage_screen = any(any(x in norm(it.text) for x in _stage_words) for it in items)

    for it in items:
        t_norm = norm(it.text)
        if not t_norm or len(t_norm) > 20 or it.score < 0.75 or it.brightness < 110.0:
            continue
        cx_r, cy_r = it.center[0] / w, it.center[1] / h
        for k in global_forbid:
            if k not in t_norm:
                continue
            if k in _weak:
                if in_battle or it.score < 0.80 or it.brightness < 115.0:
                    continue
                if not (0.20 <= cx_r <= 0.80 and 0.18 <= cy_r <= 0.82):
                    continue
                if not (has_shop_ctx or (has_popup_btn and not on_stage_screen)):
                    continue
            return {
                "type": "pause",
                "rule": None,
                "reason": (
                    f"画面出现付费/消费相关文字「{k}」"
                    f"（原文「{it.text}」置信度={it.score:.2f} 坐标=({cx_r:.2f},{cy_r:.2f})），"
                    "为保护账号财产已自动暂停"
                ),
            }

    # 3. 剧情跳过与确认跳过优先（确保战斗中穿插的Boss台词对话第一时间跳过）
    for rule in rules:
        if rule.action in ("pause", "stop"):
            continue
        if not ("跳过" in rule.name and "教学" not in rule.name):
            continue
        if now - rule.last_fire < rule.cooldown:
            continue
        if rule.require_any and not any(norm(k) in all_text for k in rule.require_any):
            continue
        if rule.forbid and any(norm(k) in all_text for k in rule.forbid):
            continue
        target = rule.find(items, w, h, default_max_len)
        if target is not None:
            cx, cy = target.center
            return {
                "type": "click_ratio",
                "rule": rule,
                "pos": (cx / w, cy / h),
                "in_battle": in_battle,
                "in_labyrinth": in_labyrinth,
                "target_text": target.text,
                "desc": f"{rule.name}：点击「{target.text}」",
            }

    # 4. 手操烧魂（手动精控）接管（取消系统 AUTO + 留技能/烧魂/点杀小弟）
    if manual_combat and combat_ctrl is not None and in_battle:
        c_dec = combat_ctrl.decide(img, items, now=now)
        if c_dec is not None:
            dev_combat_log(f"[W{getattr(combat_ctrl, 'wave_index', '?')}] {c_dec.get('desc', '')}")
            if c_dec["type"] == "combat_click":
                return {
                    "type": "click_ratio",
                    "rule": Rule(name=c_dec["action_key"], cooldown=0.0),
                    "pos": c_dec["pos"],
                    "clicks": int(c_dec.get("clicks", 1)),
                    "in_battle": True,
                    "in_labyrinth": in_labyrinth,
                    "is_combat": True,
                    "fast_followup": bool(c_dec.get("fast_followup", False)),
                    "desc": str(c_dec.get("desc") or c_dec.get("action_key") or "出招中…"),
                }
            if c_dec["type"] == "combat_sequence":
                return {
                    "type": "click_sequence",
                    "rule": Rule(name=c_dec["action_key"], cooldown=0.0),
                    "steps": list(c_dec["steps"]),
                    "step_gap": float(c_dec.get("step_gap", 0.16)),
                    "in_battle": True,
                    "in_labyrinth": in_labyrinth,
                    "is_combat": True,
                    "desc": f"⚔ 手操烧魂：{c_dec.get('desc') or c_dec.get('action_key') or '出招中…'}",
                }
            if c_dec["type"] == "combat_wait":
                return {
                    "type": "none",
                    "in_battle": True,
                    "in_labyrinth": in_labyrinth,
                    "combat_wait": True,
                    "desc": "⚔ 手操烧魂：出招中…",
                    "all_text": all_text,
                }
        elif in_labyrinth and any(
            "skill" in it.text.strip().lower() and it.center[0] / w >= 0.78 and it.center[1] / h >= 0.80
            for it in items
        ):
            # 迷宫走廊正常跑图（非战斗遭遇）：重置不死状态机供下一波遭遇战使用
            combat_ctrl.reset_battle()
    elif (not manual_combat) and enable_auto_check and in_battle and (not in_labyrinth):
        # 原版自动挂机模式：若战斗中左下角出现手动回合的 TAG 按钮（说明上次手操关掉了 AUTO），自动点右上角打开系统 AUTO
        has_manual_tag = any(
            it.text.strip().upper() == "TAG" and it.center[0] / w <= 0.16 and it.center[1] / h >= 0.89
            for it in items
        )
        if has_manual_tag:
            # 2026-11-09 用户要求：不再自动点 AUTO（避免误触右上角暂停按钮）
            return {
                "type": "pause",
                "rule": Rule(name="等待开启AUTO"),
                "reason": "检测到「自动战斗」未开启，请在游戏内手动打开 AUTO 后按 F8 继续",
            }

    # 5. 按顺序执行其余操作规则（含迷宫方向罗盘、结算领奖、编队 AUTO 检查与连续进关）
    for rule in rules:
        if rule.action in ("pause", "stop"):
            continue
        if "跳过" in rule.name and "教学" not in rule.name:
            continue
        if now - rule.last_fire < rule.cooldown:
            continue
        if rule.require_any and not any(norm(k) in all_text for k in rule.require_any):
            continue
        if rule.forbid and any(norm(k) in all_text for k in rule.forbid):
            continue

        if rule.action == "compass":
            if not in_labyrinth:
                continue
            comp = detect_quest_compass(img)
            if comp is not None:
                label, pt, score = comp
                return {
                    "type": "click_ratio",
                    "rule": rule,
                    "pos": pt,
                    "in_battle": in_battle,
                    "in_labyrinth": in_labyrinth,
                    "desc": f"{rule.name}：识别到任务高亮方向「{label}」(置信度 {score:.2f})",
                }
            if allow_dead_end_compass:
                fb = find_single_compass_fallback(items, w, h)
                if fb is not None:
                    label, pt = fb
                    return {
                        "type": "click_ratio",
                        "rule": rule,
                        "pos": pt,
                        "in_battle": in_battle,
                        "in_labyrinth": in_labyrinth,
                        "desc": f"{rule.name}：死胡同自动折返方向「{label}」",
                    }
            continue

        target = rule.find(items, w, h, default_max_len)
        if target is None:
            continue

        if combat_ctrl is not None and (
            "进行任务" in rule.keywords
            or "准备战斗" in rule.name
            or "结算" in rule.name
            or "下一关" in rule.name
        ):
            combat_ctrl.reset_battle()

        # 编队界面出战前：手动精控模式下自动关闭 AUTO；原版模式下自动开启 AUTO
        if enable_auto_check and "进行任务" in rule.keywords:
            auto_state = check_team_auto_switch(img, items)
            if auto_state is not None:
                is_on, auto_pt = auto_state
                if manual_combat and is_on:
                    return {
                        "type": "click_ratio",
                        "rule": rule,
                        "pos": auto_pt,
                        "desc": "编队检查：已启用手动精控 → 自动关闭编队 AUTO",
                        "is_aux_click": True,
                    }
                if (not manual_combat) and (not is_on):
                    return {
                        "type": "click_ratio",
                        "rule": rule,
                        "pos": auto_pt,
                        "desc": "编队检查：检测到 AUTO 未开启 → 自动点击打开 AUTO",
                        "is_aux_click": True,
                    }

        if rule.action == "click_at" and rule.at:
            return {
                "type": "click_ratio",
                "rule": rule,
                "pos": (float(rule.at[0]), float(rule.at[1])),
                "in_battle": in_battle,
                "in_labyrinth": in_labyrinth,
                "desc": f"{rule.name}：识别到「{target.text}」→ 点击预设位置 {rule.at}",
            }

        cx, cy = target.center
        return {
            "type": "click_ratio",
            "rule": rule,
            "pos": (cx / w, cy / h),
            "in_battle": in_battle,
            "in_labyrinth": in_labyrinth,
            "target_text": target.text,
            "desc": f"{rule.name}：点击「{target.text}」",
        }

    return {"type": "none", "in_battle": in_battle, "in_labyrinth": in_labyrinth, "all_text": all_text}


class Bot:
    def __init__(self, cfg: dict, mode_override: str | bool | None = None):
        self.cfg = cfg
        s = cfg.get("settings", {})
        if isinstance(mode_override, str):
            self.combat_mode = mode_override.lower()
        elif mode_override is True:
            self.combat_mode = "brieg"
        elif mode_override is False:
            self.combat_mode = "auto"
        else:
            raw_mode = s.get("combat_mode")
            if isinstance(raw_mode, str) and raw_mode.lower() in ("auto", "brieg"):
                self.combat_mode = raw_mode.lower()
            else:
                self.combat_mode = "brieg" if bool(s.get("manual_combat", True)) else "auto"

        self.manual_combat = self.combat_mode == "brieg"
        raw_interval = float(s.get("interval", 0.35))
        # 原版系统 AUTO 挂机模式无需高频轮询，保持 0.60s 轻量间隔；手动精控模式保持 0.35s 高速响应
        self.interval = raw_interval if self.manual_combat else max(raw_interval, 0.60)
        self.min_score = float(s.get("min_score", 0.55))
        self.default_max_len = int(s.get("default_max_len", 8))
        self.enable_auto_check = bool(s.get("enable_auto_battle_check", True))
        self.idle_click_after = float(s.get("idle_click_after", 4.5))
        self.idle_click_at = tuple(s.get("idle_click_at", [0.5, 0.78]))
        self.save_unknown_after = float(s.get("save_unknown_after", 20))
        self.auto_pause_unknown_after = float(s.get("auto_pause_unknown_after", 20))
        self.cutscene_press_seconds = float(s.get("cutscene_press_seconds", 3.4))
        # 准备战斗自动补位状态
        self._fill_state = "idle"
        self._fill_pos: tuple[float, float] | None = None
        self._fill_count = 0
        self._fill_fail = 0
        self._fill_last = 0.0
        self._fill_deadline = 0.0
        self.stuck_repeat = int(s.get("stuck_repeat", 8))
        self.capture_method = s.get("capture", "auto")
        self.global_forbid = [norm(x) for x in cfg.get("global_forbid", [])]
        # 战斗内双击/连点的两下间隔（秒）：30ms 太近会被游戏吞成一次点击
        _cg = s.get("combat_click_gap_ms", 140)
        try:
            if isinstance(_cg, (list, tuple)) and len(_cg) == 2:
                self.combat_click_gap = (float(_cg[0]) + float(_cg[1])) / 2.0 / 1000.0
            else:
                self.combat_click_gap = float(_cg) / 1000.0
        except (TypeError, ValueError):
            self.combat_click_gap = 0.14
        self.rules = [Rule(**{k: v for k, v in r.items()}) for r in cfg.get("rules", [])]
        self.combat_ctrl: BriegSimpleCombatController | None = (
            BriegSimpleCombatController() if self.combat_mode == "brieg" else None
        )

        hwnd = find_game_window()
        win_obj = None
        _bind_done = False
        ipc_mode = False
        # 1) Steam 原生窗口优先：只要不是模拟器窗口，就用原来的 Win32 驱动
        if hwnd:
            from core import EMULATOR_INFO

            if not EMULATOR_INFO:
                win_obj = GameWindow(hwnd, s.get("click_mode", "foreground"))
        # 2) 没有 Steam 窗口 → 尝试 MuMu 原生 IPC（截图 6ms / 触控 <1ms / 支持最小化）
        if win_obj is None:
            try:
                from mumu_ipc import open_mumu_ipc

                win_obj = open_mumu_ipc()
                ipc_mode = win_obj is not None
            except Exception:  # noqa: BLE001
                win_obj = None
        # 3) IPC 不可用但有模拟器窗口 → 回退普通窗口截图
        if win_obj is None and hwnd:
            win_obj = GameWindow(hwnd, s.get("click_mode", "foreground"))
        if win_obj is None:
            _hint = ""
            try:
                _p = write_env_diag("未能绑定游戏窗口")
                if _p:
                    _hint = "\n已生成诊断文件：%s" % _p
            except Exception:  # noqa: BLE001
                pass
            raise SystemExit(
                "❌ 未找到《第七史诗》游戏窗口！\n"
                "请确认：1. 游戏已从 Steam 启动；2. 或 MuMu 模拟器已打开并进入游戏；"
                "3. 游戏处于窗口模式且没有最小化。" + _hint
            )
        if ipc_mode:
            try:
                _mw, _mh = win_obj.client_size()
                log(f"🖥 模拟器模式：已绑定渲染层 {_mw}×{_mh}（不含模拟器工具栏）")
            except Exception:  # noqa: BLE001
                pass
        self.win = win_obj
        if not _bind_done and self.combat_ctrl is not None:
            try:
                self.combat_ctrl.bind_runtime(self.win, self.ocr)
                _bind_done = True
            except Exception:  # noqa: BLE001
                pass
        # 驱动已确定（Steam / 模拟器）→ 再套一次平台覆盖（skill_pos 等按平台不同的项）
        try:
            from combat import _apply_pos_overrides
            from core import load_rules_cfg, runtime_root

            _cfg2 = load_rules_cfg(runtime_root() / "rules.yaml")
            _s2 = _cfg2.get("settings") or {}
            if _s2:
                self.min_score = float(_s2.get("min_score", self.min_score))
                self.capture_method = _s2.get("capture", self.capture_method)
            _apply_pos_overrides()
        except Exception:  # noqa: BLE001
            pass
        if self.win.is_minimized():
            log("检测到游戏窗口处于最小化状态，正在恢复窗口...")
            self.win.activate()
        log(f"✅ 已连接游戏窗口，画面尺寸 {self.win.client_size()}，点击模式：{self.win.click_mode}")
        if hasattr(self.win, "build_compat_diag_line"):
            try:
                log(self.win.build_compat_diag_line(self.capture_method))
            except Exception:  # noqa: BLE001
                pass
        try:
            from core import EMULATOR_INFO

            if EMULATOR_INFO:
                log(
                    f"🖥 模拟器模式：已绑定渲染层 {EMULATOR_INFO.get('w')}×{EMULATOR_INFO.get('h')}"
                    "（不含模拟器工具栏）"
                )
                _ew, _eh = EMULATOR_INFO.get("w") or 0, EMULATOR_INFO.get("h") or 0
                if _ew and _eh and abs(_ew / _eh - 16 / 9) > 0.06:
                    log(
                        f"⚠ 模拟器画面不是 16:9（当前 {_ew}×{_eh}），识别可能不稳；"
                        "建议在 MuMu 设置里把分辨率改成 1600×900 或 1920×1080"
                    )
        except Exception:  # noqa: BLE001
            pass
        _cw, _ch = self.win.client_size()
        if not (1600 <= _cw <= 1900 and 900 <= _ch <= 1060):
            log(
                f"⚠ 当前窗口 {_cw}×{_ch} 不在推荐范围（1819×1023），识别可能不稳；"
                "可在图形界面点「📐 应用尺寸」自动调整"
            )
        log("⏳ 正在加载 OCR 模型，请稍候...")
        self.ocr = Ocr()
        # 注入给战斗控制器（长按学习技能特性需要 win + ocr）
        try:
            if self.combat_ctrl is not None:
                self.combat_ctrl.bind_runtime(self.win, self.ocr)
        except Exception:  # noqa: BLE001
            pass
        mode_desc = {
            "auto": "【原版】系统 AUTO 自动挂机战斗 + 自动点跳过过剧情（任意队伍通用）",
            "brieg": "【手操烧魂】自动检测战斗状态（F8 暂停 / F10 退出）",
        }[self.combat_mode]
        log(f"✅ 模型加载完成！当前模式：{mode_desc}")

        now = time.time()
        self.paused = False
        self.last_match_time = now
        self.last_unknown_save = 0.0
        self.last_idle_click = 0.0
        self.last_battle_hud_time = 0.0
        self.last_auto_on_click = 0.0
        self.battle_still_since = now
        self.tried_in_stage_auto = False
        self._next_sleep = self.interval

        self.repeat_name = ""
        self.repeat_count = 0
        self.prev_small: np.ndarray | None = None
        self.last_action_small: np.ndarray | None = None
        self.saw_motion_since_last_action = False
        self._key_state = {VK_F8: False, VK_F10: False}

    # ---------- 热键 ----------
    def _pressed(self, vk: int) -> bool:
        down = bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
        was = self._key_state[vk]
        self._key_state[vk] = down
        return down and not was

    def poll_hotkeys(self) -> bool:
        if self._pressed(VK_F10):
            log("⏹ 收到 F10 热键，正在退出脚本。")
            return False
        if self._pressed(VK_F8):
            self.paused = not self.paused
            if self.paused:
                log("⏸ 已手动暂停（再按一次 F8 继续运行，按 F10 退出）")
            else:
                log("▶ 继续自动过剧情！")
                now = time.time()
                self.last_match_time = now
                self.battle_still_since = now
                self.tried_in_stage_auto = False
                self.repeat_count = 0
                self.last_action_small = None
                self.saw_motion_since_last_action = True
                # 恢复时无条件清空手操状态机：避免上一轮的记忆把这一轮卡住
                if self.combat_ctrl is not None:
                    self.combat_ctrl.reset_battle()
        return True

    def pause(self, reason: str, img: np.ndarray | None = None, items: list[OcrItem] | None = None) -> None:
        self.paused = True
        log("=" * 58)
        log(f"⚠ 自动暂停：{reason}")
        log("👉 请在游戏里手动处理（如换装备/清背包/补体力），处理完后按键盘【F8】继续！")
        log("=" * 58)
        if img is not None:
            self.save_debug(img, "paused", items)
        for freq in (1000, 1300, 1000):
            try:
                winsound.Beep(freq, 220)
            except Exception:  # noqa: BLE001
                pass

    def _team_incomplete(self, img) -> bool:
        """读底部提示行「需要配置英雄的位子」→ 判断队伍还有空位。"""
        import time as _t

        now = _t.time()
        if now - getattr(self, "_hint_at", 0.0) < 0.15:
            return getattr(self, "_hint_cache", False)
        self._hint_at = now
        h, w = img.shape[:2]
        roi = img[int(h * 0.86) : int(h * 0.97), int(w * 0.20) : int(w * 0.80)]
        if roi.size == 0:
            self._hint_cache = False
            return False
        roi = cv2.resize(roi, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        saved = getattr(self.ocr, "last_dim_items", None)
        try:
            items = self.ocr.read(roi, 0.30)
        except Exception:  # noqa: BLE001
            items = []
        finally:
            self.ocr.last_dim_items = saved
        hint = any("需要配置英雄" in it.text for it in items)
        self._hint_cache = hint
        return hint

    # ---------- 准备战斗自动补位 ----------
    def _fill_step(self, img, items) -> bool:
        """严格流程：
        ① 识别空位；无 → 交给规则点「战斗开始」
        ② 有 → 先点空位（不管有没有加号）
        ③ 右侧弹出英雄列表 → 点英雄左边的加号
        ④ 回到 ①，直到没有空位；若连续 N=3 次无效（空位数未减少/超时）则按防呆放行
        """
        w, h = img.shape[1], img.shape[0]
        text = " ".join(it.text for it in items)
        # 「选择辅助英雄」页：助战默认已选好，直接点「选择队伍」进编队页，绝不补位
        if ("选择辅助英雄" in text) or ("辅助英雄队长" in text):
            self._fill_state = "idle"
            self._fill_pos = None
            self._fill_no_change = 0
            self._fill_prev_empty = None
            btn = next((it for it in items if "选择队伍" in norm(it.text)), None)
            if btn is not None:
                now_sup = time.time()
                if now_sup - float(getattr(self, "_fill_sup_at", 0.0)) > 1.2:
                    self._fill_sup_at = now_sup
                    self.win.click_ratio(btn.center[0] / w, btn.center[1] / h)
                    log("🧩 助战页 → 点击「选择队伍」")
                    return True
            return True
        # 弹窗门控（2026-11-13）：游戏弹窗（如「战斗指南」战力警告）会盖住编队页，
        # blue_empty_pads 会把弹窗中央误判成空位并连点（实测 17:17:42~50 连点 3 次，
        # 还把「确认/关闭弹窗」规则一起拦住了）。弹窗时放弃补位、清空计数，交主循环去关弹窗。
        _has_popup = any(k in text for k in ("战斗指南", "不再显示")) or any(
            clean_btn_text(it.text) in ("取消", "确认", "确定", "关闭")
            and 0.20 <= it.center[0] / w <= 0.80
            and 0.45 <= it.center[1] / h <= 0.88
            for it in items
        )
        if _has_popup:
            self._fill_state = "idle"
            self._fill_pos = None
            self._fill_count = 0
            self._fill_fail = 0
            self._fill_no_change = 0
            self._fill_prev_empty = None
            return False

        # 页面门控（2026-11-14，Gemini 方案）：只认真正的编队页——页面标题「准备战斗」在左上角，
        # 或底部有「管理队伍」/「队伍战斗力」。主线关卡选择页右下角按钮也叫「准备战斗」，
        # 旧判定只查文本会误进补位，在关卡地图上误判空位并点屏幕中心（日志 02:02~02:04 复现）。
        _norm_text = norm(text)
        _prep_header = any(
            "准备战斗" in norm(it.text) and it.center[0] / w < 0.35 and it.center[1] / h < 0.15
            for it in items
        )
        _on_prep_page = _prep_header or ("管理队伍" in _norm_text) or ("队伍战斗力" in _norm_text)
        if not _on_prep_page:
            # 补位点击可能误入敌人详情等页面：连续脱离准备战斗画面时按一次 ESC 退回
            if self._fill_state != "idle":
                now_esc = time.time()
                if now_esc - float(getattr(self, "_fill_esc_at", 0.0)) > 2.0:
                    self._fill_esc_at = now_esc
                    try:
                        self.win.press_key(27)  # VK_ESCAPE
                        log("🧩 补位后页面异常 → 按 ESC 尝试退回")
                    except Exception:  # noqa: BLE001
                        pass
            self._fill_state = "idle"
            self._fill_count = 0
            self._fill_fail = 0
            self._fill_no_change = 0
            self._fill_prev_empty = None
            return False

        now = time.time()
        if now - self._fill_last < 0.6:
            return True  # 动画冷却期内拦住主循环，防止趁机点「进行任务」

        no_change = int(getattr(self, "_fill_no_change", 0))
        if no_change >= 3 or self._fill_count >= 8 or self._fill_fail >= 4:
            return False

        pads = blue_empty_pads(img)
        slot = pads[0] if pads else None
        plus = hero_plus_btn(img)

        if now - getattr(self, "_fill_log_at", 0.0) > 1.5:
            self._fill_log_at = now
            log(
                "🧩 补位检查：空位=%s 英雄加号=%s 状态=%s 已完成=%d 失败=%d"
                % (
                    "无" if not slot else "(%.2f,%.2f)" % (slot[0], slot[1]),
                    "无" if not plus else "(%.2f,%.2f)" % (plus[0], plus[1]),
                    self._fill_state,
                    self._fill_count,
                    self._fill_fail,
                )
            )

        # 等待英雄列表：有点加号就补
        if self._fill_state == "await_list":
            if plus is not None:
                self.win.click_ratio(plus[0], plus[1])
                self._fill_count += 1
                self._fill_last = now
                self._fill_state = "idle"
                log("🧩 点击英雄加号补位（第 %d 个）" % self._fill_count)
                return True
            if now > self._fill_deadline:
                self._fill_state = "idle"
                self._fill_fail += 1
                no_change += 1
                self._fill_no_change = no_change
                self._fill_prev_empty = None
                if no_change >= 3 or self._fill_fail >= 4:
                    log("🧩 [连续 %d 次补位无响应，疑似关卡人数限制，放行]" % no_change)
                    return False
            return True  # 列表弹出前一直拦住主循环

        # 校验上一轮补位是否让空位数减少（占用槽位数增加）
        prev_empty = getattr(self, "_fill_prev_empty", None)
        if prev_empty is not None:
            if len(pads) < prev_empty:
                no_change = 0
            else:
                no_change += 1
            self._fill_no_change = no_change
            self._fill_prev_empty = None
            if no_change >= 3:
                log("🧩 [连续 %d 次补位后占用槽位数未变化，疑似关卡人数限制，放行]" % no_change)
                return False

        # 空闲态：有空位就先点空位
        if slot is None:
            return False
        self.win.click_ratio(slot[0], slot[1])
        self._fill_pos = slot
        self._fill_prev_empty = len(pads)
        self._fill_state = "await_list"
        self._fill_last = now
        self._fill_deadline = now + 2.0
        log("🧩 发现空位 → 点击空位 (%.2f,%.2f)" % (slot[0], slot[1]))
        return True

    def save_debug(self, img: np.ndarray, tag: str, items: list[OcrItem] | None = None) -> None:
        d = ROOT / "debug" / tag
        d.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%m%d_%H%M%S")
        cv2.imencode(".png", img)[1].tofile(str(d / f"{stamp}.png"))
        if items is not None:
            h, w = img.shape[:2]
            lines = [f"{it.text}\t{it.score:.2f}\t({it.center[0]/w:.3f},{it.center[1]/h:.3f})" for it in items]
            (d / f"{stamp}.txt").write_text("\n".join(lines), encoding="utf-8")

    # ---------- 主循环单步 ----------
    def step(self) -> None:
        if not self.win.is_alive():
            hwnd = find_game_window()
            if not hwnd:
                self.pause("游戏窗口已关闭，重新打开游戏后按 F8 可继续")
                return
            self.win.hwnd = hwnd

        self._next_sleep = self.interval
        now = time.time()
        # 模拟器 IPC 驱动没有 _capture_printwindow（截图走 IPC），这里必须守卫
        pw_img = (
            self.win._capture_printwindow()
            if self.capture_method in ("auto", "printwindow") and hasattr(self.win, "_capture_printwindow")
            else None
        )
        if pw_img is not None:
            _pw_ok = True
            if hasattr(self.win, "_is_valid_pw_frame"):
                _pw_ok = bool(self.win._is_valid_pw_frame(pw_img))
            else:
                _pw_ok = float(pw_img.mean()) > 3.0
            if _pw_ok:
                self._pw_verified = True
                self._pw_black_streak = 0
                img = pw_img
            elif getattr(self, "_pw_verified", False):
                self._pw_black_streak = getattr(self, "_pw_black_streak", 0) + 1
                # 短暂黑场（过场）不回退；连续 8 帧全黑说明 PrintWindow 不再可用，解锁改屏幕抓图
                if self._pw_black_streak < 8:
                    self.last_match_time = now
                    return
                self._pw_verified = False
                img = self.win.capture("screen")
            else:
                img = self.win.capture(self.capture_method)
        else:
            img = self.win.capture(self.capture_method)

        # 桌面窗口涂黑掩码只用于「屏幕抓图」路径：Win32 窗口驱动才可能把自己的窗口截进去。
        # IPC 驱动 hwnd=0，读的是安卓帧缓冲，不会被桌面窗口遮挡——2026-11-13 修：此前对 IPC 帧
        # 也套了这段掩码，把桌面窗口矩形当图片坐标涂黑，右下角出现纯黑块（v1.2.1 回归）。
        if getattr(self.win, "hwnd", 0) and not getattr(self, "_pw_verified", False):
            try:
                import os as _os

                import win32gui as _wg
                import win32process as _wp

                from core import _parent_pid

                _pids = {_os.getpid(), _parent_pid(_os.getpid())} - {0}
                _gx, _gy = self.win.client_origin_on_screen()
                _gw, _gh = self.win.client_size()

                def _mask_cb(hwnd, _lparam):
                    try:
                        if not _wg.IsWindowVisible(hwnd) or _wg.IsIconic(hwnd):
                            return True
                        _, pid = _wp.GetWindowThreadProcessId(hwnd)
                        if pid in _pids and hwnd != self.win.hwnd:
                            l, t, r, b = _wg.GetWindowRect(hwnd)
                            x1, y1 = max(0, l - _gx), max(0, t - _gy)
                            x2, y2 = min(_gw, r - _gx), min(_gh, b - _gy)
                            if x2 > x1 and y2 > y1:
                                img[y1:y2, x1:x2] = 0
                    except Exception:  # noqa: BLE001
                        pass
                    return True

                _wg.EnumWindows(_mask_cb, None)
            except Exception:  # noqa: BLE001
                pass
        # 纯黑加载过渡帧或显示器息屏状态：静默等待，不计入超时也不做 OCR
        if float(img.mean()) < 2.0:
            self.last_match_time = now
            return

        items = self.ocr.read(img, self.min_score)

        small = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (64, 36)).astype(np.int16)
        frame_diff = 999.0 if self.prev_small is None else float(np.abs(small - self.prev_small).mean())
        self.prev_small = small
        if frame_diff >= 18.0:
            # 两回合之间发生了技能释放或敌方攻击动画，用于区分多回合Boss战与窗口被遮挡卡死
            self.saw_motion_since_last_action = True

        allow_dead_end = (now - self.battle_still_since) > 3.5 and frame_diff < 6.0
        decision = analyze_frame(
            img=img,
            items=items,
            rules=self.rules,
            global_forbid=self.global_forbid,
            default_max_len=self.default_max_len,
            enable_auto_check=self.enable_auto_check,
            now=now,
            allow_dead_end_compass=allow_dead_end,
            manual_combat=self.manual_combat,
            combat_ctrl=self.combat_ctrl,
        )

        if decision.get("in_battle"):
            self.last_battle_hud_time = now

        # 双通道：亮场没认出战斗，但暗场（被遮罩压暗）认得出 → 说明是弹窗/暂停菜单，不是真离开战斗
        dim_items = getattr(self.ocr, "last_dim_items", None) or []
        # 通关结算画面会保留被压暗的波次数字（如 2/2），不能据此认为「还在战斗」
        bright_text = " ".join(it.text for it in items)
        is_result_screen = any(
            k in bright_text for k in ("CLEAR", "关卡任务", "闯关成功", "获得的道具", "战斗结果", "胜利")
        )
        if (
            dim_items
            and not is_result_screen
            and not decision.get("in_battle")
            and has_battle_hud(img, dim_items)
        ):
            self.last_match_time = now
            self.last_battle_hud_time = now
            if now - getattr(self, "_last_mask_log", 0.0) > 5.0:
                log("🛡 弹窗遮挡 → 暂停点击，关闭后自动继续")
                self._last_mask_log = now
            if getattr(self, "_mask_since", None) is None:
                self._mask_since = now
            elif now - self._mask_since > 20.0:
                self._mask_since = None
                self.pause("弹窗/暂停菜单已持续 20 秒，请在游戏里关掉它后按 F8 继续", img, items)
            return
        self._mask_since = None

        # 准备战斗：有空位就先补位，补不上就正常出战
        try:
            if self._fill_step(img, items):
                return
        except Exception:  # noqa: BLE001
            pass

        if decision["type"] == "key":
            log(f"⌨ {decision.get('desc', '发送按键')}")
            try:
                self.win.press_key(int(decision.get("vk", 27)))
            except Exception:  # noqa: BLE001
                pass
            self.last_match_time = now
            self._next_sleep = 0.6
            return

        if decision["type"] == "pause":
            self.pause(decision["reason"], img, items)
            return

        if decision["type"] in ("click_ratio", "click_sequence"):
            if decision.get("is_turn_on_auto") and (now - self.last_auto_on_click) < 2.5:
                self.last_battle_hud_time = now
                self.last_match_time = now
                return
            if decision.get("is_turn_on_auto"):
                self.last_auto_on_click = now
            rule: Rule = decision["rule"]
            is_combat_click = bool(decision.get("is_combat"))

            # 对比上一次执行动作时的画面（多回合战斗若中间经历过技能动画 saw_motion_since_last_action，则重置计数）
            action_changed = (
                self.last_action_small is None
                or float(np.abs(small - self.last_action_small).mean()) > 14.0
                or (is_combat_click and self.saw_motion_since_last_action)
            )
            if rule.name == self.repeat_name and not action_changed:
                self.repeat_count += 1
            else:
                self.repeat_name, self.repeat_count = rule.name, 1

            # 助战选择页特殊兜底：若默认没选中好友导致点“选择队伍”没反应，自动点第一位好友
            all_text = norm("".join(it.text for it in items))
            if (
                self.repeat_count == 2
                and decision.get("target_text") == "选择队伍"
                and ("选择辅助英雄" in all_text or "辅助英雄" in all_text)
            ):
                log("检测到尚未选中助战英雄 → 自动选择列表第 1 位好友")
                self.win.click_ratio(0.40, 0.32)
                time.sleep(0.35)

            # 跳过剧情或手动二段点技能时，允许更高点击上限
            if "跳过" in rule.name:
                limit = max(self.stuck_repeat, 15)
            elif is_combat_click:
                # 用户要求：技能没放出来就继续重复点，不要几次就停
                limit = max(self.stuck_repeat, 40)
            else:
                limit = self.stuck_repeat
            if self.repeat_count >= limit:
                self.save_debug(img, "stuck", items)
                self.pause(
                    f"「{rule.name}」连续点击 {self.repeat_count} 次画面无变化（请检查窗口是否被遮挡或未以管理员运行）",
                    None,
                )
                return

            if not decision.get("is_aux_click") and not is_combat_click:
                rule.last_fire = now
            self.last_match_time = now
            self.last_action_small = small.copy()
            self.saw_motion_since_last_action = False
            self.battle_still_since = now
            self.tried_in_stage_auto = False
            if decision.get("fast_followup"):
                self._next_sleep = 0.09
            elif decision["type"] == "click_sequence":
                self._next_sleep = 0.20
            elif is_combat_click:
                self._next_sleep = 0.15

            log(f"🖱 {decision['desc']}")
            if decision["type"] == "click_sequence":
                gap = float(decision.get("step_gap", 0.16))
                for idx, (pt, clks) in enumerate(decision["steps"]):
                    if idx > 0:
                        time.sleep(gap)
                    # 战斗内的技能点击用短按，保证连点/双击能被游戏识别
                    self.win.click_ratio(
                        pt[0], pt[1], clicks=int(clks), quick=is_combat_click,
                        click_gap=self.combat_click_gap if is_combat_click else None,
                    )
            else:
                pos: tuple[float, float] = decision["pos"]
                clicks = int(decision.get("clicks", 1))
                self.win.click_ratio(
                    *pos, clicks=clicks, quick=is_combat_click,
                    click_gap=self.combat_click_gap if is_combat_click else None,
                )
            return

        # ---------------- 当前没有任何规则命中 ----------------
        in_battle = bool(decision.get("in_battle"))
        in_labyrinth = bool(decision.get("in_labyrinth"))
        if decision.get("combat_wait"):
            self.last_battle_hud_time = now
            self.last_match_time = now
            self.battle_still_since = now
            self._next_sleep = 0.12
            return

        if in_battle:
            self.last_battle_hud_time = now
            self.last_match_time = now  # 战斗/跑图中属于正常推进，不计入未知界面空闲
            if frame_diff >= 3.5:
                self.battle_still_since = now
                self.tried_in_stage_auto = False
            else:
                still_secs = now - self.battle_still_since
                # 迷宫探索走廊静止（或非手动战术模式静止）时，自动点击右上角开启寻路/自动战斗
                # 2026-11-09：不再自动点右上角 AUTO（曾误触暂停按钮）。
                # 战斗画面 5 秒毫无变化 → 直接暂停，交给人判断。
                if still_secs > 5.0:
                    self.pause(
                        "战斗画面 5 秒没有任何变化，可能已弹窗/卡住。请确认游戏处于战斗界面后按 F8 继续",
                        img,
                        items,
                    )
            return

        # 刚从战斗 HUD 切入角色/Boss 大招动画（S3 特写会隐藏 UI 约 5~13 秒），不乱点屏幕
        if now - self.last_battle_hud_time < 15.0:
            return

        idle = now - self.last_match_time

        # 如果画面正在播放动态视频（如全屏 CG 动画），重置静态超时但仍轻点屏幕以唤出右上角“跳过”按钮
        # 动态视频，或「几乎没文字 + 很暗」的剪影过场（视频静止帧）都按过场处理
        looks_cutscene = frame_diff > 10.0 or (not items and float(img.mean()) < 60.0)
        if looks_cutscene:
            if self.idle_click_after and idle > self.idle_click_after and now - self.last_idle_click > self.idle_click_after:
                if frame_diff > 10.0:
                    log("🎬 检测到动态过场演出 → 长按画面尝试唤出「跳过」按钮")
                else:
                    log("🎬 检测到无文字过场画面 → 长按尝试唤出「跳过」按钮")
                self.win.press_ratio(self.idle_click_at[0], self.idle_click_at[1], seconds=self.cutscene_press_seconds)
                self.last_idle_click = now
            return

        if self.save_unknown_after and idle > self.save_unknown_after and now - self.last_unknown_save > 30:
            self.save_debug(img, "unknown", items)
            self.last_unknown_save = now
            log(f"📸 已 {idle:.0f} 秒未识别到按钮，当前画面已自动保存到 debug/unknown 文件夹（可用于补充校正）")

        if self.auto_pause_unknown_after and idle > self.auto_pause_unknown_after:
            self.pause(
                f"连续 {int(idle)} 秒未识别到可操作按钮（请确认已进入冒险章节地图界面）",
                img,
                items,
            )
            return

        if self.idle_click_after and idle > self.idle_click_after and now - self.last_idle_click > self.idle_click_after:
            log("💬 轻点屏幕下方推进对话/结算")
            self.win.click_ratio(*self.idle_click_at)
            self.last_idle_click = now

    def run(self) -> None:
        banner_mode = {
            "auto": "【原版】系统 AUTO 自动挂机战斗 + 自动点跳过过剧情（任意队伍通用）",
            "brieg": "【手操烧魂】自动检测战斗状态（F8 暂停 / F10 退出）",
        }[self.combat_mode]
        print("=" * 66)
        print("  第七史诗（Steam 简中版）自动过剧情助手")
        print(f"  当前运行版本：{banner_mode}")
        print("  快捷键：【F8】暂停 / 继续      【F10】退出程序")
        print("  提示：运行期间请勿最小化或遮挡游戏窗口，尽量不要动鼠标")
        print("=" * 66)
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
                self.step()
            except InputBlockedError as e:
                log("=" * 58)
                log(f"❌ 无法模拟鼠标：{e}")
                log("👉 解决：关闭本窗口，直接双击文件夹里的 .bat 启动；")
                log("   不要从 AI 助手/沙箱/受限终端中启动，也不要锁屏或用远程桌面。")
                log("=" * 58)
                for freq in (1000, 1300, 1000):
                    try:
                        winsound.Beep(freq, 220)
                    except Exception:  # noqa: BLE001
                        pass
                return
            except Exception as e:  # noqa: BLE001
                log(f"⚠ 本轮检测出现异常（将自动重试）：{e!r}")
                self._next_sleep = self.interval
            end = time.time() + self._next_sleep
            while time.time() < end:
                if not self.poll_hotkeys():
                    return
                time.sleep(0.05)


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
    """若非管理员，自动弹出 Windows UAC 提权运行新窗口；成功拉起新窗口返回 True。

    注意：Low 完整性进程（沙箱/受限启动）里 runas 得到的仍是 Low，无法借此提权，
    因此不做无意义的重启，直接交给启动自检定位启动来源。
    """
    if is_admin() or "--no-elevate" in sys.argv or "--elevated" in sys.argv:
        return False
    script = str(Path(__file__).resolve())
    extra_args = " ".join(f'"{a}"' for a in sys.argv[1:])
    # 保留 -s / -E 隔离参数，确保分享版便携 Python 提权后依然不受对方电脑上其他 Python 环境干扰
    py_flags = ("-s " if sys.flags.no_user_site else "") + ("-E " if sys.flags.ignore_environment else "")
    params = f'{py_flags}"{script}" --elevated {extra_args}'.strip()
    ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, str(ROOT), 1)
    if int(ret) <= 32:
        print(f"⚠ 自动提权失败（code={int(ret)}），将按当前权限继续（可能无法控制鼠标）", flush=True)
        return False
    return True


def _resolve_mode_override() -> str | None:
    if "--auto" in sys.argv:
        return "auto"
    if "--brieg" in sys.argv:
        return "brieg"
    if "--shop" in sys.argv:
        return "shop"
    if "--chain" in sys.argv:
        return "chain"
    if "--theater" in sys.argv:
        return "theater"
    if "--select" in sys.argv:
        print("=" * 68)
        print("  第七史诗 自动化助手 —— 请选择要启动的程序：")
        print()
        print("    [1] 原版：系统 AUTO 自动挂机战斗 + 自动点跳过（任意队伍通用）")
        print("    [2] 手操烧魂：自动检测战斗状态")
        print("    [3] 秘密商店：自动刷新商店购买【圣约书签 & 神秘奖牌】（可设剩余天空石停止）")
        print("    [4] 串联版：秘密商店刷完 → 自动关闭商店 → 打开主线 → 布里克强攻过剧情")
        print("    [5] 月光剧场：自动观影（剧情点击 + 战斗开AUTO + 买票/用票 + 换片）")
        print("=" * 68)
        while True:
            ans = input("请输入数字 1 / 2 / 3 / 4 / 5 后按回车（默认 1）：").strip()
            if ans in ("", "1"):
                return "auto"
            if ans == "2":
                return "brieg"
            if ans == "3":
                return "shop"
            if ans == "4":
                return "chain"
            if ans == "5":
                return "theater"
            print("输入无效，请输入 1、2、3、4 或 5。")
    return None


def main() -> int:
    ensure_utf8_console("第七史诗 自动过剧情助手 [F8 暂停/继续 | F10 退出]")
    if try_elevate():
        return 0

    elevated_window = "--elevated" in sys.argv
    try:
        mode_override = _resolve_mode_override()
        if mode_override == "shop":
            import shop

            return shop.run_shop_flow(elevated_window=elevated_window)
        if mode_override == "chain":
            import chain

            return chain.run_chain_flow(elevated_window=elevated_window)
        if mode_override == "theater":
            import theater

            return theater.run_theater_flow(elevated_window=elevated_window)
        if mode_override == "auto":
            ensure_utf8_console("第七史诗 自动过剧情 [原版：AUTO自动挂机+点跳过 | F8暂停 F10退出]")
        elif mode_override == "brieg":
            ensure_utf8_console("第七史诗 自动过剧情 [手操烧魂 | F8暂停 F10退出]")

        if not is_admin():
            log("⚠ 提示：当前未授予管理员权限。若游戏内自动点击无反应，请重新双击启动脚本并在弹窗点「是」。")
        cfg_path = ROOT / "rules.yaml"
        if not cfg_path.exists():
            raise SystemExit(f"❌ 找不到配置文件：{cfg_path}")
        from core import load_rules_cfg

        cfg = load_rules_cfg(cfg_path)
        Bot(cfg, mode_override=mode_override).run()
        return 0
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
