"""统计窗口（2.0）：KPI 卡片 + 效率看板 + 双图表，纯 Tkinter 深色主题。"""
from __future__ import annotations

import tkinter as tk
from datetime import datetime
from tkinter import messagebox

import stats

PERIODS = (("日", "day"), ("周", "week"), ("月", "month"), ("年", "year"))

T = {
    "bg": "#121418",
    "card": "#1C2026",
    "btn": "#262B35",
    "active": "#3B82F6",
    "border": "#2A303C",
    "text": "#F3F4F6",
    "sub": "#8A94A6",
    "blue": "#3B82F6",
    "blue_hi": "#60A5FA",
    "purple": "#A855F7",
    "purple_hi": "#C084FC",
    "red": "#F43F5E",
    "gold": "#F59E0B",
    "green": "#10B981",
}

F = {
    "kpi": ("Microsoft YaHei UI", 20, "bold"),
    "kpi_small": ("Microsoft YaHei UI", 16, "bold"),
    "title": ("Microsoft YaHei UI", 10, "bold"),
    "body": ("Microsoft YaHei UI", 9),
    "mono": ("Consolas", 9),
}


def rounded(cv: tk.Canvas, x1, y1, x2, y2, r=10, **kw):
    """圆角矩形。"""
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return cv.create_polygon(pts, smooth=True, **kw)


def fmt_num(v: float) -> str:
    v = int(v)
    if v >= 1e8:
        return f"{v / 1e8:.1f}亿"
    if v >= 1e4:
        return f"{v / 1e4:.1f}万"
    return f"{v:,}"


class KpiCard(tk.Canvas):
    def __init__(self, parent, title: str, accent: str, width=223, height=118):
        super().__init__(parent, width=width, height=height, bg=T["bg"], highlightthickness=0)
        self.w, self.h = width, height
        rounded(self, 1, 1, width - 1, height - 1, r=12, fill=T["card"], outline=T["border"])
        self.create_line(14, 3, width - 14, 3, fill=accent, width=3)
        self.create_text(16, 24, text=title, fill=T["sub"], font=F["title"], anchor="w")
        self.val = self.create_text(16, 62, text="—", fill=accent, font=F["kpi"], anchor="w")
        self.sub = self.create_text(16, 96, text="", fill=T["sub"], font=F["body"], anchor="w")

    def update_values(self, value: str, subtext: str) -> None:
        self.itemconfigure(self.val, text=value)
        self.itemconfigure(self.sub, text=subtext)


class Segmented(tk.Frame):
    """深色胶囊切换（无原生白底）。"""

    def __init__(self, parent, options, default, command=None):
        super().__init__(parent, bg=T["card"])
        self.var = tk.StringVar(value=default)
        for text, val in options:
            tk.Radiobutton(
                self, text=text, value=val, variable=self.var, indicatoron=False,
                bg=T["card"], fg=T["sub"], selectcolor=T["active"], bd=0,
                activebackground=T["btn"], activeforeground=T["text"],
                font=F["body"], padx=12, pady=3, cursor="hand2",
                command=lambda: command(self.var.get()) if command else None,
            ).pack(side="left", padx=1)


class Chart(tk.Canvas):
    """柱状图：支持单色 / 双色并列，只画有数据的日期。"""

    def __init__(self, parent, height=330):
        super().__init__(parent, height=height, bg=T["card"], highlightthickness=0)
        self.bind("<Configure>", lambda _e: self._redraw())
        self._series_a: list[tuple[str, float]] = []
        self._series_b: list[tuple[str, float]] = []
        self._title = ""
        self._color_a = T["blue"]
        self._color_b = T["purple"]
        self._name_a = ""
        self._name_b = ""
        self._extra_top = None  # 供外部放控件

    def set_data(self, series_a, series_b=(), title="", color_a=T["blue"], color_b=T["purple"],
                 name_a="", name_b=""):
        self._title = title
        self._color_a, self._color_b = color_a, color_b
        self._name_a, self._name_b = name_a, name_b
        # 只保留有数据的桶
        keep = {k for k, v in series_a if v} | {k for k, v in series_b if v}
        self._series_a = [(k, v) for k, v in series_a if k in keep]
        self._series_b = [(k, v) for k, v in series_b if k in keep]
        self._redraw()

    def _redraw(self) -> None:
        self.delete("all")
        w = max(320, self.winfo_width())
        h = max(160, self.winfo_height())
        rounded(self, 1, 1, w - 1, h - 1, r=12, fill=T["card"], outline=T["border"])

        # Header 独立区域（避免和纵轴数字重叠）
        self.create_text(18, 24, text=self._title, fill=T["text"], font=F["title"], anchor="w")
        legend_x = w - 20
        if self._series_b:
            self.create_rectangle(legend_x - 240, 19, legend_x - 229, 30, fill=self._color_a, width=0)
            self.create_text(legend_x - 223, 24, text=self._name_a, fill=T["sub"], font=F["body"], anchor="w")
            self.create_rectangle(legend_x - 130, 19, legend_x - 119, 30, fill=self._color_b, width=0)
            self.create_text(legend_x - 113, 24, text=self._name_b, fill=T["sub"], font=F["body"], anchor="w")

        left, right, top, bottom = 66, w - 24, 56, h - 34
        pw, ph = max(10, right - left), max(10, bottom - top)

        pairs = [(k, a, b) for (k, a), (_, b) in zip(self._series_a, self._series_b)] if self._series_b else [(k, a, 0) for k, a in self._series_a]
        values = [max(a, b) for _k, a, b in pairs]
        vmax = max(values) if values else 0
        if vmax <= 0:
            self.create_text(left + pw / 2, top + ph / 2, text="暂无数据", fill=T["sub"], font=F["body"])
            return

        for i in range(4):
            y = bottom - ph * i / 3
            self.create_line(left - 8, y, right, y, fill=T["border"], dash=(3, 3))
            self.create_text(left - 12, y, text=fmt_num(vmax * i / 3), fill=T["sub"],
                             font=F["mono"], anchor="e")

        n = len(pairs)
        slot = pw / max(1, n)
        bar_w = max(8, min(46, slot * 0.62))
        step = max(1, (n + 4) // 6)
        for i, (label, a, b) in enumerate(pairs):
            cx = left + slot * (i + 0.5)
            if self._series_b:
                half = bar_w / 2
                if a > 0:
                    bh = ph * a / vmax
                    self.create_rectangle(cx - half - 1, bottom - bh, cx - 1, bottom,
                                          fill=self._color_a, width=0)
                    if n <= 14:
                        self.create_text(cx - half - 6, bottom - bh - 6, text=fmt_num(a),
                                         fill=self._color_a, font=F["mono"], anchor="e")
                if b > 0:
                    bh = ph * b / vmax
                    self.create_rectangle(cx + 1, bottom - bh, cx + half + 1, bottom,
                                          fill=self._color_b, width=0)
                    if n <= 14:
                        self.create_text(cx + half + 6, bottom - bh - 6, text=fmt_num(b),
                                         fill=self._color_b, font=F["mono"], anchor="w")
            else:
                if a > 0:
                    bh = ph * a / vmax
                    self.create_rectangle(cx - bar_w / 2, bottom - bh, cx + bar_w / 2, bottom,
                                          fill=self._color_a, width=0)
                    if n <= 16:
                        self.create_text(cx, bottom - bh - 13, text=fmt_num(a),
                                         fill=self._color_a, font=F["mono"])
            if i % step == 0:
                self.create_text(cx, bottom + 14, text=label, fill=T["sub"], font=F["mono"])


class StatsWindow(tk.Toplevel):
    def __init__(self, master) -> None:
        super().__init__(master)
        self.title("📊 数据统计")
        self.geometry("960x1040")
        self.minsize(900, 760)
        self.configure(bg=T["bg"])
        self.period = "day"
        self.consume_metric = "sky"
        self._after_id = None

        self._build_topbar()
        self._build_kpi()
        self._build_mid()
        self._build_charts()

        self.refresh()
        self._tick()

    # ---------- 界面 ----------
    def _build_topbar(self) -> None:
        bar = tk.Frame(self, bg=T["bg"], padx=16, pady=10)
        bar.pack(fill="x")
        tk.Label(bar, text="周期", bg=T["bg"], fg=T["sub"], font=F["title"]).pack(side="left", padx=(0, 8))
        seg = Segmented(bar, PERIODS, "日", command=self._set_period)
        seg.pack(side="left")
        self._period_seg = seg

        tk.Button(bar, text="清除数据…", bg=T["btn"], fg=T["red"], bd=0, padx=12, pady=4,
                  activebackground=T["border"], activeforeground=T["red"],
                  font=F["body"], cursor="hand2", command=self._clear).pack(side="right", padx=(8, 0))
        tk.Button(bar, text="🎽 红装记录", bg=T["btn"], fg=T["gold"], bd=0, padx=12, pady=4,
                  activebackground=T["border"], activeforeground=T["gold"],
                  font=F["body"], cursor="hand2", command=self._open_gear).pack(side="right", padx=(8, 0))
        tk.Button(bar, text="刷新", bg=T["btn"], fg=T["text"], bd=0, padx=12, pady=4,
                  activebackground=T["border"], activeforeground=T["text"],
                  font=F["body"], cursor="hand2", command=self.refresh).pack(side="right")

    def _build_kpi(self) -> None:
        row = tk.Frame(self, bg=T["bg"], padx=16)
        row.pack(fill="x", pady=(0, 10))
        self.card_cov = KpiCard(row, "圣约书签（本周期）", T["blue"])
        self.card_mys = KpiCard(row, "神秘奖牌（本周期）", T["purple"])
        self.card_cost = KpiCard(row, "本周期消耗", T["red"])
        self.card_value = KpiCard(row, "性价比", T["green"])
        for i, c in enumerate((self.card_cov, self.card_mys, self.card_cost, self.card_value)):
            c.pack(side="left", padx=(0 if i == 0 else 12, 0))

    def _build_mid(self) -> None:
        row = tk.Frame(self, bg=T["bg"], padx=16)
        row.pack(fill="x", pady=(0, 12))
        self.mid_left = tk.Canvas(row, width=456, height=118, bg=T["bg"], highlightthickness=0)
        self.mid_left.pack(side="left")
        self.mid_right = tk.Canvas(row, width=456, height=118, bg=T["bg"], highlightthickness=0)
        self.mid_right.pack(side="right")

    def _build_charts(self) -> None:
        area = tk.Frame(self, bg=T["bg"], padx=16)
        area.pack(fill="both", expand=True, pady=(0, 12))
        self.chart_out = Chart(area, height=340)
        self.chart_out.pack(fill="x", pady=(0, 12))
        self.chart_cost = Chart(area, height=320)
        self.chart_cost.pack(fill="both", expand=True)
        self.consume_seg = Segmented(self.chart_cost, (("天空石", "sky"), ("金币", "gold")), "sky",
                                     command=self._set_consume)
        self.consume_seg.place(in_=self.chart_cost, relx=1.0, x=-16, y=12, anchor="ne")

    # ---------- 交互 ----------
    def _set_period(self, key: str) -> None:
        self.period = key
        self.refresh()

    def _set_consume(self, key: str) -> None:
        self.consume_metric = key
        self.refresh()

    def _open_gear(self) -> None:
        try:
            from gear_ui import GearWindow

            GearWindow(self)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("红装记录", f"打不开红装记录：{exc}", parent=self)

    def _clear(self) -> None:
        win = tk.Toplevel(self)
        win.title("清除数据")
        win.configure(bg=T["bg"])
        win.geometry("460x320")
        tk.Label(win, text="选择要删除的时间范围（会先自动归档一份）：", bg=T["bg"], fg=T["text"],
                 font=F["body"]).pack(anchor="w", padx=12, pady=10)
        var = tk.StringVar(value="7")
        for text, val in (("最近 1 天", "1"), ("最近 7 天", "7"), ("最近 30 天", "30"),
                          ("最近 1 年", "365"), ("全部历史", "all")):
            tk.Radiobutton(win, text=text, value=val, variable=var, bg=T["bg"], fg=T["text"],
                           selectcolor=T["card"], activebackground=T["bg"],
                           font=F["body"]).pack(anchor="w", padx=24)

        def do_clear() -> None:
            v = var.get()
            if not messagebox.askyesno("确认清除", "清除后统计会重新开始累计（原数据会归档保留）。继续？", parent=win):
                return
            days = None if v == "all" else float(v)
            removed, archive = stats.prune(days)
            win.destroy()
            messagebox.showinfo("完成", f"已删除 {removed} 条记录\n归档：{archive.name if archive else '无'}", parent=self)
            self.refresh()

        tk.Button(win, text="确认清除", bg=T["btn"], fg=T["text"], bd=0, padx=16, pady=5,
                  font=F["body"], command=do_clear).pack(pady=12)

    # ---------- 数据 ----------
    def refresh(self) -> None:
        events = stats.load_events()
        t_period = stats.totals(events, since=self._period_start())
        t_session = stats.session_totals(events)
        sky_avg, gold_avg = stats.avg_cost(t_period)

        cov_n = t_period["covenant_n"]
        mys_n = t_period["mystic_n"]
        total_n = cov_n + mys_n or 1
        self.card_cov.update_values(
            f"+{t_period['covenant']:,}",
            f"{cov_n} 次购买 · 占 {cov_n / total_n * 100:.0f}%",
        )
        self.card_mys.update_values(
            f"+{t_period['mystic']:,}",
            f"{mys_n} 次购买 · 占 {mys_n / total_n * 100:.0f}%",
        )
        self.card_cost.update_values(
            f"-{t_period['sky']:,} 石",
            f"金币 {('-' + format(t_period['gold'], ',')) if t_period['gold'] else '0'} · 刷新 {t_period['refresh']} 次",
        )

        if cov_n == 0:
            grade, tip = "—", "本周期还没有出货"
        elif sky_avg <= 600:
            grade, tip = "很划算", f"{sky_avg:.0f} 石/50本 · 期望 758"
        elif sky_avg <= 950:
            grade, tip = "正常", f"{sky_avg:.0f} 石/50本 · 期望 758"
        else:
            grade, tip = "偏贵", f"{sky_avg:.0f} 石/50本 · 期望 758"
        self.card_value.update_values(grade, tip)

        self._draw_session(t_session)
        self._draw_ratio(cov_n, mys_n, sky_avg, gold_avg)
        self._draw_charts(events)

    def _draw_session(self, s: dict) -> None:
        cv = self.mid_left
        cv.delete("all")
        w, h = 456, 118
        rounded(cv, 1, 1, w - 1, h - 1, r=12, fill=T["card"], outline=T["border"])
        cv.create_text(16, 22, text="⚡ 本次运行", fill=T["text"], font=F["title"], anchor="w")
        cv.create_text(w - 16, 22, text=f"刷新 {s['refresh']} 次", fill=T["sub"], font=F["body"], anchor="e")
        items = [
            ("圣约书签", f"+{s['covenant']:,}", T["blue"]),
            ("神秘奖牌", f"+{s['mystic']:,}", T["purple"]),
            ("消耗天空石", f"-{s['sky']:,}", T["red"]),
        ]
        for i, (label, val, col) in enumerate(items):
            x = 16 + i * 146
            cv.create_text(x, 58, text=label, fill=T["sub"], font=F["body"], anchor="w")
            cv.create_text(x, 86, text=val, fill=col, font=F["kpi_small"], anchor="w")

    def _draw_ratio(self, cov_n: int, mys_n: int, sky_avg: float, gold_avg: float) -> None:
        cv = self.mid_right
        cv.delete("all")
        w, h = 456, 118
        rounded(cv, 1, 1, w - 1, h - 1, r=12, fill=T["card"], outline=T["border"])

        total = cov_n + mys_n
        ratio_txt = f"书签 : 神秘 = {cov_n / mys_n:.1f} : 1" if mys_n else "书签 : 神秘 = —"
        cv.create_text(16, 22, text=ratio_txt, fill=T["sub"], font=F["body"], anchor="w")

        bx1, bx2, by = 16, w - 16, 38
        if total:
            split = bx1 + int((bx2 - bx1) * cov_n / total)
        else:
            split = bx1
        cv.create_rectangle(bx1, by, split, by + 10, fill=T["blue"], width=0)
        cv.create_rectangle(split + 2, by, bx2, by + 10, fill=T["purple"], width=0)

        cv.create_text(16, 68, text=f"每 50 书签成本 {sky_avg:.1f} 石", fill=T["sub"], font=F["body"], anchor="w")
        cv.create_text(w - 16, 68, text=f"金币 {gold_avg:,.0f}", fill=T["sub"], font=F["body"], anchor="e")

        gy1, gy2, gy = 16, w - 16, 86
        seg = (gy2 - gy1) / 3
        cv.create_rectangle(gy1, gy, gy1 + seg, gy + 8, fill=T["green"], width=0)
        cv.create_rectangle(gy1 + seg + 1, gy, gy1 + seg * 2, gy + 8, fill=T["blue"], width=0)
        cv.create_rectangle(gy1 + seg * 2 + 1, gy, gy2, gy + 8, fill=T["red"], width=0)
        pos = max(0.0, min(1.0, sky_avg / 1200.0))
        cx = gy1 + (gy2 - gy1) * pos
        cv.create_polygon(cx - 5, gy - 7, cx + 5, gy - 7, cx, gy - 1, fill=T["text"])

    def _draw_charts(self, events: list[dict]) -> None:
        cov = stats.series(events, self.period, "covenant")
        mys = stats.series(events, self.period, "mystic")
        cost = stats.series(events, self.period, self.consume_metric)
        self.chart_out.set_data(
            cov, mys, "产出趋势", T["blue"], T["purple"], "圣约书签", "神秘奖牌"
        )
        title = "消耗金币" if self.consume_metric == "gold" else "消耗天空石"
        self.chart_cost.set_data(cost, (), title, T["red"], T["gold"])

    def _period_start(self) -> datetime:
        now = datetime.now()
        if self.period == "day":
            return now.replace(hour=0, minute=0, second=0, microsecond=0)
        if self.period == "week":
            return now.replace(hour=0, minute=0, second=0, microsecond=0) - __import__("datetime").timedelta(days=now.weekday())
        if self.period == "month":
            return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

    def _tick(self) -> None:
        try:
            if self.winfo_exists():
                self.refresh()
                self._after_id = self.after(3000, self._tick)
        except Exception:  # noqa: BLE001
            pass

    def destroy(self) -> None:
        if self._after_id:
            try:
                self.after_cancel(self._after_id)
            except Exception:  # noqa: BLE001
                pass
        super().destroy()
