"""PRTS 光学线框终端组件库（纯 Tkinter + Pillow 2x SSAA，通透双层线框 + 悬停动态特效）。

- 除顶部防骗声明保留警示红外，全界面严格仅使用黑、白、灰三色；
- 摒弃沉重的纯黑实心色块，采用「垂直光学微渐变 + 双层内嵌切角线框 + 右侧微十字阵列」；
- 内置四大悬停动态特效：RGBA 45° 光学扫光、双层齿圈对转咬合、四角准星收缩、字符解码；
- 挂机静置时 0.0% CPU 占用（所有动画仅在鼠标交互或数值变动时按需运行 <= 180ms）。
"""
from __future__ import annotations

import ctypes
import math
import random
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import Callable

from PIL import Image, ImageDraw, ImageTk

# ---------------------------------------------------------------------------
# 1. 严格黑白灰光学调色板（冰川浅色 LIGHT / 曜石深色 DARK）
# ---------------------------------------------------------------------------
LIGHT = {
    "bg": "#EAE9E4",          # 工业暖灰底板
    "panel": "#E1E0DA",       # 次级容器底色
    "card_top": "#FAF9F6",    # 玻璃卡顶部高光色
    "card_bot": "#EFECE6",    # 玻璃卡底部微阴影色
    "card_hover_top": "#FFFFFF",
    "card_hover_bot": "#F5F4F0",
    "sel_top": "#FFFFFF",     # 选中态高透亮白顶
    "sel_bot": "#E6E8EC",     # 选中态冷银灰底
    "bevel_hi": "#FFFFFF",    # 玻璃顶边 1px 折射高光
    "ink": "#121316",         # 主文字/主线框（深炭黑）
    "mid": "#4E525A",         # 二级文字（中灰）
    "sub": "#7B808A",         # 辅助文字（浅灰）
    "dim": "#C8C6BE",         # 常态外框线
    "inner_line": "#DCDBD4",  # 双层内嵌细线
    "line_hi": "#121316",     # 激活/选中主边框
    "dot": "#D2D0C8",         # 微十字点阵色
    "watermark": "#D8D6CE",   # 常态大号数字色
    "watermark_sel": "#121316",
    "warn_red": "#C62828",    # 唯一允许的彩色：顶部防骗警示红
    "log_bg": "#F4F3EF",
    "beam_rgb": (255, 255, 255),
    "beam_alpha": 150,
}

DARK = {
    "bg": "#0D0E11",          # 曜石主背景
    "panel": "#131519",       # 次级容器底色
    "card_top": "#1B1E24",    # 玻璃卡顶部微亮色
    "card_bot": "#14161B",    # 玻璃卡底部深色
    "card_hover_top": "#232730",
    "card_hover_bot": "#181B22",
    "sel_top": "#2A2F3A",     # 选中态通透石墨顶（告别死白刺眼块）
    "sel_bot": "#1B1E26",     # 选中态通透石墨底
    "bevel_hi": "#343946",    # 玻璃顶边 1px 折射高光
    "ink": "#ECEFF4",         # 主文字（冷白）
    "mid": "#9499A3",         # 二级文字
    "sub": "#656A75",         # 辅助文字
    "dim": "#282C35",         # 常态外框线
    "inner_line": "#1E222A",  # 双层内嵌细线
    "line_hi": "#ECEFF4",     # 激活/选中高亮白框
    "dot": "#252932",         # 微十字点阵色
    "watermark": "#262A34",   # 常态大号数字色
    "watermark_sel": "#ECEFF4",
    "warn_red": "#E04547",    # 唯一允许的彩色：顶部防骗警示红
    "log_bg": "#090A0C",
    "beam_rgb": (255, 255, 255),
    "beam_alpha": 38,
}

C: dict = dict(LIGHT)
MODE: dict[str, str] = {"name": "light"}

FALLBACK = ("Microsoft YaHei UI", "Segoe UI", "SimHei")
FONT_UI = "Microsoft YaHei UI"
FONT_MONO = "Consolas"

_IMG_CACHE: dict[tuple, ImageTk.PhotoImage] = {}
_REDRAW: list[Callable[[], None]] = []
_ROOT_REF: list[tk.Misc] = []


def pick_font() -> str:
    try:
        fams = set(tkfont.families())
    except Exception:  # noqa: BLE001
        return "Microsoft YaHei UI"
    for f in FALLBACK:
        if f in fams:
            return f
    return "Microsoft YaHei UI"


def set_theme(name: str) -> None:
    """切换 light / dark 主题并重绘所有组件。"""
    global C, FONT_UI
    target = "dark" if name == "dark" else "light"
    MODE["name"] = target
    C.clear()
    C.update(DARK if target == "dark" else LIGHT)
    FONT_UI = pick_font()
    _IMG_CACHE.clear()
    for root in list(_ROOT_REF):
        try:
            if root.winfo_exists():
                enable_dark_titlebar(root, dark=(target == "dark"))
        except Exception:  # noqa: BLE001
            pass
    for cb in list(_REDRAW):
        try:
            cb()
        except Exception:  # noqa: BLE001
            pass


def on_theme_change(cb: Callable[[], None]) -> None:
    if cb not in _REDRAW:
        _REDRAW.append(cb)


def enable_dark_titlebar(win: tk.Misc, dark: bool = True) -> None:
    try:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        val = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), 4) == 0:
                break
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# 2. 精密微动效调度器（Quartic Out 急起急停，单次 <= 180ms，挂机 0% CPU）
# ---------------------------------------------------------------------------
class _Animator:
    @staticmethod
    def ease_out_quart(t: float) -> float:
        return 1.0 - (1.0 - t) ** 4

    @classmethod
    def run(
        cls,
        widget: tk.Misc,
        duration_ms: int,
        step_fn: Callable[[float], None],
        done_fn: Callable[[], None] | None = None,
        tag: str = "anim",
    ) -> None:
        attr = f"_prts_job_{tag}"
        old = getattr(widget, attr, None)
        if old is not None:
            try:
                widget.after_cancel(old)
            except Exception:  # noqa: BLE001
                pass
            setattr(widget, attr, None)

        frames = max(3, min(12, duration_ms // 15))
        state = {"f": 0}

        def _tick() -> None:
            if not widget.winfo_exists():
                return
            state["f"] += 1
            t = min(1.0, state["f"] / frames)
            try:
                step_fn(cls.ease_out_quart(t))
            except Exception:  # noqa: BLE001
                return
            if t < 1.0:
                setattr(widget, attr, widget.after(15, _tick))
            else:
                setattr(widget, attr, None)
                if done_fn:
                    try:
                        done_fn()
                    except Exception:  # noqa: BLE001
                        pass

        _tick()


# ---------------------------------------------------------------------------
# 3. 全局 ttk 样式与防裁字布局优化
# ---------------------------------------------------------------------------
def setup_dark_style(root: tk.Misc) -> ttk.Style:
    if root not in _ROOT_REF:
        _ROOT_REF.append(root)
    style = ttk.Style(root)

    def _apply() -> None:
        try:
            style.theme_use("clam")
        except Exception:  # noqa: BLE001
            pass
        root.configure(bg=C["bg"])
        enable_dark_titlebar(root, dark=(MODE["name"] == "dark"))

        style.configure(
            ".",
            background=C["bg"],
            foreground=C["ink"],
            fieldbackground=C["card_top"],
            bordercolor=C["dim"],
            lightcolor=C["bg"],
            darkcolor=C["bg"],
            focuscolor=C["bg"],
        )
        style.configure("TFrame", background=C["bg"])
        style.configure("TLabel", background=C["bg"], foreground=C["ink"])
        style.configure("Sub.TLabel", background=C["bg"], foreground=C["sub"], font=(FONT_UI, 9))

        # 工具按钮：通透细框，悬停时加深边框与底色，不再变死黑块
        style.configure(
            "TButton",
            background=C["card_top"],
            foreground=C["ink"],
            bordercolor=C["dim"],
            lightcolor=C["bevel_hi"],
            darkcolor=C["card_bot"],
            focuscolor=C["card_top"],
            relief="solid",
            borderwidth=1,
            padding=(9, 4),
            font=(FONT_UI, 9, "bold"),
        )
        style.map(
            "TButton",
            background=[("pressed", C["panel"]), ("active", C["sel_bot"]), ("disabled", C["panel"])],
            foreground=[("disabled", C["sub"])],
            bordercolor=[("active", C["line_hi"]), ("disabled", C["dim"])],
        )

        # 输入框：光学浅凹槽 + 聚焦加深边框
        style.configure(
            "TEntry",
            fieldbackground=C["card_top"],
            foreground=C["ink"],
            insertcolor=C["ink"],
            bordercolor=C["dim"],
            lightcolor=C["bevel_hi"],
            darkcolor=C["card_bot"],
            borderwidth=1,
            padding=(5, 3),
        )
        style.map(
            "TEntry",
            fieldbackground=[("focus", C["card_hover_top"]), ("disabled", C["panel"])],
            foreground=[("disabled", C["sub"])],
            bordercolor=[("focus", C["line_hi"]), ("!focus", C["dim"])],
        )

        style.configure(
            "TCheckbutton",
            background=C["bg"],
            foreground=C["ink"],
            indicatorcolor=C["card_top"],
            indicatorrelief="solid",
            focuscolor=C["bg"],
            padding=(2, 2),
        )
        style.map(
            "TCheckbutton",
            background=[("active", C["bg"])],
            indicatorcolor=[("selected", C["ink"]), ("!selected", C["card_top"])],
            foreground=[("disabled", C["sub"])],
        )

        style.configure(
            "TLabelframe",
            background=C["bg"],
            bordercolor=C["dim"],
            lightcolor=C["dim"],
            darkcolor=C["dim"],
            borderwidth=1,
            relief="solid",
        )
        style.configure("TLabelframe.Label", background=C["bg"], foreground=C["mid"], font=(FONT_UI, 9, "bold"))
        style.configure(
            "TScrollbar",
            background=C["card_top"],
            troughcolor=C["bg"],
            bordercolor=C["bg"],
            arrowcolor=C["mid"],
            relief="flat",
        )
        _polish_widget_tree(root)

    _apply()
    on_theme_change(_apply)
    root.after(30, lambda: _polish_widget_tree(root))
    return style


def _polish_widget_tree(root: tk.Misc) -> None:
    """修正说明文字字号防止右边缘裁字，并补齐第 6 格光学遥测面板。"""
    try:
        stack = [root]
        while stack:
            w = stack.pop()
            stack.extend(w.winfo_children())
            cls = w.winfo_class()
            if cls == "Text":
                w.configure(
                    bg=C["log_bg"],
                    fg=C["ink"],
                    insertbackground=C["ink"],
                    bd=0,
                    highlightthickness=1,
                    highlightbackground=C["dim"],
                    highlightcolor=C["line_hi"],
                )
            elif cls == "TLabel":
                txt = str(w.cget("text"))
                fg = str(w.cget("foreground"))
                if "（" in txt or "开源免费" in txt or "运行后" in txt or fg in ("#666", "#888", "#999"):
                    w.configure(foreground=C["sub"], font=(FONT_UI, 9))

        if PrtsTile._all:
            grid_parent = PrtsTile._all[0].master
            if grid_parent and grid_parent.winfo_exists():
                has_slot6 = any(
                    getattr(ch, "_is_telemetry_filler", False)
                    for ch in grid_parent.winfo_children()
                )
                if not has_slot6 and len(PrtsTile._all) == 5:
                    filler = _TelemetrySlot(grid_parent)
                    filler._is_telemetry_filler = True  # type: ignore[attr-defined]
                    filler.grid(row=1, column=2, sticky="ew", padx=6, pady=6)
                    grid_parent.columnconfigure(2, weight=1)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# 4. Pillow 2× 超采样：通透光学底板 + RGBA 斜向扫光束
# ---------------------------------------------------------------------------
def _parse_rgb(hex_col: str) -> tuple[int, int, int]:
    h = hex_col.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _lerp_rgb(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


def _hazard_strip(w: int, h: int, color: str, alpha: int = 210, pitch: int = 16) -> ImageTk.PhotoImage:
    w, h = max(8, int(w)), max(8, int(h))
    key = ("haz", w, h, color, alpha, pitch, MODE["name"])
    if key in _IMG_CACHE:
        return _IMG_CACHE[key]
    s = 2
    W, H, P = w * s, h * s, pitch * s
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    rgb = _parse_rgb(color)
    band = max(4, P // 2)
    for x in range(-H, W + H, P):
        d.polygon([(x, H), (x + band, H), (x + H + band, 0), (x + H, 0)], fill=(*rgb, alpha))
    photo = ImageTk.PhotoImage(img.resize((w, h), Image.Resampling.LANCZOS))
    _IMG_CACHE[key] = photo
    return photo


def _optical_card(
    w: int,
    h: int,
    cut: int,
    top_hex: str,
    bot_hex: str,
    outer_hex: str,
    inner_hex: str,
    outer_w: int = 1,
    left_bar: str | None = None,
    dot_matrix: bool = True,
) -> ImageTk.PhotoImage:
    """2倍超采样生成「垂直微渐变 + 双层内嵌切角线框 + 稀疏十字微点阵」通透底板。"""
    w, h = max(48, int(w)), max(28, int(h))
    key = (
        "opt_card", w, h, cut, top_hex, bot_hex,
        outer_hex, inner_hex, outer_w, left_bar, dot_matrix, MODE["name"],
    )
    if key in _IMG_CACHE:
        return _IMG_CACHE[key]

    s = 2
    W, H, K = w * s, h * s, cut * s

    # 1. 绘制垂直光学微渐变
    grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    c_top, c_bot = _parse_rgb(top_hex), _parse_rgb(bot_hex)
    for y in range(H):
        col = _lerp_rgb(c_top, c_bot, y / max(1, H - 1))
        gd.line([(0, y), (W, y)], fill=(*col, 255))

    # 右侧 35% 区域叠加稀疏微点阵（營造通透精密感，彻底告别密集横条纹）
    if dot_matrix:
        dot_rgb = _parse_rgb(C["dot"])
        start_x = int(W * 0.58)
        for gx in range(start_x, W - 16, 24):
            for gy in range(16, H - 16, 24):
                gd.rectangle([gx - 1, gy - 1, gx + 1, gy + 1], fill=(*dot_rgb, 180))

    # 2. 构造右下 45° 斜切遮罩
    mask = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(mask)
    pts_outer = [(1, 1), (W - 2, 1), (W - 2, H - K - 2), (W - K - 2, H - 2), (1, H - 2)]
    md.polygon(pts_outer, fill=255)

    out_img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out_img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(out_img)

    # 3. 顶部 1px 玻璃高光折射边
    bevel_rgb = _parse_rgb(C["bevel_hi"])
    d.line([(4, 3), (W - 6, 3)], fill=(*bevel_rgb, 210), width=2)

    # 4. 内层悬浮细线框（距外框 4px，形成通透双层结构）
    pad = 4 * s
    ki = max(4, K - 3 * s)
    pts_inner = [
        (pad, pad),
        (W - pad - 1, pad),
        (W - pad - 1, H - ki - pad),
        (W - ki - pad, H - pad - 1),
        (pad, H - pad - 1),
    ]
    d.polygon(pts_inner, outline=inner_hex, width=1)

    # 5. 左侧战术导轨条（选中或悬停时显现）
    if left_bar:
        d.polygon(
            [(2, 2), (5 * s, 2), (5 * s, H - 2), (2, H - 2)],
            fill=left_bar,
        )

    # 6. 外层精密主线框
    d.polygon(pts_outer, outline=outer_hex, width=outer_w * s)

    photo = ImageTk.PhotoImage(out_img.resize((w, h), Image.Resampling.LANCZOS))
    _IMG_CACHE[key] = photo
    return photo


def _shimmer_beam(h: int) -> ImageTk.PhotoImage:
    """生成带真 Alpha 渐变通道的 45° 光学扫光束（用于鼠标悬停掠光动画）。"""
    h = max(24, int(h))
    bw = 110
    key = ("beam", bw, h, MODE["name"])
    if key in _IMG_CACHE:
        return _IMG_CACHE[key]

    img = Image.new("RGBA", (bw, h), (0, 0, 0, 0))
    px = img.load()
    r, g, b = C["beam_rgb"]
    peak_a = C["beam_alpha"]
    slant = 28.0

    for y in range(h):
        shift = (y / max(1, h)) * slant
        for x in range(bw):
            # 以斜线为中心计算高斯衰减透明度
            center = (bw * 0.55) - shift
            dist = abs(x - center) / (bw * 0.36)
            if dist < 1.0:
                a = int(peak_a * ((1.0 - dist) ** 2))
                px[x, y] = (r, g, b, a)

    photo = ImageTk.PhotoImage(img)
    _IMG_CACHE[key] = photo
    return photo


def _dual_parallelogram_glass(
    w: int,
    h: int,
    split_x: int,
    slant: int,
    gap: int,
    active_left: bool,
    active_right: bool,
    hover_zone: str | None,
) -> ImageTk.PhotoImage:
    """2倍超采样绘制双平行四边形光学按钮（通透双层线框，彻底告别死黑实心块）。"""
    key = ("dual_glass", w, h, split_x, slant, gap, active_left, active_right, hover_zone, MODE["name"])
    if key in _IMG_CACHE:
        return _IMG_CACHE[key]

    s = 2
    W, H = w * s, h * s
    SP, SL, GP = split_x * s, slant * s, gap * s
    CUT = 11 * s

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 左按钮（启动）坐标
    pts_l = [(1, 8 * s), (8 * s, 1), (SP, 1), (SP - SL, H - 2), (1, H - 2)]
    in_l = [(4 * s, 10 * s), (10 * s, 4 * s), (SP - 4 * s, 4 * s), (SP - SL - 3 * s, H - 5 * s), (4 * s, H - 5 * s)]

    if active_left:
        fill_l = C["card_hover_top"] if hover_zone == "start" else C["sel_bot"]
        out_l = C["line_hi"]
        bw_l = 2 * s
    else:
        fill_l = C["panel"]
        out_l = C["dim"]
        bw_l = 1 * s

    d.polygon(pts_l, fill=fill_l, outline=out_l, width=bw_l)
    d.polygon(in_l, outline=C["inner_line"], width=1)
    if active_left:
        # 左侧高对比导轨条（点明主按钮层级，又保持内部通透）
        d.polygon([(2, 8 * s), (6 * s, 4 * s), (6 * s, H - 2), (2, H - 2)], fill=C["line_hi"])

    # 右按钮（停止）坐标
    rx_top = SP + GP
    rx_bot = SP - SL + GP
    pts_r = [(rx_top, 1), (W - 2, 1), (W - 2, H - CUT - 2), (W - CUT - 2, H - 2), (rx_bot, H - 2)]
    in_r = [
        (rx_top + 3 * s, 4 * s),
        (W - 5 * s, 4 * s),
        (W - 5 * s, H - CUT - 4 * s),
        (W - CUT - 4 * s, H - 5 * s),
        (rx_bot + 4 * s, H - 5 * s),
    ]

    if active_right:
        fill_r = C["card_hover_top"] if hover_zone == "stop" else C["sel_bot"]
        out_r = C["line_hi"]
        bw_r = 2 * s
    else:
        fill_r = C["card_top"] if hover_zone == "stop" else C["panel"]
        out_r = C["dim"]
        bw_r = 1 * s

    d.polygon(pts_r, fill=fill_r, outline=out_r, width=bw_r)
    d.polygon(in_r, outline=C["inner_line"], width=1)

    photo = ImageTk.PhotoImage(img.resize((w, h), Image.Resampling.LANCZOS))
    _IMG_CACHE[key] = photo
    return photo


# ---------------------------------------------------------------------------
# 5. 对外契约组件实现（含四大悬停动态特效）
# ---------------------------------------------------------------------------
class HazardBanner(tk.Canvas):
    """顶部防骗工业警示条（全界面唯一保留警示红的区域）。"""

    def __init__(self, parent: tk.Misc, text: str, right_text: str = "E7PILOT // NON-COMMERCIAL"):
        super().__init__(parent, height=30, bg=C["bg"], highlightthickness=0)
        self.text = text
        self.right_text = right_text
        self.bind("<Configure>", lambda _e: self._render())
        on_theme_change(self._render)

    def _render(self) -> None:
        w = max(240, self.winfo_width())
        h = 30
        self.delete("all")
        self.configure(bg=C["bg"])

        self.create_rectangle(0, 1, w - 1, h - 1, fill=C["card_top"], outline=C["dim"], width=1)
        self.create_image(1, 2, image=_hazard_strip(84, h - 4, C["warn_red"], 210, 15), anchor="nw")
        self.create_rectangle(88, 6, 91, h - 6, fill=C["warn_red"], width=0)

        self.create_text(
            100,
            h // 2,
            text=f"WARNING //  {self.text}",
            fill=C["warn_red"],
            anchor="w",
            font=(FONT_UI, 10, "bold"),
        )
        if w > 660:
            self.create_text(
                w - 12,
                h // 2,
                text=f"[ {self.right_text} ]",
                fill=C["sub"],
                anchor="e",
                font=(FONT_MONO, 8),
            )


class PrtsTile(tk.Canvas):
    """通透光学功能磁贴：悬停触发 45° 玻璃扫光 + 双层齿圈对转咬合 + 四角准星收缩 + 字符解码。"""

    _all: list["PrtsTile"] = []

    def __init__(
        self,
        parent: tk.Misc,
        idx: str,
        key: str,
        title: str,
        desc: str,
        var: tk.StringVar,
        on_pick: Callable[[], None],
    ):
        super().__init__(parent, height=82, bg=C["bg"], highlightthickness=0, cursor="hand2")
        self.idx = idx
        self.key = key
        self.title = title
        self.desc = desc
        self.var = var
        self.on_pick = on_pick
        self._hover = False
        self._disabled = False
        self._p = 0.0  # 0.0 (静止) -> 1.0 (悬停特效满展开)
        self._scramble_tag = f"NODE.{idx}"

        self.bind("<Configure>", lambda _e: self._render())
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<Button-1>", self._click)
        PrtsTile._all.append(self)
        var.trace_add("write", lambda *_: self._render())
        on_theme_change(self._render)

    def set_disabled(self, disabled: bool) -> None:
        self._disabled = bool(disabled)
        self.configure(cursor="arrow" if self._disabled else "hand2")
        self._render()

    def _enter(self, _e=None) -> None:
        if self._disabled:
            return
        self._hover = True
        hex_Pool = "0123456789ABCDEF/X#"

        def _step(p: float) -> None:
            self._p = p
            if p < 0.85:
                rnd = "".join(random.choice(hex_Pool) for _ in range(3))
                self._scramble_tag = f"SYNC // {rnd}"
            else:
                self._scramble_tag = f"LOCK // {self.idx}" if self.var.get() == self.key else f"READY // {self.idx}"
            self._render()

        _Animator.run(
            self,
            195,
            _step,
            done_fn=lambda: (
                setattr(self, "_p", 1.0),
                setattr(
                    self,
                    "_scramble_tag",
                    f"LOCK // {self.idx}" if self.var.get() == self.key else f"READY // {self.idx}",
                ),
                self._render(),
            ),
            tag="tile_fx",
        )

    def _leave(self, _e=None) -> None:
        self._hover = False

        def _step(p: float) -> None:
            self._p = 1.0 - p
            self._render()

        _Animator.run(
            self,
            135,
            _step,
            done_fn=lambda: (
                setattr(self, "_p", 0.0),
                setattr(self, "_scramble_tag", f"NODE.{self.idx}"),
                self._render(),
            ),
            tag="tile_fx",
        )

    def _click(self, _e=None) -> None:
        if self._disabled:
            return
        if self.var.get() != self.key:
            self.var.set(self.key)
            self.on_pick()
        # 点击瞬间再触发一次光学扫光与齿圈咬合确认
        self._enter()

    def _draw_corner_brackets(self, w: int, h: int, p: float, color: str) -> None:
        """绘制四角光学取景框（随悬停进度 p 从外向内收缩咬合）。"""
        d = int(7 - 4 * p)  # 从边距 7px 收缩到 3px
        arm = 7
        # 左上 ┌
        self.create_line(d, d, d + arm, d, fill=color, width=1)
        self.create_line(d, d, d, d + arm, fill=color, width=1)
        # 右上 ┐
        self.create_line(w - d - arm, d, w - d, d, fill=color, width=1)
        self.create_line(w - d, d, w - d, d + arm, fill=color, width=1)
        # 左下 └
        self.create_line(d, h - d, d + arm, h - d, fill=color, width=1)
        self.create_line(d, h - d - arm, d, h - d, fill=color, width=1)

    def _draw_lock_rings(self, cx: int, cy: int, p: float, sel: bool) -> None:
        """绘制右侧双层战术齿圈（鼠标悬停时正反向对转咬合，致敬齿圈同步器）。"""
        r_out = 22
        r_in = 16
        col_main = C["ink"] if (sel or p > 0.15) else C["dim"]
        col_sub = C["mid"] if (sel or p > 0.15) else C["inner_line"]

        # 外环两段对称装甲弧：悬停时从偏置角 +55° 急停旋转归零
        ang_out = int((1.0 - p) * (0 if sel else 55))
        for base in (35, 215):
            self.create_arc(
                cx - r_out, cy - r_out, cx + r_out, cy + r_out,
                start=base + ang_out, extent=75,
                style="arc", outline=col_main, width=2 if (sel or p > 0.5) else 1,
            )

        # 内环两段校准弧：悬停时从反向 -80° 逆向旋转咬合
        ang_in = int((1.0 - p) * (0 if sel else -80))
        for base in (125, 305):
            self.create_arc(
                cx - r_in, cy - r_in, cx + r_in, cy + r_in,
                start=base + ang_in, extent=65,
                style="arc", outline=col_sub, width=1,
            )

        # 咬合到位时的十字刻度准星
        if sel or p > 0.3:
            tk_len = 3
            self.create_line(cx, cy - r_out - tk_len, cx, cy - r_out + 1, fill=col_main)
            self.create_line(cx, cy + r_out - 1, cx, cy + r_out + tk_len, fill=col_main)
            self.create_line(cx - r_out - tk_len, cy, cx - r_out + 1, cy, fill=col_main)
            self.create_line(cx + r_out - 1, cy, cx + r_out + tk_len, cy, fill=col_main)

    def _render(self) -> None:
        w = max(200, self.winfo_width())
        h = max(76, self.winfo_height())
        sel = self.var.get() == self.key
        p = self._p

        self.delete("all")
        self.configure(bg=C["bg"])

        # 1. 选择通透玻璃底板参数（无死黑实心块）
        if sel:
            top_c, bot_c = C["sel_top"], C["sel_bot"]
            out_c, in_c, bw = C["line_hi"], C["mid"], 2
            lbar = C["line_hi"]
            fg_idx = C["watermark_sel"]
        elif self._hover or p > 0.02:
            top_c, bot_c = C["card_hover_top"], C["card_hover_bot"]
            out_c, in_c, bw = C["line_hi"], C["dim"], 1
            lbar = C["mid"]
            fg_idx = C["mid"]
        else:
            top_c, bot_c = C["card_top"], C["card_bot"]
            out_c, in_c, bw = C["dim"], C["inner_line"], 1
            lbar = None
            fg_idx = C["watermark"]

        plate = _optical_card(w, h, 18, top_c, bot_c, out_c, in_c, outer_w=bw, left_bar=lbar)
        self.create_image(0, 0, image=plate, anchor="nw")

        # 2. 悬停动态特效 A：RGBA 45° 光学玻璃扫光束从左向右掠过
        if 0.01 < p < 0.99:
            beam_x = int(-100 + (w + 90) * p)
            self.create_image(beam_x, 2, image=_shimmer_beam(h - 4), anchor="nw")

        # 3. 悬停动态特效 B：上下激光细线双向展开 + 四角准星向内收缩
        if p > 0.02 or sel:
            line_w = int((w - 28) * (1.0 if sel else p))
            self.create_line(8, 1, 8 + line_w, 1, fill=C["line_hi"], width=2)
            self._draw_corner_brackets(w, h, 1.0 if sel else p, C["ink"] if sel else C["mid"])

        # 4. 悬停动态特效 C：右侧双层齿圈对转咬合 + 编号锚点
        ring_cx, ring_cy = w - 38, h // 2 + 2
        self._draw_lock_rings(ring_cx, ring_cy, p, sel)
        self.create_text(
            ring_cx,
            ring_cy,
            text=self.idx,
            fill=fg_idx,
            font=(FONT_MONO, 15 if sel else 13, "bold"),
        )

        # 5. 左上角通透幾何指示器（外框 + 内部随动核心块）
        shift = int(3 * p)
        sq_x, sq_y = 15 + shift, 15
        self.create_rectangle(sq_x, sq_y, sq_x + 10, sq_y + 10, outline=C["ink"], width=1)
        if sel or p > 0.35:
            pad = 2 if sel else 3
            self.create_rectangle(sq_x + pad, sq_y + pad, sq_x + 10 - pad, sq_y + 10 - pad, fill=C["ink"], width=0)

        # 6. 顶部微距遥测角标（带动态解码效果）
        tag_txt = "[ LOCKED ]" if (sel and p == 0.0) else f"[ {self._scramble_tag} ]"
        self.create_text(
            w - 14,
            13,
            text=tag_txt,
            fill=C["ink"] if (sel or p > 0.2) else C["sub"],
            anchor="e",
            font=(FONT_MONO, 7, "bold" if sel else "normal"),
        )

        # 7. 主标题与副标题（层次分明）
        self.create_text(
            sq_x + 16,
            20,
            text=self.title,
            fill=C["ink"],
            anchor="w",
            font=(FONT_UI, 11, "bold"),
        )
        self.create_text(
            sq_x,
            51,
            text=self.desc,
            fill=C["mid"] if (sel or p > 0.2) else C["sub"],
            anchor="w",
            font=(FONT_UI, 9),
        )


class _TelemetrySlot(tk.Canvas):
    """第 6 格光学遥测补位面板（悬停同样带扫光与雷达扫描微动效）。"""

    def __init__(self, parent: tk.Misc):
        super().__init__(parent, height=82, bg=C["bg"], highlightthickness=0)
        self._p = 0.0
        self.bind("<Configure>", lambda _e: self._render())
        self.bind("<Enter>", lambda _e: _Animator.run(
            self, 180, lambda p: (setattr(self, "_p", p), self._render()), tag="slot6"
        ))
        self.bind("<Leave>", lambda _e: _Animator.run(
            self, 120, lambda p: (setattr(self, "_p", 1.0 - p), self._render()), tag="slot6"
        ))
        on_theme_change(self._render)

    def _render(self) -> None:
        w = max(200, self.winfo_width())
        h = max(76, self.winfo_height())
        p = self._p
        self.delete("all")
        self.configure(bg=C["bg"])
        plate = _optical_card(w, h, 18, C["panel"], C["bg"], C["dim"], C["inner_line"], outer_w=1)
        self.create_image(0, 0, image=plate, anchor="nw")
        if 0.01 < p < 0.99:
            self.create_image(int(-90 + (w + 80) * p), 2, image=_shimmer_beam(h - 4), anchor="nw")

        self.create_text(14, 17, text="PRTS // TELEMETRY NODE", fill=C["mid"], anchor="w", font=(FONT_MONO, 8, "bold"))
        self.create_text(14, 40, text="OCR ENGINE · LOCAL ONNX", fill=C["sub"], anchor="w", font=(FONT_MONO, 8))
        self.create_text(14, 59, text="CALIBRATION: 1819×1023 [OK]", fill=C["sub"], anchor="w", font=(FONT_MONO, 8))

        # 右侧极简十字标尺
        cx, cy = w - 36, h // 2 + 2
        r = 16
        self.create_oval(cx - r, cy - r, cx + r, cy + r, outline=C["dim"], width=1)
        ang = p * math.pi * 0.75
        dx, dy = int(math.cos(ang) * r), int(math.sin(ang) * r)
        self.create_line(cx - dx, cy - dy, cx + dx, cy + dy, fill=C["mid"], width=1)
        self.create_text(cx, cy, text="06", fill=C["sub"], font=(FONT_MONO, 10, "bold"))


class DualActionBar(tk.Canvas):
    """通透双平行四边形主控按钮（收紧宽度防右侧裁字，悬停触发扫光与双箭头推进动效）。"""

    W, H, SPLIT, SLANT, GAP = 326, 46, 188, 15, 6

    def __init__(self, parent: tk.Misc, on_start: Callable[[], None], on_stop: Callable[[], None]):
        super().__init__(
            parent,
            width=self.W,
            height=self.H,
            bg=C["bg"],
            highlightthickness=0,
            cursor="hand2",
        )
        self.on_start = on_start
        self.on_stop = on_stop
        self.enabled_start = True
        self.enabled_stop = False
        self._zone: str | None = None
        self._p = 0.0

        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", self._leave)
        self.bind("<Button-1>", self._click)
        on_theme_change(self._render)
        self._render()

    def state(self, spec=None):
        if spec is None:
            return [] if self.enabled_start else ["disabled"]
        spec = list(spec)
        if "disabled" in spec:
            self.enabled_start, self.enabled_stop = False, True
        if "!disabled" in spec:
            self.enabled_start, self.enabled_stop = True, False
        self._render()
        return None

    def set_running(self, running: bool) -> None:
        self.enabled_start, self.enabled_stop = (not running), bool(running)
        self._render()

    def _zone_at(self, x: int, y: int) -> str:
        boundary = self.SPLIT - (y / max(1, self.H)) * self.SLANT
        return "start" if x < boundary else "stop"

    def _motion(self, e) -> None:
        z = self._zone_at(e.x, e.y)
        if z != self._zone:
            self._zone = z
            _Animator.run(
                self,
                165,
                lambda p: (setattr(self, "_p", p), self._render()),
                tag="bar_fx",
            )

    def _leave(self, _e) -> None:
        self._zone = None
        _Animator.run(
            self,
            110,
            lambda p: (setattr(self, "_p", 1.0 - p), self._render()),
            tag="bar_fx",
        )

    def _click(self, e) -> None:
        z = self._zone_at(e.x, e.y)
        if z == "start" and self.enabled_start:
            self.on_start()
        elif z == "stop" and self.enabled_stop:
            self.on_stop()

    def _render(self) -> None:
        w, h = self.W, self.H
        p = self._p
        self.delete("all")
        self.configure(bg=C["bg"])

        bg_img = _dual_parallelogram_glass(
            w, h, self.SPLIT, self.SLANT, self.GAP,
            self.enabled_start, self.enabled_stop, self._zone,
        )
        self.create_image(0, 0, image=bg_img, anchor="nw")

        # 悬停光学扫光掠过当前激活半区
        if 0.01 < p < 0.99:
            if self._zone == "start" and self.enabled_start:
                self.create_image(int(-70 + 210 * p), 2, image=_shimmer_beam(h - 4), anchor="nw")
            elif self._zone == "stop" and self.enabled_stop:
                self.create_image(int(160 + 160 * p), 2, image=_shimmer_beam(h - 4), anchor="nw")

        # 左侧「启动」：镂空几何三角 + 悬停推进双箭头
        fg_l = C["ink"] if self.enabled_start else C["sub"]
        sub_l = C["mid"] if self.enabled_start else C["dim"]
        shift_l = int(4 * p) if (self._zone == "start" and self.enabled_start) else 0

        # 绘制精密双层三角图标
        tx, ty = 22 + shift_l, h // 2
        self.create_polygon([tx, ty - 6, tx, ty + 6, tx + 9, ty], fill="", outline=fg_l, width=1)
        if self.enabled_start:
            self.create_polygon([tx + 2, ty - 3, tx + 2, ty + 3, tx + 6, ty], fill=fg_l, width=0)

        self.create_text(tx + 16, ty, text="启动", fill=fg_l, anchor="w", font=(FONT_UI, 11, "bold"))
        chev = "»" if (self._zone == "start" and self.enabled_start) else "//"
        self.create_text(tx + 58 + shift_l, ty + 1, text=f"{chev} ENGAGE", fill=sub_l, anchor="w", font=(FONT_MONO, 8, "bold"))

        # 右侧「停止」：通透方中方准星 + 文本
        fg_r = C["ink"] if self.enabled_stop else C["sub"]
        shift_r = int(3 * p) if (self._zone == "stop" and self.enabled_stop) else 0
        sx, sy = 208 + shift_r, h // 2
        self.create_rectangle(sx, sy - 6, sx + 12, sy + 6, outline=fg_r, width=1)
        self.create_rectangle(sx + 4, sy - 2, sx + 8, sy + 2, fill=fg_r, width=0)
        self.create_text(sx + 20, sy, text="停止", fill=fg_r, anchor="w", font=(FONT_UI, 10, "bold"))
        self.create_text(sx + 56, sy + 1, text="HALT", fill=C["sub"], anchor="w", font=(FONT_MONO, 8))


class BarHandle:
    """启动/停止按钮状态代理。"""

    def __init__(self, bar: DualActionBar, role: str):
        self.bar = bar
        self.role = role

    def state(self, spec=None):
        if spec is None:
            is_on = self.bar.enabled_start if self.role == "start" else self.bar.enabled_stop
            return [] if is_on else ["disabled"]
        spec = list(spec)
        on = "!disabled" in spec
        if self.role == "start":
            self.bar.enabled_start, self.bar.enabled_stop = on, not on
        else:
            self.bar.enabled_stop, self.bar.enabled_start = on, not on
        self.bar._render()
        return None

    def configure(self, **_kw) -> None:
        pass


class StatCards(tk.Frame):
    """5 宫格通透光学统计卡：支持悬停扫光 + 数值变动 Ticker 滚动。"""

    SPEC = (
        ("圣约书签", "COV.01", "covenant", "+"),
        ("神秘奖牌", "MYS.02", "mystic", "+"),
        ("消耗天空石", "SKY.03", "sky", "-"),
        ("消耗金币", "GLD.04", "gold", "-"),
        ("刷新次数", "REF.05", "refresh", ""),
    )

    def __init__(self, parent: tk.Misc):
        super().__init__(parent, bg=C["bg"])
        self.cards: dict[str, tk.Canvas] = {}
        self.values: dict[str, int] = {}
        self._last: dict[str, int] = {}

        for col, (label, code, key, prefix) in enumerate(self.SPEC):
            cv = tk.Canvas(self, height=62, bg=C["bg"], highlightthickness=0, cursor="hand2")
            cv.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 6, 0))
            self.columnconfigure(col, weight=1, uniform="stat")

            cv._meta = (label, code, key, prefix)  # type: ignore[attr-defined]
            cv._hp = 0.0  # type: ignore[attr-defined]
            cv.bind("<Configure>", lambda _e, c=cv: self._draw_card(c))
            cv.bind("<Enter>", lambda _e, c=cv: _Animator.run(
                c, 160, lambda p: (setattr(c, "_hp", p), self._draw_card(c)), tag="stat_hover"
            ))
            cv.bind("<Leave>", lambda _e, c=cv: _Animator.run(
                c, 110, lambda p: (setattr(c, "_hp", 1.0 - p), self._draw_card(c)), tag="stat_hover"
            ))
            self.cards[key] = cv
            self._last[key] = 0

        on_theme_change(self.retint)

    def _draw_card(self, cv: tk.Canvas, pulse: bool = False) -> None:
        label, code, key, prefix = getattr(cv, "_meta")
        hp = getattr(cv, "_hp", 0.0)
        w = max(100, cv.winfo_width())
        h = max(54, cv.winfo_height())
        val_num = self._last.get(key, 0)
        txt = f"{prefix}{val_num:,}" if val_num else "0"

        cv.delete("all")
        cv.configure(bg=C["bg"])
        active = pulse or hp > 0.1
        plate = _optical_card(
            w, h, 10,
            C["card_hover_top"] if active else C["card_top"],
            C["card_hover_bot"] if active else C["card_bot"],
            C["line_hi"] if active else C["dim"],
            C["inner_line"],
            outer_w=1,
            dot_matrix=False,
        )
        cv.create_image(0, 0, image=plate, anchor="nw")
        if 0.01 < hp < 0.99:
            cv.create_image(int(-80 + (w + 70) * hp), 2, image=_shimmer_beam(h - 4), anchor="nw")

        # 顶部精密刻度短横线
        bar_w = int(24 + (w - 36) * hp) if not pulse else (w - 4)
        cv.create_line(6, 2, 6 + bar_w, 2, fill=C["line_hi"] if active else C["mid"], width=2)

        cv.create_text(12, 17, text=label, fill=C["mid"], anchor="w", font=(FONT_UI, 9, "bold"))
        cv.create_text(w - 10, 17, text=code, fill=C["sub"], anchor="e", font=(FONT_MONO, 8))
        val_id = cv.create_text(
            12, 41, text=txt, fill=C["ink"], anchor="w", font=(FONT_MONO, 14, "bold")
        )
        self.values[key] = val_id

    def retint(self) -> None:
        self.configure(bg=C["bg"])
        for cv in self.cards.values():
            self._draw_card(cv)

    def update_values(self, data: dict) -> None:
        for key, cv in self.cards.items():
            new_val = int(data.get(key, 0) or 0)
            old_val = self._last.get(key, 0)
            if new_val == old_val:
                continue
            self._last[key] = new_val
            _, _, _, prefix = getattr(cv, "_meta")
            self._draw_card(cv, pulse=True)
            val_id = self.values.get(key)
            if val_id is None:
                continue

            def _step(p: float, c=cv, vid=val_id, o=old_val, n=new_val, pfx=prefix) -> None:
                cur = int(o + (n - o) * p)
                c.itemconfigure(vid, text=(f"{pfx}{cur:,}" if cur else "0"))

            _Animator.run(
                cv,
                150,
                _step,
                done_fn=lambda c=cv: self._draw_card(c, pulse=False),
                tag=f"stat_{key}",
            )


class StatusLed(tk.Canvas):
    """通透双层线框状态指示器（宽度收紧至 286px 释放右侧热键文字空间）。"""

    def __init__(self, parent: tk.Misc):
        super().__init__(parent, width=286, height=46, bg=C["bg"], highlightthickness=0)
        self._text = "就绪"
        self._disp_text = self._text
        on_theme_change(lambda: self._paint(self._text, animate=False))
        self._paint(self._text, animate=False)

    def _classify(self, text: str) -> str:
        if "运行" in text or "ACTIVE" in text:
            return "running"
        if any(k in text for k in ("暂停", "停止", "失败", "异常", "超", "没找到")):
            return "alert"
        return "ready"

    def _render_canvas(self) -> None:
        w, h = 286, 46
        mode = self._classify(self._text)
        self.delete("all")
        self.configure(bg=C["bg"])

        if mode == "running":
            plate = _optical_card(
                w, h, 10, C["sel_top"], C["sel_bot"],
                C["line_hi"], C["mid"], outer_w=2, left_bar=C["line_hi"], dot_matrix=True,
            )
            tag_str = "ACTIVE"
        elif mode == "alert":
            plate = _optical_card(
                w, h, 10, C["card_hover_top"], C["card_bot"],
                C["line_hi"], C["dim"], outer_w=1, left_bar=C["mid"], dot_matrix=False,
            )
            tag_str = "HALT"
        else:
            plate = _optical_card(
                w, h, 10, C["card_top"], C["card_bot"],
                C["dim"], C["inner_line"], outer_w=1, dot_matrix=False,
            )
            tag_str = "READY"

        self.create_image(0, 0, image=plate, anchor="nw")

        # 左侧双环准星指示器
        cx, cy = 22, h // 2
        self.create_rectangle(cx - 6, cy - 6, cx + 6, cy + 6, outline=C["ink"], width=1)
        if mode == "running":
            self.create_rectangle(cx - 3, cy - 3, cx + 3, cy + 3, fill=C["ink"], width=0)
        elif mode == "ready":
            self.create_rectangle(cx - 1, cy - 1, cx + 1, cy + 1, fill=C["ink"], width=0)

        self.create_text(
            36,
            h // 2,
            text=f"{tag_str} // {self._disp_text}",
            fill=C["ink"],
            anchor="w",
            font=(FONT_UI, 9, "bold"),
        )

    def _paint(self, text: str, animate: bool = True) -> None:
        changed = text != self._text
        self._text = text
        if not animate or not changed:
            self._disp_text = text
            self._render_canvas()
            return

        glyphs = "01X/_<#"
        n = len(text)

        def _step(p: float) -> None:
            locked = int(n * p)
            tail = "".join(random.choice(glyphs) for _ in range(min(2, n - locked)))
            self._disp_text = text[:locked] + tail
            self._render_canvas()

        _Animator.run(
            self,
            140,
            _step,
            done_fn=lambda: (setattr(self, "_disp_text", text), self._render_canvas()),
            tag="status_glitch",
        )

    def set_status(self, text: str) -> None:
        self._paint(text, animate=True)