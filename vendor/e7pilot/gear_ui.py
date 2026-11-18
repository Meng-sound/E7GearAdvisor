"""红装记录窗口：列出本次/历史买到的 85 传说装备（读 debug/统计.jsonl）。"""
from __future__ import annotations

import csv
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import stats


def _load_gear_rows() -> list[dict]:
    """取出购买记录（gear_buy），按时间倒序。"""
    rows: list[dict] = []
    for rec in stats.load_events():
        if rec.get("k") != "gear_buy":
            continue
        rows.append(rec)
    rows.sort(key=lambda r: str(r.get("t", "")), reverse=True)
    return rows


def _fmt_num(v, suffix: str = "") -> str:
    if v is None or v == "":
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if f == int(f):
        return f"{int(f)}{suffix}"
    return f"{f:g}{suffix}"


class GearWindow(tk.Toplevel):
    def __init__(self, master) -> None:
        super().__init__(master)
        self.title("🎽 红装记录")
        self.geometry("980x620")
        self.configure(bg="#1e1e1e")
        self._rows = _load_gear_rows()

        top = ttk.Frame(self, padding=(10, 8))
        top.pack(fill="x")
        self.summary = tk.StringVar(value="")
        ttk.Label(top, textvariable=self.summary, foreground="#2e7d32").pack(side="left")
        ttk.Button(top, text="刷新", command=self.refresh).pack(side="right", padx=4)
        ttk.Button(top, text="导出 CSV", command=self.export_csv).pack(side="right")

        cols = ("time", "name", "quality", "score", "speed", "crit", "critdmg", "price")
        heads = ("时间", "名称", "品质", "分数", "速度", "暴击", "暴伤", "价格")
        widths = (165, 230, 70, 60, 60, 70, 70, 110)
        self.tree = ttk.Treeview(self, columns=cols, show="headings")
        for c, h, w in zip(cols, heads, widths):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        sb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.place(relx=1.0, rely=1.0, anchor="se", height=520)

        self.refresh()

    def refresh(self) -> None:
        self._rows = _load_gear_rows()
        for item in self.tree.get_children():
            self.tree.delete(item)
        for r in self._rows:
            self.tree.insert(
                "",
                "end",
                values=(
                    str(r.get("t", "")).replace("T", " "),
                    r.get("name", ""),
                    r.get("quality", ""),
                    _fmt_num(r.get("score")),
                    _fmt_num(r.get("speed")),
                    _fmt_num(r.get("crit"), "%"),
                    _fmt_num(r.get("critdmg"), "%"),
                    f"{int(r.get('price') or 0):,}",
                ),
            )
        total_gold = sum(int(r.get("price") or 0) for r in self._rows)
        self.summary.set(f"共 {len(self._rows)} 件，消耗金币 {total_gold:,}")

    def export_csv(self) -> None:
        if not self._rows:
            messagebox.showinfo("导出", "还没有红装记录", parent=self)
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".csv",
            initialfile=f"红装记录_{time.strftime('%Y%m%d_%H%M%S')}.csv",
            filetypes=[("CSV 文件", "*.csv")],
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["时间", "名称", "品质", "装备分数", "速度", "暴击", "暴伤", "价格"])
                for r in self._rows:
                    w.writerow([
                        str(r.get("t", "")),
                        r.get("name", ""),
                        r.get("quality", ""),
                        r.get("score", ""),
                        r.get("speed", ""),
                        r.get("crit", ""),
                        r.get("critdmg", ""),
                        int(r.get("price") or 0),
                    ])
            messagebox.showinfo("导出完成", f"已保存到：\n{path}", parent=self)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("导出失败", str(exc), parent=self)
