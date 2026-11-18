"""PRTS 悬浮晶体与星环光晕 UI 引擎（纯 Tkinter + Pillow 高斯光学合成，严格黑白灰三色）。

核心特性：
1. 极低透明度悬浮玻璃（20% Alpha）：底层空间透视网格清晰穿透玻璃，配高斯悬浮阴影与高光棱边；
2. 全局景深自动模糊（DoF Blur）：鼠标悬停任一磁贴/主控按钮时，其余卡片自动进入高斯失焦模糊态；
3. 黑字星环光晕环绕（Orbital Halo）：悬停时黑色文字背后透出纯白高斯光晕，3D 倾角发光星环围绕文字旋转；
4. 挂机零 CPU 抢占：鼠标移开或脚本挂机时所有定时器 100% 销毁，静置 CPU 占用 0.0%。
"""
from __future__ import annotations

import ctypes
import math
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import Callable

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageTk

# ---------------------------------------------------------------------------
# 1. 严格黑白灰光学调色板（为了体现纯白发光与高透玻璃，底场必须为雾银中灰/曜石深灰）
# ---------------------------------------------------------------------------
LIGHT = {
    "bg": "#D5D8DF",            # 雾银空间基准底色（衬托纯白发光与高透玻璃）
    "panel": "#CFD3DC",         # 次级容器底色
    "grid_line": "#C2C6D0",     # 空间透视构成线（透过玻璃可见）
    "grid_node": "#AEB3BF",     # 空间坐标十字节点
    "glass_tint": (255, 255, 255),
    "glass_alpha": 48,          # 极低不透明度（约 18%），极度通透
    "glass_hover_alpha": 88,    # 悬停时玻璃聚光增亮
    "glass_sel_alpha": 115,     # 选中时高透晶体态
    "shadow_rgb": (18, 20, 26),
    "shadow_alpha": 42,         # 悬浮投影浓度
    "glow_rgb": (255, 255, 255),# 纯白散射光感
    "rim_light": "#FFFFFF",     # 玻璃左上 1.5px 镜面高光棱
    "rim_dark": "#9EA4B0",      # 玻璃右下背光折角暗棱
    "ink": "#0D0E12",           # 极深曜石黑字（与背后纯白星环形成强烈透光反差）
    "mid": "#3E434D",           # 二级文字
    "sub": "#636975",           # 辅助说明文字
    "dim": "#B2B7C2",           # 静止态细框线
    "watermark": "#B8BDC8",     # 静止态编号色
    "warn_red": "#C62828",      # 唯一允许的彩色：顶部防骗声明警示红
    "log_bg": "#E6E8EE",
}

DARK = {
    "bg": "#0B0C0F",            # 曜石深空底色
    "panel": "#101217",         # 次级容器底色
    "grid_line": "#181B22",     # 空间透视构成线
    "grid_node": "#262B36",     # 空间坐标十字节点
    "glass_tint": (240, 245, 255),
    "glass_alpha": 24,          # 极低不透明度（约 9%），深空高透黑晶玻璃
    "glass_hover_alpha": 46,
    "glass_sel_alpha": 64,
    "shadow_rgb": (0, 0, 0),
    "shadow_alpha": 135,
    "glow_rgb": (255, 255, 255),
    "rim_light": "#FFFFFF",     # 镜面纯白发光棱
    "rim_dark": "#2D323E",      # 背光暗棱
    "ink": "#0B0C0F",           # 悬停星环中心反色黑字（透出白光）
    "ink_normal": "#F2F4F8",    # 常态冷白字
    "mid": "#949BA8",
    "sub": "#5E6472",
    "dim": "#252934",
    "watermark": "#222630",
    "warn_red": "#E5484D",      # 唯一允许的彩色：顶部防骗声明警示红
    "log_bg": "#08090B",
}

C: dict = dict(LIGHT)
MODE: dict[str, str] = {"name": "light"}

FALLBACK = ("Microsoft YaHei UI", "Segoe UI", "SimHei")
FONT_UI = "Microsoft YaHei UI"
FONT_MONO = "Consolas"

_IMG_CACHE: dict[tuple, ImageTk.PhotoImage] = {}
_PIL_CACHE: dict[tuple, Image.Image] = {}
_REDRAW: list[Callable[[], None]] = []
_ROOT_REF: list[tk.Misc] = []

_CACHE_LIMIT = 240  # 图缓存上限：超了就按插入顺序淘汰最老的（正在显示的图不受影响）


def _cache_put(key: tuple, photo: ImageTk.PhotoImage) -> None:
    """写图缓存并限容。

    画布不会替我们保住 PhotoImage（实测：Python 引用一丢，画布上的图就变白），
    所以每个控件都把自己当前那张图存在 self._prts_photo 上，这里淘汰是安全的。
    """
    _IMG_CACHE[key] = photo
    while len(_IMG_CACHE) > _CACHE_LIMIT:
        _IMG_CACHE.pop(next(iter(_IMG_CACHE)))


# ---------------------------------------------------------------------------
# 2. 全局景深聚焦总线（控制「悬停一处、其余自动高斯模糊」）
# ---------------------------------------------------------------------------
class _FocusBus:
    _active: object | None = None
    _peers: list = []

    @classmethod
    def register(cls, widget: object) -> None:
        if widget not in cls._peers:
            cls._peers.append(widget)

    @classmethod
    def acquire(cls, widget: object) -> None:
        if cls._active is widget:
            return
        cls._active = widget
        for p in list(cls._peers):
            try:
                p.on_focus_bus_change(focused=(p is widget), any_active=True)
            except Exception:  # noqa: BLE001
                pass

    @classmethod
    def release(cls, widget: object) -> None:
        if cls._active is not widget:
            return
        cls._active = None
        for p in list(cls._peers):
            try:
                p.on_focus_bus_change(focused=False, any_active=False)
            except Exception:  # noqa: BLE001
                pass


def pick_font() -> str:
    try:
        fams = set(tkfont.families())
    except Exception:  # noqa: BLE001
        return "Microsoft YaHei UI"
    for f in FALLBACK:
        if f in fams:
            return f
    return "Microsoft YaHei UI"


def _load_pil_font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """加载系统内置字体用于 Pillow 真高斯模糊与发光字渲染。"""
    key = ("font", size, bold, mono)
    if key in _PIL_CACHE:
        return _PIL_CACHE[key]  # type: ignore[return-value]
    candidates = (
        ("consolab.ttf", "consola.ttf", "msyhbd.ttc")
        if mono
        else (("msyhbd.ttc", "msyh.ttc", "simhei.ttf") if bold else ("msyh.ttc", "simhei.ttf"))
    )
    for name in candidates:
        try:
            f = ImageFont.truetype(name, size)
            _PIL_CACHE[key] = f  # type: ignore[assignment]
            return f
        except Exception:  # noqa: BLE001
            continue
    f_def = ImageFont.load_default()
    _PIL_CACHE[key] = f_def  # type: ignore[assignment]
    return f_def


def set_theme(name: str) -> None:
    global C, FONT_UI
    target = "dark" if name == "dark" else "light"
    MODE["name"] = target
    C.clear()
    C.update(DARK if target == "dark" else LIGHT)
    FONT_UI = pick_font()
    _IMG_CACHE.clear()
    _PIL_CACHE.clear()
    _FocusBus._active = None
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


class _Animator:
    """Quartic Out (1 - (1-t)^4) 急停微动效，单次 <= 145ms。"""

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

        frames = max(3, min(9, duration_ms // 16))
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
                setattr(widget, attr, widget.after(16, _tick))
            else:
                setattr(widget, attr, None)
                if done_fn:
                    try:
                        done_fn()
                    except Exception:  # noqa: BLE001
                        pass

        _tick()

    @staticmethod
    def cancel(widget: tk.Misc, tag: str = "anim") -> None:
        attr = f"_prts_job_{tag}"
        old = getattr(widget, attr, None)
        if old is not None:
            try:
                widget.after_cancel(old)
            except Exception:  # noqa: BLE001
                pass
            setattr(widget, attr, None)


# ---------------------------------------------------------------------------
# 3. 全局 ttk 玻璃化样式与空间构成增强
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

        fg_main = C.get("ink_normal", C["ink"])
        glass_hex = "#E6E9F0" if MODE["name"] == "light" else "#171A21"
        glass_hi = "#FFFFFF" if MODE["name"] == "light" else "#262B36"

        style.configure(
            ".",
            background=C["bg"],
            foreground=fg_main,
            fieldbackground=glass_hex,
            bordercolor=C["dim"],
            lightcolor=C["rim_light"],
            darkcolor=C["rim_dark"],
            focuscolor=C["bg"],
        )
        style.configure("TFrame", background=C["bg"])
        style.configure("TLabel", background=C["bg"], foreground=fg_main)
        style.configure("Sub.TLabel", background=C["bg"], foreground=C["sub"], font=(FONT_UI, 9))

        # 顶部与内联工具按钮：左上亮棱 + 右下暗棱的悬浮玻璃片
        style.configure(
            "TButton",
            background=glass_hex,
            foreground=fg_main,
            bordercolor=C["dim"],
            lightcolor=C["rim_light"],
            darkcolor=C["rim_dark"],
            focuscolor=glass_hex,
            relief="raised",
            borderwidth=1,
            padding=(9, 4),
            font=(FONT_UI, 9, "bold"),
        )
        style.map(
            "TButton",
            background=[("pressed", C["panel"]), ("active", glass_hi), ("disabled", C["panel"])],
            foreground=[("active", C["ink"] if MODE["name"] == "light" else "#FFFFFF"), ("disabled", C["sub"])],
            bordercolor=[("active", C["rim_light"]), ("disabled", C["dim"])],
        )

        style.configure(
            "TEntry",
            fieldbackground=glass_hex,
            foreground=fg_main,
            insertcolor=fg_main,
            bordercolor=C["dim"],
            lightcolor=C["rim_light"],
            darkcolor=C["rim_dark"],
            borderwidth=1,
            padding=(5, 3),
        )
        style.map(
            "TEntry",
            fieldbackground=[("focus", glass_hi), ("disabled", C["panel"])],
            bordercolor=[("focus", C["rim_light"]), ("!focus", C["dim"])],
        )

        style.configure(
            "TCheckbutton",
            background=C["bg"],
            foreground=fg_main,
            indicatorcolor=glass_hex,
            indicatorrelief="solid",
            focuscolor=C["bg"],
            padding=(2, 2),
        )
        style.map(
            "TCheckbutton",
            background=[("active", C["bg"])],
            indicatorcolor=[("selected", fg_main), ("!selected", glass_hex)],
        )

        style.configure(
            "TLabelframe",
            background=C["bg"],
            bordercolor=C["dim"],
            lightcolor=C["rim_light"],
            darkcolor=C["dim"],
            borderwidth=1,
            relief="solid",
        )
        style.configure("TLabelframe.Label", background=C["bg"], foreground=C["mid"], font=(FONT_UI, 9, "bold"))
        style.configure(
            "TScrollbar",
            background=glass_hex,
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
    try:
        fg_main = C.get("ink_normal", C["ink"])
        stack = [root]
        while stack:
            w = stack.pop()
            stack.extend(w.winfo_children())
            cls = w.winfo_class()
            if cls == "Text":
                w.configure(
                    bg=C["log_bg"],
                    fg=fg_main,
                    insertbackground=fg_main,
                    bd=0,
                    highlightthickness=1,
                    highlightbackground=C["dim"],
                    highlightcolor=C["rim_light"],
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
# 4. Pillow 光学玻璃、悬浮阴影、星环光晕与真高斯景深合成器
# ---------------------------------------------------------------------------
def _parse_rgb(hex_col: str) -> tuple[int, int, int]:
    h = hex_col.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _dof_blur(img: Image.Image, radius: float, veil_alpha: int | None = None) -> Image.Image:
    """景深失焦：模糊 + 一层极薄雾。夜间改用淡白提亮，否则暗底卡片会糊成一坨纯黑看不见。"""
    out = img.filter(ImageFilter.GaussianBlur(radius=radius))
    w, h = out.size
    if MODE["name"] == "dark":
        return Image.alpha_composite(out, Image.new("RGBA", (w, h), (255, 255, 255, 26)))
    if veil_alpha:
        return Image.alpha_composite(out, Image.new("RGBA", (w, h), (*_parse_rgb(C["bg"]), veil_alpha)))
    return out


def _draw_spatial_subgrid(d: ImageDraw.ImageDraw, w: int, h: int, seed: int = 1) -> None:
    """在底层绘制图二风格的透视扇区几何线网与微十字准星（透过高透玻璃可见）。"""
    line_rgb = _parse_rgb(C["grid_line"])
    node_rgb = _parse_rgb(C["grid_node"])

    # 1. 贯穿式斜向透视折线（模拟图二背景地形折线）
    x_turn = int(w * (0.32 + (seed % 3) * 0.14))
    y_mid = int(h * 0.55)
    d.line([(0, y_mid + 12), (x_turn, y_mid - 10), (w, y_mid - 10)], fill=(*line_rgb, 255), width=1)
    d.line([(x_turn, y_mid - 10), (x_turn + 28, h)], fill=(*line_rgb, 180), width=1)

    # 2. 空间微十字节点
    for gx in range(28, w - 20, 64):
        for gy in (18, h - 18):
            d.line([(gx - 3, gy), (gx + 3, gy)], fill=(*node_rgb, 210), width=1)
            d.line([(gx, gy - 3), (gx, gy + 3)], fill=(*node_rgb, 210), width=1)


def _render_floating_glass_card(
    w: int,
    h: int,
    idx: str,
    title: str,
    desc: str,
    mode_state: str,  # "normal" | "selected" | "hover" | "blurred"
    orbit_deg: float = 0.0,
    elev_p: float = 0.0,
) -> ImageTk.PhotoImage:
    """合成完整的「底层空间线网 + 悬浮投影 + 极低透明度玻璃 + 黑字发光星环 + 景深模糊」图像。"""
    w, h = max(180, int(w)), max(74, int(h))
    # 对非旋转态严格缓存；旋转态将角度量化到 12° 步长（30帧环形缓存），零重复模糊开销
    q_deg = int(orbit_deg // 12) * 12 if mode_state == "hover" else 0
    q_elev = round(elev_p, 1)
    cache_key = ("glass_tile_v3", w, h, idx, title, mode_state, q_deg, q_elev, MODE["name"])
    if cache_key in _IMG_CACHE:
        return _IMG_CACHE[cache_key]

    bg_rgb = _parse_rgb(C["bg"])
    base = Image.new("RGBA", (w, h), (*bg_rgb, 255))
    bd = ImageDraw.Draw(base)

    # --- Step 1: 底层空间构成线网（在玻璃下方，透过高透玻璃折射可见） ---
    seed_num = int(idx) if idx.isdigit() else 6
    _draw_spatial_subgrid(bd, w, h, seed=seed_num)

    # 计算玻璃板的悬浮几何参数（悬停或选中时向上浮起 3px）
    lift = int(3 * q_elev) if mode_state in ("hover", "selected") else 0
    mx, my_top, my_bot = 6, 6 - lift, h - 8 - lift
    cut = 16
    glass_poly = [
        (mx, my_top),
        (w - mx, my_top),
        (w - mx, my_bot - cut),
        (w - mx - cut, my_bot),
        (mx, my_bot),
    ]

    # --- Step 2: 悬浮立体阴影（Drop Shadow）与散射外发光（Outer Bloom） ---
    shadow_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow_layer)
    sh_dy = 4 + lift
    sh_poly = [(x + 2, y + sh_dy) for (x, y) in glass_poly]
    sh_alpha = C["shadow_alpha"] + (28 if mode_state in ("hover", "selected") else 0)
    sd.polygon(sh_poly, fill=(*C["shadow_rgb"], sh_alpha))
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=4.5))
    base = Image.alpha_composite(base, shadow_layer)

    # 悬停或选中时，按钮四周向外散发纯白光学辉光（Outer Glow）
    if mode_state in ("hover", "selected"):
        glow_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow_layer)
        g_alpha = 165 if mode_state == "hover" else 110
        gd.polygon(glass_poly, outline=(*C["glow_rgb"], g_alpha), width=3)
        glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=5.0))
        base = Image.alpha_composite(base, glow_layer)

    # --- Step 3: 极低透明度高透玻璃本体 + 斜向高光折射带 ---
    glass_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gld = ImageDraw.Draw(glass_layer)
    if mode_state == "hover":
        g_alpha = C["glass_hover_alpha"]
    elif mode_state == "selected":
        g_alpha = C["glass_sel_alpha"]
    else:
        g_alpha = C["glass_alpha"]

    gld.polygon(glass_poly, fill=(*C["glass_tint"], g_alpha))

    # 玻璃表面 45° 镜面高光反射切面（模拟真实水晶玻璃折射）
    refl_x = int(w * 0.42 + q_elev * 24)
    refl_poly = [
        (refl_x, my_top + 1),
        (refl_x + 46, my_top + 1),
        (refl_x + 14, my_bot - 1),
        (refl_x - 32, my_bot - 1),
    ]
    gld.polygon(refl_poly, fill=(255, 255, 255, 38 if mode_state != "hover" else 68))

    # 玻璃立体棱边：左上纯白高光棱（1.5px） + 右下暗部折射棱（1px）
    rim_hi = _parse_rgb(C["rim_light"])
    rim_lo = _parse_rgb(C["rim_dark"])
    gld.line([glass_poly[4], glass_poly[0], glass_poly[1]], fill=(*rim_hi, 245), width=2)
    gld.line([glass_poly[1], glass_poly[2], glass_poly[3], glass_poly[4]], fill=(*rim_lo, 190), width=1)

    # 内嵌悬浮细线框（距玻璃边缘 4px）
    in_poly = [
        (mx + 4, my_top + 4),
        (w - mx - 4, my_top + 4),
        (w - mx - 4, my_bot - cut - 2),
        (w - mx - cut - 2, my_bot - 4),
        (mx + 4, my_bot - 4),
    ]
    gld.polygon(in_poly, outline=(*rim_hi, 120 if mode_state in ("hover", "selected") else 55), width=1)
    base = Image.alpha_composite(base, glass_layer)

    # --- Step 4: 星环光晕（后半环 + 文字背光星云） ---
    f_title = _load_pil_font(15, bold=True)
    f_desc = _load_pil_font(12, bold=False)
    f_idx = _load_pil_font(20 if mode_state in ("hover", "selected") else 18, bold=True, mono=True)
    f_tag = _load_pil_font(10, bold=True, mono=True)

    tx, ty = mx + 26, my_top + 11
    # 量标题的真实墨迹外框：星环中心对准文字中心，白柔光只包住文字（不再糊成一大片）
    try:
        _tb = f_title.getbbox(title)
        ink_l, ink_t, ink_r, ink_b = tx + _tb[0], ty + _tb[1], tx + _tb[2], ty + _tb[3]
    except Exception:  # noqa: BLE001
        ink_l, ink_t = tx, ty
        ink_r, ink_b = tx + len(title) * 15, ty + 15
    ink_w, ink_h = max(10, ink_r - ink_l), max(10, ink_b - ink_t)

    ring_cx = (ink_l + ink_r) / 2
    ring_cy = (ink_t + ink_b) / 2
    rx, ry = max(40, ink_w / 2 + 18), 15  # 椭圆星环长短半轴：放大一点，绕在字外面而不是压在字上
    tilt_rad = math.radians(-14)               # 图二标志性的 -14° 空间透视倾角

    def _orbit_pt(deg: float) -> tuple[float, float]:
        rad = math.radians(deg)
        ox, oy = rx * math.cos(rad), ry * math.sin(rad)
        px = ring_cx + ox * math.cos(tilt_rad) - oy * math.sin(tilt_rad)
        py = ring_cy + ox * math.sin(tilt_rad) + oy * math.cos(tilt_rad)
        return px, py

    if mode_state in ("hover", "selected"):
        halo_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        hd = ImageDraw.Draw(halo_layer)

        # 1) 黑字背后的纯白柔光：贴着标题墨迹外框的圆角胶囊（原来是糊住标题的大椭圆白斑）
        pad_x, pad_y = 7, 4
        pill = [ink_l - pad_x, ink_t - pad_y, ink_r + pad_x, ink_b + pad_y]
        hd.rounded_rectangle(
            pill,
            radius=max(6, (pill[3] - pill[1]) // 2),
            fill=(255, 255, 255, 233 if mode_state == "hover" else 190),
        )
        # 右侧编号背后的发光底座（略收一圈，避免盖住刻度环）
        num_cx, num_cy = w - mx - 34, (my_top + my_bot) // 2 + 2
        hd.ellipse([num_cx - 21, num_cy - 21, num_cx + 21, num_cy + 21], fill=(255, 255, 255, 198))

        # 2) 绘制星环的「后半轨道」（180° ~ 360°，位于文字背面）
        back_pts = [_orbit_pt(a) for a in range(180, 362, 6)]
        hd.line(back_pts, fill=(255, 255, 255, 220), width=2)

        # 只叠模糊层、不叠硬边层：得到一圈柔光，而不是一块白贴纸
        halo_soft = halo_layer.filter(ImageFilter.GaussianBlur(radius=5.0))
        base = Image.alpha_composite(base, halo_soft)
        base = Image.alpha_composite(base, halo_soft)

    # --- Step 5: 星环整圈 + 星芒（透明度压低，且整圈都画在文字「下面」） ---
    if MODE["name"] == "dark" and mode_state not in ("hover", "selected"):
        fg_main = _parse_rgb(C["ink_normal"])
    else:
        # 悬停/选中或浅色模式下，采用极深曜石黑字，与背后的纯白星环光晕形成极致反差
        fg_main = _parse_rgb(C["ink"])
    if mode_state in ("hover", "selected"):
        ring_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        rd = ImageDraw.Draw(ring_layer)
        ring_pts = [_orbit_pt(a) for a in range(0, 362, 5)]
        rd.line(ring_pts, fill=(255, 255, 255, 150), width=1)   # 原来是 245 白 2px，盖住字
        rd.line(ring_pts, fill=(*fg_main, 65), width=1)

        sx, sy = _orbit_pt(q_deg)
        sx2, sy2 = _orbit_pt((q_deg + 180) % 360)
        rd.ellipse([sx2 - 3, sy2 - 3, sx2 + 3, sy2 + 3], fill=(255, 255, 255, 170))
        trail_pts = [_orbit_pt(q_deg - step * 6) for step in range(1, 7)]
        if len(trail_pts) >= 2:
            rd.line(trail_pts, fill=(255, 255, 255, 135), width=2)
        rd.ellipse([sx - 5, sy - 5, sx + 5, sy + 5], fill=(255, 255, 255, 220))
        rd.line([(sx - 9, sy), (sx + 9, sy)], fill=(255, 255, 255, 185), width=1)
        rd.line([(sx, sy - 9), (sx, sy + 9)], fill=(255, 255, 255, 185), width=1)
        rd.ellipse([sx - 2, sy - 2, sx + 2, sy + 2], fill=(*fg_main, 235))
        base = Image.alpha_composite(base, ring_layer.filter(ImageFilter.GaussianBlur(radius=1.5)))

    # --- Step 6: 绘制锐利黑字、几何锚点与右侧双层星环刻度（永远最上层） ---
    td = ImageDraw.Draw(base)

    fg_desc = _parse_rgb(C["mid"] if mode_state in ("hover", "selected") else C["sub"])
    fg_num = fg_main if mode_state in ("hover", "selected") else _parse_rgb(C["watermark"])

    # 左侧几何准星块
    sq_x, sq_y = mx + 11, my_top + 15
    td.rectangle([sq_x, sq_y, sq_x + 9, sq_y + 9], outline=(*fg_main, 230), width=1)
    if mode_state in ("hover", "selected"):
        td.rectangle([sq_x + 2, sq_y + 2, sq_x + 7, sq_y + 7], fill=(*fg_main, 255))
        # 左侧悬浮发光立柱
        td.line([(mx + 1, my_top + 6), (mx + 1, my_bot - 6)], fill=(*fg_main, 255), width=2)

    # 绘制主标题与副标题
    td.text((tx, ty), title, font=f_title, fill=(*fg_main, 255))
    td.text((sq_x, my_top + 41), desc, font=f_desc, fill=(*fg_desc, 240))

    # 右侧图二同款同心星环刻度盘 + 编号 01~05
    num_cx, num_cy = w - mx - 34, (my_top + my_bot) // 2 + 4
    r_outer, r_inner = 20, 14
    ring_col = (*fg_main, 210) if mode_state in ("hover", "selected") else (*_parse_rgb(C["dim"]), 180)
    td.arc(
        [num_cx - r_outer, num_cy - r_outer, num_cx + r_outer, num_cy + r_outer],
        start=25 + q_deg,
        end=135 + q_deg,
        fill=ring_col,
        width=2 if mode_state in ("hover", "selected") else 1,
    )
    td.arc(
        [num_cx - r_outer, num_cy - r_outer, num_cx + r_outer, num_cy + r_outer],
        start=205 + q_deg,
        end=315 + q_deg,
        fill=ring_col,
        width=2 if mode_state in ("hover", "selected") else 1,
    )
    td.arc(
        [num_cx - r_inner, num_cy - r_inner, num_cx + r_inner, num_cy + r_inner],
        start=110 - q_deg,
        end=250 - q_deg,
        fill=(*_parse_rgb(C["mid"]), 170),
        width=1,
    )
    td.text((num_cx - 11, num_cy - 11), idx, font=f_idx, fill=(*fg_num, 255))

    # 右上角微型终端状态铭牌
    tag_str = "ORBIT // ACTIVE" if mode_state == "hover" else ("LOCKED" if mode_state == "selected" else f"NODE.{idx}")
    # 右对齐：原来从 w-mx-68 起画会冲出卡片右边缘，只显示成 “ORBIT // ACT”
    td.text((w - mx - 8, my_top + 4), tag_str, font=f_tag, fill=(*fg_desc, 210), anchor="ra")

    # --- Step 6: 星环光晕的「前半轨道」+ 旋转星芒光核（从黑字正前方穿过的 3D 环绕感） ---
    # --- Step 7: 全局景深失焦模糊（当鼠标悬停在其他按钮上时，本卡片自动高斯模糊） ---
    if mode_state == "blurred":
        base = _dof_blur(base, 2.6, veil_alpha=78)

    photo = ImageTk.PhotoImage(base)
    _cache_put(cache_key, photo)
    return photo


# ---------------------------------------------------------------------------
# 5. 对外契约组件实现
# ---------------------------------------------------------------------------
class HazardBanner(tk.Canvas):
    """顶部高透玻璃警示条（全界面唯一保留警示红的区域）。"""

    def __init__(self, parent: tk.Misc, text: str, right_text: str = "E7PILOT // NON-COMMERCIAL"):
        super().__init__(parent, height=32, bg=C["bg"], highlightthickness=0)
        self.text = text
        self.right_text = right_text
        self.bind("<Configure>", lambda _e: self._render())
        on_theme_change(self._render)

    def _render(self) -> None:
        w = max(240, self.winfo_width())
        h = 32
        self.delete("all")
        self.configure(bg=C["bg"])

        key = ("haz_glass", w, h, MODE["name"])
        if key not in _IMG_CACHE:
            bg_rgb = _parse_rgb(C["bg"])
            img = Image.new("RGBA", (w, h), (*bg_rgb, 255))
            d = ImageDraw.Draw(img)
            # 玻璃底条
            d.rectangle([2, 2, w - 3, h - 3], fill=(*C["glass_tint"], C["glass_hover_alpha"]))
            d.line([(2, 2), (w - 3, 2)], fill=(*_parse_rgb(C["rim_light"]), 230), width=1)
            d.line([(2, h - 3), (w - 3, h - 3)], fill=(*_parse_rgb(C["rim_dark"]), 180), width=1)
            # 左侧红色斜纹警示块
            red_rgb = _parse_rgb(C["warn_red"])
            for x in range(-h, 86, 14):
                d.polygon([(x, h - 4), (x + 7, h - 4), (x + h - 2, 4), (x + h - 9, 4)], fill=(*red_rgb, 215))
            _cache_put(key, ImageTk.PhotoImage(img))

        self._prts_photo = _IMG_CACHE[key]
        self.create_image(0, 0, image=self._prts_photo, anchor="nw")
        self.create_text(
            98,
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
    """悬浮高透玻璃磁贴：悬停触发全局景深模糊 + 黑字发光星环旋转，静置 0% CPU。"""

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
        super().__init__(parent, height=84, bg=C["bg"], highlightthickness=0, cursor="hand2")
        self.idx = idx
        self.key = key
        self.title = title
        self.desc = desc
        self.var = var
        self.on_pick = on_pick

        self._hover = False
        self._blurred = False
        self._disabled = False
        self._elev_p = 0.0
        self._orbit_deg = 0.0
        self._orbit_job: str | None = None

        self.bind("<Configure>", lambda _e: self._render())
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<Button-1>", self._click)

        PrtsTile._all.append(self)
        _FocusBus.register(self)
        var.trace_add("write", lambda *_: self._render())
        on_theme_change(self._render)

    def on_focus_bus_change(self, focused: bool, any_active: bool) -> None:
        """响应全局景深总线：当其他按钮被悬停时，本卡片立即切换为高斯失焦模糊态。"""
        should_blur = any_active and (not focused)
        if should_blur != self._blurred:
            self._blurred = should_blur
            self._render()

    def set_disabled(self, disabled: bool) -> None:
        self._disabled = bool(disabled)
        self.configure(cursor="arrow" if self._disabled else "hand2")
        self._render()

    def _enter(self, _e=None) -> None:
        if self._disabled:
            return
        self._hover = True
        _FocusBus.acquire(self)
        _Animator.run(
            self,
            135,
            lambda p: (setattr(self, "_elev_p", p), self._render()),
            tag="elev",
        )
        self._start_star_ring_orbit()

    def _leave(self, _e=None) -> None:
        self._hover = False
        self._stop_star_ring_orbit()
        _FocusBus.release(self)
        _Animator.run(
            self,
            120,
            lambda p: (setattr(self, "_elev_p", 1.0 - p), self._render()),
            done_fn=lambda: (setattr(self, "_elev_p", 0.0), self._render()),
            tag="elev",
        )

    def _start_star_ring_orbit(self) -> None:
        """仅在鼠标悬停于当前按钮上时驱动星环围绕黑字旋转，移开立即销毁定时器。"""
        self._stop_star_ring_orbit()

        def _tick() -> None:
            if not self._hover or not self.winfo_exists():
                self._orbit_job = None
                return
            self._orbit_deg = (self._orbit_deg + 12.0) % 360.0
            self._render()
            self._orbit_job = self.after(30, _tick)

        _tick()

    def _stop_star_ring_orbit(self) -> None:
        if self._orbit_job is not None:
            try:
                self.after_cancel(self._orbit_job)
            except Exception:  # noqa: BLE001
                pass
            self._orbit_job = None

    def _click(self, _e=None) -> None:
        if self._disabled:
            return
        if self.var.get() != self.key:
            self.var.set(self.key)
            self.on_pick()
        self._render()

    def _render(self) -> None:
        w = max(200, self.winfo_width())
        h = max(78, self.winfo_height())
        sel = self.var.get() == self.key

        if self._blurred:
            mode_state = "blurred"
        elif self._hover:
            mode_state = "hover"
        elif sel:
            mode_state = "selected"
        else:
            mode_state = "normal"

        self.delete("all")
        self.configure(bg=C["bg"])
        photo = _render_floating_glass_card(
            w, h, self.idx, self.title, self.desc,
            mode_state=mode_state,
            orbit_deg=self._orbit_deg,
            elev_p=1.0 if sel else self._elev_p,
        )
        self._prts_photo = photo
        self.create_image(0, 0, image=photo, anchor="nw")


class _TelemetrySlot(tk.Canvas):
    """第 6 格悬浮玻璃遥测卡（同样参与全局景深模糊与星环悬停）。"""

    def __init__(self, parent: tk.Misc):
        super().__init__(parent, height=84, bg=C["bg"], highlightthickness=0)
        self._hover = False
        self._blurred = False
        self._orbit_deg = 0.0
        self._orbit_job: str | None = None

        self.bind("<Configure>", lambda _e: self._render())
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        _FocusBus.register(self)
        on_theme_change(self._render)

    def on_focus_bus_change(self, focused: bool, any_active: bool) -> None:
        should_blur = any_active and (not focused)
        if should_blur != self._blurred:
            self._blurred = should_blur
            self._render()

    def _enter(self, _e=None) -> None:
        self._hover = True
        _FocusBus.acquire(self)

        def _tick() -> None:
            if not self._hover or not self.winfo_exists():
                return
            self._orbit_deg = (self._orbit_deg + 12.0) % 360.0
            self._render()
            self._orbit_job = self.after(30, _tick)

        _tick()

    def _leave(self, _e=None) -> None:
        self._hover = False
        if self._orbit_job:
            try:
                self.after_cancel(self._orbit_job)
            except Exception:  # noqa: BLE001
                pass
            self._orbit_job = None
        _FocusBus.release(self)
        self._render()

    def _render(self) -> None:
        w = max(200, self.winfo_width())
        h = max(78, self.winfo_height())
        state = "blurred" if self._blurred else ("hover" if self._hover else "normal")
        self.delete("all")
        self.configure(bg=C["bg"])
        photo = _render_floating_glass_card(
            w, h, "06", "环境遥测节点", "LOCAL ONNX · 1819×1023 [OK]",
            mode_state=state,
            orbit_deg=self._orbit_deg,
            elev_p=1.0 if self._hover else 0.0,
        )
        self._prts_photo = photo
        self.create_image(0, 0, image=photo, anchor="nw")


class DualActionBar(tk.Canvas):
    """悬浮玻璃双平行四边形主控按钮：散发光感 + 悬停星环围绕『启动/停止』旋转 + 联动全局景深模糊。"""

    W, H, SPLIT, SLANT, GAP = 326, 50, 188, 15, 6

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
        self._blurred = False
        self._orbit_deg = 0.0
        self._orbit_job: str | None = None

        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", self._leave)
        self.bind("<Button-1>", self._click)
        _FocusBus.register(self)
        on_theme_change(self._render)
        self._render()

    def on_focus_bus_change(self, focused: bool, any_active: bool) -> None:
        should_blur = any_active and (not focused)
        if should_blur != self._blurred:
            self._blurred = should_blur
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
            _FocusBus.acquire(self)
            self._start_orbit()
            self._render()

    def _leave(self, _e) -> None:
        self._zone = None
        self._stop_orbit()
        _FocusBus.release(self)
        self._render()

    def _start_orbit(self) -> None:
        self._stop_orbit()

        def _tick() -> None:
            if self._zone is None or not self.winfo_exists():
                self._orbit_job = None
                return
            self._orbit_deg = (self._orbit_deg + 15.0) % 360.0
            self._render()
            self._orbit_job = self.after(30, _tick)

        _tick()

    def _stop_orbit(self) -> None:
        if self._orbit_job is not None:
            try:
                self.after_cancel(self._orbit_job)
            except Exception:  # noqa: BLE001
                pass
            self._orbit_job = None

    def _click(self, e) -> None:
        z = self._zone_at(e.x, e.y)
        if z == "start" and self.enabled_start:
            self._stop_orbit()
            _FocusBus.release(self)
            self.on_start()
        elif z == "stop" and self.enabled_stop:
            self._stop_orbit()
            _FocusBus.release(self)
            self.on_stop()

    def _render(self) -> None:
        w, h = self.W, self.H
        q_deg = int(self._orbit_deg // 15) * 15 if self._zone else 0
        key = (
            "dual_star_v3",
            w, h,
            self.enabled_start, self.enabled_stop,
            self._zone, self._blurred, q_deg, MODE["name"],
        )
        if key not in _IMG_CACHE:
            bg_rgb = _parse_rgb(C["bg"])
            base = Image.new("RGBA", (w, h), (*bg_rgb, 255))
            bd = ImageDraw.Draw(base)
            _draw_spatial_subgrid(bd, w, h, seed=9)

            sp, sl, gp = self.SPLIT, self.SLANT, self.GAP
            pts_l = [(4, 10), (10, 4), (sp, 4), (sp - sl, h - 6), (4, h - 6)]
            pts_r = [(sp + gp, 4), (w - 4, 4), (w - 4, h - 14), (w - 12, h - 6), (sp - sl + gp, h - 6)]

            # 悬浮投影与散射外发光
            sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            sd = ImageDraw.Draw(sh)
            sd.polygon([(x + 1, y + 4) for x, y in pts_l], fill=(*C["shadow_rgb"], C["shadow_alpha"] + 15))
            sd.polygon([(x + 1, y + 4) for x, y in pts_r], fill=(*C["shadow_rgb"], C["shadow_alpha"] + 15))
            base = Image.alpha_composite(base, sh.filter(ImageFilter.GaussianBlur(radius=3.5)))

            glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            gd = ImageDraw.Draw(glow)
            if self.enabled_start:
                gd.polygon(pts_l, outline=(255, 255, 255, 190 if self._zone == "start" else 115), width=3)
            if self.enabled_stop:
                gd.polygon(pts_r, outline=(255, 255, 255, 190 if self._zone == "stop" else 115), width=3)
            base = Image.alpha_composite(base, glow.filter(ImageFilter.GaussianBlur(radius=4.0)))

            # 高透玻璃层
            glass = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            gld = ImageDraw.Draw(glass)
            a_l = C["glass_sel_alpha"] if self.enabled_start else C["glass_alpha"]
            a_r = C["glass_sel_alpha"] if self.enabled_stop else C["glass_alpha"]
            gld.polygon(pts_l, fill=(*C["glass_tint"], a_l))
            gld.polygon(pts_r, fill=(*C["glass_tint"], a_r))

            rim_hi = _parse_rgb(C["rim_light"])
            rim_lo = _parse_rgb(C["rim_dark"])
            gld.line([pts_l[4], pts_l[0], pts_l[1], pts_l[2]], fill=(*rim_hi, 240), width=2)
            gld.line([pts_l[2], pts_l[3], pts_l[4]], fill=(*rim_lo, 190), width=1)
            gld.line([pts_r[4], pts_r[0], pts_r[1]], fill=(*rim_hi, 230), width=2)
            gld.line([pts_r[1], pts_r[2], pts_r[3], pts_r[4]], fill=(*rim_lo, 190), width=1)
            base = Image.alpha_composite(base, glass)

            # 悬停侧：贴字柔光 + 环绕星环，全部画在文字「下面」，文字永远压在它们上面
            active = None
            if self._zone == "start" and self.enabled_start:
                active = (83, 65, 18, 148)   # (环心 x, 椭圆半径 x, 标签左, 标签右)
            elif self._zone == "stop" and self.enabled_stop:
                active = (253, 53, 200, 306)
            if active is not None:
                cx, r_x, lb_l, lb_r = active
                halo = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                hd = ImageDraw.Draw(halo)
                # 只给标签本体垫一层薄柔光，不再整块按钮铺白斑
                hd.rounded_rectangle(
                    [lb_l - 8, 11, lb_r + 8, h - 11],
                    radius=13,
                    fill=(255, 255, 255, 96 if MODE["name"] == "light" else 118),
                )
                base = Image.alpha_composite(base, halo.filter(ImageFilter.GaussianBlur(radius=6.0)))

                orb = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                od = ImageDraw.Draw(orb)
                cy = h // 2
                pts = [
                    (cx + r_x * math.cos(math.radians(a)), cy + 13 * math.sin(math.radians(a)))
                    for a in range(0, 361, 8)
                ]
                od.line(pts, fill=(255, 255, 255, 150), width=1)  # 原来 240/2px，太抢视线
                sx = cx + r_x * math.cos(math.radians(q_deg))
                sy = cy + 13 * math.sin(math.radians(q_deg))
                od.ellipse([sx - 3, sy - 3, sx + 3, sy + 3], fill=(255, 255, 255, 210))
                od.line([(sx - 7, sy), (sx + 7, sy)], fill=(255, 255, 255, 185), width=1)
                od.line([(sx, sy - 7), (sx, sy + 7)], fill=(255, 255, 255, 185), width=1)
                base = Image.alpha_composite(base, orb)

            f_btn = _load_pil_font(15, bold=True)
            f_sub = _load_pil_font(10, bold=True, mono=True)
            td = ImageDraw.Draw(base)

            fg_l = _parse_rgb(C["ink"]) if (self.enabled_start or MODE["name"] == "light") else _parse_rgb(C["sub"])
            fg_r = _parse_rgb(C["ink"]) if (self.enabled_stop or MODE["name"] == "light") else _parse_rgb(C["sub"])
            if MODE["name"] == "dark":
                if self.enabled_start and self._zone != "start":
                    fg_l = _parse_rgb(C["ink_normal"])
                if self.enabled_stop and self._zone != "stop":
                    fg_r = _parse_rgb(C["ink_normal"])

            # "▶" 在 msyhbd.ttc 里没有字形（会渲染成方框），改成直接画三角形
            a_on = 255 if self.enabled_start else 130
            td.polygon([(29, 18), (29, 31), (40, 24)], fill=(*fg_l, a_on))
            td.text((47, 14), "启动", font=f_btn, fill=(*fg_l, a_on))
            td.text((104, 18), "ENGAGE", font=f_sub, fill=(*fg_l, 180 if self.enabled_start else 100))
            td.text((210, 14), "■ 停止", font=f_btn, fill=(*fg_r, 255 if self.enabled_stop else 130))
            td.text((274, 18), "HALT", font=f_sub, fill=(*fg_r, 180 if self.enabled_stop else 100))

            if self._blurred:
                base = _dof_blur(base, 2.4)

            _cache_put(key, ImageTk.PhotoImage(base))

        self._prts_photo = _IMG_CACHE[key]
        self.delete("all")
        self.configure(bg=C["bg"])
        self.create_image(0, 0, image=self._prts_photo, anchor="nw")


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
    """5 宫格悬浮玻璃统计卡：同样支持悬停星环光晕与景深联动。"""

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
        self._last: dict[str, int] = {}
        self._blurred = False

        for col, (label, code, key, prefix) in enumerate(self.SPEC):
            cv = tk.Canvas(self, height=64, bg=C["bg"], highlightthickness=0, cursor="hand2")
            cv.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 6, 0))
            self.columnconfigure(col, weight=1, uniform="stat")

            cv._meta = (label, code, key, prefix)  # type: ignore[attr-defined]
            cv._hover = False  # type: ignore[attr-defined]
            cv._deg = 0.0      # type: ignore[attr-defined]
            cv._job = None     # type: ignore[attr-defined]
            cv.bind("<Configure>", lambda _e, c=cv: self._draw_card(c))
            cv.bind("<Enter>", lambda _e, c=cv: self._enter_card(c))
            cv.bind("<Leave>", lambda _e, c=cv: self._leave_card(c))
            self.cards[key] = cv
            self._last[key] = 0

        _FocusBus.register(self)
        on_theme_change(self.retint)

    def on_focus_bus_change(self, focused: bool, any_active: bool) -> None:
        should_blur = any_active and (not focused)
        if should_blur != self._blurred:
            self._blurred = should_blur
            for cv in self.cards.values():
                self._draw_card(cv)

    def _enter_card(self, cv: tk.Canvas) -> None:
        cv._hover = True  # type: ignore[attr-defined]
        _FocusBus.acquire(self)

        def _tick() -> None:
            if not getattr(cv, "_hover", False) or not cv.winfo_exists():
                return
            cv._deg = (getattr(cv, "_deg", 0.0) + 15.0) % 360.0  # type: ignore[attr-defined]
            for sib in self.cards.values():
                self._draw_card(sib)
            cv._job = cv.after(32, _tick)  # type: ignore[attr-defined]

        _tick()

    def _leave_card(self, cv: tk.Canvas) -> None:
        cv._hover = False  # type: ignore[attr-defined]
        job = getattr(cv, "_job", None)
        if job:
            try:
                cv.after_cancel(job)
            except Exception:  # noqa: BLE001
                pass
            cv._job = None  # type: ignore[attr-defined]
        _FocusBus.release(self)
        for sib in self.cards.values():
            self._draw_card(sib)

    def _draw_card(self, cv: tk.Canvas) -> None:
        label, code, key, prefix = getattr(cv, "_meta")
        is_hover = getattr(cv, "_hover", False)
        any_sib_hover = any(getattr(s, "_hover", False) for s in self.cards.values())
        card_blur = self._blurred or (any_sib_hover and not is_hover)

        w = max(100, cv.winfo_width())
        h = max(56, cv.winfo_height())
        val_num = self._last.get(key, 0)
        txt = f"{prefix}{val_num:,}" if val_num else "0"
        q_deg = int(getattr(cv, "_deg", 0.0) // 15) * 15 if is_hover else 0

        ckey = ("stat_glass_v3", w, h, key, txt, is_hover, card_blur, q_deg, MODE["name"])
        if ckey not in _IMG_CACHE:
            bg_rgb = _parse_rgb(C["bg"])
            base = Image.new("RGBA", (w, h), (*bg_rgb, 255))
            bd = ImageDraw.Draw(base)
            _draw_spatial_subgrid(bd, w, h, seed=len(code))

            lift = 2 if is_hover else 0
            poly = [(4, 5 - lift), (w - 4, 5 - lift), (w - 4, h - 13 - lift), (w - 12, h - 5 - lift), (4, h - 5 - lift)]

            sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            ImageDraw.Draw(sh).polygon([(x + 1, y + 3 + lift) for x, y in poly], fill=(*C["shadow_rgb"], C["shadow_alpha"]))
            base = Image.alpha_composite(base, sh.filter(ImageFilter.GaussianBlur(radius=3.0)))

            glass = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            gd = ImageDraw.Draw(glass)
            gd.polygon(poly, fill=(*C["glass_tint"], C["glass_hover_alpha"] if is_hover else C["glass_alpha"]))
            rim_hi = _parse_rgb(C["rim_light"])
            rim_lo = _parse_rgb(C["rim_dark"])
            gd.line([poly[4], poly[0], poly[1]], fill=(*rim_hi, 235), width=2)
            gd.line([poly[1], poly[2], poly[3], poly[4]], fill=(*rim_lo, 180), width=1)
            base = Image.alpha_composite(base, glass)

            if is_hover:
                halo = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                ImageDraw.Draw(halo).ellipse([10, 14, w - 10, h - 6], fill=(255, 255, 255, 225))
                base = Image.alpha_composite(base, halo.filter(ImageFilter.GaussianBlur(radius=4.5)))

            f_lbl = _load_pil_font(12, bold=True)
            f_cod = _load_pil_font(10, bold=False, mono=True)
            f_val = _load_pil_font(17, bold=True, mono=True)
            td = ImageDraw.Draw(base)
            fg_ink = _parse_rgb(C["ink"] if (is_hover or MODE["name"] == "light") else C["ink_normal"])
            td.text((12, 9 - lift), label, font=f_lbl, fill=(*_parse_rgb(C["mid"]), 240))
            td.text((w - 48, 10 - lift), code, font=f_cod, fill=(*_parse_rgb(C["sub"]), 210))
            td.text((12, 31 - lift), txt, font=f_val, fill=(*fg_ink, 255))

            if is_hover:
                orb = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                od = ImageDraw.Draw(orb)
                cx, cy, rx, ry = w // 2, 39 - lift, w // 2 - 14, 9
                pts = [(cx + rx * math.cos(math.radians(a)), cy + ry * math.sin(math.radians(a))) for a in range(0, 361, 10)]
                od.line(pts, fill=(255, 255, 255, 235), width=2)
                sx, sy = cx + rx * math.cos(math.radians(q_deg)), cy + ry * math.sin(math.radians(q_deg))
                od.ellipse([sx - 3, sy - 3, sx + 3, sy + 3], fill=(255, 255, 255, 255))
                base = Image.alpha_composite(base, orb)

            if card_blur:
                base = _dof_blur(base, 2.2)

            _cache_put(ckey, ImageTk.PhotoImage(base))

        cv._prts_photo = _IMG_CACHE[ckey]
        cv.delete("all")
        cv.configure(bg=C["bg"])
        cv.create_image(0, 0, image=cv._prts_photo, anchor="nw")

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
            self._draw_card(cv)


class StatusLed(tk.Canvas):
    """悬浮高透玻璃状态指示器（带双环星轨刻度与状态光晕）。"""

    def __init__(self, parent: tk.Misc):
        super().__init__(parent, width=286, height=50, bg=C["bg"], highlightthickness=0)
        self._text = "就绪"
        self._blurred = False
        _FocusBus.register(self)
        on_theme_change(lambda: self._paint(self._text))
        self._paint(self._text)

    def on_focus_bus_change(self, focused: bool, any_active: bool) -> None:
        should_blur = any_active and (not focused)
        if should_blur != self._blurred:
            self._blurred = should_blur
            self._paint(self._text)

    def _paint(self, text: str) -> None:
        self._text = text
        w, h = 286, 50
        is_run = "运行" in text or "ACTIVE" in text
        key = ("led_glass_v3", w, h, text, is_run, self._blurred, MODE["name"])
        if key not in _IMG_CACHE:
            bg_rgb = _parse_rgb(C["bg"])
            base = Image.new("RGBA", (w, h), (*bg_rgb, 255))
            bd = ImageDraw.Draw(base)
            _draw_spatial_subgrid(bd, w, h, seed=7)

            poly = [(4, 5), (w - 4, 5), (w - 4, h - 13), (w - 12, h - 5), (4, h - 5)]
            sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            ImageDraw.Draw(sh).polygon([(x + 1, y + 4) for x, y in poly], fill=(*C["shadow_rgb"], C["shadow_alpha"]))
            base = Image.alpha_composite(base, sh.filter(ImageFilter.GaussianBlur(radius=3.5)))

            if is_run:
                glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                ImageDraw.Draw(glow).ellipse([12, 8, w - 12, h - 8], fill=(255, 255, 255, 210))
                base = Image.alpha_composite(base, glow.filter(ImageFilter.GaussianBlur(radius=5.0)))

            glass = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            gd = ImageDraw.Draw(glass)
            gd.polygon(poly, fill=(*C["glass_tint"], C["glass_sel_alpha"] if is_run else C["glass_alpha"]))
            rim_hi = _parse_rgb(C["rim_light"])
            rim_lo = _parse_rgb(C["rim_dark"])
            gd.line([poly[4], poly[0], poly[1]], fill=(*rim_hi, 240), width=2)
            gd.line([poly[1], poly[2], poly[3], poly[4]], fill=(*rim_lo, 180), width=1)
            base = Image.alpha_composite(base, glass)

            f_txt = _load_pil_font(12, bold=True)
            td = ImageDraw.Draw(base)
            fg_ink = _parse_rgb(C["ink"] if (is_run or MODE["name"] == "light") else C["ink_normal"])

            # 左侧双层星环指示准星
            cx, cy = 24, h // 2
            td.arc([cx - 9, cy - 9, cx + 9, cy + 9], start=20, end=310, fill=(*fg_ink, 230), width=2)
            td.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], fill=(*fg_ink, 255))
            tag = "ORBIT" if is_run else "READY"
            td.text((40, 16), f"{tag} // {text}", font=f_txt, fill=(*fg_ink, 255))

            if self._blurred:
                base = _dof_blur(base, 2.2)

            _cache_put(key, ImageTk.PhotoImage(base))

        self._prts_photo = _IMG_CACHE[key]
        self.delete("all")
        self.configure(bg=C["bg"])
        self.create_image(0, 0, image=self._prts_photo, anchor="nw")

    def set_status(self, text: str) -> None:
        self._paint(text)