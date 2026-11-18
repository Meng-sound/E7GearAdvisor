"""统计模块：追加式事件日志 + 日/周/月/年聚合（纯标准库，不依赖第三方）。

事件格式（debug/统计.jsonl，每行一条）：
    {"t": "2026-11-10T01:20:33", "k": "buy", "item": "圣约书签", "qty": 50, "gold": 500000}
    {"t": "...", "k": "refresh", "sky": 3}
    {"t": "...", "k": "session"}          # 一次运行开始
"""
from __future__ import annotations

import json
import os
import time
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path

import shutil

from core import runtime_root, user_data_dir

FILE_NAME = "统计.jsonl"
ARCHIVE_PREFIX = "统计_归档_"


def stats_path() -> Path:
    """统计文件位置：用户数据目录（不会随程序更新丢失）。"""
    p = user_data_dir()
    target = p / FILE_NAME
    # 首次启动：把旧位置（程序目录 debug/）的数据迁移过来
    if not target.exists():
        old = runtime_root() / "debug" / FILE_NAME
        try:
            if old.exists() and old.resolve() != target.resolve():
                shutil.copy2(old, target)
        except Exception:  # noqa: BLE001
            pass
    return target


def log_event(kind: str, **fields) -> None:
    """追加一条事件（失败静默，绝不影响主流程）。"""
    try:
        rec = {"t": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "k": str(kind)}
        rec.update(fields)
        with stats_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


def load_events(path: Path | None = None) -> list[dict]:
    p = path or stats_path()
    out: list[dict] = []
    if not p.exists():
        return out
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if isinstance(rec, dict) and rec.get("t"):
                out.append(rec)
    except Exception:  # noqa: BLE001
        return out
    return out


def _parse(rec: dict) -> datetime | None:
    try:
        return datetime.strptime(str(rec["t"]), "%Y-%m-%dT%H:%M:%S")
    except Exception:  # noqa: BLE001
        return None


# ---------------- 聚合 ----------------
def bucket_key(dt: datetime, period: str) -> str:
    if period == "day":
        return dt.strftime("%Y-%m-%d")
    if period == "week":
        y, w, _ = dt.isocalendar()
        return f"{y}-W{w:02d}"
    if period == "month":
        return dt.strftime("%Y-%m")
    return dt.strftime("%Y")


def bucket_label(key: str, period: str) -> str:
    if period == "day":
        return key[5:]  # MM-DD
    if period == "week":
        y, w = key.split("-W")
        return f"{int(w)}周"
    if period == "month":
        return key[5:] + "月" if False else key
    return key + "年"


def _buckets(period: str, count: int, now: datetime | None = None) -> list[str]:
    """返回最近 count 个桶的 key（按时间正序，含空桶）。"""
    now = now or datetime.now()
    keys: list[str] = []
    if period == "day":
        for i in range(count - 1, -1, -1):
            keys.append((now - timedelta(days=i)).strftime("%Y-%m-%d"))
    elif period == "week":
        monday = now - timedelta(days=now.weekday())
        for i in range(count - 1, -1, -1):
            d = monday - timedelta(weeks=i)
            y, w, _ = d.isocalendar()
            keys.append(f"{y}-W{w:02d}")
    elif period == "month":
        y, m = now.year, now.month
        for i in range(count - 1, -1, -1):
            mm = m - i
            yy = y
            while mm <= 0:
                mm += 12
                yy -= 1
            keys.append(f"{yy}-{mm:02d}")
    else:
        for i in range(count - 1, -1, -1):
            keys.append(str(now.year - i))
    return keys


PERIOD_COUNT = {"day": 30, "week": 12, "month": 12, "year": 5}


def series(events: list[dict], period: str, metric: str) -> list[tuple[str, float]]:
    """按周期聚合某个指标。metric: covenant / mystic / sky / gold。"""
    order = _buckets(period, PERIOD_COUNT.get(period, 30))
    acc: dict[str, float] = {k: 0.0 for k in order}
    for rec in events:
        dt = _parse(rec)
        if dt is None:
            continue
        key = bucket_key(dt, period)
        if key not in acc:
            continue
        k = rec.get("k")
        if metric in ("covenant", "mystic"):
            if k == "buy" and rec.get("item") == ("圣约书签" if metric == "covenant" else "神秘奖牌"):
                qty = int(rec.get("qty") or 0)
                if metric == "covenant" and qty >= 50:
                    qty = 5  # 旧数据兼容：书签每次实际 5 个
                acc[key] += float(qty)
        elif metric == "sky":
            if k == "refresh":
                acc[key] += float(rec.get("sky") or 0)
        elif metric == "gold":
            if k == "buy":
                acc[key] += float(rec.get("gold") or 0)
    return [(bucket_label(k, period), acc[k]) for k in order]


def totals(events: list[dict], since: datetime | None = None) -> dict:
    """汇总：书签/神秘数量与次数、消耗天空石/金币。"""
    out = {"covenant": 0, "mystic": 0, "covenant_n": 0, "mystic_n": 0, "sky": 0, "gold": 0, "refresh": 0}
    _last_buy: dict = {}  # 防重复：同名商品 3 秒内重复记账只算一次
    for rec in events:
        dt = _parse(rec)
        if dt is None or (since is not None and dt < since):
            continue
        k = rec.get("k")
        if k == "buy":
            item = rec.get("item")
            qty = int(rec.get("qty") or 0)
            _prev = _last_buy.get(item)
            if _prev is not None and dt is not None and 0 <= (dt - _prev).total_seconds() <= 3:
                continue  # 同一购买弹窗被重复记了，跳过
            _last_buy[item] = dt if dt is not None else _prev
            if item == "圣约书签":
                # 一条 buy 事件 = 一次购买；书签固定 5 个/次，
                # 不再依赖 qty 字段（旧版本记成 50、OCR 也可能记成库存数）
                out["covenant"] += 5
                out["covenant_n"] += 1
            elif item == "神秘奖牌":
                out["mystic"] += 50
                out["mystic_n"] += 1
            out["gold"] += int(rec.get("gold") or 0)
        elif k == "refresh":
            out["sky"] += int(rec.get("sky") or 0)
            out["refresh"] += 1
    return out


def session_start_time(events: list[dict]) -> datetime | None:
    """最近一次 session 事件的时刻（用于「本次运行」统计）。"""
    last = None
    for rec in events:
        if rec.get("k") == "session":
            dt = _parse(rec)
            if dt is not None:
                last = dt
    return last


def session_totals(events: list[dict]) -> dict:
    start = session_start_time(events)
    return totals(events, since=start) if start else {"covenant": 0, "mystic": 0, "covenant_n": 0, "mystic_n": 0, "sky": 0, "gold": 0, "refresh": 0}


def avg_cost(t: dict, qty_per_buy: int = 50) -> tuple[float, float]:
    """每 50 书签的平均成本：(天空石, 金币)。

    天空石按「购买次数占比」分摊（书签和奖牌各占一个货位，按件数分摊不公平），
    金币只算书签自己的花费。
    """
    cov_n = int(t.get("covenant_n") or 0)
    mys_n = int(t.get("mystic_n") or 0)
    bundles = t.get("covenant", 0) / max(1, qty_per_buy)
    if bundles <= 0:
        return 0.0, 0.0
    share = cov_n / max(1, cov_n + mys_n)
    sky = t["sky"] * share / bundles
    gold = t["gold"] / bundles
    return sky, gold


def prune(days: float | None) -> tuple[int, Path | None]:
    """删除最近 N 天的事件（None=全部），返回 (删除条数, 归档路径)。"""
    p = stats_path()
    events = load_events(p)
    if not events:
        return 0, None
    now = datetime.now()
    keep: list[dict] = []
    removed = 0
    cutoff = None if days is None else now - timedelta(days=days)
    for rec in events:
        dt = _parse(rec)
        if days is None:
            removed += 1          # 全部历史：全删
            continue
        if dt is not None and dt >= cutoff:
            removed += 1          # 最近 N 天：删掉
        else:
            keep.append(rec)      # 更早的历史保留
    if removed == 0:
        return 0, None

    archive = p.parent / f"{ARCHIVE_PREFIX}{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
    try:
        archive.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in events), encoding="utf-8"
        )
        # 原子替换：先写临时文件再 rename，避免被占用时写坏原文件
        tmp = p.with_suffix(".tmp")
        tmp.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in keep), encoding="utf-8"
        )
        for _ in range(3):
            try:
                os.replace(tmp, p)
                break
            except PermissionError:
                time.sleep(0.3)
        else:
            raise PermissionError("统计文件被占用")
    except Exception:  # noqa: BLE001
        return 0, None
    return removed, archive
