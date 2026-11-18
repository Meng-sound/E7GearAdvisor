"""装备解析、可解释评分、角色适配与强化观察。仅使用 Python 标准库。"""
from __future__ import annotations

import copy
import json
import math
import re
import sqlite3
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

LABELS = {
    "atk_pct": "攻击力%", "hp_pct": "生命值%", "def_pct": "防御力%",
    "atk": "攻击力", "hp": "生命值", "def": "防御力", "spd": "速度",
    "crit": "暴击率%", "cdmg": "暴击伤害%", "eff": "效果命中%", "res": "效果抗性%",
}
SLOTS = ["武器", "头盔", "铠甲", "项链", "戒指", "鞋子"]
SETS = ['攻击','防御','生命','速度','暴击','破灭','命中','抵抗','吸血','反击','夹攻','免疫','愤怒','贯穿','复仇','伤口','保护','激流','逆袭','回击','开战','追击','弱化','全力']

PCT_KEYS = {k for k in LABELS if k not in {"atk", "hp", "def", "spd"}}
WEIGHTS = {k: (1.5 if k == "crit" else 1.125 if k == "cdmg" else 2 if k == "spd" else 1)
           for k in LABELS}
DEFAULT_RULES = {
    "version": 1,
    "source": "用户提供的 GVG 萌新打铁指南思维导图；视频正文未读取",
    "source_url": "https://www.bilibili.com/video/BV1VMnM6aEFf",
    "weights": WEIGHTS,
    "flat_reference": {"atk": 1000, "hp": 6000, "def": 600},
    "try_score": 28, "keep_reforged_score": 90, "speed_chase_start": 2,
    "single_percent_keep": 25, "triple_roll_keep": 3,
    "speed_keep": 15, "finished_keep_score": 70,
    "stop_after_low_rolls": False,
    "notes": ["70分成品保留线、15速保留线是工具默认值，不是视频结论，可自行调整。",
              "固定生命/攻击/防御以参考基础属性换算为百分比；不是将小词条一律算5分。",
              "评分只统计副属性；主属性与套装用于角色适配。", 
              "未实现无历史条件下的精确重铸预测；只对实际90级成品应用90分规则。"],
}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Stat:
    key: str
    value: float


@dataclass
class Gear:
    name: str = ""
    slot: str = ""
    set_name: str = ""
    level: int | None = None
    enhance: int | None = None
    grade: str = ""
    main: Stat | None = None
    subs: list[Stat] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    screen_score: float | None = None

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        d = copy.deepcopy(d)
        d["main"] = Stat(**d["main"]) if d.get("main") else None
        d["subs"] = [Stat(**s) for s in d.get("subs", [])]
        return cls(**d)


def _clean(s):
    s = unicodedata.normalize("NFKC", s)
    return re.sub(r"\s+", "", s).replace("％", "%").replace("﹢", "+")


def parse_stat(line: str):
    line = re.sub(r'\(\+[^)]*\)', '', _clean(line))
    names = [("暴击伤害", "cdmg"), ("暴击伤害率", "cdmg"), ("暴击率", "crit"),
             ("暴击概率", "crit"), ("效果命中", "eff"), ("效果抗性", "res"),
             ("效果抵抗", "res"), ("速度", "spd"), ("攻击力", "atk"),
             ("生命值", "hp"), ("防御力", "def"), ("爆伤", "cdmg"),
             ("暴伤", "cdmg"), ("暴击", "crit"), ("攻击", "atk"),
             ("生命", "hp"), ("防御", "def"), ("命中", "eff"), ("抗性", "res")]
    for label, key in sorted(names, key=lambda p: -len(p[0])):
        if label not in line:
            continue
        # 套装加成行不作为副属性；需要选择仅包含单件装备的区域。
        if "套装" in line or "套裝" in line:
            return None
        raw_tail = line.split(label, 1)[1]
        prefix_percent = '%' in re.match(r'^[%:：]*',raw_tail).group(0)
        tail = raw_tail.lstrip("%:：")
        # 实机强化页：暴击伤害(1) 14%(+7%)，括号次数和本次增量均不是当前值。
        tail = re.sub(r"^\(\d+\)", "", tail)
        m = re.search(r"(?<![\d.,])[+]?((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(%?)(?![\d.,])", tail)
        if not m:
            return None
        if key in {"atk", "hp", "def"} and (prefix_percent or m.group(2)):
            key += "_pct"
        return Stat(key, float(m.group(1).replace(',','')))
    return None


def parse_text(text: str) -> Gear:
    lines = [_clean(l) for l in text.splitlines() if l.strip()]
    joined = "\n".join(lines)
    g = Gear()
    for slot in SLOTS:
        if slot in joined:
            g.slot = slot
            break
    if not g.slot and "靴" in joined:
        g.slot = "鞋子"
    if not g.slot and "头饰" in joined:
        g.slot = "头盔"
    if not g.slot and "盔甲" in joined:
        g.slot = "铠甲"
    for name in sorted(SETS, key=len, reverse=True):
        if name + "套装" in joined or name + "套裝" in joined or "套装:" + name in joined:
            g.set_name = name
            break
    for grade in ["史诗", "英雄", "稀有", "普通", "优良"]:
        if grade in joined:
            g.grade = grade
            break
    if "传说" in joined:
        g.grade = "史诗"
    m = re.search(r"(?:装备等级|等级|[Ll][Vv][.]?)[:：]?(\d{1,2})(?!\d)", joined)
    if m:
        g.level = int(m.group(1))
    else:
        # 面板中的裸等级必须独占一行，避免误把副属性数值当成装备等级。
        m = re.search(r"(?m)^(?:Lv[.]?)?(55|70|71|75|78|80|85|88|90)$", joined)
        if m:
            g.level = int(m.group(1))
    enhancement_text='\n'.join(line for line in lines if not any(word in line for word in ('获得','獲得','装备分数','裝備分數')))
    m = re.search(r"(?:强化|强[化]等级)[:：]?\+?(1[0-5]|[0-9])(?!\d)", enhancement_text)
    if not m:
        # 只允许无属性名称的标题行，防止把 +8% 攻击误当作强化等级。
        for line in lines:
            if not parse_stat(line) and not any(word in line for word in ("获得","獲得","装备分数","裝備分數")):
                m = re.search(r"\+(1[0-5]|[0-9])(?![\d.%])", line)
                if m:
                    break
    if m:
        g.enhance = int(m.group(1))
    stat_lines = [(l, parse_stat(l)) for l in lines]
    stat_lines = [(l, s) for l, s in stat_lines if s]
    main_seen = False
    for line, stat in stat_lines:
        if "主属性" in line or "主属" in line:
            if main_seen:
                g.warnings.append("发现多条主属性，可能框入对比装备。")
            g.main = stat
            main_seen = True
        else:
            g.subs.append(stat)
    if not main_seen and len(g.subs) >= 3:
        g.main = g.subs.pop(0)
        g.warnings.append("暂把第一条属性作为主属性，请在左侧校对。")
    header = []
    for line in lines:
        if parse_stat(line) or re.fullmatch(r"\d+", line):
            continue
        if any(k in line for k in ["套装", "等级", "副属性", "主属性", "强化:"]):
            continue
        header.append(line)
    if header:
        g.name = header[0][:70]
        if re.fullmatch(r'(?:传说|史诗|英雄|稀有)(?:武器|头盔|铠甲|项链|戒指|鞋子)',g.name) and len(header)>1:
            g.name=header[1][:70]
    return g


def validate(g: Gear):
    errors = []
    if g.slot not in SLOTS:
        errors.append("请选择装备部位")
    if not g.set_name:
        errors.append("请填写套装")
    if g.level is None or not 1 <= g.level <= 99:
        errors.append("请确认装备等级")
    if g.enhance is None or not 0 <= g.enhance <= 15:
        errors.append("请确认强化等级（0—15）")
    if g.grade not in ["史诗", "英雄", "稀有", "普通", "优良"]:
        errors.append("请确认装备品质")
    if not g.main:
        errors.append("缺少主属性")
    if not 1 <= len(g.subs) <= 4:
        errors.append("副属性数量须为1—4条")
    if len({s.key for s in g.subs}) != len(g.subs):
        errors.append("副属性重复，可能把主属性或对比面板也读入了")
    if g.main and any(s.key == g.main.key for s in g.subs):
        errors.append("主属性与副属性同名，请确认是否识别错行")
    for s in ([g.main] if g.main else []) + g.subs:
        if s.key not in LABELS or not math.isfinite(s.value) or s.value <= 0:
            errors.append("属性名称或数值无效")
        elif s.key in PCT_KEYS and s.value > 100:
            errors.append("单件百分比属性超过100，请核对小数点或单位")
        elif s.key == "spd" and s.value > 60:
            errors.append("单件速度超过60，请核对")
    if g.main:
        fixed = {"武器": "atk", "头盔": "hp", "铠甲": "def"}
        if g.slot in fixed and g.main.key != fixed[g.slot]:
            errors.append("该部位的主属性类型不符")
        if g.main.key == "spd" and g.slot != "鞋子":
            errors.append("速度主属性只适用于鞋子")
        if g.main.key in {"crit", "cdmg"} and g.slot != "项链":
            errors.append("暴击/暴伤主属性只适用于项链")
        if g.main.key in {"eff", "res"} and g.slot != "戒指":
            errors.append("命中/抗性主属性只适用于戒指")
    illegal = {"武器": {"def", "def_pct"}, "铠甲": {"atk", "atk_pct"}}
    if any(s.key in illegal.get(g.slot, set()) for s in g.subs):
        errors.append("副属性包含该部位不应出现的攻击/防御词条，请核对")
    initial = {"史诗": 4, "英雄": 3, "稀有": 2}.get(g.grade)
    if initial and g.enhance is not None:
        # 英雄装备在+12补第四条；稀有装备在+9、+12补第三、四条。
        expected = initial
        if initial == 3 and g.enhance >= 12:
            expected = 4
        if initial == 2:
            expected = 2 + int(g.enhance >= 9) + int(g.enhance >= 12)
        if len(g.subs) != expected:
            errors.append(f"{g.grade}+{g.enhance} 应有{expected}条副属性，当前{len(g.subs)}条")
    return list(dict.fromkeys(errors))


def stat_score(s: Stat, rules, base=None):
    if s.key in {"atk", "hp", "def"}:
        reference = (base or {}).get(s.key) or rules["flat_reference"][s.key]
        return s.value / reference * 100
    return s.value * rules["weights"].get(s.key, 1)


def total_score(g: Gear, rules):
    return sum(stat_score(s, rules) for s in g.subs)


def _submap(g):
    return {s.key: s.value for s in g.subs}


def compare_observation(before: Gear, after: Gear):
    """只能比较用户锁定的同一件装备；多次强化只记录合计，不臆造逐跳。"""
    a, b = _submap(before), _submap(after)
    if before.slot != after.slot or before.set_name != after.set_name or before.grade != after.grade:
        raise ValueError("部位、套装或品质发生改变，请新建装备档案")
    if not before.main or not after.main or before.main.key != after.main.key:
        raise ValueError("主属性类型改变，请先核对是否切换了装备")
    if before.level != after.level:
        raise ValueError("装备等级发生变化（可能重铸），请新建基线，不把变化计为强化跳值")
    if after.enhance is None or before.enhance is None or after.enhance < before.enhance:
        raise ValueError("强化等级倒退或缺失，请新建装备档案或校对")
    if after.main.value < before.main.value:
        raise ValueError("主属性下降，请核对是否识别错了装备")
    if after.enhance == before.enhance and after.main.value != before.main.value:
        raise ValueError("强化等级未变而主属性改变，请校对")
    if set(a) - set(b):
        raise ValueError("原有副属性消失，请核对识别结果")
    changes = []
    for key, value in b.items():
        delta = value - a.get(key, 0)
        if delta < 0:
            raise ValueError("副属性下降，不符合普通强化过程，请校对")
        if delta > 0:
            changes.append({"key": key, "before": a.get(key), "after": value,
                            "delta": delta, "kind": "新增" if key not in a else "提升"})
    steps = after.enhance // 3 - before.enhance // 3
    if not changes and after.enhance == before.enhance:
        return None
    if steps == 0 and changes:
        raise ValueError("未跨过副属性强化节点但副属性改变，可能是OCR或装备切换")
    if steps == 1 and len(changes) != 1:
        raise ValueError("单次副属性节点应只改变一条属性，当前结果需校对")
    if steps > 0 and (not changes or len(changes) > steps):
        raise ValueError("变化数量与跨过的强化节点不一致，请校对")
    if steps == 1 and changes[0]["kind"] == "新增" and len(a) == 4:
        raise ValueError("已有四条副属性时不应新增属性")
    if steps == 1:
        maxima = {"spd": 5, "crit": 6, "cdmg": 8, "atk": 60, "def": 45, "hp": 250}
        c = changes[0]
        maximum = maxima.get(c["key"], 9 if (after.level or 0) >= 86 else 8)
        if c["delta"] > maximum:
            raise ValueError("单次跳值超过保守上限，请检查OCR或是否更换了装备")
    exact = steps == 1
    return {"from": before.enhance, "to": after.enhance, "steps": steps,
            "exact": exact, "changes": changes,
            "main_change": {"key":after.main.key,"before":before.main.value,"after":after.main.value,
                            "delta":after.main.value-before.main.value},
            "screen_score_before":before.screen_score,"screen_score_after":after.screen_score,
            "note": "观察到单次节点" if exact else "跨越多节点，仅知道合计，逐跳顺序未知" if steps > 1 else "仅主属性成长"}


def evaluate(g: Gear, rules, events=None, confirmed=False):
    errors = validate(g)
    score = total_score(g, rules)
    reasons, keep = [], []
    subs = _submap(g)
    if g.level == 90 and g.enhance == 15 and score >= rules["keep_reforged_score"]:
        keep.append("实际90级成品达到90分保留线")
    if subs.get("spd", 0) >= rules["speed_keep"]:
        keep.append(f"速度达到自定义保留线{rules['speed_keep']}，可作为追速件")
    if any(s.key in {"atk_pct", "hp_pct", "def_pct", "eff", "res"} and
           s.value >= rules["single_percent_keep"] for s in g.subs):
        keep.append("单条百分比属性达到25，可保留专用角色候选")
    exact_rolls = [e for e in (events or []) if e["exact"] and e["changes"] and
                   e["changes"][0]["kind"] == "提升"]
    counts = {}
    for e in exact_rolls:
        k = e["changes"][0]["key"]
        counts[k] = counts.get(k, 0) + 1
    if max(counts.values(), default=0) >= rules["triple_roll_keep"]:
        keep.append("有同一词条被实际观察到提升至少三次")
    survival = {"hp", "hp_pct", "def", "def_pct"}
    if exact_rolls and len(exact_rolls) >= 3 and all(e["changes"][0]["key"] in survival for e in exact_rolls):
        keep.append("已观察到的提升集中生命/防御，保留生存配装候选")
    if keep:
        decision = "保留候选"
        reasons.extend(keep)
    elif g.enhance is not None and g.enhance < 15:
        if g.enhance == 0 and score >= rules["try_score"]:
            decision = "可以试强"
            reasons.append(f"初始副属性分{score:.1f}达到{rules['try_score']}分试强线")
        elif g.slot != "鞋子" and g.grade in {"英雄", "史诗"} and subs.get("spd", 0) >= rules["speed_chase_start"]:
            decision = "追速候选"
            reasons.append("非鞋子、英雄及以上品质且有速度，可按节点试强；不是保证继续强化划算")
        else:
            decision = "待定／先停手"
            reasons.append("未满足当前试强或保留规则；先检查角色有效词条与现有装备")
    elif score >= rules["finished_keep_score"]:
        decision = "保留候选"
        reasons.append(f"达到自定义成品线{rules['finished_keep_score']}分，仍需看角色用途")
    else:
        decision = "分解候选"
        reasons.append("未命中当前保留规则；须先确认专用角色、速度需求和库存替代品")
    if any(s.key in {"atk", "hp", "def"} for s in g.subs):
        reasons.append("固定属性总分使用参考基础值；角色有效分则按该角色基础值换算")
    if errors or not confirmed:
        decision = "待校对"
        reasons = errors + (["OCR结果尚未人工校对"] if not confirmed else []) + reasons
    return {"decision": decision, "score": round(score, 2), "reasons": reasons,
            "errors": errors, "counts": counts}


ARCHETYPES = {
    "攻击暴击输出": {"atk_pct": 1, "atk": 1, "crit": 1, "cdmg": 1, "spd": .8, "hp_pct": .15, "def_pct": .15},
    "生命暴击输出": {"hp_pct": 1, "hp": 1, "crit": 1, "cdmg": 1, "spd": .8, "def_pct": .6, "atk_pct": .1},
    "防御暴击输出": {"def_pct": 1, "def": 1, "crit": 1, "cdmg": 1, "spd": .8, "hp_pct": .6},
    "高速控制": {"spd": 1.5, "eff": 1, "hp_pct": .65, "def_pct": .5, "res": .15},
    "生存辅助": {"spd": 1, "hp_pct": 1, "hp": 1, "def_pct": 1, "def": 1, "res": 1},
    "攻击非暴击": {"atk_pct": 1, "atk": 1, "spd": 1, "hp_pct": .6, "def_pct": .6, "res": .6},
}


def recommend(g: Gear, heroes, rules, owned_only=False,score_func=None):
    results = []
    for hero in heroes:
        if owned_only and not hero.get("owned", False):
            continue
        weights = hero.get("weights") or ARCHETYPES.get(hero.get("archetype"), {})
        if not weights:
            continue
        effective = sum((score_func(s,hero.get("base")) if score_func else stat_score(s, rules, hero.get("base"))) * weights.get(s.key, 0) for s in g.subs)
        useful = [LABELS[s.key] for s in g.subs if weights.get(s.key, 0) >= .5]
        wasted = [LABELS[s.key] for s in g.subs if weights.get(s.key, 0) == 0]
        fixed_slot = g.slot in SLOTS[:3]
        accepted_main = hero.get("main", {}).get(g.slot)
        compatible = True if fixed_slot else None if not accepted_main else bool(g.main and g.main.key in accepted_main)
        set_match = g.set_name in hero.get("sets", [])
        # 有效分不是成功率。主属性不符则单独降级，不通过副属性高分掩盖。
        rank = effective + (3 if set_match else 0) - (30 if compatible is False else 0)
        contribution = {}
        for s in ([g.main] if g.main else []) + g.subs:
            k = s.key.removesuffix("_pct")
            base = hero.get("base", {}).get(k)
            value = s.value / 100 * base if s.key.endswith("_pct") and base else s.value
            key = k if not s.key.endswith("_pct") or base else s.key
            contribution[key] = contribution.get(key, 0) + value
        results.append({"name": hero.get("name_zh") or hero["name"], "name_en": hero["name"],
                        "effective": round(effective, 1), "effective_exact":effective,"weights":weights,"rank": rank,
                        "main_ok": compatible, "set_match": set_match, "useful": useful,
                        "wasted": wasted, "contribution": contribution,
                        "archetype": hero.get("archetype", "自定义"),
                        "basis": hero.get("basis", "用户配装档案"), "owned": hero.get("owned", False)})
    return sorted(results, key=lambda x: x["rank"], reverse=True)


def import_heroes(payload):
    """接受本工具角色档案或 sidekick 的 heroes.json；自动分类仅作候选。"""
    if isinstance(payload, dict):
        payload = payload.get("heroes", payload.get("data", []))
    if not isinstance(payload, list):
        raise ValueError("角色数据库应为JSON数组，或含heroes数组的对象")
    output, seen = [], set()
    for raw in payload:
        if not isinstance(raw, dict) or raw.get("expiredOn"):
            continue
        name = raw.get("name")
        if not name or name in seen:
            continue
        seen.add(name)
        if raw.get("archetype") or raw.get("weights"):
            h = copy.deepcopy(raw)
            if h.get("archetype") not in ARCHETYPES and not h.get("weights"):
                raise ValueError(f"{name} 的配装类型不受支持")
            if h.get("weights") and any(k not in LABELS or not isinstance(v, (int, float)) or
                                        not math.isfinite(v) or v < 0 for k, v in h["weights"].items()):
                raise ValueError(f"{name} 的权重无效")
            for k, v in h.get("base", {}).items():
                if not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
                    raise ValueError(f"{name} 的基础属性无效")
            if not isinstance(h.get("owned", False), bool):
                raise ValueError(f"{name} 的 owned 应为 true 或 false")
            for slot, keys in h.get("main", {}).items():
                if slot not in SLOTS or not isinstance(keys, list) or any(k not in LABELS for k in keys):
                    raise ValueError(f"{name} 的主属性偏好无效")
            output.append(h)
            continue
        skills = " ".join(str(raw.get(f"skill{i}", "")) for i in range(1, 4)).lower()
        archetype = "攻击暴击输出"
        role = raw.get("role", "")
        if role == "Soul Weaver" or role == "Knight":
            archetype = "生存辅助"
        if re.search(r"damage.*?proportion\w* to.*?(?:max |maximum )?health", skills):
            archetype = "生命暴击输出"
        if re.search(r"damage.*?proportion\w* to.*?defen[cs]e", skills):
            archetype = "防御暴击输出"
        if re.search(r"cannot (?:trigger |deal )?(?:a )?critical|never.*critical", skills):
            archetype = "攻击非暴击"
        base = {}
        for source, target in [("attack", "atk"), ("health", "hp"), ("defense", "def"), ("speed", "spd")]:
            try:
                value = float(raw.get(source, 0))
                if math.isfinite(value) and value > 0:
                    base[target] = value
            except (TypeError, ValueError):
                pass
        output.append({"name": name, "key": raw.get("key", name), "base": base,
                       "archetype": archetype, "sets": [], "owned": False,
                       "basis": "由职业和英文技能关键词自动分类，未核实当前版本配装；请编辑角色档案"})
    if not output:
        raise ValueError("没有可用角色，请检查数据库格式")
    return output


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS items(id INTEGER PRIMARY KEY, label TEXT, created TEXT);
        CREATE TABLE IF NOT EXISTS observations(id INTEGER PRIMARY KEY, item_id INTEGER REFERENCES items(id),
            created TEXT, gear TEXT, event TEXT);
        """)

    def create_item(self, label):
        with self.db:
            cur = self.db.execute("INSERT INTO items(label,created) VALUES (?,?)", (label or "未命名装备", now()))
        return cur.lastrowid

    def list_items(self):
        return self.db.execute("SELECT id,label,created FROM items ORDER BY id DESC").fetchall()

    def observations(self, item_id):
        rows = self.db.execute("SELECT created,gear,event FROM observations WHERE item_id=? ORDER BY id", (item_id,)).fetchall()
        return [{"created": r[0], "gear": json.loads(r[1]), "event": json.loads(r[2]) if r[2] else None} for r in rows]

    def record(self, item_id, gear):
        errors = validate(gear)
        if errors:
            raise ValueError("；".join(errors))
        history = self.observations(item_id)
        event = compare_observation(Gear.from_dict(history[-1]["gear"]), gear) if history else None
        if history and event is None:
            return None
        with self.db:
            self.db.execute("INSERT INTO observations(item_id,created,gear,event) VALUES(?,?,?,?)",
                            (item_id, now(), json.dumps(gear.to_dict(), ensure_ascii=False),
                             json.dumps(event, ensure_ascii=False) if event else None))
        return event or {"note": "已记录起始基线；此前逐跳历史未知", "changes": []}

    def export(self, destination):
        items = []
        for item_id, label, created in self.list_items():
            items.append({"id": item_id, "label": label, "created": created,
                          "observations": self.observations(item_id)})
        Path(destination).write_text(json.dumps({"version": 1, "items": items}, ensure_ascii=False, indent=2), encoding="utf-8")

    def close(self):
        self.db.close()
