from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import urllib.request

from core import (ARCHETYPES, DEFAULT_RULES, Gear, LABELS, SETS, SLOTS, Stat, Store,
                  evaluate, import_heroes, parse_text, recommend, validate)
from ocr import WindowsOCR
from vision import ScreenReader

ROOT = Path(__file__).resolve().parent
USER = Path(os.environ.get("E7_ADVISOR_HOME", str(ROOT / "userdata")))
BG, PANEL, FIELD, TEXT, MUTED, GOLD, GREEN = "#10151f", "#1a2230", "#232e40", "#edf0f6", "#a8b4c7", "#e7bf72", "#72d7ba"
FONT = "Microsoft YaHei UI"
SOURCE = "https://raw.githubusercontent.com/tsukiyakii4uu/e7-e7-sidekick-resources/main/heroes.json"


class RegionSelector(tk.Toplevel):
    def __init__(self, root, callback):
        super().__init__(root)
        self.callback = callback
        user32 = ctypes.windll.user32
        self.left, self.top = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
        width, height = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
        self.overrideredirect(True)
        self.geometry(f"{width}x{height}{self.left:+}{self.top:+}")
        self.attributes("-topmost", True)
        self.attributes("-alpha", .36)
        self.canvas = tk.Canvas(self, bg="#07121c", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_text(width // 2, 75, text="拖动框选单件装备完整面板 · 包括等级、强化等级、主副属性 · Esc 取消",
                                fill="white", font=(FONT, 18))
        self.start = None
        self.rectangle = None
        self.bind("<ButtonPress-1>", self.press)
        self.bind("<B1-Motion>", self.drag)
        self.bind("<ButtonRelease-1>", self.release)
        self.bind("<Escape>", lambda e: self.destroy())
        self.focus_force()
        self.grab_set()

    def press(self, event):
        self.start = (event.x, event.y)
        if self.rectangle:
            self.canvas.delete(self.rectangle)
        self.rectangle = self.canvas.create_rectangle(event.x, event.y, event.x, event.y, outline="#f5ca74", width=4)

    def drag(self, event):
        if self.start:
            self.canvas.coords(self.rectangle, *self.start, event.x, event.y)

    def release(self, event):
        if not self.start:
            return
        x1, x2 = sorted([self.start[0] + self.left, event.x + self.left])
        y1, y2 = sorted([self.start[1] + self.top, event.y + self.top])
        self.destroy()
        if x2 - x1 >= 80 and y2 - y1 >= 80:
            self.callback([x1, y1, x2, y2])


class Advisor(tk.Tk):
    def __init__(self):
        super().__init__()
        USER.mkdir(parents=True, exist_ok=True)
        self.title("第七史诗 · 装备研判台 0.2 实机校准版")
        self.geometry("1370x920")
        self.minsize(1150, 820)
        self.configure(bg=BG)
        self.rules = self.load_json("rules.json", DEFAULT_RULES)
        self.heroes = import_heroes(self.load_json("heroes.json", {}))
        # 更新内置名单时补充新角色，保留用户已编辑的档案。
        builtin=import_heroes(json.loads((ROOT/'data/heroes.json').read_text(encoding='utf-8')))
        known={h['name']:h for h in self.heroes}
        for h in builtin:known.setdefault(h['name'],h)
        self.heroes=list(known.values())
        self.db = Store(USER / "observations.sqlite3")
        self.current_item = None
        self.region = None
        self.ocr = None
        self.live = False
        self.busy = False
        self.session = 0
        self.candidate = None
        self.candidate_count = 0
        self.last_applied = None
        self.results = queue.Queue()
        self.rec_rows = {}
        self.rec_list = []
        self.batch_entries = []
        self.screen_score = None
        self.confirmed = tk.BooleanVar(value=False)
        self.owned_only = tk.BooleanVar(value=False)
        self.topmost = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="先加载演示，或框选游戏装备面板。实时模式不自动保存，校对后点击记录。")
        self.vars = {k: tk.StringVar() for k in ["name", "slot", "set_name", "grade", "level", "enhance"]}
        self.main_key = tk.StringVar()
        self.main_value = tk.StringVar()
        self.sub_keys = [tk.StringVar() for _ in range(4)]
        self.sub_values = [tk.StringVar() for _ in range(4)]
        self._style()
        self._build()
        for variable in list(self.vars.values()) + [self.main_key, self.main_value] + self.sub_keys + self.sub_values:
            variable.trace_add("write", self.form_changed)
        self.refresh_items()
        self.refresh_heroes()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<F8>", lambda e: self.scan_once())
        self.bind("<F9>", lambda e: self.toggle_live())
        self.after(100, self.poll)

    def form_changed(self, *args):
        self.confirmed.set(False)
        self.decision_label.configure(text="属性已变更，待重算", foreground=GOLD)

    def load_json(self, name, default):
        path = USER / name
        if not path.exists():
            path = ROOT / "data" / name
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except (ValueError, OSError):
            return default

    def _style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=PANEL, foreground=TEXT, font=(FONT, 10))
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=PANEL)
        style.configure("TLabel", background=PANEL, foreground=TEXT)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("TButton", background=FIELD, foreground=TEXT, padding=(12, 8), borderwidth=0)
        style.map("TButton", background=[("active", "#35445d")])
        style.configure("Accent.TButton", background=GOLD, foreground=BG)
        style.map("Accent.TButton", background=[("active", "#f6d99b")])
        style.configure("TEntry", fieldbackground=FIELD, foreground=TEXT, insertcolor=TEXT, padding=5)
        style.configure("TCombobox", fieldbackground=FIELD, foreground=TEXT, arrowcolor=GOLD, padding=4)
        style.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", TEXT)])
        style.configure("TCheckbutton", background=PANEL, foreground=TEXT)
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(14, 10), background=PANEL, foreground=MUTED)
        style.map("TNotebook.Tab", background=[("selected", FIELD)], foreground=[("selected", GOLD)])
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT,
                        rowheight=32, borderwidth=0)
        style.configure("Treeview.Heading", background=FIELD, foreground=MUTED, padding=7)
        style.map("Treeview", background=[("selected", "#34415b")])
        self.option_add("*TCombobox*Listbox.background", FIELD)
        self.option_add("*TCombobox*Listbox.foreground", TEXT)

    def text_widget(self, parent, height=8):
        t = tk.Text(parent, height=height, wrap="word", bg=PANEL, fg=TEXT, insertbackground=GOLD,
                    relief="flat", font=(FONT, 10), padx=14, pady=10, undo=True)
        return t

    def set_text(self, widget, text):
        widget.delete("1.0", "end")
        widget.insert("1.0", text)

    def button(self, parent, title, command, accent=False):
        b = ttk.Button(parent, text=title, command=command, style="Accent.TButton" if accent else "TButton")
        b.pack(side="left", padx=(0, 7))
        return b

    def _build(self):
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=24, pady=(18, 12))
        tk.Label(header, text="E7 / 装备研判台", bg=BG, fg=GOLD, font=(FONT, 23, "bold")).pack(side="left")
        tk.Label(header, text="中文客户端 · 实时观察 · 每一跳都有依据", bg=BG, fg=MUTED,
                 font=(FONT, 11)).pack(side="left", padx=22)
        ttk.Checkbutton(header, text="窗口置顶", variable=self.topmost,
                        command=lambda: self.attributes("-topmost", self.topmost.get())).pack(side="right")
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=24, pady=(0, 10))
        self.button(toolbar, "① 框选面板", self.select_region, True)
        self.button(toolbar, "识别一次 F8", self.scan_once)
        self.live_button = self.button(toolbar, "开始实时 F9", self.toggle_live)
        self.button(toolbar, "读取截图", self.open_image)
        self.button(toolbar, "加载演示", self.load_demo)
        self.button(toolbar, "演示下一跳", self.demo_roll)
        ttk.Label(toolbar,text="批量部位",background=BG,foreground=MUTED).pack(side='left',padx=(8,4))
        self.batch_slot=tk.StringVar(value='头盔')
        ttk.Combobox(toolbar,textvariable=self.batch_slot,values=SLOTS,state='readonly',width=7).pack(side='left')
        tk.Label(self, textvariable=self.status, bg=BG, fg=MUTED, anchor="w", font=(FONT, 10)).pack(fill="x", padx=24, pady=(0, 12))
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=24, pady=(0, 12))
        left = ttk.Frame(body, style="Card.TFrame", padding=18, width=390)
        left.pack(side="left", fill="y", padx=(0, 16))
        left.pack_propagate(False)
        ttk.Label(left, text="01  装备属性校对", font=(FONT, 14, "bold")).pack(anchor="w", pady=(0, 10))
        self.field(left, "装备名称", self.vars["name"])
        row = ttk.Frame(left, style="Card.TFrame")
        row.pack(fill="x", pady=5)
        for title, key, values in [("部位", "slot", SLOTS), ("品质", "grade", ["史诗", "英雄", "稀有", "优良", "普通"])]:
            col = ttk.Frame(row, style="Card.TFrame")
            col.pack(side="left", fill="x", expand=True, padx=(0, 8))
            ttk.Label(col, text=title, style="Muted.TLabel").pack(anchor="w")
            ttk.Combobox(col, textvariable=self.vars[key], values=values, state="readonly", width=12).pack(fill="x", pady=(4, 0))
        self.field(left, "套装", self.vars["set_name"], SETS)
        row = ttk.Frame(left, style="Card.TFrame")
        row.pack(fill="x", pady=5)
        for title, key in [("装备等级", "level"), ("强化等级 0—15", "enhance")]:
            col = ttk.Frame(row, style="Card.TFrame")
            col.pack(side="left", fill="x", expand=True, padx=(0, 8))
            ttk.Label(col, text=title, style="Muted.TLabel").pack(anchor="w")
            ttk.Entry(col, textvariable=self.vars[key], width=12).pack(fill="x", pady=(4, 0))
        ttk.Label(left, text="主属性  /  类型中的 % 决定单位", style="Muted.TLabel").pack(anchor="w", pady=(12, 5))
        self.stat_row(left, self.main_key, self.main_value)
        ttk.Label(left, text="副属性  /  固定值与百分比请区分", style="Muted.TLabel").pack(anchor="w", pady=(12, 5))
        for k, v in zip(self.sub_keys, self.sub_values):
            self.stat_row(left, k, v)
        ttk.Checkbutton(left, text="我已核对本次的所有属性与单位", variable=self.confirmed).pack(anchor="w", pady=(15, 7))
        ttk.Button(left, text="② 计算评分与角色适配", command=self.calculate, style="Accent.TButton").pack(fill="x", pady=4)
        ttk.Button(left, text="③ 校对并记录本次强化快照", command=self.record).pack(fill="x", pady=4)
        ttk.Button(left, text="切换到另一件装备（新档案）", command=self.new_item).pack(fill="x", pady=4)
        ttk.Label(left, text="只观察屏幕，不操作游戏。\n每次切换装备请新建档案。\n实时模式有新结果时会撤销校对标记。",
                  foreground=MUTED, justify="left", wraplength=335).pack(anchor="w", pady=(12, 0))
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True)
        banner = ttk.Frame(right, style="Card.TFrame", padding=18)
        banner.pack(fill="x", pady=(0, 12))
        self.decision_label = ttk.Label(banner, text="等待装备", font=(FONT, 22, "bold"), foreground=GOLD)
        self.decision_label.pack(anchor="w")
        self.score_label = ttk.Label(banner, text="副属性参考分 —  /  角色有效分见下表", foreground=MUTED)
        self.score_label.pack(anchor="w", pady=6)
        self.reason = ttk.Label(banner, text="加载演示即可体验属性识别、角色适配和强化记录。", wraplength=800, justify="left")
        self.reason.pack(fill="x")
        self.notebook = ttk.Notebook(right)
        self.notebook.pack(fill="both", expand=True)
        roles_tab = ttk.Frame(self.notebook, style="Card.TFrame", padding=12)
        history_tab = ttk.Frame(self.notebook, style="Card.TFrame", padding=12)
        raw_tab = ttk.Frame(self.notebook, style="Card.TFrame", padding=12)
        rules_tab = ttk.Frame(self.notebook, style="Card.TFrame", padding=12)
        db_tab = ttk.Frame(self.notebook, style="Card.TFrame", padding=12)
        self.batch_tab=ttk.Frame(self.notebook,style='Card.TFrame',padding=12)
        self.notebook.add(self.batch_tab,text='制作总览')
        ttk.Label(self.batch_tab,text='读取整张制作总览截图，或框选完整游戏窗口；按左→右、上→下编号。点击一件可校对。',
                  foreground=MUTED,wraplength=760).pack(anchor='w',pady=(0,10))
        self.batch_tree=ttk.Treeview(self.batch_tab,columns=('id','gear','screen','score','spd','advice'),show='headings',height=10)
        for key,title,width in [('id','#',35),('gear','品质 / 套装',160),('screen','画面分',70),
                                ('score','参考分',70),('spd','速度',55),('advice','未校对初筛',180)]:
            self.batch_tree.heading(key,text=title);self.batch_tree.column(key,width=width,minwidth=30)
        self.batch_tree.pack(fill='both',expand=True)
        self.batch_tree.bind('<<TreeviewSelect>>',self.choose_batch)
        ttk.Label(self.batch_tab,text='未知图标/数字留空并标记待校对。当前图标模板覆盖这次截图中的反击、抵抗、破灭、吸血套装。\n制作模式按初始+0处理，不用于库存或已强化装备；画面分与参考分使用不同口径。',
                  foreground=MUTED,wraplength=760).pack(anchor='w',pady=(12,0))
        for tab, title in [(roles_tab, "角色适配"), (history_tab, "强化跳值"), (raw_tab, "原始识别"),
                           (rules_tab, "判断规则"), (db_tab, "角色数据库")]:
            self.notebook.add(tab, text=title)
        top = ttk.Frame(roles_tab, style="Card.TFrame")
        top.pack(fill="x", pady=(0, 8))
        ttk.Checkbutton(top, text="只看我拥有的角色", variable=self.owned_only, command=self.calculate).pack(side="left")
        self.hero_count = ttk.Label(top, text="", foreground=MUTED)
        self.hero_count.pack(side="right")
        self.roles_tree = ttk.Treeview(roles_tab, columns=("hero", "score", "main", "set"), show="headings", height=6)
        for key, title, width in [("hero", "候选角色 / 玩法", 260), ("score", "有效分", 80),
                                  ("main", "主属性", 90), ("set", "套装", 80)]:
            self.roles_tree.heading(key, text=title)
            self.roles_tree.column(key, width=width, minwidth=60)
        self.roles_tree.pack(fill="both", expand=True)
        self.roles_tree.bind("<<TreeviewSelect>>", self.show_role)
        self.role_detail = self.text_widget(roles_tab, 8)
        self.role_detail.pack(fill="x", pady=(10, 0))
        self.role_detail.insert("1.0", "推荐基于角色玩法权重，分数不是适配概率。\n内置342个社区角色候选，自动分类仍需按玩法校准。\n单件装备无法判断最终面板、暴击溢出、整套搭配或谁是最优人选。")
        hbar = ttk.Frame(history_tab, style="Card.TFrame")
        hbar.pack(fill="x", pady=(0, 10))
        self.item_var = tk.StringVar()
        self.item_combo = ttk.Combobox(hbar, textvariable=self.item_var, state="readonly", width=30)
        self.item_combo.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.item_combo.bind("<<ComboboxSelected>>", self.choose_item)
        self.button(hbar, "导出记录", self.export_records)
        self.history_text = self.text_widget(history_tab, 15)
        self.history_text.pack(fill="both", expand=True)
        self.raw = self.text_widget(raw_tab, 15)
        self.raw.pack(fill="both", expand=True)
        ttk.Label(raw_tab, text="OCR不提供可靠置信分。可在此修改文字后重新解析；主属性请写“主属性：”。",
                  wraplength=740, foreground=MUTED).pack(anchor="w", pady=8)
        ttk.Button(raw_tab, text="解析上面的文字", command=self.parse_raw).pack(anchor="w")
        self.rules_text = self.text_widget(rules_tab, 15)
        self.rules_text.pack(fill="both", expand=True)
        self.set_text(self.rules_text, json.dumps(self.rules, ensure_ascii=False, indent=2))
        ttk.Button(rules_tab, text="保存并应用规则", command=self.save_rules).pack(anchor="w", pady=(8, 0))
        ttk.Label(db_tab, text="角色数据 ≠ 配装结论。自动导入按职业/技能粗分，必须按自己的玩法校准。",
                  wraplength=740, foreground=MUTED).pack(anchor="w", pady=(0, 8))
        dbar = ttk.Frame(db_tab, style="Card.TFrame")
        dbar.pack(fill="x", pady=(0, 10))
        self.button(dbar, "导入本地JSON", self.import_local)
        self.button(dbar, "下载社区角色库", self.download_heroes)
        self.button(dbar, "导出角色档案", self.export_heroes)
        self.db_list = tk.Listbox(db_tab, height=7, bg=PANEL, fg=TEXT, selectbackground=FIELD,
                                 font=(FONT, 10), relief="flat", exportselection=False)
        self.db_list.pack(fill="both", expand=True)
        self.db_list.bind("<<ListboxSelect>>", self.edit_hero)
        self.hero_editor = self.text_widget(db_tab, 10)
        self.hero_editor.pack(fill="x", pady=(8, 0))
        ttk.Button(db_tab, text="保存选中角色（owned:true 为拥有）", command=self.save_hero).pack(anchor="w", pady=(8, 0))

    def field(self, parent, title, variable, values=None):
        ttk.Label(parent, text=title, style="Muted.TLabel").pack(anchor="w", pady=(5, 4))
        if values:
            ttk.Combobox(parent, textvariable=variable, values=values).pack(fill="x")
        else:
            ttk.Entry(parent, textvariable=variable).pack(fill="x")

    def stat_row(self, parent, keyvar, valuevar):
        row = ttk.Frame(parent, style="Card.TFrame")
        row.pack(fill="x", pady=3)
        ttk.Combobox(row, textvariable=keyvar, values=[""] + list(LABELS.values()), state="readonly", width=18).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Entry(row, textvariable=valuevar, width=9).pack(side="left")

    def get_gear(self):
        inverse = {v: k for k, v in LABELS.items()}
        data = {k: v.get().strip() for k, v in self.vars.items()}
        for k in ["level", "enhance"]:
            data[k] = int(data[k]) if data[k] else None
        def stat(key, value):
            if not key.get() and not value.get().strip():
                return None
            if not key.get() or not value.get().strip():
                raise ValueError("属性类型和数值都需要填写；空白副属性请同时清空两项")
            return Stat(inverse[key.get()], float(value.get().strip().rstrip("%")))
        data["main"] = stat(self.main_key, self.main_value)
        data["subs"] = [s for s in (stat(k, v) for k, v in zip(self.sub_keys, self.sub_values)) if s]
        return Gear(**data,screen_score=self.screen_score)

    def fill_gear(self, gear):
        self.screen_score=gear.screen_score
        for k, v in self.vars.items():
            value = getattr(gear, k)
            v.set("" if value is None else str(value))
        self.main_key.set(LABELS.get(gear.main.key, "") if gear.main else "")
        self.main_value.set(f"{gear.main.value:g}" if gear.main else "")
        for i, (k, v) in enumerate(zip(self.sub_keys, self.sub_values)):
            s = gear.subs[i] if i < len(gear.subs) else None
            k.set(LABELS.get(s.key, "") if s else "")
            v.set(f"{s.value:g}" if s else "")
        self.confirmed.set(False)

    def calculate(self):
        try:
            gear = self.get_gear()
            history = self.db.observations(self.current_item) if self.current_item else []
            events = [o["event"] for o in history if o["event"]]
            result = evaluate(gear, self.rules, events, self.confirmed.get())
            self.decision_label.configure(text=result["decision"], foreground=GOLD if result["decision"] != "保留候选" else GREEN)
            game_score=f"画面分 {gear.screen_score:g}  /  " if gear.screen_score is not None else ''
            self.score_label.configure(text=f"{game_score}副属性参考分 {result['score']:.1f}  /  两者口径不同，不相加")
            self.reason.configure(text="\n".join("• " + r for r in result["reasons"][:4]))
            self.roles_tree.delete(*self.roles_tree.get_children())
            self.rec_rows = {}
            self.rec_list = recommend(gear, self.heroes, self.rules, self.owned_only.get()) if not result["errors"] else []
            for index, rec in enumerate(self.rec_list[:50]):
                iid = str(index)
                self.rec_rows[iid] = rec
                self.roles_tree.insert("", "end", iid=iid, values=(f"{rec['name']} / {rec['archetype']}", rec["effective"],
                                       "可用" if rec["main_ok"] else "不合适" if rec['main_ok'] is False else '未校准', "匹配" if rec["set_match"] else "未指定/散件"))
            self.hero_count.configure(text=f"数据库 {len(self.heroes)} 人 · 展示前50")
            if self.rec_list:
                self.roles_tree.selection_set("0")
                self.show_role()
            else:
                self.set_text(self.role_detail, "请先补全装备属性。若勾选只看已拥有，请在角色数据库把 owned 改为 true。")
            return gear
        except (ValueError, KeyError, TypeError) as exc:
            self.status.set("请校对：" + str(exc))
            self.decision_label.configure(text="待校对", foreground=GOLD)
            return None

    def show_batch(self, result):
        self.batch_entries=result['entries']
        self.batch_tree.delete(*self.batch_tree.get_children())
        self.current_item=None
        self.fill_gear(Gear())
        for i,entry in enumerate(self.batch_entries):
            g=entry['gear'];e=evaluate(g,self.rules,confirmed=True)
            speed=next((s.value for s in g.subs if s.key=='spd'),0)
            screen=entry['screen_score']
            advice=e['decision'] if not e['errors'] else '待补全'
            self.batch_tree.insert('', 'end', iid=str(i),values=(i+1,f'{g.grade} / {g.set_name or "未知"}',
                                   f'{screen:g}' if screen is not None else '—',f'{e["score"]:.1f}',f'{speed:g}',advice))
        self.notebook.select(self.batch_tab)
        self.decision_label.configure(text=f'识别到 {len(self.batch_entries)} 件制作装备',foreground=GOLD)
        self.score_label.configure(text='逐件点击、校对后再记录。黄色画面分与副属性参考分分开显示。')
        self.reason.configure(text='批量初筛仅用于找候选；未知图标或数字会留空。切换制作批次会产生新的候选列表。')

    def choose_batch(self,event=None):
        selected=self.batch_tree.selection()
        if not selected:return
        self.stop_live()
        self.current_item=None
        entry=self.batch_entries[int(selected[0])]
        self.fill_gear(entry['gear'])
        self.calculate()
        self.status.set('已选择制作候选；请核对属性。'+ '；'.join(entry['gear'].warnings))

    def show_role(self, event=None):
        selected = self.roles_tree.selection()
        if not selected or selected[0] not in self.rec_rows:
            return
        r = self.rec_rows[selected[0]]
        contributions = "、".join(f"{LABELS.get(k, k)} +{v:.1f}" for k, v in r["contribution"].items())
        self.set_text(self.role_detail, f"{r['name']}  ·  {r['name_en']}\n"
                      f"玩法：{r['archetype']}　有效分：{r['effective']}（不是百分比）\n"
                      f"有效词条：{'、'.join(r['useful']) or '无'}　低效/无效：{'、'.join(r['wasted']) or '无'}\n"
                      f"单件基础贡献（主+副）：{contributions}\n"
                      f"依据：{r['basis']}\n"
                      "单件基础贡献不含套装、神器、专属、阵型、被动及最终面板溢出；需结合其他五件装备。")

    def parse_raw(self):
        self.stop_live()
        gear = parse_text(self.raw.get("1.0", "end"))
        self.fill_gear(gear)
        self.calculate()
        self.status.set("文字已解析，核对左侧；" + "；".join(gear.warnings))

    def load_demo(self):
        self.stop_live()
        self.current_item = None
        text = (ROOT / "data/demo.txt").read_text(encoding="utf-8")
        self.set_text(self.raw, text)
        self.fill_gear(parse_text(text))
        self.confirmed.set(True)
        self.calculate()
        self.set_text(self.history_text, "演示：先点击“记录本次强化快照”，再点“演示下一跳”，校对后再次记录。\n演示数据不是游戏读取结果。")
        self.status.set("演示数据已载入；可以查看角色有效词条并体验逐次强化记录。")

    def demo_roll(self):
        if not self.vars["name"].get().startswith("史诗+0测试项链"):
            self.status.set("请先加载演示；此按钮只修改测试装备。")
            return
        gear = self.get_gear()
        if gear.enhance >= 15:
            self.status.set("演示已到+15。重新加载演示可重来。")
            return
        gear.enhance += 3
        next(s for s in gear.subs if s.key == "spd").value += 3
        gear.main.value += 8
        self.fill_gear(gear)
        self.confirmed.set(True)
        self.calculate()
        self.status.set("模拟了一次速度+3。点击“记录本次强化快照”可保存该跳。")

    def new_item(self):
        self.stop_live()
        self.current_item = None
        self.confirmed.set(False)
        self.item_var.set("")
        self.set_text(self.history_text, "新装备尚未记录基线。校对后点击记录。\n若装备已经强化，此前的每次跳值无法由最终属性唯一还原。")
        self.status.set("已解除上一件装备的记录。请打开新装备，再识别并记录基线。")

    def record(self):
        self.stop_live()
        gear = self.calculate()
        if not gear:
            return
        if not self.confirmed.get():
            messagebox.showinfo("先校对", "核对属性后，请勾选“我已核对本次的所有属性与单位”。")
            return
        errors = validate(gear)
        if errors:
            messagebox.showerror("属性待校对", "\n".join(errors))
            return
        try:
            if self.current_item is None:
                self.current_item = self.db.create_item(gear.name or f"{gear.set_name}{gear.slot}")
            event = self.db.record(self.current_item, gear)
            self.refresh_items()
            self.show_history()
            self.calculate()
            self.status.set("已记录。强化后再次识别、校对、记录；切换装备前请新建档案。" if event else "属性与上次相同，未重复保存。")
        except ValueError as exc:
            messagebox.showerror("未记录此次变化", str(exc))

    def refresh_items(self):
        self.item_ids = {}
        for item_id, label, date in self.db.list_items():
            self.item_ids[f"#{item_id}  {label}"] = item_id
        self.item_combo["values"] = list(self.item_ids)
        for label, item_id in self.item_ids.items():
            if self.current_item == item_id:
                self.item_var.set(label)

    def choose_item(self, event=None):
        self.stop_live()
        self.current_item = self.item_ids.get(self.item_var.get())
        history = self.db.observations(self.current_item)
        if history:
            self.fill_gear(Gear.from_dict(history[-1]["gear"]))
            self.confirmed.set(True)
            self.calculate()
        self.show_history()
        self.status.set("已加载历史档案；继续强化前请确认游戏中是同一件装备。")

    def show_history(self):
        history = self.db.observations(self.current_item)
        lines = []
        for o in history:
            g = o["gear"]
            event = o["event"]
            lines.append(f"{o['created']}  ·  +{g['enhance']}")
            if not event:
                lines.append("起始基线；此前逐跳历史未知。")
            else:
                lines.append(f"+{event['from']} → +{event['to']}  /  {event['note']}")
                for c in event["changes"]:
                    old = "无" if c["before"] is None else f"{c['before']:g}"
                    lines.append(f"  {LABELS[c['key']]}：{old} → {c['after']:g}　{c['kind']} +{c['delta']:g}")
                mc=event.get('main_change')
                if mc and mc['delta']:
                    lines.append(f"  主属性成长（单列）：{LABELS[mc['key']]} {mc['before']:g} → {mc['after']:g}，+{mc['delta']:g}")
                if event.get('screen_score_before') is not None and event.get('screen_score_after') is not None:
                    lines.append(f"  画面装备分数：{event['screen_score_before']:g} → {event['screen_score_after']:g}（不同于副属性分）")
            lines.append("")
        self.set_text(self.history_text, "\n".join(lines) or "暂无记录。")

    def export_records(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", initialfile="e7-enhancement-history.json")
        if path:
            self.db.export(path)
            self.status.set("强化记录已导出。")

    def select_region(self):
        self.stop_live()
        RegionSelector(self, self.region_selected)

    def region_selected(self, rect):
        self.region = rect
        self.status.set(f"已选择屏幕区域 {rect}。保持游戏窗口位置不变，按F8读取。")

    def ensure_ocr(self):
        if self.ocr is None:
            self.ocr = WindowsOCR()
        return self.ocr

    def scan_once(self):
        if not self.region:
            self.status.set("请先框选完整的单件装备面板。")
            return
        self.start_scan({"rect": self.region[:]})

    def open_image(self):
        path = filedialog.askopenfilename(filetypes=[("装备截图", "*.png *.jpg *.jpeg *.bmp"), ("所有文件", "*.*")])
        if path:
            self.stop_live()
            self.start_scan({"path": str(Path(path).resolve())})

    def start_scan(self, request):
        if self.busy:
            self.status.set("上一轮OCR仍在处理，请稍候。")
            return
        self.busy = True
        session = self.session
        slot=self.batch_slot.get()
        self.status.set("正在读取中文装备属性…请保持面板静止。")
        def run():
            try:
                ocr = self.ensure_ocr()
                data = ScreenReader(ocr).read(request,slot=slot)
                self.results.put(("ocr", session, data))
            except Exception as exc:
                self.results.put(("error", session, str(exc)))
        threading.Thread(target=run, daemon=True).start()

    def toggle_live(self):
        if self.live:
            self.stop_live()
            self.status.set("实时识别已暂停。")
            return
        if not self.region:
            self.status.set("先框选单件装备面板，再开始实时识别。")
            return
        self.live = True
        self.candidate = None
        self.candidate_count = 0
        self.last_applied = None
        self.live_button.configure(text="暂停实时 F9")
        self.scan_once()

    def stop_live(self):
        self.live = False
        self.session += 1
        self.live_button.configure(text="开始实时 F9")

    def poll(self):
        try:
            while True:
                kind, session, value = self.results.get_nowait()
                if kind in {"ocr", "error"}:
                    self.busy = False
                    if session != self.session:
                        if self.live:
                            token = self.session
                            self.after(100, lambda t=token: self.scan_once() if self.live and self.session == t else None)
                        continue
                if kind == "error":
                    self.stop_live()
                    self.status.set("识别失败：" + value[:200])
                    if self.ocr:
                        self.ocr.close()
                        self.ocr = None
                elif kind == "ocr":
                    text = value.get("text", "")
                    fingerprint=json.dumps([e['gear'].to_dict() for e in value['entries']],ensure_ascii=False) if value.get('kind')=='batch' else json.dumps(value['gear'].to_dict(),ensure_ascii=False)
                    self.set_text(self.raw, text)
                    stable = True
                    if self.live:
                        self.candidate_count = self.candidate_count + 1 if fingerprint == self.candidate else 1
                        self.candidate = fingerprint
                        stable = self.candidate_count >= 2
                    if text.strip() and stable and fingerprint != self.last_applied:
                        if value.get('kind')=='batch':
                            self.show_batch(value)
                            self.status.set('制作总览已识别，点击候选装备后校对。')
                        else:
                            gear=value['gear']
                            self.fill_gear(gear)
                            self.calculate()
                            self.status.set('新属性已识别，请校对。'+'；'.join(gear.warnings))
                        self.last_applied = fingerprint
                    elif not text.strip():
                        self.status.set("没有识别到文字；检查游戏是否被遮挡、最小化，或重新框选。")
                    elif not stable:
                        self.status.set("等待连续两次相同结果，避免把强化动画当作属性变化。")
                    else:
                        self.status.set("实时观察中，当前文字稳定。校对前可按F9暂停。")
                    if self.live:
                        token = self.session
                        self.after(1800, lambda t=token: self.scan_once() if self.live and self.session == t else None)
                elif kind == "heroes":
                    self.merge_heroes(value)
                    self.status.set(f"社区库已导入，共{len(self.heroes)}名角色；自动分类仅作候选，请校准权重。")
                elif kind == "download_error":
                    self.status.set("下载失败，可在浏览器下载社区 heroes.json 后导入：" + value[:150])
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def save_rules(self):
        try:
            value = json.loads(self.rules_text.get("1.0", "end"))
            merged = json.loads(json.dumps(DEFAULT_RULES))
            merged.update(value)
            for k in ["try_score", "keep_reforged_score", "speed_chase_start", "single_percent_keep",
                      "triple_roll_keep", "speed_keep", "finished_keep_score"]:
                if not isinstance(merged[k], (int, float)) or not 0 <= merged[k] <= 1000:
                    raise ValueError(f"{k} 必须为0—1000的数值")
            for k in LABELS:
                v = merged["weights"].get(k, 1)
                if not isinstance(v, (int, float)) or not 0 <= v <= 100:
                    raise ValueError("词条权重须为0—100的数值")
            if any(not isinstance(merged["flat_reference"].get(k), (int, float)) or
                   not 0 < merged["flat_reference"][k] <= 100000 for k in ["atk", "hp", "def"]):
                raise ValueError("固定值换算参考基础属性须大于0")
            (USER / "rules.json").write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
            self.rules = merged
            self.calculate()
            self.status.set("规则已保存并应用。")
        except (ValueError, TypeError, KeyError) as exc:
            messagebox.showerror("规则格式错误", str(exc))

    def refresh_heroes(self):
        self.db_list.delete(0, "end")
        for h in self.heroes:
            self.db_list.insert("end", f"{'● 已拥有' if h.get('owned') else '○ 未标记'}  {h.get('name_zh') or h['name']}  /  {h.get('archetype', '自定义')}")

    def edit_hero(self, event=None):
        sel = self.db_list.curselection()
        if sel:
            self.set_text(self.hero_editor, json.dumps(self.heroes[sel[0]], ensure_ascii=False, indent=2))

    def persist_heroes(self):
        (USER / "heroes.json").write_text(json.dumps({"source": SOURCE, "heroes": self.heroes}, ensure_ascii=False, indent=2), encoding="utf-8")

    def save_hero(self):
        sel = self.db_list.curselection()
        if not sel:
            return
        try:
            parsed = import_heroes([json.loads(self.hero_editor.get("1.0", "end"))])[0]
            self.heroes[sel[0]] = parsed
            self.persist_heroes()
            self.refresh_heroes()
            self.calculate()
            self.status.set("角色档案已保存；可编辑 weights 设置每条属性的有效权重。")
        except (ValueError, KeyError, IndexError) as exc:
            messagebox.showerror("角色格式错误", str(exc))

    def merge_heroes(self, imported):
        existing = {h["name"]: h for h in self.heroes}
        for h in imported:
            # 导入补充角色，保留用户已有配装档案。
            if h["name"] not in existing:
                existing[h["name"]] = h
        self.heroes = list(existing.values())
        self.persist_heroes()
        self.refresh_heroes()
        self.calculate()

    def import_local(self):
        path = filedialog.askopenfilename(filetypes=[("角色数据库 JSON", "*.json")])
        if path:
            try:
                self.merge_heroes(import_heroes(json.loads(Path(path).read_text(encoding="utf-8-sig"))))
                self.status.set(f"已合并角色档案，共{len(self.heroes)}人。已有角色档案保留，可在编辑框中调整。")
            except (OSError, ValueError) as exc:
                messagebox.showerror("导入失败", str(exc))

    def download_heroes(self):
        self.status.set("正在从公开社区仓库下载角色JSON；不会上传屏幕或装备记录。")
        def run():
            try:
                request = urllib.request.Request(SOURCE, headers={"User-Agent": "E7GearAdvisor/0.1"})
                with urllib.request.urlopen(request, timeout=25) as r:
                    data = r.read(15 * 1024 * 1024 + 1)
                if len(data) > 15 * 1024 * 1024:
                    raise ValueError("数据库超出15MB限制")
                self.results.put(("heroes", 0, import_heroes(json.loads(data))))
            except Exception as exc:
                self.results.put(("download_error", 0, str(exc)))
        threading.Thread(target=run, daemon=True).start()

    def export_heroes(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", initialfile="e7-hero-profiles.json")
        if path:
            Path(path).write_text(json.dumps({"source": SOURCE, "heroes": self.heroes}, ensure_ascii=False, indent=2), encoding="utf-8")
            self.status.set("角色配装档案已导出。")

    def close(self):
        if self.ocr:
            self.ocr.close()
        self.db.close()
        self.destroy()


def main():
    if os.name == "nt":
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()
    app = Advisor()
    app.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        USER.mkdir(parents=True, exist_ok=True)
        details = traceback.format_exc()
        (USER / "startup-error.log").write_text(details, encoding="utf-8")
        if os.name == "nt":
            ctypes.windll.user32.MessageBoxW(None, "程序启动失败，请查看 userdata/startup-error.log。\n" + details[-600:],
                                            "装备研判台", 16)
        else:
            raise
