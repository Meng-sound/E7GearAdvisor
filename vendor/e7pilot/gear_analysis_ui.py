"""装备分析看板（只读离线可视化）：复用 stats_ui 深色主题渲染 gear_analysis 分析结果。"""
from __future__ import annotations

import json
import math
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime
from pathlib import Path
from tkinter import filedialog
from typing import Any, Callable

import gear_analysis
from stats_ui import F, T, rounded

# ==============================================================================
# 1. 面向玩家的 UI 文案字典（初稿按《UI文案清单》集中管理，审稿只改此处不动逻辑）
# ==============================================================================
UI_TEXTS: dict[str, Any] = {
    # U1–U3: 入口与窗口
    "entry_btn": "📈 装备分析",
    "title": "装备分析看板",
    "open_error": "打不开装备分析窗口：{exc}",
    # U4–U8: 文件栏
    "file_label": "扫描文件",
    "btn_refresh": "刷新",
    "btn_browse": "浏览…",
    "browse_dialog_title": "选择装备扫描 JSON 文件",
    "browse_filetype_label": "JSON 文件",
    "summary": "共 {total} 件 · 有效 {valid} 件 · 90级 {lv90} / 88级 {lv88} / 85级 {lv85} / ≤80级 {lv80}",
    # U9–U10: 警示与画像
    "warn_title": "扫描提示",
    "profile_title": "账号画像",
    # U11–U15: 六维雷达 / 流派 / 关键指标
    "radar_title": "账号六维（0–100）",
    "radar_idle_hint": "悬停或点击顶点查看：质量分 / 深度分 / 部位 Top-4",
    "radar_detail_line1": "质量分 {q} · 深度分 {d}",
    "radar_detail_line2": "部位 Top-4：{parts}",
    "arch_title": "流派契合度",
    "metrics_title": "关键指标",
    # U16a–U16l: 关键指标标签
    "metrics": {
        "spd17_all": "17+ 速（含活动）",
        "spd17_craft": "17+ 速（手工）",
        "spd18_all": "18+ 速（含活动）",
        "spd18_craft": "18+ 速（手工）",
        "spd21_all": "21+ 速（含活动）",
        "spd21_craft": "21+ 速（手工）",
        "spd23_all": "23+ 速（含活动）",
        "spd23_craft": "23+ 速（手工）",
        "spd25_all": "25+ 速（含活动）",
        "spd25_craft": "25+ 速（手工）",
        "craft_pct": "自刷85/90占比",
        "event_pct": "活动88占比",
        "purity_pct": "90+面板自洽率",
        "mismatched": "歪胚件数",
        "eq_avg_gs": "已穿戴均裸分",
        "idle_high": "闲置高分",
    },
    # 速度件列表（点击关键指标的速度计数后弹出）
    "speed_items": {
        "title": "{threshold}+ 速装备 · {scope}（共 {count} 件）",
        "scope_all": "含活动",
        "scope_craft": "手工",
        "headers": ("ID", "部位", "名称", "套装", "速度", "等级", "已穿戴"),
        "empty": "没有符合条件的装备",
        "hint": "点击一行查看装备详情",
        "close": "关闭",
    },
    # U17–U19: 下方 3 个分段页
    "tabs": {
        "sandbox": "极限配装与套装容量",
        "matrix": "右三件与 6×6 短板",
        "actions": "金矿与低效清单",
    },
    # U20–U26: Tab1 沙盘与套装
    "sandbox_title": "虚拟极限配装沙盘",
    "sandbox_ranks": ("一速", "二速", "三速"),
    "sandbox_spd_fmt": "{spd} 速",
    "sandbox_meta_fmt": "含活动88装 {ev} 件 · ID: {ids}",
    "sandbox_craft_title": "纯手工一速对照",
    "sandbox_empty": "缺少部位，无法推算沙盘（缺：{parts}）",
    "set_cap_title": "套装成套容量",
    "set_cap_headers": ("套装", "件数", "左/右", "可凑套数", "均有效分", "提示"),
    "set_notes_title": "2026 新增套装效果",
    # U27–U31: Tab2 右三件与热力
    "right_matrix_title": "右三件稀缺矩阵",
    "right_matrix_headers": ("部位", "主属性 / 档位", "件数", "均有效分"),
    "heatmap_title": "6×6 木桶短板热力",
    "cell_na": "—",
    "weak_spot_label": "短板格",
    "heatmap_summary": "{label}（<{thresh}）：共 {count} 格 · 最弱：{items}",
    "heatmap_none_weak": "{label}（<{thresh}）：0 格",
    # U32–U36: Tab3 行动清单
    "goldmine_title": "待重铸 85 潜力金矿（共 {n} 件）",
    "goldmine_headers": ("ID", "部位", "名称", "套装", "速度", "最佳维度", "有效分", "面板分"),
    "ineff_title": "已穿戴低效 / 歪胚（共 {n} 件）",
    "ineff_headers": ("ID", "部位", "名称", "等级", "裸分", "最佳维度", "有效分", "歪胚"),
    "list_limit": "仅展示前 {shown} 件（共 {total} 件）",
    "list_empty": "当前无符合条件的装备",
    # 装备详情弹窗（Tab3 行点击）
    "detail": {
        "title": "装备详情",
        "close": "关闭",
        "missing": "原始扫描数据里找不到该装备（id={id}），可能来自旧版本 JSON。",
        "field_main": "主属性",
        "field_subs": "副属性",
        "field_set": "套装",
        "field_score": "面板分数",
        "field_raw_gs": "裸分",
        "field_best": "最佳维度",
        "field_equipped": "已穿戴",
        "field_mismatch": "歪胚",
        "field_effective": "有效分",
        "pct_inferred": "（%兜底）",
        "yes": "是",
        "no": "否",
    },
    # U55–U62: 战备体检（Phase 1，下个小版本）
    "readiness": {
        "card_title": "战备",
        "index_label": "战备综合指数",
        "unit": "/ 1000",
        "knife": "尖刀上限",
        "bench": "达标板凳",
        "quality": "装备成色",
        "formula_hint": "查看说明",
        "badge_lower": "未扫到底 · 下限参考",
        "insufficient": "样本不足一百件",
        "formula_title": "战备综合指数 · 说明",
        "formula_body": (
            "战备综合指数（0–1000）：综合衡量账号的\n"
            "“上限、厚度与毕业度”\n\n"
            "尖刀（40%）：你最强的两个方向有多能打\n"
            "（看六维配装上限）；\n\n"
            "板凳（40%）：达标主力装有多少件\n"
            "（自刷算 1 件，活动 88 装算半件，\n"
            "160 当量封顶）；\n\n"
            "成色（20%）：一半看高分装有没有歪词条注水，\n"
            "一半看全号 90 级重铸毕业比例。\n\n"
            "扫描不足 100 件不出总分；未扫到背包底端时，\n"
            "当前分数仅作下限参考。"
        ),
    },
    # U63–U67: 导出装备数据（用于收集/对齐大佬数据）
    "export": {
        "btn": "📤 导出",
        "dialog_title": "导出装备数据",
        "success": "已导出装备数据（{size} KB）：\n{path}",
        "error": "导出失败：{reason}",
        "empty": "当前没有可导出的扫描数据，请先扫描或加载一个 JSON。",
        "filetype": "JSON 文件",
    },
    # U8, U37–U42: 清理旧装备数据
    "cleanup": {
        "btn": "🗑 清理旧装备数据",
        "title": "清理旧装备数据",
        "confirm": "将删除 {n} 个旧扫描文件（共 {mb} MB），保留最新 1 份扫描结果与 1 份 OCR 详情。删除后不可恢复，是否继续？",
        "ok": "删除",
        "cancel": "取消",
        "ack": "确定",
        "done": "已清理 {n} 个文件，释放 {mb} MB。",
        "partial": "有 {k} 个文件删除失败（可能被占用），已跳过。",
        "empty": "没有需要清理的旧数据。",
    },
    # U43–U46: 空态 / 错误 / 小标签
    "empty_no_scan": "还没有扫描记录。请先点「🔍 装备扫描」生成数据。",
    "load_error": "读取扫描文件失败：{reason}",
    "level_short": {
        "90": "90",
        "88": "88",
        "85": "85",
        "le80": "≤80",
    },
    "yes_no": ("是", "否"),
    "dropdown_arrow": "▾",
}

# ==============================================================================
# 2. 布局与绘图尺寸常量（颜色统一引用 stats_ui.T，不写硬编码色值）
# ==============================================================================
UI_CONST: dict[str, Any] = {
    "win_size": "1080x820",
    "min_w": 1000,
    "min_h": 760,
    "pad_x": 14,
    "card_r": 12,
    "card_gap": 10,
    "scrollbar_w": 8,
    "dropdown_w": 265,
    "dropdown_max_rows": 10,
    "radar_w": 456,
    "arch_min_h": 182,
    "metrics_min_h": 232,
    "radar_rings": (20, 40, 60, 80, 100),
    "radar_hit_r": 26,
    "tab1_left_w": 365,
    "tab2_left_w": 400,
    "table_row_min_h": 27,
    "table_hdr_min_h": 30,
    "heatmap_cell_min_h": 34,
    "heatmap_strong_gs": 60.0,
    "scan_json_glob": "装备扫描_*.json",
    "scan_export_glob": "E7Pilot_装备数据_*.json",
    "scan_ocr_glob": "装备扫描_OCR详情_*.txt",
    # 列规格: (权重, 最小像素宽, 对齐)
    "set_cap_cols": (
        (14, 80, "w"),
        (7, 40, "e"),
        (8, 50, "center"),
        (9, 56, "e"),
        (10, 60, "e"),
        (52, 200, "w"),
    ),
    "right_mat_cols": (
        (18, 56, "w"),
        (36, 100, "w"),
        (20, 56, "e"),
        (26, 72, "e"),
    ),
    "goldmine_cols": (
        (7, 46, "e"),
        (9, 56, "center"),
        (28, 150, "w"),
        (15, 92, "w"),
        (9, 52, "e"),
        (13, 84, "w"),
        (10, 64, "e"),
        (9, 60, "e"),
    ),
    "speed_cols": (
        (7, 40, "e"),
        (10, 56, "w"),
        (28, 150, "w"),
        (16, 100, "w"),
        (9, 50, "e"),
        (9, 50, "center"),
        (9, 56, "center"),
    ),
    "ineff_cols": (
        (7, 46, "e"),
        (9, 56, "center"),
        (29, 150, "w"),
        (9, 54, "center"),
        (10, 62, "e"),
        (15, 86, "w"),
        (11, 64, "e"),
        (10, 56, "center"),
    ),
}


# ==============================================================================
# 3. 数据目录、扫描文件发现与清理纯函数
# ==============================================================================
def get_debug_dir() -> Path:
    """延迟导入 core.runtime_root，避免模块顶层触发 cv2/mss/win32 重依赖。"""
    try:
        from core import runtime_root

        return Path(runtime_root()) / "debug"
    except Exception:  # noqa: BLE001
        return Path(__file__).resolve().parent / "debug"


def list_scan_json_files(debug_dir: Path | None = None) -> list[Path]:
    """按文件名（时间戳）倒序返回 debug 目录下的装备扫描 JSON 与导出包。"""
    d = debug_dir if debug_dir is not None else get_debug_dir()
    if not d.is_dir():
        return []
    files = [
        p
        for pattern in (UI_CONST["scan_json_glob"], UI_CONST["scan_export_glob"])
        for p in d.glob(pattern)
        if p.is_file()
    ]
    files = list(dict.fromkeys(files))
    files.sort(key=lambda p: p.name, reverse=True)
    return files


def plan_cleanup_files(debug_dir: Path | None = None) -> tuple[list[Path], int]:
    """仅在 debug 目录内规划清理目标：扫描 JSON 与 OCR 详情 txt 各自保留最新 1 份。"""
    d = debug_dir if debug_dir is not None else get_debug_dir()
    if not d.is_dir():
        return [], 0
    to_delete: list[Path] = []
    for pattern in (UI_CONST["scan_json_glob"], UI_CONST["scan_ocr_glob"]):
        matched = sorted(
            (p for p in d.glob(pattern) if p.is_file()),
            key=lambda p: p.name,
            reverse=True,
        )
        to_delete.extend(matched[1:])
    total_bytes = 0
    for p in to_delete:
        try:
            total_bytes += p.stat().st_size
        except OSError:
            pass
    return to_delete, total_bytes


def execute_cleanup(targets: list[Path]) -> tuple[int, int, int]:
    """逐个删除旧文件；单个异常记失败数、不中断。返回 (成功数, 释放字节, 失败数)。"""
    deleted, freed_bytes, failed = 0, 0, 0
    for p in targets:
        try:
            sz = p.stat().st_size
        except OSError:
            sz = 0
        try:
            p.unlink()
            deleted += 1
            freed_bytes += sz
        except OSError:
            failed += 1
    return deleted, freed_bytes, failed


# ==============================================================================
# 4. 深色通用小组件（零 ttk 白底、DPI 像素自适应）
# ==============================================================================
def _apply_dark_titlebar(win: tk.Misc) -> None:
    try:
        import prts

        prts.enable_dark_titlebar(win, dark=True)
    except Exception:  # noqa: BLE001
        pass


def _ellipsize(text: str, font_obj: tkfont.Font, max_px: int) -> str:
    """按实际 DPI 像素宽度裁剪过长文本，防止长文案挤压溢出。"""
    if max_px <= 12 or not text:
        return ""
    if font_obj.measure(text) <= max_px:
        return text
    ell = "…"
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if font_obj.measure(text[:mid] + ell) <= max_px:
            lo = mid
        else:
            hi = mid - 1
    return (text[:lo] + ell) if lo > 0 else ell


def _tier_color(tier_text: str) -> str:
    """4 档徽章配色（新口径 T1 最强 → T4 最弱）。"""
    if tier_text.startswith("T1"):
        return T["gold"]
    if tier_text.startswith("T2"):
        return T["purple"]
    if tier_text.startswith("T3"):
        return T["blue"]
    return T["sub"]


class DarkVScrollbar(tk.Canvas):
    """纯 Canvas 深色滚动条（内容未超屏时自动隐去滑块，杜绝原生白底）。"""

    def __init__(self, parent: tk.Misc, command: Callable[..., Any]) -> None:
        w = UI_CONST["scrollbar_w"]
        super().__init__(parent, width=w, bg=T["bg"], highlightthickness=0, bd=0)
        self._cmd = command
        self._first = 0.0
        self._last = 1.0
        self._hover = False
        self._drag_offset = 0.0
        self.bind("<Configure>", lambda _e: self._redraw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)

    def set(self, first: float | str, last: float | str) -> None:
        self._first = max(0.0, min(1.0, float(first)))
        self._last = max(0.0, min(1.0, float(last)))
        self._redraw()

    def _on_enter(self, _e: tk.Event) -> None:
        self._hover = True
        self._redraw()

    def _on_leave(self, _e: tk.Event) -> None:
        self._hover = False
        self._redraw()

    def _on_press(self, e: tk.Event) -> None:
        if self._last - self._first >= 0.999:
            return
        h = max(1, self.winfo_height())
        y1 = self._first * h
        y2 = max(y1 + 24, self._last * h)
        if y1 <= e.y <= y2:
            self._drag_offset = e.y - y1
        else:
            self._drag_offset = (y2 - y1) / 2.0
            self._move_to(e.y - self._drag_offset)

    def _on_drag(self, e: tk.Event) -> None:
        if self._last - self._first >= 0.999:
            return
        self._move_to(e.y - self._drag_offset)

    def _move_to(self, top_px: float) -> None:
        h = max(1, self.winfo_height())
        span = max(0.02, self._last - self._first)
        frac = max(0.0, min(1.0 - span, top_px / h))
        self._cmd("moveto", frac)

    def _redraw(self) -> None:
        self.delete("all")
        if self._last - self._first >= 0.999:
            return
        w = max(4, self.winfo_width())
        h = max(24, self.winfo_height())
        y1 = int(self._first * h) + 2
        y2 = max(y1 + 24, int(self._last * h) - 2)
        col = T["sub"] if self._hover else T["btn"]
        self.create_rectangle(1, y1, w - 1, min(h - 2, y2), fill=col, outline=T["border"])


class DarkTabBar(tk.Frame):
    """stats_ui.Segmented 风格深色分段切换条（Radiobutton indicatoron=False）。"""

    def __init__(
        self,
        parent: tk.Misc,
        options: list[tuple[str, str]],
        default: str,
        command: Callable[[str], None],
    ) -> None:
        super().__init__(parent, bg=T["card"], padx=3, pady=3)
        self.var = tk.StringVar(value=default)
        self._cmd = command
        self._btns: dict[str, tk.Radiobutton] = {}
        for text, key in options:
            rb = tk.Radiobutton(
                self,
                text=text,
                value=key,
                variable=self.var,
                indicatoron=False,
                bg=T["card"],
                fg=T["sub"],
                selectcolor=T["active"],
                activebackground=T["btn"],
                activeforeground=T["text"],
                bd=0,
                font=F["title"],
                padx=16,
                pady=5,
                cursor="hand2",
                command=self._on_select,
            )
            rb.pack(side="left", padx=2)
            self._btns[key] = rb
        self._sync_colors()

    def _on_select(self) -> None:
        self._sync_colors()
        self._cmd(self.var.get())

    def _sync_colors(self) -> None:
        cur = self.var.get()
        for k, rb in self._btns.items():
            rb.configure(fg=(T["text"] if k == cur else T["sub"]))


class CanvasTable(tk.Canvas):
    """自适应深色圆角表格（替代 ttk.Treeview，无白底、按列宽自动省略防挤压）。"""

    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        headers: tuple[str, ...],
        col_specs: tuple[tuple[int, int, str], ...],
        rows: list[list[tuple[str, str]]],
        f_title: tkfont.Font,
        f_body: tkfont.Font,
        footer_note: str = "",
        empty_text: str = "",
        on_row_click: Callable[[int], None] | None = None,
    ) -> None:
        self._title = title
        self._headers = headers
        self._col_specs = col_specs
        self._rows = rows
        self._ft = f_title
        self._fb = f_body
        self._footer = footer_note
        self._empty_text = empty_text or UI_TEXTS["list_empty"]
        self._on_row_click = on_row_click
        self._row_hits: list[tuple[int, int]] = []

        lh_t = f_title.metrics("linespace")
        lh_b = f_body.metrics("linespace")
        self._top_h = lh_t + 20
        self._hdr_h = max(UI_CONST["table_hdr_min_h"], lh_b + 12)
        self._row_h = max(UI_CONST["table_row_min_h"], lh_b + 10)
        self._foot_h = (lh_b + 12) if footer_note else 10
        body_rows = max(1, len(rows))
        total_h = self._top_h + self._hdr_h + body_rows * self._row_h + self._foot_h

        super().__init__(parent, height=total_h, bg=T["bg"], highlightthickness=0)
        self._total_h = total_h
        self.bind("<Configure>", lambda _e: self._redraw())
        if on_row_click is not None:
            self.bind("<Button-1>", self._on_click)
            self.bind("<Motion>", self._on_motion)
            self.bind("<Leave>", lambda _e: self.configure(cursor=""))

    def _compute_col_x(self, inner_w: int) -> list[tuple[int, int, str]]:
        # 列最小宽按"表头/单元格实测像素"动态计算，避免 150% DPI 下固定像素宽不够导致截断
        pads = 16
        min_ws: list[int] = []
        for ci, (_w, min_w, _align) in enumerate(self._col_specs):
            need = 0
            if ci < len(self._headers):
                need = max(need, self._fb.measure(self._headers[ci]))
            for r_cells in self._rows:
                if ci < len(r_cells):
                    need = max(need, self._fb.measure(r_cells[ci][0]))
            min_ws.append(max(min_w, int(need) + pads))

        weights = [w for w, _, _ in self._col_specs]
        total_weight = max(1, sum(weights))
        if inner_w >= sum(min_ws):
            extra = inner_w - sum(min_ws)
            raw_ws = [mw + int(extra * w / total_weight) for mw, w in zip(min_ws, weights)]
        else:
            scale = inner_w / max(1, sum(min_ws))
            raw_ws = [max(24, int(mw * scale)) for mw in min_ws]
        if raw_ws:
            raw_ws[-1] += inner_w - sum(raw_ws)

        out: list[tuple[int, int, str]] = []
        cur_x = 14
        for rw, (_, _, align) in zip(raw_ws, self._col_specs):
            out.append((cur_x, rw, align))
            cur_x += rw
        return out

    def _redraw(self) -> None:
        self.delete("all")
        self._row_hits = []
        w = max(260, self.winfo_width())
        h = self._total_h
        rounded(self, 1, 1, w - 1, h - 1, r=UI_CONST["card_r"], fill=T["card"], outline=T["border"])
        self.create_text(14, self._top_h // 2 + 2, text=self._title, fill=T["text"], font=F["title"], anchor="w")

        cols = self._compute_col_x(w - 28)
        hy1 = self._top_h
        hy2 = hy1 + self._hdr_h
        self.create_rectangle(10, hy1, w - 10, hy2, fill=T["btn"], outline="")

        for hdr, (cx, cw, align) in zip(self._headers, cols):
            txt = _ellipsize(hdr, self._fb, cw - 8)
            tx = cx + 4 if align == "w" else (cx + cw - 4 if align == "e" else cx + cw // 2)
            self.create_text(tx, (hy1 + hy2) // 2, text=txt, fill=T["sub"], font=F["body"], anchor=align)

        ry = hy2
        if not self._rows:
            self.create_text(
                w // 2,
                ry + self._row_h // 2,
                text=self._empty_text,
                fill=T["sub"],
                font=F["body"],
            )
            ry += self._row_h
        else:
            for idx, r_cells in enumerate(self._rows):
                ny = ry + self._row_h
                self._row_hits.append((ry, ny))
                if idx > 0:
                    self.create_line(12, ry, w - 12, ry, fill=T["border"])
                for (val_str, color), (cx, cw, align) in zip(r_cells, cols):
                    txt = _ellipsize(val_str, self._fb, cw - 8)
                    tx = cx + 4 if align == "w" else (cx + cw - 4 if align == "e" else cx + cw // 2)
                    self.create_text(tx, (ry + ny) // 2, text=txt, fill=color, font=F["body"], anchor=align)
                ry = ny

        if self._footer:
            self.create_text(
                14,
                ry + self._foot_h // 2,
                text=_ellipsize(self._footer, self._fb, w - 28),
                fill=T["gold"],
                font=F["body"],
                anchor="w",
            )


    def _row_index_at(self, y: int) -> int | None:
        for i, (y1, y2) in enumerate(self._row_hits):
            if y1 <= y <= y2:
                return i
        return None

    def _on_click(self, e: tk.Event) -> None:
        if self._on_row_click is None:
            return
        idx = self._row_index_at(int(e.y))
        if idx is not None:
            self._on_row_click(idx)

    def _on_motion(self, e: tk.Event) -> None:
        if self._on_row_click is None:
            return
        hover = self._row_index_at(int(e.y)) is not None
        self.configure(cursor=("hand2" if hover else ""))


def show_dark_dialog(parent: tk.Misc, title: str, message: str, *, confirm: bool = False) -> bool:
    """深色自定义模态对话框（确认框返回 True/False，提示框返回 False）。"""
    dlg = tk.Toplevel(parent)
    dlg.title(title)
    dlg.configure(bg=T["bg"])
    dlg.resizable(False, False)
    dlg.transient(parent.winfo_toplevel())
    _apply_dark_titlebar(dlg)

    result = {"ok": False}
    outer = tk.Frame(dlg, bg=T["card"], highlightbackground=T["border"], highlightthickness=1, padx=20, pady=16)
    outer.pack(fill="both", expand=True, padx=10, pady=10)

    tk.Label(
        outer,
        text=title,
        bg=T["card"],
        fg=T["text"],
        font=F["title"],
        anchor="w",
    ).pack(fill="x", pady=(0, 8))

    tk.Label(
        outer,
        text=message,
        bg=T["card"],
        fg=T["sub"],
        font=F["body"],
        justify="left",
        wraplength=420,
        anchor="w",
    ).pack(fill="x", pady=(0, 16))

    btn_row = tk.Frame(outer, bg=T["card"])
    btn_row.pack(fill="x")

    def _confirm_yes() -> None:
        result["ok"] = True
        dlg.destroy()

    def _close() -> None:
        dlg.destroy()

    if confirm:
        tk.Button(
            btn_row,
            text=UI_TEXTS["cleanup"]["cancel"],
            bg=T["btn"],
            fg=T["text"],
            activebackground=T["border"],
            activeforeground=T["text"],
            bd=0,
            padx=16,
            pady=5,
            font=F["body"],
            cursor="hand2",
            command=_close,
        ).pack(side="right", padx=(8, 0))
        tk.Button(
            btn_row,
            text=UI_TEXTS["cleanup"]["ok"],
            bg=T["red"],
            fg=T["text"],
            activebackground=T["red"],
            activeforeground=T["text"],
            bd=0,
            padx=16,
            pady=5,
            font=F["title"],
            cursor="hand2",
            command=_confirm_yes,
        ).pack(side="right")
    else:
        tk.Button(
            btn_row,
            text=UI_TEXTS["cleanup"]["ack"],
            bg=T["active"],
            fg=T["text"],
            activebackground=T["blue_hi"],
            activeforeground=T["text"],
            bd=0,
            padx=18,
            pady=5,
            font=F["body"],
            cursor="hand2",
            command=_close,
        ).pack(side="right")

    dlg.protocol("WM_DELETE_WINDOW", _close)
    dlg.bind("<Escape>", lambda _e: _close())
    dlg.update_idletasks()
    try:
        top = parent.winfo_toplevel()
        w = max(360, dlg.winfo_reqwidth())
        h = max(160, dlg.winfo_reqheight())
        x = top.winfo_rootx() + max(0, (top.winfo_width() - w) // 2)
        y = top.winfo_rooty() + max(0, (top.winfo_height() - h) // 2)
        dlg.geometry(f"{w}x{h}+{x}+{y}")
    except Exception:  # noqa: BLE001
        pass
    dlg.grab_set()
    parent.wait_window(dlg)
    return result["ok"]


# ==============================================================================
# 5. 装备分析看板主窗口
# ==============================================================================
class GearAnalysisWindow(tk.Toplevel):
    def __init__(self, master: tk.Misc | None = None) -> None:
        super().__init__(master)
        self.title(UI_TEXTS["title"])
        self.geometry(UI_CONST["win_size"])
        self.minsize(UI_CONST["min_w"], UI_CONST["min_h"])
        self.configure(bg=T["bg"])
        _apply_dark_titlebar(self)

        # 绑定到当前窗口的字体度量对象（自动适配 100%~200% DPI）
        self._f_title = tkfont.Font(self, font=F["title"])
        self._f_body = tkfont.Font(self, font=F["body"])
        self._f_mono = tkfont.Font(self, font=F["mono"])
        self._lh_title = self._f_title.metrics("linespace")
        self._lh_body = self._f_body.metrics("linespace")

        # 状态
        self._scan_files: list[Path] = []
        self._current_path: Path | None = None
        self._res: dict[str, Any] | None = None
        self._load_err: str | None = None
        self._active_tab = "sandbox"
        self._hover_dim: str | None = None
        self._pinned_dim: str | None = None
        self._radar_hit_targets: list[tuple[str, float, float, float, float]] = []
        self._dropdown_popup: tk.Toplevel | None = None
        self._last_cv_w = 0
        self._raw_by_id: dict[str, dict[str, Any]] | None = None

        self._build_topbar()
        self._build_scroll_body()
        self.bind("<MouseWheel>", self._on_mousewheel)

        self.refresh_files(prefer_latest=True)

    # ---------- 顶部文件栏与自定义下拉 ----------
    def _build_topbar(self) -> None:
        pad = UI_CONST["pad_x"]
        wrap = tk.Frame(
            self,
            bg=T["card"],
            highlightbackground=T["border"],
            highlightthickness=1,
            padx=12,
            pady=8,
        )
        wrap.pack(fill="x", padx=pad, pady=(10, 6))

        # 先排右侧清理/导出按钮，防止窄窗口挤压出界
        tk.Button(
            wrap,
            text=UI_TEXTS["cleanup"]["btn"],
            bg=T["btn"],
            fg=T["gold"],
            activebackground=T["border"],
            activeforeground=T["gold"],
            bd=0,
            padx=12,
            pady=5,
            font=F["body"],
            cursor="hand2",
            command=self._on_cleanup,
        ).pack(side="right", padx=(8, 0))
        tk.Button(
            wrap,
            text=UI_TEXTS["export"]["btn"],
            bg=T["btn"],
            fg=T["blue_hi"],
            activebackground=T["border"],
            activeforeground=T["blue_hi"],
            bd=0,
            padx=12,
            pady=5,
            font=F["body"],
            cursor="hand2",
            command=self._on_export_data,
        ).pack(side="right", padx=(8, 0))

        tk.Label(wrap, text=UI_TEXTS["file_label"], bg=T["card"], fg=T["sub"], font=F["body"]).pack(
            side="left", padx=(0, 8)
        )

        # 深色文件下拉框（避免 ttk.Combobox 白底）
        self._dd_box = tk.Frame(
            wrap,
            bg=T["btn"],
            highlightbackground=T["border"],
            highlightthickness=1,
            width=UI_CONST["dropdown_w"],
            padx=10,
            pady=4,
            cursor="hand2",
        )
        self._dd_box.pack(side="left")
        self._dd_lbl = tk.Label(
            self._dd_box,
            text=UI_TEXTS["cell_na"],
            bg=T["btn"],
            fg=T["text"],
            font=F["body"],
            anchor="w",
            cursor="hand2",
        )
        self._dd_lbl.pack(side="left", fill="x", expand=True)
        self._dd_arrow = tk.Label(
            self._dd_box,
            text=UI_TEXTS["dropdown_arrow"],
            bg=T["btn"],
            fg=T["sub"],
            font=F["body"],
            cursor="hand2",
        )
        self._dd_arrow.pack(side="right", padx=(6, 0))
        for w in (self._dd_box, self._dd_lbl, self._dd_arrow):
            w.bind("<Button-1>", lambda _e: self._toggle_file_dropdown())

        tk.Button(
            wrap,
            text=UI_TEXTS["btn_refresh"],
            bg=T["btn"],
            fg=T["text"],
            activebackground=T["border"],
            activeforeground=T["text"],
            bd=0,
            padx=12,
            pady=5,
            font=F["body"],
            cursor="hand2",
            command=lambda: self.refresh_files(prefer_latest=False),
        ).pack(side="left", padx=(8, 4))

        tk.Button(
            wrap,
            text=UI_TEXTS["btn_browse"],
            bg=T["btn"],
            fg=T["text"],
            activebackground=T["border"],
            activeforeground=T["text"],
            bd=0,
            padx=12,
            pady=5,
            font=F["body"],
            cursor="hand2",
            command=self._on_browse,
        ).pack(side="left", padx=(0, 10))

        self._summary_lbl = tk.Label(
            wrap,
            text="",
            bg=T["card"],
            fg=T["sub"],
            font=F["body"],
            anchor="w",
            justify="left",
        )
        self._summary_lbl.pack(side="left", fill="x", expand=True)
        self._summary_lbl.bind(
            "<Configure>",
            lambda e: self._summary_lbl.configure(wraplength=max(120, e.width - 6)),
        )

    def _toggle_file_dropdown(self) -> None:
        if self._dropdown_popup is not None and self._dropdown_popup.winfo_exists():
            self._dropdown_popup.destroy()
            self._dropdown_popup = None
            return
        if not self._scan_files:
            return

        pop = tk.Toplevel(self)
        pop.overrideredirect(True)
        pop.configure(bg=T["border"])
        pop.attributes("-topmost", True)
        self._dropdown_popup = pop

        inner = tk.Frame(pop, bg=T["card"], padx=2, pady=2)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        shown_files = self._scan_files[: UI_CONST["dropdown_max_rows"] * 3]
        for fp in shown_files:
            is_cur = self._current_path is not None and fp == self._current_path
            row_bg = T["active"] if is_cur else T["card"]
            lbl = tk.Label(
                inner,
                text=_ellipsize(fp.name, self._f_body, UI_CONST["dropdown_w"] + 40),
                bg=row_bg,
                fg=T["text"],
                font=F["body"],
                anchor="w",
                padx=10,
                pady=5,
                cursor="hand2",
            )
            lbl.pack(fill="x")
            if not is_cur:
                lbl.bind("<Enter>", lambda _e, w=lbl: w.configure(bg=T["btn"]))
                lbl.bind("<Leave>", lambda _e, w=lbl: w.configure(bg=T["card"]))
            lbl.bind("<Button-1>", lambda _e, target=fp: self._select_dropdown_file(target))

        pop.update_idletasks()
        bx = self._dd_box.winfo_rootx()
        by = self._dd_box.winfo_rooty() + self._dd_box.winfo_height() + 2
        pw = max(self._dd_box.winfo_width(), pop.winfo_reqwidth())
        ph = pop.winfo_reqheight()
        pop.geometry(f"{pw}x{ph}+{bx}+{by}")
        pop.focus_force()
        pop.bind("<FocusOut>", lambda _e: self._close_dropdown())
        pop.bind("<Escape>", lambda _e: self._close_dropdown())

    def _close_dropdown(self) -> None:
        if self._dropdown_popup is not None:
            try:
                self._dropdown_popup.destroy()
            except Exception:  # noqa: BLE001
                pass
            self._dropdown_popup = None

    def _select_dropdown_file(self, path: Path) -> None:
        self._close_dropdown()
        self.load_file(path)

    # ---------- 主滚动视口 ----------
    def _build_scroll_body(self) -> None:
        pad = UI_CONST["pad_x"]
        holder = tk.Frame(self, bg=T["bg"])
        holder.pack(fill="both", expand=True, padx=(pad, pad - 6), pady=(0, 10))

        self._scroll_cv = tk.Canvas(holder, bg=T["bg"], highlightthickness=0, bd=0)
        self._vscroll = DarkVScrollbar(holder, command=self._scroll_cv.yview)
        self._scroll_cv.configure(yscrollcommand=self._vscroll.set)

        self._vscroll.pack(side="right", fill="y", padx=(4, 0))
        self._scroll_cv.pack(side="left", fill="both", expand=True)

        self._content = tk.Frame(self._scroll_cv, bg=T["bg"])
        self._content_win = self._scroll_cv.create_window((0, 0), window=self._content, anchor="nw")

        self._scroll_cv.bind("<Configure>", self._on_scroll_cv_configure)
        self._content.bind("<Configure>", lambda _e: self._sync_scrollregion())

    def _on_scroll_cv_configure(self, e: tk.Event) -> None:
        if e.width != self._last_cv_w and e.width > 40:
            self._last_cv_w = e.width
            self._scroll_cv.itemconfigure(self._content_win, width=e.width)
        self._sync_scrollregion()

    def _sync_scrollregion(self) -> None:
        try:
            cw = max(1, self._scroll_cv.winfo_width())
            ch = max(1, self._scroll_cv.winfo_height())
            rh = self._content.winfo_reqheight()
            self._scroll_cv.configure(scrollregion=(0, 0, cw, max(ch, rh)))
        except Exception:  # noqa: BLE001
            pass

    def _on_mousewheel(self, e: tk.Event) -> None:
        self._close_dropdown()
        try:
            first, last = self._scroll_cv.yview()
            if last - first >= 0.999:
                return
            step = -1 if e.delta > 0 else 1
            self._scroll_cv.yview_scroll(step, "units")
        except Exception:  # noqa: BLE001
            pass

    # ---------- 文件加载与清理动作 ----------
    def refresh_files(self, *, prefer_latest: bool = False) -> None:
        prev_newest = self._scan_files[0] if self._scan_files else None
        discovered = list_scan_json_files()

        # 若当前是外部浏览加载的文件且仍存在，保留在列表首位便于切换回看
        if self._current_path is not None and self._current_path.is_file() and self._current_path not in discovered:
            if not prefer_latest:
                discovered = [self._current_path, *discovered]

        self._scan_files = discovered
        if not discovered:
            self._current_path = None
            self._res = None
            self._load_err = None
            self._dd_lbl.configure(text=UI_TEXTS["cell_na"])
            self._summary_lbl.configure(text="")
            self._render_dashboard()
            return

        has_newer = prev_newest is not None and discovered[0] != prev_newest
        if prefer_latest or has_newer or self._current_path is None or not self._current_path.is_file():
            target = discovered[0]
        else:
            target = self._current_path
        self.load_file(target)

    def load_file(self, path: Path) -> None:
        self._current_path = path
        if path not in self._scan_files and path.is_file():
            self._scan_files = [path, *self._scan_files]
        self._dd_lbl.configure(text=_ellipsize(path.name, self._f_body, UI_CONST["dropdown_w"] - 34))
        self._hover_dim = None
        self._pinned_dim = None
        self._raw_by_id = None

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            scan = raw.get("scan") if isinstance(raw, dict) else None
            if isinstance(scan, dict) and isinstance(scan.get("items"), list):
                # 支持直接打开「导出装备数据」完整包（e7pilot.gear_export.*）
                self._res = gear_analysis.analyze_payload(scan, source_name=path.name)
            else:
                self._res = gear_analysis.analyze_file(path)
            self._load_err = None
            inp = self._res.get("input", {})
            lv = inp.get("effective_level_counts", {})
            self._summary_lbl.configure(
                text=UI_TEXTS["summary"].format(
                    total=inp.get("item_count", 0),
                    valid=inp.get("valid_count", 0),
                    lv90=lv.get("90", 0),
                    lv88=lv.get("88", 0),
                    lv85=lv.get("85", 0),
                    lv80=lv.get("le80", 0),
                )
            )
        except Exception as exc:  # noqa: BLE001
            self._res = None
            self._load_err = UI_TEXTS["load_error"].format(reason=exc)
            self._summary_lbl.configure(text="")

        self._render_dashboard()

    def _on_browse(self) -> None:
        self._close_dropdown()
        init_dir = get_debug_dir()
        chosen = filedialog.askopenfilename(
            parent=self,
            title=UI_TEXTS["browse_dialog_title"],
            initialdir=str(init_dir if init_dir.is_dir() else Path.cwd()),
            filetypes=[(UI_TEXTS["browse_filetype_label"], "*.json")],
        )
        if chosen:
            self.load_file(Path(chosen))

    # ---------- 导出装备数据（完整包：原始扫描 + 分析结果） ----------
    def _build_export_payload(self) -> dict[str, Any]:
        et = UI_TEXTS["export"]
        if self._current_path is None or self._res is None:
            raise ValueError(et["empty"])
        raw_data = json.loads(self._current_path.read_text(encoding="utf-8"))
        scan_data = raw_data.get("scan") if isinstance(raw_data.get("scan"), dict) and raw_data["scan"].get("items") else raw_data
        try:
            from version import VERSION as app_version
        except Exception:  # noqa: BLE001
            app_version = "unknown"
        inp = self._res.get("input") or {}
        scan_meta = scan_data.get("meta") or {}
        res = scan_meta.get("resolution") or []
        aspect_ratio = None
        try:
            if len(res) == 2 and float(res[1]):
                aspect_ratio = round(float(res[0]) / float(res[1]), 4)
        except Exception:  # noqa: BLE001
            aspect_ratio = None
        return {
            "schema": "e7pilot.gear_export.v1.1",
            "app_version": app_version,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "source": {
                "scan_file": self._current_path.name,
                "scan_size": self._current_path.stat().st_size,
                "complete": bool(inp.get("complete")),
                "valid_count": inp.get("valid_count"),
                "stop_reason": inp.get("stop_reason"),
                "scanner_version": app_version,
                "resolution": res,
                "aspect_ratio": aspect_ratio,
            },
            "analysis": self._res,
            "scan": scan_data,
        }

    def _on_export_data(self) -> None:
        et = UI_TEXTS["export"]
        if self._current_path is None or self._res is None:
            show_dark_dialog(self, et["dialog_title"], et["empty"], confirm=False)
            return
        default_name = f"E7Pilot_装备数据_{datetime.now():%Y%m%d_%H%M%S}.json"
        path_str = filedialog.asksaveasfilename(
            parent=self,
            title=et["dialog_title"],
            defaultextension=".json",
            initialfile=default_name,
            filetypes=[(et["filetype"], "*.json")],
        )
        if not path_str:
            return
        try:
            payload = self._build_export_payload()
            text = json.dumps(payload, ensure_ascii=False, indent=1)
            out = Path(path_str)
            out.write_text(text, encoding="utf-8")
            size_kb = max(1.0, round(out.stat().st_size / 1024.0, 1))
            show_dark_dialog(
                self,
                et["dialog_title"] + " · 完成",
                et["success"].format(size=size_kb, path=out),
                confirm=False,
            )
        except Exception as exc:  # noqa: BLE001
            show_dark_dialog(self, et["dialog_title"] + " · 失败", et["error"].format(reason=exc), confirm=False)

    def _on_cleanup(self) -> None:
        self._close_dropdown()
        targets, total_bytes = plan_cleanup_files()
        ct = UI_TEXTS["cleanup"]
        if not targets:
            show_dark_dialog(self, ct["title"], ct["empty"], confirm=False)
            return

        mb_str = f"{total_bytes / (1024 * 1024):.2f}"
        ok = show_dark_dialog(
            self,
            ct["title"],
            ct["confirm"].format(n=len(targets), mb=mb_str),
            confirm=True,
        )
        if not ok:
            return

        deleted, freed_bytes, failed = execute_cleanup(targets)
        freed_mb = f"{freed_bytes / (1024 * 1024):.2f}"
        if failed == 0:
            msg = ct["done"].format(n=deleted, mb=freed_mb)
        elif deleted > 0:
            msg = ct["done"].format(n=deleted, mb=freed_mb) + "\n" + ct["partial"].format(k=failed)
        else:
            msg = ct["partial"].format(k=failed)

        show_dark_dialog(self, ct["title"], msg, confirm=False)
        self.refresh_files(prefer_latest=True)

    # ---------- Tab3 行点击：装备详情弹窗（回查原始扫描 JSON） ----------
    def _lookup_raw_item(self, item_id: Any) -> dict[str, Any] | None:
        if self._raw_by_id is None:
            self._raw_by_id = {}
            try:
                if self._current_path is not None and self._current_path.is_file():
                    data = json.loads(self._current_path.read_text(encoding="utf-8"))
                    scan = data.get("scan") if isinstance(data.get("scan"), dict) else data
                    for it in scan.get("items") or []:
                        if isinstance(it, dict):
                            self._raw_by_id[str(it.get("id"))] = it
            except Exception:  # noqa: BLE001
                self._raw_by_id = {}
        return self._raw_by_id.get(str(item_id))

    def _on_action_row_click(self, rows: list[dict[str, Any]], idx: int) -> None:
        if 0 <= idx < len(rows):
            self._show_item_detail(rows[idx])

    def _current_scan_items(self) -> list[dict[str, Any]]:
        if self._current_path is None or not self._current_path.is_file():
            return []
        try:
            data = json.loads(self._current_path.read_text(encoding="utf-8"))
            scan = data.get("scan") if isinstance(data.get("scan"), dict) else data
            raw_items = scan.get("items") if isinstance(scan, dict) else None
            if not isinstance(raw_items, list):
                return []
            return [it for it in raw_items if isinstance(it, dict)]
        except Exception:  # noqa: BLE001
            return []

    def _speed_items(self, threshold: int, craft_only: bool) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for idx, raw in enumerate(self._current_scan_items(), start=1):
            cleaned = gear_analysis.validate_and_clean_item(raw, idx)
            if not cleaned.get("valid"):
                continue
            if cleaned["part"] == "鞋子" and cleaned["main_key"] == "速度":
                continue
            speed = int(cleaned["sub_map"].get("速度", 0) or 0)
            if speed < threshold:
                continue
            if craft_only and cleaned["is_event_88"]:
                continue
            rows.append(
                {
                    "id": cleaned["id"],
                    "part": cleaned["part"],
                    "name": cleaned["name"],
                    "set": cleaned["set_name"],
                    "speed": speed,
                    "level": cleaned["effective_level"],
                    "equipped": bool(cleaned["equipped"]),
                }
            )
        rows.sort(key=lambda r: (-r["speed"], str(r["id"])))
        return rows

    def _show_speed_items(self, threshold: int, craft_only: bool) -> None:
        st = UI_TEXTS["speed_items"]
        items = self._speed_items(threshold, craft_only)
        scope = st["scope_craft"] if craft_only else st["scope_all"]
        title = st["title"].format(threshold=threshold, scope=scope, count=len(items))

        dlg = tk.Toplevel(self)
        dlg.title(title)
        dlg.configure(bg=T["bg"])
        dlg.transient(self)
        _apply_dark_titlebar(dlg)
        dlg.grab_set()
        dlg.geometry("880x560")

        outer = tk.Frame(dlg, bg=T["bg"])
        outer.pack(fill="both", expand=True, padx=10, pady=10)
        tk.Label(
            outer,
            text=st["hint"],
            bg=T["bg"],
            fg=T["sub"],
            font=F["body"],
            anchor="w",
        ).pack(fill="x", pady=(0, 6))

        body = tk.Frame(outer, bg=T["bg"])
        body.pack(fill="both", expand=True)
        canvas = tk.Canvas(body, bg=T["bg"], highlightthickness=0)
        scroll = DarkVScrollbar(body, command=canvas.yview)
        inner = tk.Frame(canvas, bg=T["bg"])
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win_id, width=e.width))
        canvas.configure(yscrollcommand=scroll.set)
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        lv_map = UI_TEXTS["level_short"]
        yes_txt, no_txt = UI_TEXTS["yes_no"]
        table_rows: list[list[tuple[str, str]]] = []
        for it in items:
            lv = str(it["level"])
            spd = int(it["speed"])
            table_rows.append(
                [
                    (str(it["id"]), T["sub"]),
                    (str(it["part"]), T["text"]),
                    (str(it["name"]), T["text"]),
                    (str(it["set"]), T["blue_hi"]),
                    (str(spd), T["gold"] if spd >= 23 else T["text"]),
                    (lv_map.get(lv, lv), T["sub"]),
                    (yes_txt if it["equipped"] else no_txt, T["text"] if it["equipped"] else T["sub"]),
                ]
            )

        table = CanvasTable(
            inner,
            title,
            st["headers"],
            UI_CONST["speed_cols"],
            table_rows,
            self._f_title,
            self._f_body,
            empty_text=st["empty"],
            on_row_click=lambda i: self._show_item_detail({"id": items[i]["id"]}),
        )
        table.pack(fill="x")

        tk.Button(
            outer,
            text=st["close"],
            bg=T["btn"],
            fg=T["text"],
            activebackground=T["border"],
            activeforeground=T["text"],
            bd=0,
            padx=16,
            pady=5,
            font=F["body"],
            cursor="hand2",
            command=dlg.destroy,
        ).pack(anchor="e", pady=(8, 0))

    @staticmethod
    def _fmt_stat(stat: dict[str, Any]) -> str:
        key = str(stat.get("key") or stat.get("type") or "?")
        val = stat.get("value")
        is_pct = bool(stat.get("is_percent", key.endswith("%")))
        if isinstance(val, (int, float)):
            v = f"{val:g}"
        else:
            v = str(val)
        label = key if key.endswith("%") or not is_pct else f"{key}%"
        return f"{label} {v}{'%' if is_pct else ''}"

    def _show_item_detail(self, row: dict[str, Any]) -> None:
        dt = UI_TEXTS["detail"]
        item_id = row.get("id")
        raw = self._lookup_raw_item(item_id)

        dlg = tk.Toplevel(self)
        dlg.title(dt["title"])
        dlg.configure(bg=T["bg"])
        dlg.resizable(False, False)
        dlg.transient(self)
        _apply_dark_titlebar(dlg)
        dlg.grab_set()

        outer = tk.Frame(
            dlg,
            bg=T["card"],
            highlightbackground=T["border"],
            highlightthickness=1,
            padx=20,
            pady=16,
        )
        outer.pack(fill="both", expand=True, padx=10, pady=10)

        if raw is None:
            tk.Label(
                outer,
                text=dt["missing"].format(id=item_id),
                bg=T["card"],
                fg=T["gold"],
                font=F["body"],
                justify="left",
                wraplength=460,
                anchor="w",
            ).pack(fill="x")
        else:
            lv = raw.get("level")
            quality = str(raw.get("quality") or "")
            part = str(raw.get("part") or "")
            name = str(raw.get("name") or "")
            header = f"#{item_id}  Lv{lv if lv is not None else '?'}  {quality}  {part}  ·  {name}"
            tk.Label(
                outer,
                text=header,
                bg=T["card"],
                fg=T["text"],
                font=F["title"],
                anchor="w",
                justify="left",
                wraplength=520,
            ).pack(fill="x", pady=(0, 4))

            set_obj = raw.get("set") if isinstance(raw.get("set"), dict) else {}
            set_name = str(set_obj.get("name") or row.get("set") or "—")
            pieces = set_obj.get("pieces")
            required = set_obj.get("required")
            set_line = f"{dt['field_set']}：{set_name}"
            if pieces is not None and required is not None:
                set_line += f"（{pieces}/{required}）"
            tk.Label(
                outer,
                text=set_line,
                bg=T["card"],
                fg=T["sub"],
                font=F["body"],
                anchor="w",
            ).pack(fill="x", pady=(0, 8))

            grid = tk.Frame(outer, bg=T["card"])
            grid.pack(fill="x", pady=(0, 6))
            grid.columnconfigure(1, weight=1)

            ms = raw.get("main_stat") if isinstance(raw.get("main_stat"), dict) else {}
            info_rows: list[tuple[str, str]] = [
                (dt["field_main"], self._fmt_stat(ms)),
                (dt["field_score"], str(raw.get("score", row.get("panel_score", "—")))),
            ]
            if "raw_gs" in row:
                info_rows.append((dt["field_raw_gs"], f"{float(row.get('raw_gs') or 0):.2f}"))
            if row.get("best_dim"):
                info_rows.append(
                    (dt["field_best"], f"{row.get('best_dim')} / {float(row.get('best_valid_gs') or 0):.2f}")
                )
            elif "best_valid_gs" in row:
                info_rows.append((dt["field_effective"], f"{float(row.get('best_valid_gs') or 0):.2f}"))
            info_rows.append((dt["field_equipped"], dt["yes"] if raw.get("equipped") else dt["no"]))
            if "mismatched" in row:
                info_rows.append(
                    (dt["field_mismatch"], dt["yes"] if row.get("mismatched") else dt["no"])
                )

            for r_idx, (lbl, val) in enumerate(info_rows):
                tk.Label(
                    grid,
                    text=lbl,
                    bg=T["card"],
                    fg=T["sub"],
                    font=F["body"],
                    anchor="w",
                ).grid(row=r_idx, column=0, sticky="w", padx=(0, 12), pady=1)
                tk.Label(
                    grid,
                    text=val,
                    bg=T["card"],
                    fg=T["text"],
                    font=F["body"],
                    anchor="w",
                    justify="left",
                    wraplength=420,
                ).grid(row=r_idx, column=1, sticky="w", pady=1)

            tk.Frame(outer, bg=T["border"], height=1).pack(fill="x", pady=(6, 6))
            tk.Label(
                outer,
                text=dt["field_subs"],
                bg=T["card"],
                fg=T["text"],
                font=F["title"],
                anchor="w",
            ).pack(fill="x", pady=(0, 2))
            subs = raw.get("substats") if isinstance(raw.get("substats"), list) else []
            if subs:
                for s in subs:
                    if not isinstance(s, dict):
                        continue
                    line = "· " + self._fmt_stat(s)
                    if s.get("pct_inferred"):
                        line += dt["pct_inferred"]
                    tk.Label(
                        outer,
                        text=line,
                        bg=T["card"],
                        fg=T["blue_hi"],
                        font=F["body"],
                        anchor="w",
                    ).pack(fill="x")
            else:
                tk.Label(outer, text="—", bg=T["card"], fg=T["sub"], font=F["body"], anchor="w").pack(fill="x")

        btn_row = tk.Frame(outer, bg=T["card"])
        btn_row.pack(fill="x", pady=(12, 0))
        tk.Button(
            btn_row,
            text=dt["close"],
            bg=T["btn"],
            fg=T["text"],
            activebackground=T["border"],
            activeforeground=T["text"],
            bd=0,
            padx=18,
            pady=5,
            font=F["body"],
            cursor="hand2",
            command=dlg.destroy,
        ).pack(side="right")

        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        dlg.update_idletasks()
        try:
            w = max(420, dlg.winfo_reqwidth())
            h = max(220, dlg.winfo_reqheight())
            x = self.winfo_rootx() + max(0, (self.winfo_width() - w) // 2)
            y = self.winfo_rooty() + max(0, (self.winfo_height() - h) // 2)
            dlg.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:  # noqa: BLE001
            pass
        self.wait_window(dlg)

    # ---------- 主看板渲染 ----------
    def _render_dashboard(self) -> None:
        for child in self._content.winfo_children():
            child.destroy()
        self._scroll_cv.yview_moveto(0.0)

        if self._load_err:
            self._render_state_card(self._load_err, accent=T["red"])
            self.after_idle(self._sync_scrollregion)
            return

        if self._res is None:
            self._render_state_card(UI_TEXTS["empty_no_scan"], accent=T["sub"])
            self.after_idle(self._sync_scrollregion)
            return

        res = self._res
        warnings = res.get("input", {}).get("warnings") or []
        if warnings:
            self._build_warnings_banner(self._content, warnings)

        self._build_profile_card(self._content, res)
        self._build_middle_section(self._content, res)
        self._build_bottom_tabs(self._content, res)
        self.after_idle(self._sync_scrollregion)

    def _render_state_card(self, message: str, *, accent: str) -> None:
        box = tk.Frame(
            self._content,
            bg=T["card"],
            highlightbackground=T["border"],
            highlightthickness=1,
            padx=24,
            pady=48,
        )
        box.pack(fill="x", pady=(12, 0))
        lbl = tk.Label(box, text=message, bg=T["card"], fg=accent, font=F["title"], justify="center")
        lbl.pack(fill="x")
        lbl.bind("<Configure>", lambda e: lbl.configure(wraplength=max(240, e.width - 20)))

    def _build_warnings_banner(self, parent: tk.Misc, warnings: list[str]) -> None:
        bar = tk.Frame(
            parent,
            bg=T["card"],
            highlightbackground=T["gold"],
            highlightthickness=1,
            padx=12,
            pady=7,
        )
        bar.pack(fill="x", pady=(0, UI_CONST["card_gap"]))
        head = tk.Label(
            bar,
            text=UI_TEXTS["warn_title"],
            bg=T["card"],
            fg=T["sub"],
            font=F["body"],
            anchor="w",
        )
        head.pack(fill="x")
        txt = "\n".join(warnings)
        body = tk.Label(
            bar,
            text=txt,
            bg=T["card"],
            fg=T["gold"],
            font=F["body"],
            anchor="w",
            justify="left",
        )
        body.pack(fill="x", pady=(2, 0))
        body.bind("<Configure>", lambda e: body.configure(wraplength=max(260, e.width - 8)))

    def _build_profile_card(self, parent: tk.Misc, res: dict[str, Any]) -> None:
        tier_str = str(res.get("tier") or "")
        acc = res.get("account") or {}
        naming = str(acc.get("naming") or acc.get("main_lean") or "")
        tags: list[str] = list(acc.get("tags") or [])
        t_col = _tier_color(tier_str)

        cv = tk.Canvas(parent, height=78, bg=T["bg"], highlightthickness=0)
        cv.pack(fill="x", pady=(0, UI_CONST["card_gap"]))

        def _draw(_e: tk.Event | None = None) -> None:
            cv.delete("all")
            w = max(320, cv.winfo_width())
            badge_w = max(142, self._f_title.measure(tier_str) + 34)
            rx = 16 + badge_w + 16
            avail_w = max(160, w - rx - 16)

            # 计算成色标签胶囊流式折行坐标
            pill_h = self._lh_body + 8
            px, py = rx, 14 + self._lh_body + 6 + self._lh_title + 8
            placements: list[tuple[int, int, int, str]] = []
            for tg in tags:
                txt = _ellipsize(tg, self._f_body, avail_w - 20)
                pw = self._f_body.measure(txt) + 20
                if placements and px + pw > w - 16:
                    px = rx
                    py += pill_h + 6
                placements.append((px, py, pw, txt))
                px += pw + 8

            req_h = max(76, (py + pill_h + 12) if placements else (16 + self._lh_body + self._lh_title + 20))
            if int(cv.cget("height")) != req_h:
                cv.configure(height=req_h)

            rounded(cv, 1, 1, w - 1, req_h - 1, r=UI_CONST["card_r"], fill=T["card"], outline=T["border"])
            cv.create_text(16, 15, text=UI_TEXTS["profile_title"], fill=T["sub"], font=F["body"], anchor="w")

            # 4 档徽章
            by1 = 26
            by2 = min(req_h - 10, by1 + max(36, self._lh_title + 16))
            rounded(cv, 16, by1, 16 + badge_w, by2, r=8, fill=T["btn"], outline=t_col)
            cv.create_text(
                16 + badge_w // 2,
                (by1 + by2) // 2,
                text=tier_str,
                fill=t_col,
                font=F["title"],
            )

            # 主副倾向命名
            cv.create_text(
                rx,
                16 + self._lh_body // 2 + 6,
                text=_ellipsize(naming, self._f_title, avail_w),
                fill=T["text"],
                font=F["title"],
                anchor="w",
            )

            # 成色标签胶囊
            for x1, y1, pw, txt in placements:
                rounded(cv, x1, y1, x1 + pw, y1 + pill_h, r=8, fill=T["btn"], outline=T["border"])
                cv.create_text(x1 + pw // 2, y1 + pill_h // 2, text=txt, fill=T["sub"], font=F["body"])

        cv.bind("<Configure>", _draw)

    # ---------- 中部：左六边形雷达 + 右流派条与关键指标 ----------
    def _build_middle_section(self, parent: tk.Misc, res: dict[str, Any]) -> None:
        gap = UI_CONST["card_gap"]
        arch_h = max(UI_CONST["arch_min_h"], self._lh_title + 26 + 5 * (self._lh_body + 12))
        metrics_h = max(UI_CONST["metrics_min_h"], self._lh_title + 26 + 8 * (self._lh_body + 12))
        radar_h = arch_h + gap + metrics_h

        row = tk.Frame(parent, bg=T["bg"])
        row.pack(fill="x", pady=(0, gap))

        self._radar_cv = tk.Canvas(
            row,
            width=UI_CONST["radar_w"],
            height=radar_h,
            bg=T["bg"],
            highlightthickness=0,
        )
        self._radar_cv.pack(side="left", padx=(0, gap))
        self._radar_cv.bind("<Configure>", lambda _e: self._draw_radar())
        self._radar_cv.bind("<Motion>", self._on_radar_motion)
        self._radar_cv.bind("<Leave>", self._on_radar_leave)
        self._radar_cv.bind("<Button-1>", self._on_radar_click)

        right_col = tk.Frame(row, bg=T["bg"])
        right_col.pack(side="left", fill="both", expand=True)

        arch_cv = tk.Canvas(right_col, height=arch_h, bg=T["bg"], highlightthickness=0)
        arch_cv.pack(fill="x", pady=(0, gap))
        arch_cv.bind("<Configure>", lambda _e, c=arch_cv: self._draw_archetypes(c, res))

        metrics_cv = tk.Canvas(right_col, height=metrics_h, bg=T["bg"], highlightthickness=0)
        metrics_cv.pack(fill="x")
        metrics_cv.bind("<Configure>", lambda _e, c=metrics_cv: self._draw_key_metrics(c, res))
        metrics_cv.bind("<Button-1>", self._on_metric_click)
        metrics_cv.bind("<Motion>", lambda e, c=metrics_cv: self._on_metric_motion(e, c))
        metrics_cv.bind("<Leave>", lambda _e, c=metrics_cv: c.configure(cursor=""))

    def _draw_radar(self) -> None:
        cv = getattr(self, "_radar_cv", None)
        if cv is None or not cv.winfo_exists() or self._res is None:
            return
        cv.delete("all")
        w = max(320, cv.winfo_width())
        h = max(280, cv.winfo_height())
        rounded(cv, 1, 1, w - 1, h - 1, r=UI_CONST["card_r"], fill=T["card"], outline=T["border"])
        cv.create_text(16, 22, text=UI_TEXTS["radar_title"], fill=T["text"], font=F["title"], anchor="w")

        dims_data = self._res.get("dims") or {}
        dim_names = list(gear_analysis.TEXTS["dims"].values())
        n = len(dim_names)

        top_pad = self._lh_title + 16
        foot_h = self._lh_body * 2 + 22
        avail_h = max(120, h - top_pad - foot_h)
        label_pad_v = self._lh_body * 2 + 8
        max_r = max(46.0, min(w * 0.27, (avail_h - label_pad_v * 2) / 2.0))
        cx = w / 2.0
        cy = top_pad + avail_h / 2.0

        angles = [-math.pi / 2.0 + i * (2.0 * math.pi / n) for i in range(n)]

        # 五圈网格 20/40/60/80/100 + 轴线
        for ring_v in UI_CONST["radar_rings"]:
            rr = max_r * (ring_v / 100.0)
            r_pts: list[float] = []
            for ang in angles:
                r_pts.extend((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
            cv.create_polygon(r_pts, fill="", outline=T["border"])

        for ang in angles:
            cv.create_line(cx, cy, cx + max_r * math.cos(ang), cy + max_r * math.sin(ang), fill=T["border"])

        # 数据多边形（半透明点阵填充 + 实线高亮描边）
        poly_pts: list[float] = []
        v_coords: list[tuple[float, float, float]] = []
        for d_name, ang in zip(dim_names, angles):
            sc = float((dims_data.get(d_name) or {}).get("score", 0.0))
            sc_clamped = max(0.0, min(100.0, sc))
            vr = max_r * (sc_clamped / 100.0)
            vx, vy = cx + vr * math.cos(ang), cy + vr * math.sin(ang)
            poly_pts.extend((vx, vy))
            v_coords.append((vx, vy, sc))

        cv.create_polygon(poly_pts, fill=T["blue"], stipple="gray25", outline="")
        cv.create_polygon(poly_pts, fill="", outline=T["blue_hi"], width=2)

        active_dim = self._hover_dim or self._pinned_dim
        self._radar_hit_targets = []

        for idx, (d_name, ang, (vx, vy, sc)) in enumerate(zip(dim_names, angles, v_coords)):
            is_sel = d_name == active_dim
            dot_r = 5.5 if is_sel else 4.0
            cv.create_oval(
                vx - dot_r,
                vy - dot_r,
                vx + dot_r,
                vy + dot_r,
                fill=(T["gold"] if is_sel else T["blue_hi"]),
                outline=T["card"],
            )

            ox = cx + (max_r + 12.0) * math.cos(ang)
            oy = cy + (max_r + 10.0) * math.sin(ang)
            if idx == 0:
                anchor_mode = "center"
                ny, sy = oy - self._lh_body - 2, oy
            elif idx == 3:
                anchor_mode = "center"
                ny, sy = oy + 2, oy + self._lh_body + 4
            elif math.cos(ang) > 0:
                anchor_mode = "w"
                ny, sy = oy - self._lh_body / 2, oy + self._lh_body / 2 + 2
            else:
                anchor_mode = "e"
                ny, sy = oy - self._lh_body / 2, oy + self._lh_body / 2 + 2

            cv.create_text(
                ox,
                ny,
                text=d_name,
                fill=(T["gold"] if is_sel else T["sub"]),
                font=(F["title"] if is_sel else F["body"]),
                anchor=anchor_mode,
            )
            cv.create_text(
                ox,
                sy,
                text=f"{sc:.1f}",
                fill=(T["gold"] if is_sel else T["text"]),
                font=F["title"],
                anchor=anchor_mode,
            )
            self._radar_hit_targets.append((d_name, vx, vy, ox, (ny + sy) / 2.0))

        # 底部悬停/点击明细区
        fy = h - foot_h + 6
        cv.create_line(14, fy - 4, w - 14, fy - 4, fill=T["border"])
        if active_dim and active_dim in dims_data:
            d_obj = dims_data[active_dim]
            l1 = f"{active_dim} · " + UI_TEXTS["radar_detail_line1"].format(
                q=f"{float(d_obj.get('quality_score', 0.0)):.1f}",
                d=f"{float(d_obj.get('depth_score', 0.0)):.1f}",
            )
            pk = d_obj.get("part_topk") or {}
            parts_str = " / ".join(f"{p} { float(v):.1f}" for p, v in pk.items())
            l2 = UI_TEXTS["radar_detail_line2"].format(parts=parts_str)
            cv.create_text(
                16,
                fy + self._lh_body // 2 + 2,
                text=_ellipsize(l1, self._f_body, w - 32),
                fill=T["blue_hi"],
                font=F["body"],
                anchor="w",
            )
            cv.create_text(
                16,
                fy + self._lh_body + self._lh_body // 2 + 6,
                text=_ellipsize(l2, self._f_body, w - 32),
                fill=T["sub"],
                font=F["body"],
                anchor="w",
            )
        else:
            cv.create_text(
                16,
                fy + (foot_h - 10) // 2,
                text=_ellipsize(UI_TEXTS["radar_idle_hint"], self._f_body, w - 32),
                fill=T["sub"],
                font=F["body"],
                anchor="w",
            )

    def _hit_test_radar(self, x: float, y: float) -> str | None:
        best_dim: str | None = None
        best_d2 = float(UI_CONST["radar_hit_r"] ** 2)
        for d_name, vx, vy, lx, ly in self._radar_hit_targets:
            d_v = (x - vx) ** 2 + (y - vy) ** 2
            d_l = ((x - lx) * 0.65) ** 2 + (y - ly) ** 2
            d2 = min(d_v, d_l)
            if d2 <= best_d2:
                best_d2 = d2
                best_dim = d_name
        return best_dim

    def _on_radar_motion(self, e: tk.Event) -> None:
        hit = self._hit_test_radar(float(e.x), float(e.y))
        if hit != self._hover_dim:
            self._hover_dim = hit
            self._radar_cv.configure(cursor=("hand2" if hit else ""))
            self._draw_radar()

    def _on_radar_leave(self, _e: tk.Event) -> None:
        if self._hover_dim is not None:
            self._hover_dim = None
            self._draw_radar()

    def _on_radar_click(self, e: tk.Event) -> None:
        hit = self._hit_test_radar(float(e.x), float(e.y))
        self._pinned_dim = None if (hit and hit == self._pinned_dim) else hit
        self._draw_radar()

    def _draw_archetypes(self, cv: tk.Canvas, res: dict[str, Any]) -> None:
        cv.delete("all")
        w = max(280, cv.winfo_width())
        h = max(140, cv.winfo_height())
        rounded(cv, 1, 1, w - 1, h - 1, r=UI_CONST["card_r"], fill=T["card"], outline=T["border"])
        cv.create_text(16, 22, text=UI_TEXTS["arch_title"], fill=T["text"], font=F["title"], anchor="w")

        arch = res.get("archetypes") or {}
        items = sorted(arch.items(), key=lambda kv: (-float(kv[1]), kv[0]))
        palette = (T["blue"], T["purple"], T["blue_hi"], T["green"], T["sub"])

        top_y = self._lh_title + 22
        row_h = (h - top_y - 10) / max(1, len(items))
        lbl_w = max(48, max((self._f_body.measure(k) for k, _ in items), default=36) + 14)
        bx1 = 16 + lbl_w
        bx2 = max(bx1 + 60, w - 64)
        bar_thick = max(10, min(14, int(row_h * 0.46)))

        for i, (name, raw_val) in enumerate(items):
            val = max(0.0, min(100.0, float(raw_val)))
            cy = top_y + row_h * (i + 0.5)
            col = palette[i % len(palette)]
            cv.create_text(16, cy, text=name, fill=T["sub"], font=F["body"], anchor="w")
            cv.create_rectangle(bx1, cy - bar_thick / 2, bx2, cy + bar_thick / 2, fill=T["btn"], outline="")
            fill_w = (bx2 - bx1) * (val / 100.0)
            if fill_w >= 2:
                cv.create_rectangle(
                    bx1,
                    cy - bar_thick / 2,
                    bx1 + fill_w,
                    cy + bar_thick / 2,
                    fill=col,
                    outline="",
                )
            cv.create_text(w - 16, cy, text=f"{val:.1f}", fill=T["text"], font=F["mono"], anchor="e")

    def _draw_key_metrics(self, cv: tk.Canvas, res: dict[str, Any]) -> None:
        cv.delete("all")
        self._metric_hits = []
        w = max(280, cv.winfo_width())
        h = max(140, cv.winfo_height())
        rounded(cv, 1, 1, w - 1, h - 1, r=UI_CONST["card_r"], fill=T["card"], outline=T["border"])
        cv.create_text(16, 22, text=UI_TEXTS["metrics_title"], fill=T["text"], font=F["title"], anchor="w")

        km = (res.get("account") or {}).get("key_metrics") or {}
        mt = UI_TEXTS["metrics"]
        mismatched_v = int(km.get("mismatched_high_es_count", 0))
        idle_v = int(km.get("unequipped_high_gs_count", 0))
        cells: list[tuple[str, str, str, tuple[int, bool] | None]] = []
        for threshold in (17, 18, 21, 23, 25):
            for craft_only in (False, True):
                suffix = "craft" if craft_only else "all"
                key = f"spd_ge{threshold}_{'craft_only' if craft_only else 'all'}"
                cells.append(
                    (
                        mt[f"spd{threshold}_{suffix}"],
                        str(km.get(key, 0)),
                        T["blue_hi"] if craft_only else T["text"],
                        (threshold, craft_only),
                    )
                )
        cells.extend(
            [
                (mt["craft_pct"], f"{float(km.get('craft_85_90_pct', 0.0)):.1f}%", T["text"], None),
                (mt["event_pct"], f"{float(km.get('event_88_pct', 0.0)):.1f}%", T["text"], None),
                (mt["purity_pct"], f"{float(km.get('purity_pct', 0.0)):.1f}%", T["green"], None),
                (mt["mismatched"], str(mismatched_v), T["gold"] if mismatched_v > 0 else T["text"], None),
                (mt["eq_avg_gs"], f"{float(km.get('equipped_avg_raw_gs', 0.0)):.1f}", T["text"], None),
                (mt["idle_high"], str(idle_v), T["gold"] if idle_v > 0 else T["text"], None),
            ]
        )

        top_y = self._lh_title + 22
        row_h = (h - top_y - 10) / 8.0
        col_w = (w - 32) / 2.0

        for idx, (label, val_str, v_col, action) in enumerate(cells):
            r_idx, c_idx = divmod(idx, 2)
            x_left = 16 + c_idx * col_w + (6 if c_idx > 0 else 0)
            x_right = 16 + (c_idx + 1) * col_w - (10 if c_idx < 1 else 8)
            cy = top_y + row_h * (r_idx + 0.5)
            val_px = self._f_mono.measure(val_str)
            lbl_txt = _ellipsize(label, self._f_body, int(x_right - x_left - val_px - 10))
            cv.create_text(x_left, cy, text=lbl_txt, fill=T["sub"], font=F["body"], anchor="w")
            cv.create_text(x_right, cy, text=val_str, fill=v_col, font=F["mono"], anchor="e")
            if action is not None:
                threshold, craft_only = action
                self._metric_hits.append(
                    (x_left - 4, x_right + 4, cy - row_h / 2, cy + row_h / 2, threshold, craft_only)
                )

    def _metric_cell_at(self, x: int, y: int) -> tuple[int, bool] | None:
        for x1, x2, y1, y2, threshold, craft_only in getattr(self, "_metric_hits", []):
            if x1 <= x <= x2 and y1 <= y <= y2:
                return threshold, craft_only
        return None

    def _on_metric_click(self, e: tk.Event) -> None:
        hit = self._metric_cell_at(int(e.x), int(e.y))
        if hit is not None:
            self._show_speed_items(*hit)

    def _on_metric_motion(self, e: tk.Event, cv: tk.Canvas) -> None:
        cv.configure(cursor=("hand2" if self._metric_cell_at(int(e.x), int(e.y)) else ""))

    # ---------- 下方 3 个分段页 ----------
    def _build_bottom_tabs(self, parent: tk.Misc, res: dict[str, Any]) -> None:
        tb = UI_TEXTS["tabs"]
        bar_row = tk.Frame(parent, bg=T["bg"])
        bar_row.pack(fill="x", pady=(0, UI_CONST["card_gap"]))

        options = [
            (tb["sandbox"], "sandbox"),
            (tb["matrix"], "matrix"),
            (tb["actions"], "actions"),
        ]
        seg = DarkTabBar(bar_row, options, self._active_tab, command=self._on_switch_tab)
        seg.pack(side="left")

        self._tab_host = tk.Frame(parent, bg=T["bg"])
        self._tab_host.pack(fill="both", expand=True)
        self._render_active_tab(res)

    def _on_switch_tab(self, tab_key: str) -> None:
        self._active_tab = tab_key
        if self._res is not None:
            self._render_active_tab(self._res)
            self.after_idle(self._sync_scrollregion)

    def _render_active_tab(self, res: dict[str, Any]) -> None:
        for child in self._tab_host.winfo_children():
            child.destroy()
        if self._active_tab == "sandbox":
            self._build_tab_sandbox(self._tab_host, res)
        elif self._active_tab == "matrix":
            self._build_tab_matrix(self._tab_host, res)
        else:
            self._build_tab_actions(self._tab_host, res)

    # ---------- 战备体检（Phase 1：战备综合指数，只读展示） ----------
    def _build_readiness_card(self, parent: tk.Misc, res: dict[str, Any]) -> None:
        rt = UI_TEXTS["readiness"]
        r = (res.get("account") or {}).get("readiness") or {}
        card = tk.Frame(
            parent,
            bg=T["card"],
            highlightbackground=T["border"],
            highlightthickness=1,
            padx=16,
            pady=12,
        )
        card.pack(fill="x", pady=(0, UI_CONST["card_gap"]))

        head = tk.Frame(card, bg=T["card"])
        head.pack(fill="x")
        tk.Label(head, text=rt["card_title"], bg=T["card"], fg=T["text"], font=F["title"]).pack(side="left")
        link = tk.Label(head, text=rt["formula_hint"], bg=T["card"], fg=T["blue_hi"], font=F["body"], cursor="hand2")
        link.pack(side="right")
        link.bind(
            "<Button-1>",
            lambda _e: show_dark_dialog(self, rt["formula_title"], rt["formula_body"], confirm=False),
        )

        body = tk.Frame(card, bg=T["card"])
        body.pack(fill="x", pady=(8, 0))

        row_h = self._lh_body + 16
        left = tk.Frame(body, bg=T["card"], width=200, height=row_h * 3 + 6)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        value_txt = f"{float(r['display_index']):.0f}" if r.get("display_index") is not None else "—"
        tk.Label(left, text=rt["index_label"], bg=T["card"], fg=T["sub"], font=F["body"], anchor="w").pack(fill="x")
        val_row = tk.Frame(left, bg=T["card"])
        val_row.pack(fill="x", anchor="w")
        tk.Label(val_row, text=value_txt, bg=T["card"], fg=T["gold"], font=F["kpi"]).pack(side="left")
        tk.Label(
            val_row,
            text=rt["unit"],
            bg=T["card"],
            fg=T["sub"],
            font=F["body"],
        ).pack(side="left", padx=(4, 0), pady=(10, 0))
        if not r.get("shown"):
            tk.Label(
                left,
                text=rt["insufficient"],
                bg=T["card"],
                fg=T["gold"],
                font=F["body"],
                anchor="w",
                justify="left",
                wraplength=190,
            ).pack(fill="x", pady=(2, 0))
        elif not r.get("complete"):
            tk.Label(
                left,
                text=rt["badge_lower"],
                bg=T["card"],
                fg=T["gold"],
                font=F["body"],
                anchor="w",
            ).pack(fill="x", pady=(2, 0))

        cv = tk.Canvas(body, bg=T["card"], highlightthickness=0, height=row_h * 3 + 6)
        cv.pack(side="left", fill="x", expand=True, padx=(18, 0))
        bars = [
            (rt["knife"], float(r.get("knife") or 0.0), T["blue_hi"]),
            (rt["bench"], float(r.get("bench") or 0.0), T["purple"]),
            (rt["quality"], float(r.get("quality") or 0.0), T["green"]),
        ]

        def _draw(_e: tk.Event | None = None) -> None:
            cv.delete("all")
            w = max(260, cv.winfo_width())
            label_w = max(self._f_body.measure(lbl) for lbl, _, _ in bars) + 12
            bar_x0 = 6 + label_w + 10
            bar_x1 = max(bar_x0 + 40, w - 56)
            for i, (label, val, color) in enumerate(bars):
                cy = i * row_h + 4 + row_h // 2
                cv.create_text(6, cy, text=label, anchor="w", fill=T["sub"], font=self._f_body)
                cv.create_rectangle(bar_x0, cy - 5, bar_x1, cy + 5, fill=T["btn"], outline="")
                frac = max(0.0, min(1.0, val / 100.0))
                cv.create_rectangle(bar_x0, cy - 5, bar_x0 + (bar_x1 - bar_x0) * frac, cy + 5, fill=color, outline="")
                cv.create_text(w - 4, cy, text=f"{val * 10.0:.0f}", anchor="e", fill=T["text"], font=self._f_body)

        cv.bind("<Configure>", _draw)
        self.after(30, _draw)

    # ---------- Tab1：极限配装沙盘 + 套装容量 + 2026 口径 ----------
    def _build_tab_sandbox(self, parent: tk.Misc, res: dict[str, Any]) -> None:
        gap = UI_CONST["card_gap"]
        sub = res.get("submodules") or {}
        sb = sub.get("sandbox") or {}
        set_cap = sub.get("set_capacity") or {}
        missing_parts = (res.get("input") or {}).get("missing_parts") or []

        self._build_readiness_card(parent, res)

        wrap = tk.Frame(parent, bg=T["bg"])
        wrap.pack(fill="x")

        top_row = tk.Frame(wrap, bg=T["bg"])
        top_row.pack(fill="x")

        left_col = tk.Frame(top_row, bg=T["bg"], width=UI_CONST["tab1_left_w"])
        left_col.pack(side="left", fill="y", padx=(0, gap))
        left_col.pack_propagate(True)

        # 沙盘卡片
        sb_card = tk.Frame(
            left_col,
            bg=T["card"],
            highlightbackground=T["border"],
            highlightthickness=1,
            padx=14,
            pady=12,
            width=UI_CONST["tab1_left_w"],
        )
        sb_card.pack(fill="x", pady=(0, gap))
        tk.Label(sb_card, text=UI_TEXTS["sandbox_title"], bg=T["card"], fg=T["text"], font=F["title"], anchor="w").pack(
            fill="x", pady=(0, 8)
        )

        teams = sb.get("teams") or []
        ranks = UI_TEXTS["sandbox_ranks"]
        if not teams:
            miss_txt = "、".join(missing_parts) if missing_parts else UI_TEXTS["cell_na"]
            empty_lbl = tk.Label(
                sb_card,
                text=UI_TEXTS["sandbox_empty"].format(parts=miss_txt),
                bg=T["btn"],
                fg=T["gold"],
                font=F["body"],
                justify="left",
                anchor="w",
                padx=10,
                pady=10,
                wraplength=UI_CONST["tab1_left_w"] - 48,
            )
            empty_lbl.pack(fill="x")
        else:
            for idx, tm in enumerate(teams):
                rk_name = ranks[idx] if idx < len(ranks) else f"#{tm.get('rank', idx + 1)}"
                item_box = tk.Frame(sb_card, bg=T["btn"], padx=10, pady=7)
                item_box.pack(fill="x", pady=(0, 6))
                top_line = tk.Frame(item_box, bg=T["btn"])
                top_line.pack(fill="x")
                tk.Label(
                    top_line,
                    text=f"{rk_name}  " + UI_TEXTS["sandbox_spd_fmt"].format(spd=tm.get("total_speed", 0)),
                    bg=T["btn"],
                    fg=(T["gold"] if idx == 0 else T["blue_hi"]),
                    font=F["title"],
                ).pack(side="left")
                tk.Label(
                    top_line,
                    text=str(tm.get("formula") or ""),
                    bg=T["btn"],
                    fg=T["text"],
                    font=F["mono"],
                ).pack(side="right")
                ids_str = ",".join(str(x) for x in (tm.get("item_ids") or []))
                tk.Label(
                    item_box,
                    text=UI_TEXTS["sandbox_meta_fmt"].format(ev=tm.get("event_88_used", 0), ids=ids_str),
                    bg=T["btn"],
                    fg=T["sub"],
                    font=F["body"],
                    anchor="w",
                ).pack(fill="x", pady=(2, 0))

            # 纯手工一速对照
            craft_box = tk.Frame(sb_card, bg=T["btn"], padx=10, pady=7)
            craft_box.pack(fill="x", pady=(2, 0))
            tk.Label(
                craft_box,
                text=UI_TEXTS["sandbox_craft_title"],
                bg=T["btn"],
                fg=T["purple_hi"],
                font=F["title"],
            ).pack(side="left")
            craft_f = sb.get("craft_only_top1_formula") or UI_TEXTS["cell_na"]
            tk.Label(craft_box, text=str(craft_f), bg=T["btn"], fg=T["text"], font=F["mono"]).pack(side="right")

        # 2026 套装效果口径（复用引擎 TEXTS["set_notes_2026"]）——放沙盘右侧，占满剩余宽度
        notes_col = tk.Frame(top_row, bg=T["bg"])
        notes_col.pack(side="left", fill="both", expand=True)
        notes_card = tk.Frame(
            notes_col,
            bg=T["card"],
            highlightbackground=T["border"],
            highlightthickness=1,
            padx=14,
            pady=12,
        )
        notes_card.pack(fill="both", expand=True)
        tk.Label(
            notes_card,
            text=UI_TEXTS["set_notes_title"],
            bg=T["card"],
            fg=T["text"],
            font=F["title"],
            anchor="w",
        ).pack(fill="x", pady=(0, 6))
        note_labels: list[tk.Label] = []
        for s_name, s_desc in (gear_analysis.TEXTS.get("set_notes_2026") or {}).items():
            lbl = tk.Label(
                notes_card,
                text=f"• {s_name}：{s_desc}",
                bg=T["card"],
                fg=T["sub"],
                font=F["body"],
                anchor="w",
                justify="left",
                wraplength=560,
            )
            lbl.pack(fill="x", pady=2)
            note_labels.append(lbl)

        def _sync_note_wrap(_e: tk.Event | None = None, _labels=note_labels, _host=notes_card) -> None:
            wl = max(240, _host.winfo_width() - 32)
            for _lb in _labels:
                _lb.configure(wraplength=wl)

        notes_card.bind("<Configure>", _sync_note_wrap)

        # 下方：套装成套容量表（整行全宽，避免 150% DPI 下提示列被挤压）
        table_host = tk.Frame(wrap, bg=T["bg"])
        table_host.pack(fill="x", pady=(gap, 0))

        balanced_txt = gear_analysis.TEXTS["hunt_hints"]["balanced"]
        scarce_txt = gear_analysis.TEXTS["hunt_hints"]["scarce"]
        cap_rows: list[list[tuple[str, str]]] = []
        for s_name, info in set_cap.items():
            full_cnt = int(info.get("max_full_sets", 0))
            hint_str = str(info.get("hint") or "")
            hint_col = T["green"] if hint_str == balanced_txt else (T["sub"] if hint_str == scarce_txt else T["gold"])
            cap_rows.append(
                [
                    (s_name, T["text"]),
                    (str(info.get("total", 0)), T["text"]),
                    (f"{info.get('left_count', 0)}/{info.get('right_count', 0)}", T["sub"]),
                    (str(full_cnt), T["blue_hi"] if full_cnt > 0 else T["sub"]),
                    (f"{float(info.get('avg_valid_gs', 0.0)):.1f}", T["text"]),
                    (hint_str, hint_col),
                ]
            )

        tbl = CanvasTable(
            table_host,
            UI_TEXTS["set_cap_title"],
            UI_TEXTS["set_cap_headers"],
            UI_CONST["set_cap_cols"],
            cap_rows,
            self._f_title,
            self._f_body,
        )
        tbl.pack(fill="x")

    # ---------- Tab2：右三件稀缺矩阵 + 6×6 木桶短板热力 ----------
    def _build_tab_matrix(self, parent: tk.Misc, res: dict[str, Any]) -> None:
        gap = UI_CONST["card_gap"]
        sub = res.get("submodules") or {}
        rm = sub.get("right_three_matrix") or {}
        hm = sub.get("heatmap_6x6") or {}

        wrap = tk.Frame(parent, bg=T["bg"])
        wrap.pack(fill="x")

        left_col = tk.Frame(wrap, bg=T["bg"], width=UI_CONST["tab2_left_w"])
        left_col.pack(side="left", fill="y", padx=(0, gap))

        rm_rows: list[list[tuple[str, str]]] = []
        for part_name, buckets in rm.items():
            for stat_name, info in (buckets or {}).items():
                cnt = int(info.get("count", 0))
                avg_gs = float(info.get("avg_valid_gs", 0.0))
                rm_rows.append(
                    [
                        (part_name, T["sub"]),
                        (stat_name, T["text"]),
                        (str(cnt), T["text"] if cnt > 0 else T["red"]),
                        (f"{avg_gs:.1f}" if cnt > 0 else UI_TEXTS["cell_na"], T["blue_hi"] if cnt > 0 else T["sub"]),
                    ]
                )

        rm_tbl = CanvasTable(
            left_col,
            UI_TEXTS["right_matrix_title"],
            UI_TEXTS["right_matrix_headers"],
            UI_CONST["right_mat_cols"],
            rm_rows,
            self._f_title,
            self._f_body,
        )
        rm_tbl.configure(width=UI_CONST["tab2_left_w"])
        rm_tbl.pack(fill="x")

        right_col = tk.Frame(wrap, bg=T["bg"])
        right_col.pack(side="left", fill="both", expand=True)

        cell_h = max(UI_CONST["heatmap_cell_min_h"], self._lh_body + 14)
        hm_h = (self._lh_title + 22) + (self._lh_body + 12) + 6 * cell_h + (self._lh_body * 3 + 24)
        hm_cv = tk.Canvas(right_col, height=hm_h, bg=T["bg"], highlightthickness=0)
        hm_cv.pack(fill="x")
        hm_cv.bind("<Configure>", lambda _e, c=hm_cv: self._draw_heatmap(c, hm, cell_h))

    def _draw_heatmap(self, cv: tk.Canvas, hm: dict[str, Any], cell_h: int) -> None:
        cv.delete("all")
        w = max(320, cv.winfo_width())
        h = max(240, cv.winfo_height())
        rounded(cv, 1, 1, w - 1, h - 1, r=UI_CONST["card_r"], fill=T["card"], outline=T["border"])
        cv.create_text(16, 22, text=UI_TEXTS["heatmap_title"], fill=T["text"], font=F["title"], anchor="w")

        weak_th = float(hm.get("weak_threshold", 40.0))
        strong_th = float(UI_CONST["heatmap_strong_gs"])
        cells = hm.get("cells") or {}
        parts = list(gear_analysis.ANALYSIS_CFG["parts_order"])
        dims = list(gear_analysis.TEXTS["dims"].values())

        part_col_w = max(54, max((self._f_body.measure(p) for p in parts), default=40) + 18)
        gx0 = 14 + part_col_w
        cw = max(42.0, (w - gx0 - 14) / max(1, len(dims)))
        hdr_y = self._lh_title + 22
        hdr_h = self._lh_body + 10

        for j, d_name in enumerate(dims):
            cx = gx0 + cw * (j + 0.5)
            cv.create_text(
                cx,
                hdr_y + hdr_h / 2,
                text=_ellipsize(d_name, self._f_body, int(cw - 4)),
                fill=T["sub"],
                font=F["body"],
            )

        y0 = hdr_y + hdr_h
        for i, p_name in enumerate(parts):
            ry1 = y0 + i * cell_h
            ry2 = ry1 + cell_h - 4
            cv.create_text(14, (ry1 + ry2) / 2, text=p_name, fill=T["text"], font=F["body"], anchor="w")
            p_row = cells.get(p_name) or {}
            for j, d_name in enumerate(dims):
                cx1 = gx0 + j * cw + 2
                cx2 = gx0 + (j + 1) * cw - 2
                val = p_row.get(d_name, 0.0) if d_name in p_row else None
                # 仅 鞋子 × 先手抢速 为 None（显示中性灰 "—"）；缺部位的 0.0 按短板格标红
                if val is None:
                    bg_c, bd_c, fg_c = T["btn"], T["border"], T["sub"]
                    txt = UI_TEXTS["cell_na"]
                else:
                    fv = float(val)
                    txt = f"{fv:.1f}"
                    if fv < weak_th:
                        bg_c, bd_c, fg_c = T["card"], T["red"], T["red"]
                    elif fv >= strong_th:
                        bg_c, bd_c, fg_c = T["btn"], T["green"], T["green"]
                    else:
                        bg_c, bd_c, fg_c = T["btn"], T["border"], T["blue_hi"]
                cv.create_rectangle(cx1, ry1, cx2, ry2, fill=bg_c, outline=bd_c)
                cv.create_text((cx1 + cx2) / 2, (ry1 + ry2) / 2, text=txt, fill=fg_c, font=F["mono"])

        weak_cnt = int(hm.get("weak_spots_count", 0))
        weakest_5 = hm.get("weakest_5") or []
        fy = y0 + len(parts) * cell_h + 6
        if weak_cnt > 0:
            items_txt = "、".join(f"{x['part']}-{x['dim']}({float(x['top3_avg']):.1f})" for x in weakest_5)
            foot_txt = UI_TEXTS["heatmap_summary"].format(
                label=UI_TEXTS["weak_spot_label"],
                thresh=f"{weak_th:.0f}",
                count=weak_cnt,
                items=items_txt,
            )
            foot_col = T["red"]
        else:
            foot_txt = UI_TEXTS["heatmap_none_weak"].format(
                label=UI_TEXTS["weak_spot_label"],
                thresh=f"{weak_th:.0f}",
            )
            foot_col = T["green"]
        cv.create_text(14, fy, text=foot_txt, fill=foot_col, font=F["body"], anchor="nw", width=w - 28)

    # ---------- Tab3：待重铸 85 金矿 + 已穿戴低效/歪胚清单 ----------
    def _build_tab_actions(self, parent: tk.Misc, res: dict[str, Any]) -> None:
        gap = UI_CONST["card_gap"]
        act = (res.get("submodules") or {}).get("action_lists") or {}

        gm_cnt = int(act.get("reforge_goldmine_count", 0))
        gm_list = act.get("reforge_goldmine_top")
        if gm_list is None:
            gm_list = act.get("reforge_goldmine_sample") or []

        gm_rows: list[list[tuple[str, str]]] = []
        for it in gm_list:
            spd = int(it.get("speed", 0))
            gm_rows.append(
                [
                    (str(it.get("id", "")), T["sub"]),
                    (str(it.get("part", "")), T["text"]),
                    (str(it.get("name", "")), T["text"]),
                    (str(it.get("set", "")), T["blue_hi"]),
                    (str(spd), T["gold"] if spd >= 14 else T["text"]),
                    (str(it.get("best_dim", "")), T["sub"]),
                    (f"{float(it.get('best_valid_gs', 0.0)):.2f}", T["green"]),
                    (str(it.get("panel_score", 0)), T["text"]),
                ]
            )
        gm_foot = UI_TEXTS["list_limit"].format(shown=len(gm_rows), total=gm_cnt) if len(gm_rows) < gm_cnt else ""
        gm_tbl = CanvasTable(
            parent,
            UI_TEXTS["goldmine_title"].format(n=gm_cnt),
            UI_TEXTS["goldmine_headers"],
            UI_CONST["goldmine_cols"],
            gm_rows,
            self._f_title,
            self._f_body,
            footer_note=gm_foot,
            on_row_click=lambda i, rows=gm_list: self._on_action_row_click(rows, i),
        )
        gm_tbl.pack(fill="x", pady=(0, gap))

        ie_cnt = int(act.get("inefficient_equipped_count", 0))
        ie_list = act.get("inefficient_equipped_top")
        if ie_list is None:
            ie_list = act.get("inefficient_equipped_sample") or []

        lv_map = UI_TEXTS["level_short"]
        yes_txt, no_txt = UI_TEXTS["yes_no"]
        ie_rows: list[list[tuple[str, str]]] = []
        for it in ie_list:
            raw_lv = str(it.get("level", ""))
            is_mm = bool(it.get("mismatched", False))
            ie_rows.append(
                [
                    (str(it.get("id", "")), T["sub"]),
                    (str(it.get("part", "")), T["text"]),
                    (str(it.get("name", "")), T["text"]),
                    (lv_map.get(raw_lv, raw_lv), T["sub"]),
                    (f"{float(it.get('raw_gs', 0.0)):.2f}", T["text"]),
                    (str(it.get("best_dim", "")), T["sub"]),
                    (f"{float(it.get('best_valid_gs', 0.0)):.2f}", T["red"]),
                    (yes_txt if is_mm else no_txt, T["gold"] if is_mm else T["sub"]),
                ]
            )
        ie_foot = UI_TEXTS["list_limit"].format(shown=len(ie_rows), total=ie_cnt) if len(ie_rows) < ie_cnt else ""
        ie_tbl = CanvasTable(
            parent,
            UI_TEXTS["ineff_title"].format(n=ie_cnt),
            UI_TEXTS["ineff_headers"],
            UI_CONST["ineff_cols"],
            ie_rows,
            self._f_title,
            self._f_body,
            footer_note=ie_foot,
            on_row_click=lambda i, rows=ie_list: self._on_action_row_click(rows, i),
        )
        ie_tbl.pack(fill="x")


if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    win = GearAnalysisWindow(root)
    win.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()
