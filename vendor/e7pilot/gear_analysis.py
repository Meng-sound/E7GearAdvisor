"""第七史诗背包装备扫描离线分析引擎（五层漏斗纯函数架构，零 GUI/Win32 依赖）。

用法：
  python gear_analysis.py --json <装备扫描.json>
  python gear_analysis.py --selftest [json1 json2 ...]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# ==============================================================================
# 1. 面向玩家的文案字典（统一集中待审，禁止在逻辑中散落硬编码）
# ==============================================================================
TEXTS: dict[str, Any] = {
    "dims": {
        "speed_init": "先手抢速",
        "burst_dps": "爆发输出",
        "bruiser": "阵地半肉",
        "pure_tank": "慢速抗压",
        "high_res": "高抗保核",
        "eff_ctrl": "命中控场",
    },
    "archetypes": {
        "cleave": "核爆",
        "aggro_spd": "高速",
        "standard": "阵地",
        "mid_spd": "中速",
        "turn2_tank": "肉坦",
    },
    "archetype_lean": {
        "核爆": "核爆速推",
        "高速": "高速抢先",
        "阵地": "阵地反击",
        "中速": "中速均衡",
        "肉坦": "后手抗压",
    },
    "dim_sub_feature": {
        "先手抢速": "偏高速抢跑（RTA先手向）",
        "爆发输出": "偏爆发输出（PVE/PVP过渡向）",
        "阵地半肉": "偏半肉缠斗（RTA阵地向）",
        "慢速抗压": "偏前排承伤（阵地防守向）",
        "高抗保核": "偏高抗解控（后手保核向）",
        "命中控场": "偏先手控场（干扰压制向）",
    },
    "tiers": {
        "T1": "T4 入门成型",
        "T2": "T3 精锐进阶",
        "T3": "T2 主力王者",
        "T4": "T1 稳定传说",
    },
    "level_tiers": {
        "90": "90 已重铸毕业装",
        "88": "88 固定/殿堂装",
        "85": "85 可重铸潜力装",
        "le80": "≤80 过渡装",
    },
    "warnings": {
        "incomplete_stop": "⚠ 这次扫描没扫到底，可能还有 +15 装备没扫到（建议重新扫描一次）。",
        "missing_parts": "⚠ 样本严重不完整：缺失部位【{parts}】，短板补齐机制已大幅拉低六维评分。",
        "empty_valid": "⚠ 有效 +15 装备为 0 件，无法生成有效流派画像。",
    },
    "tags": {
        "craft_high": "手工重铸主力（自刷85/90占 {craft_pct}%）",
        "event_heavy": "活动/兑换88装偏多（固定88占 {event_pct}%）",
        "purity_high": "词条纯度高（有效自洽率 {purity_pct}%）",
        "purity_mid": "词条纯度中等（有效自洽率 {purity_pct}%）",
        "purity_low": "高分混搭偏多（有效自洽率 {purity_pct}%，歪胚 {mismatched_cnt} 件）",
        "usage_active": "主力穿戴率高（穿戴均裸分 {eq_gs} / 闲置高分 {idle_high} 件）",
        "usage_idle": "存在闲置高分遗珠（未穿戴有效GS≥62 共 {idle_high} 件）",
    },
    "hunt_hints": {
        "balanced": "左三件与右三件储备均衡",
        "lack_right": "右三件严重偏少，建议定向炼制/转化项链戒指鞋",
        "lack_left": "左三件偏少，建议补充常规讨伐产出",
        "scarce": "散件储备不足以稳定成套",
    },
    "set_notes_2026": {
        # 只保留 2026 异界之隙新增套装，旧套装说明不展示（避免旧攻略/命名歧义）
        "弱化套装": "4件套：速度 +15%、弱化效果发生率 +15%",
        "全力套装": "2件套：追加回合开始时下个攻击伤害量 +20%（不叠加）",
        "开战套装": "4件套：生命值 +20%，战斗开始时重置技能冷却时间",
    },
    "report": {
        "title": "================ E7Pilot 背包装备深度分析报告 ================",
        "sec_input": "【一、样本与数据清洗】",
        "sec_dims": "【二、账号六维战力（0~100，Top-K 部位木桶均衡）】",
        "sec_arch": "【三、流派契合度与档位评定】",
        "sec_sub": "【四、五大深度诊断子模块】",
        "no_sample": "未找到可测试的装备扫描 JSON 文件。",
    },
}


# ==============================================================================
# 2. 核心配置区（全部阈值/权重/映射/反推表集中于此，改数字即可调优）
# ==============================================================================
ANALYSIS_CFG: dict[str, Any] = {
    # 部位标准顺序與分组（左三件固定主属性，右三件随机主属性）
    "parts_order": ("武器", "头盔", "铠甲", "项链", "戒指", "鞋子"),
    "left_parts": ("武器", "头盔", "铠甲"),
    "right_parts": ("项链", "戒指", "鞋子"),
    "speed_init_parts": ("武器", "头盔", "铠甲", "项链", "戒指"),  # 先手极速排除鞋子，仅对 5 部位做 Top-K

    # 正常完整结束的 stop_reason 集合；不在此集合内一律判定 complete=False
    "complete_stop_reasons": {
        "completed",
        "reached_list_bottom",
        "no_more_plus15",
        "partial_plus15_row_done",
    },

    # 第一层：合法性校验规则（依据 E7 词条互斥铁律 + +15 理论极限放宽余量，防误杀 30% 暴伤等极品）
    "validation": {
        "expected_plus": 15,
        "substat_count": 4,
        "forbidden_substats_by_part": {
            "武器": {"防御力", "防御力%"},  # 武器不出大小防御
            "铠甲": {"攻击力", "攻击力%"},  # 铠甲不出大小攻击（双暴合法）
        },
        "substat_ranges": {
            "速度": (1, 32),
            "暴击率": (1, 37),
            "暴击伤害": (1, 50),
            "攻击力%": (1, 58),
            "防御力%": (1, 58),
            "生命值%": (1, 58),
            "效果命中": (1, 58),
            "效果抗性": (1, 58),
            "攻击力": (1, 350),
            "防御力": (1, 260),
            "生命值": (1, 1500),
        },
    },

    # 第一层：88 级活动/竞技场/迷宫固定装名称关键词（严禁混入深渊龙兽/暗黑钢铁等地狱讨伐85常规装）
    "event_88_keywords": (
        "霹雳之日",
        "白羽铠甲",
        "阿塔兰特",
        "焦翼天使",
        "贝洛斯荣耀",
        "厄里斯战靴",
        "荣耀斗士",
        "毁灭者",
        "盟约破坏者",
        "家族颈链",
        "神秘调酒壶",
        "嗜血的英雄",
        "王宫女仆",
        "璀璨威光",
        "黑暗降临",
        "腐朽森精髓",
        "斗志毁灭者",
        "竞争毁灭者",
    ),
    # 90 级重铸装典型前缀（用于区分 310 防铠甲与 65%/70%/45速右三件是 90 重铸还是 88 殿堂装）
    "reforged_90_keywords": (
        "远古龙兽",
        "黄昏精髓",
        "黑暗深渊",
        "赤暗龙",
        "漆黑",
        "光辉",
        "残酷",
        "狂热",
        "不朽",
        "次元",
    ),

    # 第一层：主属性反推等效等级查表（当 level 为 None 或 OCR 错读时启用）
    "level_infer": {
        "valid_exact_levels": {85, 88, 90},
        "valid_le80_levels": {70, 71, 75, 78, 80},  # 合法低等级；其余 1~82 非法值一律走主属性反推
        "le80_max": 82,
        "weapon_atk": ((520, 90), (510, 88), (490, 85)),          # 525→90, 515→88, 500→85, ≤475→le80
        "helmet_hp": ((2800, 90), (2730, 88), (2650, 85)),        # 2835→90, 2765→88, 2700→85
        "armor_def": {
            "high_min": 305,   # 310 为 88 活动装或 90 重铸装（结合关键词区分）
            "lv85_min": 290,   # 300 为 85 装
        },
        "right_main": {
            # (90/88高档阈值, 85档阈值)；低于 85 档归入 ≤80
            "速度": (43, 39),          # 45→90/88, 40→85, 35→le80
            "暴击伤害": (68, 63),      # 70→90/88, 65→85, 55→le80
            "暴击率": (58, 53),        # 60→90/88, 55→85
            "攻击力%": (63, 58),       # 65→90/88, 60→85
            "防御力%": (63, 58),
            "生命值%": (63, 58),
            "效果命中": (63, 58),
            "效果抗性": (63, 58),
            "攻击力": (515, 490),
            "防御力": (305, 290),
            "生命值": (2730, 2650),
        },
    },

    # 第一层：Fribbels 标准副属性裸分系数（主属性不计入）
    "fribbels_weights": {
        "攻击力%": 1.0,
        "防御力%": 1.0,
        "生命值%": 1.0,
        "效果命中": 1.0,
        "效果抗性": 1.0,
        "速度": 8.0 / 4.0,          # 2.0
        "暴击伤害": 8.0 / 7.0,      # ~1.1429
        "暴击率": 8.0 / 5.0,        # 1.6
        "攻击力": 3.46 / 39.0,      # ~0.0887
        "防御力": 4.99 / 31.0,      # ~0.1610
        "生命值": 3.09 / 174.0,     # ~0.0178
    },

    # 套装全集（2026 现行 20 套装，含异界之隙新增：开战/弱化/全力）
    "sets_pieces_required": {
        "速度套装": 4,
        "破灭套装": 4,
        "反击套装": 4,
        "吸血套装": 4,
        "逆袭套装": 4,
        "回击套装": 4,
        "攻击套装": 4,
        "愤怒套装": 4,
        "复仇套装": 4,
        "创伤套装": 4,
        "弱化套装": 4,  # 2026 新增 4 件套
        "暴击套装": 2,
        "命中套装": 2,
        "生命值套装": 2,
        "防御套装": 2,
        "抗性套装": 2,
        "免疫套装": 2,
        "穿透套装": 2,
        "激流套装": 2,
        "守护套装": 4,
        "追击套装": 2,
        "团结套装": 2,
        "全力套装": 2,  # 2026 新增 2 件套
        "开战套装": 4,  # 2026 新增 4 件套（生命+20%，开局重置技能 CD）
    },

    # 第二层：单件 6 维有效分计算参数（门槛 × 主属性契合度 × 套装乘区）
    "dim_scoring": {
        "default_set_mult": 0.95,
        # 1) 先手极速：排除速度主属性鞋；副词条速度 <10 得 0 分；15/18/20+ 逐档非线性加速
        "speed_init": {
            "min_sub_spd": 10,
            "base_spd_mult": 3.0,      # 10速=30，保留原线性底座
            # 15~19 速保留原有分段（140/49 参考样本分布集中在这里）；
            # 20+ 速改用单一饱和曲线压缩，并加单件硬封顶。
            "tier_bonus_low": ((15, 2.5), (18, 4.5)),
            "high_speed_start": 19.0,
            "high_bonus_max": 15.0,       # 20+ 速额外 bonus 上限（本地扫参定稿）
            "high_bonus_half_sat": 2.0,   # 半饱和点（本地扫参定稿）
            "max_item_score": 85.0,       # 单件 speed_init 硬封顶（20 速目标约 85）
            "util_sub_mult": 0.12,     # 同件命中/生命%/防御%/暴率微弱折算
            "right_main_mult": {
                "速度": 0.0,           # 速度鞋强制排除
                "效果命中": 1.03,
                "生命值%": 1.02,
                "防御力%": 1.02,
                "暴击率": 1.02,
                "暴击伤害": 1.00,
                "攻击力%": 1.00,
                "效果抗性": 1.00,
            },
            "right_main_default": 0.90,
            "set_mult": {
                "速度套装": 1.15,
                "弱化套装": 1.06,
                "命中套装": 1.04,
                "免疫套装": 1.04,
                "穿透套装": 1.02,
                "暴击套装": 1.02,
                "激流套装": 1.02,
            },
        },
        # 2) 爆发纯C：仅认攻/双暴/速，排除命抗；右三件非输出主属性大幅降权
        "burst_dps": {
            "weights": {
                "攻击力%": 1.0,
                "暴击率": 1.6,
                "暴击伤害": 8.0 / 7.0,
                "速度": 1.6,
                "攻击力": 3.46 / 39.0,
            },
            "synergy_double_crit_bonus": 3.0,  # 双暴同在微幅奖励自洽度
            "right_main_mult": {
                "暴击伤害": 1.06,
                "暴击率": 1.04,
                "攻击力%": 1.05,
                "速度": 1.04,
                "生命值%": 0.25,
                "防御力%": 0.20,
                "效果命中": 0.15,
                "效果抗性": 0.15,
            },
            "right_main_default": 0.30,
            "set_mult": {
                "破灭套装": 1.08,
                "激流套装": 1.08,
                "穿透套装": 1.08,
                "速度套装": 1.06,
                "全力套装": 1.06,
                "暴击套装": 1.05,
                "开战套装": 1.04,
                "追击套装": 1.03,
                "愤怒套装": 1.04,
                "攻击套装": 1.02,
            },
        },
        # 3) 阵地半肉：血防+双暴+速+0.6攻%，纯脆皮或纯肉无输出适度降权
        "bruiser": {
            "weights": {
                "生命值%": 1.0,
                "防御力%": 1.0,
                "暴击率": 1.5,
                "暴击伤害": 1.10,
                "速度": 1.6,
                "攻击力%": 0.6,
                "生命值": 0.0142,
                "防御力": 0.1288,
                "攻击力": 0.04436,
            },
            "pure_glass_penalty": 0.80,  # 既非肉主属性且副属性血防之和 <8 时降权
            "pure_tank_penalty": 0.84,   # 既非输出主属性且双暴+攻% <8 时降权
            "min_bulk_sum": 8.0,
            "min_off_sum": 8.0,
            "right_main_mult": {
                "生命值%": 1.05,
                "防御力%": 1.04,
                "暴击伤害": 1.05,
                "暴击率": 1.04,
                "速度": 1.05,
                "攻击力%": 0.96,
                "效果抗性": 0.45,
                "效果命中": 0.35,
            },
            "right_main_default": 0.45,
            "set_mult": {
                "反击套装": 1.08,
                "吸血套装": 1.08,
                "穿透套装": 1.07,
                "免疫套装": 1.06,
                "速度套装": 1.05,
                "创伤套装": 1.06,
                "逆袭套装": 1.04,
                "回击套装": 1.04,
                "开战套装": 1.04,
                "生命值套装": 1.03,
                "防御套装": 1.03,
                "暴击套装": 1.03,
                "破灭套装": 1.04,
            },
        },
        # 4) 铁壁纯坦：右三件仅认生命%/防御%/速度；不计双暴攻击
        "pure_tank": {
            "weights": {
                "生命值%": 1.05,
                "防御力%": 1.05,
                "速度": 1.35,
                "效果抗性": 0.35,
                "生命值": 3.09 / 174.0,
                "防御力": 4.99 / 31.0,
            },
            "right_main_mult": {
                "生命值%": 1.08,
                "防御力%": 1.08,
                "速度": 1.05,
                "效果抗性": 0.65,
                "攻击力%": 0.15,
                "暴击伤害": 0.15,
                "暴击率": 0.15,
                "效果命中": 0.25,
            },
            "right_main_default": 0.25,
            "set_mult": {
                "守护套装": 1.08,
                "生命值套装": 1.07,
                "防御套装": 1.07,
                "免疫套装": 1.06,
                "反击套装": 1.05,
                "速度套装": 1.04,
                "抗性套装": 1.03,
            },
        },
        # 5) 高抗保核：戒指抗性主属 或 副词条抗性≥12% 才重点计，否则大幅折减
        "high_res": {
            "min_sub_res": 12,
            "below_gate_mult": 0.22,
            "ring_res_main_bonus": 10.0,
            "weights": {
                "效果抗性": 1.15,
                "生命值%": 0.95,
                "防御力%": 0.95,
                "速度": 1.45,
                "生命值": 3.09 / 174.0,
                "防御力": 4.99 / 31.0,
            },
            "right_main_mult": {
                "效果抗性": 1.12,
                "生命值%": 1.04,
                "防御力%": 1.04,
                "速度": 1.05,
                "效果命中": 0.20,
                "攻击力%": 0.15,
                "暴击伤害": 0.15,
                "暴击率": 0.15,
            },
            "right_main_default": 0.25,
            "set_mult": {
                "抗性套装": 1.10,
                "免疫套装": 1.06,
                "生命值套装": 1.06,
                "守护套装": 1.06,
                "防御套装": 1.05,
                "速度套装": 1.05,
                "反击套装": 1.04,
            },
        },
        # 6) 命中控场：戒指命中主属 或 副词条命中≥12% 才重点计
        "eff_ctrl": {
            "min_sub_eff": 12,
            "below_gate_mult": 0.25,
            "ring_eff_main_bonus": 12.0,
            "weights": {
                "效果命中": 1.10,
                "速度": 1.85,
                "生命值%": 0.60,
                "防御力%": 0.60,
                "生命值": 0.5 * (3.09 / 174.0),
                "防御力": 0.5 * (4.99 / 31.0),
            },
            "right_main_mult": {
                "效果命中": 1.10,
                "速度": 1.06,
                "生命值%": 1.02,
                "防御力%": 1.02,
                "暴击率": 0.60,
                "攻击力%": 0.55,
                "暴击伤害": 0.35,
                "效果抗性": 0.25,
            },
            "right_main_default": 0.35,
            "set_mult": {
                "命中套装": 1.09,
                "弱化套装": 1.08,
                "速度套装": 1.07,
                "免疫套装": 1.04,
                "回击套装": 1.04,
            },
        },
        # 高分混搭歪胚判定阈值（裸分高但所有单维有效分都不高，或面板高分混搭）
        "mismatched": {
            "raw_gs_min": 58.0,
            "panel_score_min": 88,
            "best_valid_max": 40.0,
            "ratio_max": 0.68,  # best_valid_gs / raw_gs 过低视为词条互搏混搭
        },
    },

    # 第三层：账号六维聚合（按部位 Top-K 均衡 + 硬通货深度饱和曲线）
    "aggregation": {
        "top_k": 4,                # 每部位取前 4 件，不足 4 件按 0 补齐惩罚短板
        "quality_weight": 0.60,
        "depth_weight": 0.40,
        "max_depth_score": 88.0,   # 非先手维 depth 安全上限（防活动装把 depth 顶到 90+；P1-b 先控顶）
        # 质量分线性映射区间 (floor -> 0分, ceil -> 100分)
        "quality_map": {
            "speed_init": (40.0, 76.0),
            "burst_dps": (42.0, 76.0),
            "bruiser": (42.0, 76.0),
            "pure_tank": (34.0, 68.0),
            "high_res": (34.0, 68.0),
            "eff_ctrl": (34.0, 68.0),
        },
        # 深度分硬通货计数权重与满分饱和目标 target_points
        "depth_currency": {
            "speed_init": {
                "craft_spd16_pts": 1.0,
                "craft_spd18_pts": 3.0,
                "craft_spd20_pts": 6.5,
                "event_spd17_pts": 0.2,   # 活动固定 17 速权重远低于手工 18+ 速
                "spd45_speed_boot_pts": 0.3,
                "target": 28.0,
            },
            "burst_dps": {"gs_t1": 62.0, "gs_t2": 71.0, "t1_pts": 1.0, "t2_pts": 2.2, "target": 44.0},
            "bruiser": {"gs_t1": 60.0, "gs_t2": 66.0, "t1_pts": 1.0, "t2_pts": 2.5, "target": 20.0},
            "pure_tank": {"gs_t1": 46.0, "gs_t2": 55.0, "t1_pts": 1.0, "t2_pts": 2.2, "target": 20.0},
            "high_res": {"gs_t1": 46.0, "gs_t2": 55.0, "t1_pts": 1.0, "t2_pts": 2.2, "target": 22.0},
            "eff_ctrl": {"gs_t1": 46.0, "gs_t2": 55.0, "t1_pts": 1.0, "t2_pts": 2.2, "target": 30.0},
        },
    },

    # 第四层：5 流派契合度与硬门控 + 4 档强度标尺
    "archetype_cfg": {
        "speed_sets": {"速度套装", "弱化套装"},
        "cleave_sets": {"激流套装", "穿透套装", "速度套装", "全力套装"},
        "standard_sets": {"反击套装", "吸血套装", "免疫套装", "穿透套装", "逆袭套装", "回击套装", "创伤套装", "开战套装"},
        "mid_sets": {"速度套装", "破灭套装", "暴击套装", "穿透套装", "生命值套装", "命中套装"},
        "tank_sets": {"生命值套装", "防御套装", "守护套装", "抗性套装", "免疫套装", "反击套装"},
        # 硬门控（防止慢速纯双爆被误判为核爆、缺 18+ 速被误判为高速）
        "gates": {
            "aggro_no_spd20_cap": 28.0,       # 0 件 20+ 速时，高速流派封顶 28
            "aggro_few_spd18_cap": 42.0,      # 18+ 速 <3 件时，高速流派封顶 42
            "cleave_low_spd_dim_thresh": 38.0,
            "cleave_low_spd_mult": 0.62,      # 一速维 <38 时，核爆契合度乘以 0.62 压低
            "cleave_no_spd18_cap": 40.0,      # 手工 18+ 速 <2 件时，核爆封顶 40
            "standard_scarce_set_thresh": 0.12,
            "standard_scarce_mult": 0.88,     # 反击/吸血/免疫等阵地套占比 <12% 时轻微折减
            "turn2_low_res_dim_thresh": 26.0, # 高抗维 <26 时，肉猪契合度折减（低抗门控）
            "turn2_low_res_mult": 0.68,
        },
        # 阵地流派公式权重（Step 2 由 Gemini 给值、从逻辑提进 CFG；改数字即可调）
        "standard_formula": {
            "bru_w": 0.50,
            "tnk_w": 0.26,
            "aux_w": 0.12,
            "set_w": 18.0,
            "set_full_ratio": 0.20,
        },
        # 4 档标尺阈值（综合主战维度分 + 手工高分件 + 极速件 + 战备保底）
        # readiness_min_display：展示口径 0–1000（Gemini 2026-11-16 拍板值）
        "tiers": {
            "T4": {"top2_dim_avg": 82.0, "valid_62_cnt": 45, "craft_spd23_cnt": 5, "readiness_min_display": 760},
            "T3": {"top2_dim_avg": 69.0, "valid_62_cnt": 22, "craft_spd18_cnt": 4, "readiness_min_display": 560},
            # 纯阵地轨：不卡死 4 件 18 速；用多维均衡替代死拉 top2
            "T3_alt_tank": {
                "top2_dim_avg": 70.0,
                "valid_62_cnt": 26,
                "craft_spd18_cnt": 2,
                "readiness_min_display": 600,
                "wide_dims_ge60": 3,
                "reforged_90_min": 36,
            },
            "T2": {"top2_dim_avg": 58.5, "valid_58_cnt": 40, "reforged_90_cnt": 24},
        },
    },

    # 第四层：成色标签阈值
    "account_tags_cfg": {
        "event_heavy_ratio": 0.20,   # 88 固定装占比 ≥20% 提示活动装偏高
        "purity_panel_es_min": 90,   # 面板分数 ≥90 作为高裸分基数
        "purity_valid_gs_min": 58.0, # 最佳维度有效分 ≥58 视为高自洽件
        "purity_high_ratio": 0.78,
        "purity_low_ratio": 0.45,
        "purity_high_max_mismatched": 2,   # 高纯度标签允许的最大歪胚件数
        "purity_low_min_mismatched": 8,    # 歪胚件数达到该值即触发"混搭偏多"
        "idle_high_gs": 62.0,
    },

    # 战备综合指数（口径 v2，2026-11-15 与 Gemini 定稿；只增展示，不影响六维/流派/4档）
    "readiness_cfg": {
        "weights": {"knife": 0.40, "bench": 0.40, "quality": 0.20},
        "bench_event88_weight": 0.5,  # 活动 88 装折半计入板凳（纯手工 0 / 全计入 1 之间的折中）
        "bench_target_D": 160.0,      # 160 件"当量"算满板凳 100 分（防入门号过早顶满）
        "min_items_to_show": 100,     # 有效件数 <100 不出综合指数
        "purity_smooth_min_samples": 5,  # 纯度分母 <5 件时做平滑收缩
        "purity_smooth_prior": 2.5,
        "quality_reforged_pct": True,    # 成色第二项用「90 已重铸占比」（v2；旧版为 85+90 手工占比）
        "display_scale": 1000,           # 界面千分制
        "display_curve_p": 1.67,         # 显示曲线：1000 × (加权分/100)^1.67
    },

    # 第五层：5 个深度子模块参数
    "submodules_cfg": {
        "sandbox_base_spd": 120,          # 标准先手英雄白值底速假设（如岚/智武级别可调，默认 120）
        "sandbox_speed_set_bonus": 0.25,  # 4 件速度套加成 +25% 底速
        "sandbox_team_count": 3,          # 推算一速 / 二速 / 三速共 3 套不重样配装
        "heatmap_top_n": 3,               # 6×6 热力表每格取 Top-3 有效分均值
        "heatmap_weak_thresh": 40.0,      # 低于 40 标记为短板格
        "reforge_goldmine": {
            "min_spd": 14,                # 85 未重铸件：速度 ≥14
            "min_valid_gs": 60.0,         # 或单维最佳有效分 ≥60（冻结规格原文）
            "max_list": 25,
        },
        "inefficient_equipped": {
            "max_valid_gs": 43.0,         # 已穿戴但最佳有效分 <43 视为低效占坑
            "max_list": 25,
        },
    },
}


# ==============================================================================
# 3. 工具与五层漏斗纯函数实现
# ==============================================================================
def _setup_console_encoding() -> None:
    """Windows 控制台 GBK 兜底，强制切 UTF-8 避免打印符号抛异常。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def _clamp(val: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, val))


def _canonical_stat_key(stat: dict[str, Any], cfg: dict[str, Any]) -> str:
    """按 is_percent 与 type/key 统一词条标准键名。"""
    raw_type = str(stat.get("type") or stat.get("key") or "").strip().rstrip("%")
    is_pct = bool(stat.get("is_percent", str(stat.get("key", "")).endswith("%")))
    if raw_type in ("攻击力", "防御力", "生命值"):
        return f"{raw_type}%" if is_pct else raw_type
    if raw_type in ("暴击率", "暴击伤害", "效果命中", "效果抗性"):
        return raw_type
    if raw_type == "速度":
        return "速度"
    return str(stat.get("key") or raw_type)


def _is_event_88_name(name: str, cfg: dict[str, Any]) -> bool:
    return any(kw in name for kw in cfg["event_88_keywords"])


def _is_reforged_90_name(name: str, cfg: dict[str, Any]) -> bool:
    return any(kw in name for kw in cfg["reforged_90_keywords"])


def infer_effective_level(
    raw_level: Any,
    part: str,
    main_key: str,
    main_val: float,
    name: str,
    quality: str,
    cfg: dict[str, Any] = ANALYSIS_CFG,
) -> tuple[str, bool]:
    """反推装备等效等级档位 ('90' | '88' | '85' | 'le80') 及是否为活动/固定 88 装。"""
    li = cfg["level_infer"]
    is_ev88 = _is_event_88_name(name, cfg)
    is_rf90 = _is_reforged_90_name(name, cfg)

    parsed_lv: int | None = None
    if isinstance(raw_level, int) and not isinstance(raw_level, bool):
        parsed_lv = raw_level
    elif isinstance(raw_level, str) and raw_level.strip().isdigit():
        parsed_lv = int(raw_level.strip())

    def _infer_from_main() -> tuple[str, bool] | None:
        """仅凭主属性数值 + 名称家族反推等级；无法判断时返回 None。"""
        if part == "武器" and main_key == "攻击力":
            for thresh, lv in li["weapon_atk"]:
                if main_val >= thresh:
                    eff = str(lv)
                    return eff, (eff == "88")
            return "le80", False

        if part == "头盔" and main_key == "生命值":
            for thresh, lv in li["helmet_hp"]:
                if main_val >= thresh:
                    eff = str(lv)
                    return eff, (eff == "88")
            return "le80", False

        if part == "铠甲" and main_key == "防御力":
            ad = li["armor_def"]
            if main_val >= ad["high_min"]:
                # 310 防御力：白羽铠甲等归 88 活动装；远古龙兽皮甲等归 90 重铸装
                if is_ev88:
                    return "88", True
                if is_rf90:
                    return "90", False
                return ("88", True) if quality != "异界传说" and parsed_lv == 881 else ("90", False)
            if main_val >= ad["lv85_min"]:
                return "85", False
            return "le80", False

        # 右三件（项链 / 戒指 / 鞋子）及兜底
        rm = li["right_main"].get(main_key)
        if rm is not None:
            high_th, lv85_th = rm
            if main_val >= high_th:
                if is_ev88:
                    return "88", True
                if is_rf90:
                    return "90", False
                # 错读如 881 且非 90 龙装家族时优先判 88，否则默认 90 重铸
                if parsed_lv is not None and str(parsed_lv).startswith("88"):
                    return "88", True
                return "90", False
            if main_val >= lv85_th:
                return "85", False
            return "le80", False

        if is_ev88:
            return "88", True
        if is_rf90:
            return "90", False
        return None

    exact_levels = li["valid_exact_levels"]
    le80_levels = li.get("valid_le80_levels") or set()

    # 1) 原始等级合法：合法 raw level 优先，不再用主属性反推覆盖
    #    （2026-11-16 修：id=47 的 raw 88 被 310 防反推成 90；id=192 的 raw 80 被 60% 主属性反推成 85）
    if parsed_lv is not None and parsed_lv in exact_levels:
        eff = str(parsed_lv)
        return eff, (eff == "88" and (is_ev88 or not is_rf90))
    if parsed_lv is not None and parsed_lv in le80_levels:
        return "le80", False

    # 2) None / 非法值（含 OCR 错读 1~69、881 等）：用主属性反推
    inferred = _infer_from_main()
    if inferred is not None:
        return inferred
    if is_ev88:
        return "88", True
    if is_rf90:
        return "90", False
    return "le80", False


def validate_and_clean_item(
    raw: Any,
    idx: int,
    cfg: dict[str, Any] = ANALYSIS_CFG,
) -> dict[str, Any]:
    """第一层：单件结构容错、合法性校验、等效等级反推与 Fribbels 裸分重算（纯函数，不修改原字典）。"""
    if not isinstance(raw, dict):
        return {"valid": False, "id": idx, "invalid_reason": "not_a_dict"}

    item_id = raw.get("id", idx)
    part = str(raw.get("part") or "").strip()
    if part not in cfg["parts_order"]:
        return {"valid": False, "id": item_id, "invalid_reason": "invalid_or_missing_part"}

    main_raw = raw.get("main_stat")
    if not isinstance(main_raw, dict) or not isinstance(main_raw.get("value"), (int, float)):
        return {"valid": False, "id": item_id, "invalid_reason": "invalid_main_stat"}

    subs_raw = raw.get("substats")
    if not isinstance(subs_raw, list) or len(subs_raw) != cfg["validation"]["substat_count"]:
        return {"valid": False, "id": item_id, "invalid_reason": "substat_count_not_4"}

    main_key = _canonical_stat_key(main_raw, cfg)
    main_val = float(main_raw["value"])

    sub_map: dict[str, float] = {}
    val_cfg = cfg["validation"]
    forbidden = val_cfg["forbidden_substats_by_part"].get(part, set())
    ranges = val_cfg["substat_ranges"]

    for s in subs_raw:
        if not isinstance(s, dict) or not isinstance(s.get("value"), (int, float)):
            return {"valid": False, "id": item_id, "invalid_reason": "invalid_substat_value"}
        s_key = _canonical_stat_key(s, cfg)
        s_val = float(s["value"])
        if s_key in sub_map:
            return {"valid": False, "id": item_id, "invalid_reason": f"duplicate_substat:{s_key}"}
        if s_key == main_key:
            return {"valid": False, "id": item_id, "invalid_reason": f"main_sub_conflict:{s_key}"}
        if s_key in forbidden:
            return {"valid": False, "id": item_id, "invalid_reason": f"part_forbidden_stat:{part}:{s_key}"}
        if s_key not in ranges:
            return {"valid": False, "id": item_id, "invalid_reason": f"unknown_substat:{s_key}"}
        lo, hi = ranges[s_key]
        if not (lo <= s_val <= hi):
            return {"valid": False, "id": item_id, "invalid_reason": f"substat_out_of_range:{s_key}={s_val}"}
        # 速度主属性鞋副词条绝不会再出速度（前面 main_sub_conflict 已拦，此处双保险）
        sub_map[s_key] = s_val

    name = str(raw.get("name") or "").strip()
    quality = str(raw.get("quality") or "未知").strip()
    set_obj = raw.get("set")
    set_name = (
        str(set_obj.get("name") or "未知套装").strip()
        if isinstance(set_obj, dict)
        else "未知套装"
    )
    panel_score_raw = raw.get("score")
    panel_score = int(panel_score_raw) if isinstance(panel_score_raw, (int, float)) else 0
    equipped = bool(raw.get("equipped", False))

    eff_level, is_event_88 = infer_effective_level(
        raw.get("level"), part, main_key, main_val, name, quality, cfg
    )

    fw = cfg["fribbels_weights"]
    raw_gs = round(sum(val * fw.get(k, 0.0) for k, val in sub_map.items()), 2)

    return {
        "valid": True,
        "id": item_id,
        "part": part,
        "name": name,
        "quality": quality,
        "raw_level": raw.get("level"),
        "effective_level": eff_level,
        "is_event_88": is_event_88,
        "set_name": set_name,
        "main_key": main_key,
        "main_val": main_val,
        "sub_map": sub_map,
        "panel_score": panel_score,
        "raw_gs": raw_gs,
        "equipped": equipped,
    }


def score_item_six_dims(item: dict[str, Any], cfg: dict[str, Any] = ANALYSIS_CFG) -> dict[str, Any]:
    """第二层：计算单件装备 6 维有效分（门槛 × 右三件主属性契合 × 套装加权）及混搭歪胚标记。"""
    ds = cfg["dim_scoring"]
    default_sm = ds["default_set_mult"]
    part = item["part"]
    is_right = part in cfg["right_parts"]
    m_key = item["main_key"]
    s_name = item["set_name"]
    subs: dict[str, float] = item["sub_map"]

    scores: dict[str, float] = {}

    # 1) 先手极速
    c_spd = ds["speed_init"]
    sub_spd = subs.get("速度", 0.0)
    if part == "鞋子" and m_key == "速度":
        scores["speed_init"] = 0.0
    elif sub_spd < c_spd["min_sub_spd"]:
        scores["speed_init"] = 0.0
    else:
        val = sub_spd * c_spd["base_spd_mult"]
        if sub_spd <= c_spd["high_speed_start"]:
            # 低速段：保留原有分段手感（140/49 主要落在这里）
            for th, bonus_per_pt in c_spd["tier_bonus_low"]:
                if sub_spd >= th:
                    val += (sub_spd - th + 1.0) * bonus_per_pt
        else:
            # 高速段：19 速处连续，20+ 用饱和曲线压缩
            low_bonus = sum(
                (c_spd["high_speed_start"] - th + 1.0) * bonus_per_pt
                for th, bonus_per_pt in c_spd["tier_bonus_low"]
                if c_spd["high_speed_start"] >= th
            )
            extra = sub_spd - c_spd["high_speed_start"]
            val += low_bonus + c_spd["high_bonus_max"] * extra / (extra + c_spd["high_bonus_half_sat"])
        util = (
            subs.get("效果命中", 0.0)
            + subs.get("生命值%", 0.0)
            + subs.get("防御力%", 0.0)
            + subs.get("暴击率", 0.0) * 1.4
        ) * c_spd["util_sub_mult"]
        val += util
        if is_right:
            val *= c_spd["right_main_mult"].get(m_key, c_spd["right_main_default"])
        val *= c_spd["set_mult"].get(s_name, default_sm)
        scores["speed_init"] = round(min(val, c_spd.get("max_item_score", 100.0)), 2)

    # 2) 爆发纯C
    c_dps = ds["burst_dps"]
    val = sum(subs.get(k, 0.0) * w for k, w in c_dps["weights"].items())
    if "暴击率" in subs and "暴击伤害" in subs:
        val += c_dps["synergy_double_crit_bonus"]
    if is_right:
        val *= c_dps["right_main_mult"].get(m_key, c_dps["right_main_default"])
    val *= c_dps["set_mult"].get(s_name, default_sm)
    scores["burst_dps"] = round(val, 2)

    # 3) 阵地半肉
    c_bru = ds["bruiser"]
    val = sum(subs.get(k, 0.0) * w for k, w in c_bru["weights"].items())
    bulk_sum = subs.get("生命值%", 0.0) + subs.get("防御力%", 0.0) + (15.0 if is_right and m_key in ("生命值%", "防御力%") else 0.0)
    off_sum = (
        subs.get("暴击率", 0.0) * 1.5
        + subs.get("暴击伤害", 0.0)
        + subs.get("攻击力%", 0.0) * 0.7
        + (15.0 if is_right and m_key in ("暴击伤害", "暴击率", "攻击力%") else 0.0)
    )
    if bulk_sum < c_bru["min_bulk_sum"]:
        val *= c_bru["pure_glass_penalty"]
    if off_sum < c_bru["min_off_sum"]:
        val *= c_bru["pure_tank_penalty"]
    if is_right:
        val *= c_bru["right_main_mult"].get(m_key, c_bru["right_main_default"])
    val *= c_bru["set_mult"].get(s_name, default_sm)
    scores["bruiser"] = round(val, 2)

    # 4) 铁壁纯坦
    c_tnk = ds["pure_tank"]
    val = sum(subs.get(k, 0.0) * w for k, w in c_tnk["weights"].items())
    if is_right:
        val *= c_tnk["right_main_mult"].get(m_key, c_tnk["right_main_default"])
    val *= c_tnk["set_mult"].get(s_name, default_sm)
    scores["pure_tank"] = round(val, 2)

    # 5) 高抗保核
    c_res = ds["high_res"]
    sub_res = subs.get("效果抗性", 0.0)
    ring_res_main = (part == "戒指" and m_key == "效果抗性")
    val = sum(subs.get(k, 0.0) * w for k, w in c_res["weights"].items())
    if ring_res_main:
        val += c_res["ring_res_main_bonus"]
    elif sub_res < c_res["min_sub_res"]:
        val *= c_res["below_gate_mult"]
    if is_right:
        val *= c_res["right_main_mult"].get(m_key, c_res["right_main_default"])
    val *= c_res["set_mult"].get(s_name, default_sm)
    scores["high_res"] = round(val, 2)

    # 6) 命中控场
    c_eff = ds["eff_ctrl"]
    sub_eff = subs.get("效果命中", 0.0)
    ring_eff_main = (part == "戒指" and m_key == "效果命中")
    val = sum(subs.get(k, 0.0) * w for k, w in c_eff["weights"].items())
    if ring_eff_main:
        val += c_eff["ring_eff_main_bonus"]
    elif sub_eff < c_eff["min_sub_eff"]:
        val *= c_eff["below_gate_mult"]
    if is_right:
        val *= c_eff["right_main_mult"].get(m_key, c_eff["right_main_default"])
    val *= c_eff["set_mult"].get(s_name, default_sm)
    scores["eff_ctrl"] = round(val, 2)

    best_dim_key = max(scores, key=lambda k: scores[k])
    best_valid_gs = scores[best_dim_key]

    mm = ds["mismatched"]
    raw_gs = item["raw_gs"]
    ratio = (best_valid_gs / raw_gs) if raw_gs > 0 else 1.0
    is_mismatched = (
        (raw_gs >= mm["raw_gs_min"] or item["panel_score"] >= mm["panel_score_min"])
        and (best_valid_gs < mm["best_valid_max"] or ratio < mm["ratio_max"])
    )

    return {
        **item,
        "dim_scores": scores,
        "best_dim_key": best_dim_key,
        "best_valid_dim": TEXTS["dims"][best_dim_key],
        "best_valid_gs": round(best_valid_gs, 2),
        "is_mismatched": is_mismatched,
    }


def aggregate_account_dims(
    items: list[dict[str, Any]],
    cfg: dict[str, Any] = ANALYSIS_CFG,
) -> tuple[dict[str, dict[str, Any]], dict[str, float]]:
    """第三层：账号级六维聚合（按部位 Top-K 补 0 均值 × 60% + 硬通货饱和深度 × 40%）。"""
    agg = cfg["aggregation"]
    top_k: int = agg["top_k"]
    q_w: float = agg["quality_weight"]
    d_w: float = agg["depth_weight"]

    dim_keys = tuple(TEXTS["dims"].keys())
    out_by_cn: dict[str, dict[str, Any]] = {}
    internal_scores: dict[str, float] = {}

    for dk in dim_keys:
        cn_name = TEXTS["dims"][dk]
        active_parts = cfg["speed_init_parts"] if dk == "speed_init" else cfg["parts_order"]

        part_topk: dict[str, float] = {}
        for p in active_parts:
            vals = sorted(
                (it["dim_scores"][dk] for it in items if it["part"] == p),
                reverse=True,
            )[:top_k]
            # 不足 K 件按 0 补齐，惩罚缺部位或薄弱部位
            padded = vals + [0.0] * max(0, top_k - len(vals))
            part_topk[p] = round(sum(padded) / top_k, 2)

        eq_avg = sum(part_topk.values()) / len(active_parts) if active_parts else 0.0
        q_lo, q_hi = agg["quality_map"][dk]
        quality_score = round(_clamp((eq_avg - q_lo) / (q_hi - q_lo) * 100.0), 1)

        # 深度分计算
        dc = agg["depth_currency"][dk]
        pts = 0.0
        if dk == "speed_init":
            for it in items:
                if it["part"] == "鞋子" and it["main_key"] == "速度":
                    if it["main_val"] >= 45 and it["set_name"] == "速度套装":
                        pts += dc["spd45_speed_boot_pts"]
                    continue
                spd = it["sub_map"].get("速度", 0.0)
                if it["is_event_88"]:
                    if spd >= 17:
                        pts += dc["event_spd17_pts"]
                else:
                    if spd >= 20:
                        pts += dc["craft_spd20_pts"]
                    elif spd >= 18:
                        pts += dc["craft_spd18_pts"]
                    elif spd >= 16:
                        pts += dc["craft_spd16_pts"]
        else:
            for it in items:
                gs = it["dim_scores"][dk]
                if gs >= dc["gs_t2"]:
                    pts += dc["t2_pts"]
                elif gs >= dc["gs_t1"]:
                    pts += dc["t1_pts"]

        # 平滑饱和映射 0~100（pts == target 时约 80 分，渐近 100 分）
        ratio = pts / max(1.0, dc["target"])
        depth_score = round(_clamp(100.0 * (1.0 - (2.718281828 ** (-1.6 * ratio)))), 1)
        # P1-b：非先手维加硬上限，防活动 88 装把 depth 顶到 90+（先手维保持原曲线）
        if dk != "speed_init":
            depth_score = min(depth_score, float(agg.get("max_depth_score", 100.0)))

        final_score = round(_clamp(q_w * quality_score + d_w * depth_score), 1)
        internal_scores[dk] = final_score
        out_by_cn[cn_name] = {
            "score": final_score,
            "quality_score": quality_score,
            "depth_score": depth_score,
            "part_topk": part_topk,
        }

    return out_by_cn, internal_scores


def evaluate_archetypes_and_account(
    items: list[dict[str, Any]],
    dim_scores: dict[str, float],
    cfg: dict[str, Any] = ANALYSIS_CFG,
) -> tuple[dict[str, float], str, dict[str, Any]]:
    """第四层：5 流派契合度（含硬门控）、4 档标尺、主副命名与手工成色/词条纯度标签。"""
    ac = cfg["archetype_cfg"]
    gates = ac["gates"]
    total = len(items)

    if total == 0:
        empty_arch = {v: 0.0 for v in TEXTS["archetypes"].values()}
        return empty_arch, TEXTS["tiers"]["T1"], {
            "main_lean": TEXTS["warnings"]["empty_valid"],
            "sub_feature": "",
            "tags": [],
            "key_metrics": {},
            "readiness": None,
        }

    # 核心速度统计（严格区分含活动固定 88 装 vs 纯自刷手工装）
    non_boot = [it for it in items if not (it["part"] == "鞋子" and it["main_key"] == "速度")]
    spd_all_17 = sum(1 for it in non_boot if it["sub_map"].get("速度", 0) >= 17)
    spd_all_18 = sum(1 for it in non_boot if it["sub_map"].get("速度", 0) >= 18)
    spd_all_20 = sum(1 for it in non_boot if it["sub_map"].get("速度", 0) >= 20)
    spd_all_21 = sum(1 for it in non_boot if it["sub_map"].get("速度", 0) >= 21)
    spd_all_23 = sum(1 for it in non_boot if it["sub_map"].get("速度", 0) >= 23)
    spd_all_25 = sum(1 for it in non_boot if it["sub_map"].get("速度", 0) >= 25)
    spd_craft_17 = sum(1 for it in non_boot if not it["is_event_88"] and it["sub_map"].get("速度", 0) >= 17)
    spd_craft_18 = sum(1 for it in non_boot if not it["is_event_88"] and it["sub_map"].get("速度", 0) >= 18)
    spd_craft_20 = sum(1 for it in non_boot if not it["is_event_88"] and it["sub_map"].get("速度", 0) >= 20)
    spd_craft_21 = sum(1 for it in non_boot if not it["is_event_88"] and it["sub_map"].get("速度", 0) >= 21)
    spd_craft_23 = sum(1 for it in non_boot if not it["is_event_88"] and it["sub_map"].get("速度", 0) >= 23)
    spd_craft_25 = sum(1 for it in non_boot if not it["is_event_88"] and it["sub_map"].get("速度", 0) >= 25)
    spd_10_to_16 = sum(1 for it in non_boot if 10 <= it["sub_map"].get("速度", 0) <= 16)

    def _set_ratio(target_sets: set[str]) -> float:
        return sum(1 for it in items if it["set_name"] in target_sets) / total

    spd_set_r = _set_ratio(ac["speed_sets"])
    clv_set_r = _set_ratio(ac["cleave_sets"])
    std_set_r = _set_ratio(ac["standard_sets"])
    mid_set_r = _set_ratio(ac["mid_sets"])
    tnk_set_r = _set_ratio(ac["tank_sets"])

    s_spd = dim_scores["speed_init"]
    s_dps = dim_scores["burst_dps"]
    s_bru = dim_scores["bruiser"]
    s_tnk = dim_scores["pure_tank"]
    s_res = dim_scores["high_res"]
    s_eff = dim_scores["eff_ctrl"]

    # 1) 高速（一速维 + 速度套密度 + 极速硬门控）
    aggro = 0.62 * s_spd + 0.18 * s_eff + 20.0 * _clamp(spd_set_r / 0.45, 0.0, 1.0)
    if spd_craft_20 == 0:
        aggro = min(aggro, gates["aggro_no_spd20_cap"])
    elif spd_craft_18 < 3:
        aggro = min(aggro, gates["aggro_few_spd18_cap"])

    # 2) 核爆（爆发纯C + 高速支撑 + 输出套密度；缺速度必须门控压低）
    cleave = 0.50 * s_dps + 0.32 * s_spd + 18.0 * _clamp(clv_set_r / 0.50, 0.0, 1.0)
    if s_spd < gates["cleave_low_spd_dim_thresh"]:
        cleave *= gates["cleave_low_spd_mult"]
    if spd_craft_18 < 2:
        cleave = min(cleave, gates["cleave_no_spd18_cap"])

    # 3) 阵地（半肉 + 纯坦 + 控场/抗性辅助 + 阵地功能套占比）
    sf = ac["standard_formula"]
    standard = (
        sf["bru_w"] * s_bru
        + sf["tnk_w"] * s_tnk
        + sf["aux_w"] * max(s_res, s_eff)
        + sf["set_w"] * _clamp(std_set_r / sf["set_full_ratio"], 0.0, 1.0)
    )
    if std_set_r < gates["standard_scarce_set_thresh"]:
        standard *= gates["standard_scarce_mult"]

    # 4) 中速（输出+半肉+控场均衡、10~16中速词条厚度、常规讨伐套厚度）
    mid_spd_density = _clamp(spd_10_to_16 / max(8.0, total * 0.18), 0.0, 1.0)
    mid_spd = (
        0.34 * s_dps
        + 0.28 * s_bru
        + 0.14 * s_eff
        + 0.08 * s_tnk
        + 14.0 * mid_spd_density
        + 12.0 * _clamp(mid_set_r / 0.75, 0.0, 1.0)
    )

    # 5) 肉猪（纯坦 + 高抗双高 + 血防抗右三件储备）
    tank_right_cnt = sum(
        1 for it in items
        if it["part"] in cfg["right_parts"] and it["main_key"] in ("生命值%", "防御力%", "效果抗性")
    )
    tank_right_density = _clamp(tank_right_cnt / max(6.0, total * 0.22), 0.0, 1.0)
    turn2_tank = (
        0.44 * s_tnk
        + 0.36 * s_res
        + 10.0 * tank_right_density
        + 10.0 * _clamp(tnk_set_r / 0.30, 0.0, 1.0)
    )
    # 低抗门控：高抗维过低时压制肉猪契合度（与核爆低速门控对称）
    if s_res < gates["turn2_low_res_dim_thresh"]:
        turn2_tank *= gates["turn2_low_res_mult"]

    archetypes = {
        TEXTS["archetypes"]["cleave"]: round(_clamp(cleave), 1),
        TEXTS["archetypes"]["aggro_spd"]: round(_clamp(aggro), 1),
        TEXTS["archetypes"]["standard"]: round(_clamp(standard), 1),
        TEXTS["archetypes"]["mid_spd"]: round(_clamp(mid_spd), 1),
        TEXTS["archetypes"]["turn2_tank"]: round(_clamp(turn2_tank), 1),
    }

    # 主倾向 + 副特征命名
    top_arch = max(archetypes, key=lambda k: archetypes[k])
    top_dim_cn = TEXTS["dims"][max(dim_scores, key=lambda k: dim_scores[k])]
    main_lean = TEXTS["archetype_lean"][top_arch]
    sub_feature = TEXTS["dim_sub_feature"][top_dim_cn]

    # 成色指标：手工比 / 词条纯度 / 穿戴使用率
    t_cfg = cfg["account_tags_cfg"]
    event_88_cnt = sum(1 for it in items if it["is_event_88"])
    craft_85_90_cnt = sum(
        1 for it in items if it["effective_level"] in ("85", "90") and not it["is_event_88"]
    )
    event_pct = round(event_88_cnt / total * 100.0, 1)
    craft_pct = round(craft_85_90_cnt / total * 100.0, 1)

    panel_90_items = [it for it in items if it["panel_score"] >= t_cfg["purity_panel_es_min"]]
    coherent_90_cnt = sum(
        1 for it in panel_90_items
        if it["best_valid_gs"] >= t_cfg["purity_valid_gs_min"] and not it["is_mismatched"]
    )
    purity_ratio = (coherent_90_cnt / len(panel_90_items)) if panel_90_items else 1.0
    purity_pct = round(purity_ratio * 100.0, 1)
    mismatched_cnt = sum(1 for it in items if it["is_mismatched"])

    eq_items = [it for it in items if it["equipped"]]
    eq_avg_raw_gs = round(sum(it["raw_gs"] for it in eq_items) / len(eq_items), 1) if eq_items else 0.0
    idle_high_cnt = sum(
        1 for it in items if (not it["equipped"]) and it["best_valid_gs"] >= t_cfg["idle_high_gs"]
    )

    tags: list[str] = []
    if event_88_cnt / total >= t_cfg["event_heavy_ratio"]:
        tags.append(TEXTS["tags"]["event_heavy"].format(event_pct=event_pct))
    else:
        tags.append(TEXTS["tags"]["craft_high"].format(craft_pct=craft_pct))

    if purity_ratio >= t_cfg["purity_high_ratio"] and mismatched_cnt <= t_cfg["purity_high_max_mismatched"]:
        tags.append(TEXTS["tags"]["purity_high"].format(purity_pct=purity_pct))
    elif purity_ratio < t_cfg["purity_low_ratio"] or mismatched_cnt >= t_cfg["purity_low_min_mismatched"]:
        tags.append(TEXTS["tags"]["purity_low"].format(purity_pct=purity_pct, mismatched_cnt=mismatched_cnt))
    else:
        tags.append(TEXTS["tags"]["purity_mid"].format(purity_pct=purity_pct))

    if idle_high_cnt > 0:
        tags.append(TEXTS["tags"]["usage_idle"].format(idle_high=idle_high_cnt))
    else:
        tags.append(TEXTS["tags"]["usage_active"].format(eq_gs=eq_avg_raw_gs, idle_high=idle_high_cnt))

    # 档位/战备共用计数（readiness 前移后只算一次）
    sorted_dims = sorted(dim_scores.values(), reverse=True)
    top2_avg = (sorted_dims[0] + sorted_dims[1]) / 2.0 if len(sorted_dims) >= 2 else 0.0
    valid_62_cnt = sum(1 for it in items if it["best_valid_gs"] >= 62.0 and not it["is_event_88"])
    valid_58_cnt = sum(1 for it in items if it["best_valid_gs"] >= 58.0 and not it["is_event_88"])
    reforged_90_cnt = sum(1 for it in items if it["effective_level"] == "90")

    # ---------- 战备综合指数（口径 v1：只增展示，不改评分）----------
    rc = cfg["readiness_cfg"]
    n58_manual = valid_58_cnt
    n62_manual = valid_62_cnt
    n58_event = sum(1 for it in items if it["is_event_88"] and it["best_valid_gs"] >= 58.0)
    n62_event = sum(1 for it in items if it["is_event_88"] and it["best_valid_gs"] >= 62.0)
    manual_equiv = n58_manual * 0.5 + n62_manual * 1.5
    event_equiv = n58_event * 0.5 + n62_event * 1.5
    bench_equiv = manual_equiv + rc["bench_event88_weight"] * event_equiv
    bench_score = round(min(100.0, bench_equiv / max(1.0, rc["bench_target_D"]) * 100.0), 1)

    es90_cnt = len(panel_90_items)
    if es90_cnt < rc["purity_smooth_min_samples"]:
        smooth_purity = (coherent_90_cnt + rc["purity_smooth_prior"]) / (
            es90_cnt + rc["purity_smooth_min_samples"]
        ) * 100.0
    else:
        smooth_purity = purity_pct
    reforged_90_pct = round(reforged_90_cnt / total * 100.0, 1) if total else 0.0
    if rc.get("quality_reforged_pct"):
        quality_second = reforged_90_pct
    else:
        quality_second = craft_pct
    quality_score = round(0.5 * smooth_purity + 0.5 * quality_second, 1)
    knife_score = round(top2_avg, 1)
    weighted_score = round(
        rc["weights"]["knife"] * knife_score
        + rc["weights"]["bench"] * bench_score
        + rc["weights"]["quality"] * quality_score,
        1,
    )
    curve_p = float(rc.get("display_curve_p") or 1.0)
    display_scale = int(rc.get("display_scale") or 100)
    display_index = round(display_scale * ((max(0.0, weighted_score) / 100.0) ** curve_p))
    readiness_info = {
        "index": weighted_score,          # 内部 0–100 加权分（保持旧字段兼容）
        "weighted_score": weighted_score,
        "display_index": display_index if total >= rc["min_items_to_show"] else None,
        "shown": total >= rc["min_items_to_show"],
        "knife": knife_score,
        "bench": bench_score,
        "quality": quality_score,
        "bench_equiv": round(bench_equiv, 2),
        "bench_manual_equiv": round(manual_equiv, 2),
        "bench_event_equiv": round(event_equiv, 2),
        "n58_manual": n58_manual,
        "n62_manual": n62_manual,
        "n58_event": n58_event,
        "n62_event": n62_event,
        "purity_pct": purity_pct,
        "smoothed_purity_pct": round(smooth_purity, 1),
        "craft_pct": craft_pct,
        "reforged_90_count": reforged_90_cnt,
        "reforged_90_pct": reforged_90_pct,
        "es90_count": es90_cnt,
        "total_items": total,
        "min_items_to_show": rc["min_items_to_show"],
        "bench_target_D": rc["bench_target_D"],
        "bench_event88_weight": rc["bench_event88_weight"],
        "weights": dict(rc["weights"]),
        "display_scale": display_scale,
        "display_curve_p": curve_p,
        "complete": None,  # 由 analyze_payload 按扫描完整性回填
    }

    # ---------- 4 档强度评定（readiness 前移后：gear 轨 + 纯阵地轨 + 战备保底）----------
    wide_dims_ge60 = sum(1 for v in dim_scores.values() if v >= 60.0)
    tc = ac["tiers"]

    # readiness 展示口径（0–1000）；<100 件时仍用内部加权算，仅不展示
    read_weighted = float(readiness_info.get("weighted_score") or 0.0)
    read_scale = int(rc.get("display_scale") or 100)
    read_curve = float(rc.get("display_curve_p") or 1.0)
    readiness_display = round(read_scale * ((max(0.0, read_weighted) / 100.0) ** read_curve))

    gear_t1 = (
        top2_avg >= tc["T4"]["top2_dim_avg"]
        and valid_62_cnt >= tc["T4"]["valid_62_cnt"]
        and spd_craft_23 >= tc["T4"]["craft_spd23_cnt"]
        and readiness_display >= tc["T4"]["readiness_min_display"]
    )
    gear_t2 = (
        top2_avg >= tc["T3"]["top2_dim_avg"]
        and valid_62_cnt >= tc["T3"]["valid_62_cnt"]
        and spd_craft_18 >= tc["T3"]["craft_spd18_cnt"]
        and readiness_display >= tc["T3"]["readiness_min_display"]
    )
    alt = tc["T3_alt_tank"]
    tank_t2 = (
        top2_avg >= alt["top2_dim_avg"]
        and valid_62_cnt >= alt["valid_62_cnt"]
        and spd_craft_18 >= alt["craft_spd18_cnt"]
        and readiness_display >= alt["readiness_min_display"]
        and wide_dims_ge60 >= alt["wide_dims_ge60"]
        and reforged_90_cnt >= alt["reforged_90_min"]
    )

    if gear_t1:
        tier_label = TEXTS["tiers"]["T4"]
    elif gear_t2 or tank_t2:
        tier_label = TEXTS["tiers"]["T3"]
    elif (
        top2_avg >= tc["T2"]["top2_dim_avg"]
        and (valid_58_cnt >= tc["T2"]["valid_58_cnt"] or reforged_90_cnt >= tc["T2"]["reforged_90_cnt"])
    ):
        tier_label = TEXTS["tiers"]["T2"]
    else:
        tier_label = TEXTS["tiers"]["T1"]

    # <100 件：最高只到 T3 精锐进阶（内部 T2），防止精简扫描绕过战备保底 / 99→100 掉档
    if total < rc["min_items_to_show"] and tier_label in (TEXTS["tiers"]["T4"], TEXTS["tiers"]["T3"]):
        tier_label = TEXTS["tiers"]["T2"]

    account_info = {
        "main_lean": main_lean,
        "sub_feature": sub_feature,
        "naming": f"主倾向：{main_lean} · 副特征：{sub_feature}",
        "tags": tags,
        "key_metrics": {
            "craft_85_90_count": craft_85_90_cnt,
            "craft_85_90_pct": craft_pct,
            "event_88_count": event_88_cnt,
            "event_88_pct": event_pct,
            "reforged_90_count": reforged_90_cnt,
            "spd_ge17_all": spd_all_17,
            "spd_ge17_craft_only": spd_craft_17,
            "spd_ge18_all": spd_all_18,
            "spd_ge18_craft_only": spd_craft_18,
            "spd_ge20_all": spd_all_20,
            "spd_ge20_craft_only": spd_craft_20,
            "spd_ge21_all": spd_all_21,
            "spd_ge21_craft_only": spd_craft_21,
            "spd_ge23_all": spd_all_23,
            "spd_ge23_craft_only": spd_craft_23,
            "spd_ge25_all": spd_all_25,
            "spd_ge25_craft_only": spd_craft_25,
            "panel_es90_count": len(panel_90_items),
            "purity_pct": purity_pct,
            "mismatched_high_es_count": mismatched_cnt,
            "equipped_count": len(eq_items),
            "equipped_avg_raw_gs": eq_avg_raw_gs,
            "unequipped_high_gs_count": idle_high_cnt,
        },
        "readiness": readiness_info,
    }
    return archetypes, tier_label, account_info


# ==============================================================================
# 4. 第五层：5 个深度子模块
# ==============================================================================
def _item_total_speed_contribution(it: dict[str, Any]) -> float:
    if it["part"] == "鞋子" and it["main_key"] == "速度":
        return float(it["main_val"])
    return float(it["sub_map"].get("速度", 0.0))


def _solve_fastest_single_loadout(
    available: list[dict[str, Any]],
    base_spd: int,
    spd_set_bonus_pct: float,
    parts_order: tuple[str, ...],
) -> dict[str, Any] | None:
    """在当前剩余装备池中精确求单套最高速度（对比 4速度+2散件 vs 纯散件6件极速）。"""
    by_part: dict[str, list[dict[str, Any]]] = {p: [] for p in parts_order}
    for it in available:
        by_part[it["part"]].append(it)
    if any(len(by_part[p]) == 0 for p in parts_order):
        return None

    best_any: dict[str, dict[str, Any]] = {}
    best_spd_set: dict[str, dict[str, Any]] = {}
    for p in parts_order:
        best_any[p] = max(by_part[p], key=lambda x: (_item_total_speed_contribution(x), x["raw_gs"], -int(x["id"])))
        spd_cands = [x for x in by_part[p] if x["set_name"] == "速度套装"]
        if spd_cands:
            best_spd_set[p] = max(
                spd_cands, key=lambda x: (_item_total_speed_contribution(x), x["raw_gs"], -int(x["id"]))
            )

    # 方案 A：散件最高速
    broken_picks = [best_any[p] for p in parts_order]
    broken_spd_cnt = sum(1 for x in broken_picks if x["set_name"] == "速度套装")
    broken_set_bonus = round(base_spd * spd_set_bonus_pct) if broken_spd_cnt >= 4 else 0
    broken_gear_spd = sum(_item_total_speed_contribution(x) for x in broken_picks)
    best_plan = {
        "total_speed": int(round(base_spd + broken_set_bonus + broken_gear_spd)),
        "has_speed_set": broken_spd_cnt >= 4,
        "picks": broken_picks,
    }

    # 方案 B：强制凑满 4 件速度套 + 2 件散件最高速（从 6 部位选损失最小的 4 个部位放速度套）
    if len(best_spd_set) >= 4:
        penalties: list[tuple[float, str]] = []
        for p in best_spd_set:
            loss = _item_total_speed_contribution(best_any[p]) - _item_total_speed_contribution(best_spd_set[p])
            penalties.append((loss, p))
        penalties.sort(key=lambda t: t[0])
        chosen_spd_parts = {p for _, p in penalties[:4]}
        picks_4 = [
            (best_spd_set[p] if p in chosen_spd_parts else best_any[p])
            for p in parts_order
        ]
        set_bonus = round(base_spd * spd_set_bonus_pct)
        gear_spd = sum(_item_total_speed_contribution(x) for x in picks_4)
        total_4 = int(round(base_spd + set_bonus + gear_spd))
        if total_4 >= best_plan["total_speed"]:
            best_plan = {
                "total_speed": total_4,
                "has_speed_set": True,
                "picks": picks_4,
            }

    picks = best_plan["picks"]
    boot = next(x for x in picks if x["part"] == "鞋子")
    boot_spd = int(_item_total_speed_contribution(boot))
    sub_spd_sum = int(sum(_item_total_speed_contribution(x) for x in picks if x["part"] != "鞋子"))
    event_used = sum(1 for x in picks if x["is_event_88"])
    if best_plan["has_speed_set"]:
        formula = f"{base_spd}×{1 + spd_set_bonus_pct:.2f}+{boot_spd}+{sub_spd_sum}={best_plan['total_speed']} 速"
    else:
        formula = f"{base_spd}(散件)+{boot_spd}+{sub_spd_sum}={best_plan['total_speed']} 速"

    return {
        "total_speed": best_plan["total_speed"],
        "speed_set_active": best_plan["has_speed_set"],
        "boot_speed": boot_spd,
        "other_5_sub_speed": sub_spd_sum,
        "event_88_used": event_used,
        "formula": formula,
        "item_ids": [x["id"] for x in picks],
    }


def build_sandbox_loadouts(items: list[dict[str, Any]], cfg: dict[str, Any] = ANALYSIS_CFG) -> dict[str, Any]:
    """子模块 1：虚拟极限配装沙盘（一速/二速/三速不重复装备贪心推算，并附纯手工一速对照）。"""
    sc = cfg["submodules_cfg"]
    base_spd = sc["sandbox_base_spd"]
    bonus_pct = sc["sandbox_speed_set_bonus"]
    parts_order = cfg["parts_order"]

    pool = list(items)
    teams: list[dict[str, Any]] = []
    used_ids: set[Any] = set()
    for rank in range(1, sc["sandbox_team_count"] + 1):
        rem = [x for x in pool if x["id"] not in used_ids]
        res = _solve_fastest_single_loadout(rem, base_spd, bonus_pct, parts_order)
        if res is None:
            break
        res["rank"] = rank
        teams.append(res)
        used_ids.update(res["item_ids"])

    # 额外给出一套“不含活动 88 固定装”的纯自刷极限一速对照
    craft_only_pool = [x for x in items if not x["is_event_88"]]
    craft_top1 = _solve_fastest_single_loadout(craft_only_pool, base_spd, bonus_pct, parts_order)

    return {
        "base_speed_assumed": base_spd,
        "teams": teams,
        "craft_only_top1_speed": craft_top1["total_speed"] if craft_top1 else None,
        "craft_only_top1_formula": craft_top1["formula"] if craft_top1 else None,
    }


def build_set_capacity(items: list[dict[str, Any]], cfg: dict[str, Any] = ANALYSIS_CFG) -> dict[str, Any]:
    """子模块 2：套装成套能力透视（按部位槽位上限严算真实可凑 4件套/2件套上限，而非简单 count//4）。"""
    req_map = cfg["sets_pieces_required"]
    parts_order = cfg["parts_order"]
    left_parts = set(cfg["left_parts"])

    by_set: dict[str, list[dict[str, Any]]] = {}
    for it in items:
        by_set.setdefault(it["set_name"], []).append(it)

    sets_report: dict[str, dict[str, Any]] = {}
    for s_name, s_items in sorted(by_set.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        req = req_map.get(s_name, 2)
        part_counts = [sum(1 for x in s_items if x["part"] == p) for p in parts_order]
        left_cnt = sum(1 for x in s_items if x["part"] in left_parts)
        right_cnt = len(s_items) - left_cnt

        # 槽位约束下的最大成套数 k：每个部位最多贡献 k 件 → sum(min(c_p, k)) >= req * k
        max_sets = 0
        for k in range(1, len(s_items) // req + 1):
            if sum(min(c, k) for c in part_counts) >= req * k:
                max_sets = k
            else:
                break

        if len(s_items) < req * 2:
            hint = TEXTS["hunt_hints"]["scarce"]
        elif left_cnt >= right_cnt * 2.0:
            hint = TEXTS["hunt_hints"]["lack_right"]
        elif right_cnt >= left_cnt * 2.0:
            hint = TEXTS["hunt_hints"]["lack_left"]
        else:
            hint = TEXTS["hunt_hints"]["balanced"]

        sets_report[s_name] = {
            "total": len(s_items),
            "required": req,
            "left_count": left_cnt,
            "right_count": right_cnt,
            "max_full_sets": max_sets,
            "avg_valid_gs": round(sum(x["best_valid_gs"] for x in s_items) / len(s_items), 1),
            "hint": hint,
        }

    return sets_report


def build_right_three_matrix(items: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    """子模块 3：右三件稀缺矩阵（件数 + 平均最佳有效分）。"""
    def _stat_bucket(subset: list[dict[str, Any]]) -> dict[str, Any]:
        if not subset:
            return {"count": 0, "avg_valid_gs": 0.0}
        return {
            "count": len(subset),
            "avg_valid_gs": round(sum(x["best_valid_gs"] for x in subset) / len(subset), 1),
        }

    necks = [x for x in items if x["part"] == "项链"]
    rings = [x for x in items if x["part"] == "戒指"]
    boots = [x for x in items if x["part"] == "鞋子"]

    return {
        "项链": {
            "暴击伤害": _stat_bucket([x for x in necks if x["main_key"] == "暴击伤害"]),
            "暴击率": _stat_bucket([x for x in necks if x["main_key"] == "暴击率"]),
            "生命值%": _stat_bucket([x for x in necks if x["main_key"] == "生命值%"]),
            "防御力%": _stat_bucket([x for x in necks if x["main_key"] == "防御力%"]),
            "攻击力%": _stat_bucket([x for x in necks if x["main_key"] == "攻击力%"]),
        },
        "戒指": {
            "攻击力%": _stat_bucket([x for x in rings if x["main_key"] == "攻击力%"]),
            "生命值%": _stat_bucket([x for x in rings if x["main_key"] == "生命值%"]),
            "防御力%": _stat_bucket([x for x in rings if x["main_key"] == "防御力%"]),
            "效果命中": _stat_bucket([x for x in rings if x["main_key"] == "效果命中"]),
            "效果抗性": _stat_bucket([x for x in rings if x["main_key"] == "效果抗性"]),
        },
        "鞋子": {
            "45速鞋": _stat_bucket([x for x in boots if x["main_key"] == "速度" and x["main_val"] >= 43]),
            "40速鞋": _stat_bucket([x for x in boots if x["main_key"] == "速度" and 38 <= x["main_val"] < 43]),
            "攻击%鞋": _stat_bucket([x for x in boots if x["main_key"] == "攻击力%"]),
            "生防肉鞋": _stat_bucket([x for x in boots if x["main_key"] in ("生命值%", "防御力%")]),
        },
    }


def build_heatmap_6x6(items: list[dict[str, Any]], cfg: dict[str, Any] = ANALYSIS_CFG) -> dict[str, Any]:
    """子模块 4：6×6 部位×维度 Top3 有效分热力表与木桶短板定位（先手极速鞋子格标 None）。"""
    sc = cfg["submodules_cfg"]
    top_n = sc["heatmap_top_n"]
    weak_th = sc["heatmap_weak_thresh"]

    cells: dict[str, dict[str, float | None]] = {}
    weak_spots: list[dict[str, Any]] = []

    for p in cfg["parts_order"]:
        row_dict: dict[str, float | None] = {}
        for dk, d_cn in TEXTS["dims"].items():
            if dk == "speed_init" and p == "鞋子":
                row_dict[d_cn] = None
                continue
            vals = sorted(
                (it["dim_scores"][dk] for it in items if it["part"] == p),
                reverse=True,
            )[:top_n]
            padded = vals + [0.0] * max(0, top_n - len(vals))
            avg_v = round(sum(padded) / top_n, 1)
            row_dict[d_cn] = avg_v
            if avg_v < weak_th:
                weak_spots.append({"part": p, "dim": d_cn, "top3_avg": avg_v})
        cells[p] = row_dict

    weak_spots.sort(key=lambda x: x["top3_avg"])
    return {
        "top_n": top_n,
        "weak_threshold": weak_th,
        "cells": cells,
        "weak_spots_count": len(weak_spots),
        "weakest_5": weak_spots[:5],
    }


def build_action_lists(items: list[dict[str, Any]], cfg: dict[str, Any] = ANALYSIS_CFG) -> dict[str, Any]:
    """子模块 5：可行动清单（待重铸 85 金矿 + 已穿戴低效占坑/高分歪胚）。"""
    sc = cfg["submodules_cfg"]
    rg = sc["reforge_goldmine"]
    ie = sc["inefficient_equipped"]

    goldmine: list[dict[str, Any]] = []
    inefficient: list[dict[str, Any]] = []

    for it in items:
        spd = int(it["sub_map"].get("速度", 0))
        if (
            it["effective_level"] == "85"
            and not it["is_event_88"]
            and (spd >= rg["min_spd"] or it["best_valid_gs"] >= rg["min_valid_gs"])
        ):
            goldmine.append({
                "id": it["id"],
                "part": it["part"],
                "name": it["name"],
                "set": it["set_name"],
                "speed": spd,
                "best_dim": it["best_valid_dim"],
                "best_valid_gs": it["best_valid_gs"],
                "panel_score": it["panel_score"],
            })

        if it["equipped"] and (it["best_valid_gs"] < ie["max_valid_gs"] or it["is_mismatched"]):
            inefficient.append({
                "id": it["id"],
                "part": it["part"],
                "name": it["name"],
                "level": it["effective_level"],
                "raw_gs": it["raw_gs"],
                "best_dim": it["best_valid_dim"],
                "best_valid_gs": it["best_valid_gs"],
                "mismatched": it["is_mismatched"],
            })

    goldmine.sort(key=lambda x: (-x["speed"], -x["best_valid_gs"], x["id"]))
    inefficient.sort(key=lambda x: (x["best_valid_gs"], x["id"]))

    return {
        "reforge_goldmine_count": len(goldmine),
        "inefficient_equipped_count": len(inefficient),
        "reforge_goldmine_top": goldmine[: rg["max_list"]],
        "inefficient_equipped_top": inefficient[: ie["max_list"]],
    }


# ==============================================================================
# 5. 顶层分析入口与可读文本报告
# ==============================================================================
def analyze_payload(
    payload: dict[str, Any],
    source_name: str = "<memory>",
    cfg: dict[str, Any] = ANALYSIS_CFG,
) -> dict[str, Any]:
    """纯函数总入口：输入扫描 JSON 字典，输出确定性完整结构（用于 CLI / UI / 自检）。"""
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    raw_items = payload.get("items") if isinstance(payload.get("items"), list) else []

    stop_reason = str(meta.get("stop_reason") or "unknown")
    complete_stop = stop_reason in cfg["complete_stop_reasons"]

    valid_items: list[dict[str, Any]] = []
    invalid_counts: dict[str, int] = {}
    eff_level_counts: dict[str, int] = {"90": 0, "88": 0, "85": 0, "le80": 0}

    for idx, r_it in enumerate(raw_items, start=1):
        cleaned = validate_and_clean_item(r_it, idx, cfg)
        if not cleaned["valid"]:
            reason = str(cleaned["invalid_reason"]).split(":")[0]
            invalid_counts[reason] = invalid_counts.get(reason, 0) + 1
            continue
        scored = score_item_six_dims(cleaned, cfg)
        valid_items.append(scored)
        lv_key = scored["effective_level"]
        eff_level_counts[lv_key] = eff_level_counts.get(lv_key, 0) + 1

    present_parts = {it["part"] for it in valid_items}
    missing_parts = [p for p in cfg["parts_order"] if p not in present_parts]
    is_complete = bool(complete_stop and not missing_parts and len(valid_items) > 0)

    warnings: list[str] = []
    if not complete_stop:
        warnings.append(TEXTS["warnings"]["incomplete_stop"].format(stop_reason=stop_reason))
    if missing_parts:
        warnings.append(TEXTS["warnings"]["missing_parts"].format(parts="、".join(missing_parts)))
    if not valid_items:
        warnings.append(TEXTS["warnings"]["empty_valid"])

    dims_cn, internal_dims = aggregate_account_dims(valid_items, cfg)
    archetypes, tier_label, account_info = evaluate_archetypes_and_account(valid_items, internal_dims, cfg)
    if account_info.get("readiness"):
        account_info["readiness"]["complete"] = is_complete

    sandbox = build_sandbox_loadouts(valid_items, cfg)
    set_cap = build_set_capacity(valid_items, cfg)
    right_mat = build_right_three_matrix(valid_items)
    heatmap = build_heatmap_6x6(valid_items, cfg)
    actions = build_action_lists(valid_items, cfg)

    return {
        "input": {
            "file": source_name,
            "item_count": len(raw_items),
            "valid_count": len(valid_items),
            "stop_reason": stop_reason,
            "complete": is_complete,
            "missing_parts": missing_parts,
            "warnings": warnings,
            "effective_level_counts": eff_level_counts,
            "invalid_counts": invalid_counts,
        },
        "dims": dims_cn,
        "archetypes": archetypes,
        "tier": tier_label,
        "account": account_info,
        "item_details": [
            {
                "id": it["id"],
                "part": it["part"],
                "name": it["name"],
                "set": it["set_name"],
                "level": it["effective_level"],
                "event_88": it["is_event_88"],
                "raw_gs": it["raw_gs"],
                "best_dim": it["best_valid_dim"],
                "best_valid_gs": it["best_valid_gs"],
                "mismatched": it["is_mismatched"],
                "equipped": it["equipped"],
            }
            for it in valid_items
        ],
        "submodules": {
            "sandbox": sandbox,
            "set_capacity": set_cap,
            "right_three_matrix": right_mat,
            "heatmap_6x6": heatmap,
            "action_lists": actions,
        },
    }


def analyze_file(path: Path | str, cfg: dict[str, Any] = ANALYSIS_CFG) -> dict[str, Any]:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON 顶层结构不是对象: {p}")
    return analyze_payload(data, source_name=p.name, cfg=cfg)


def format_human_report(res: dict[str, Any]) -> str:
    """生成面向终端阅读的中文排版报告（--json 模式使用）。"""
    inp = res["input"]
    acc = res["account"]
    sub = res["submodules"]
    lines: list[str] = [TEXTS["report"]["title"]]

    lines.append(TEXTS["report"]["sec_input"])
    lines.append(
        f"  文件: {inp['file']} | 扫描件数: {inp['item_count']} (有效 {inp['valid_count']}) | "
        f"结束原因: {inp['stop_reason']} | 完整样本: {'是' if inp['complete'] else '否'}"
    )
    lv = inp["effective_level_counts"]
    lines.append(f"  等效等级归位: 90级={lv['90']} | 88级={lv['88']} | 85级={lv['85']} | ≤80级={lv['le80']}")
    if inp["invalid_counts"]:
        lines.append(f"  异常拦截统计: {inp['invalid_counts']}")
    for w in inp["warnings"]:
        lines.append(f"  {w}")

    lines.append("")
    lines.append(TEXTS["report"]["sec_dims"])
    for d_name, d_obj in res["dims"].items():
        pk_str = " ".join(f"{k}:{v:.1f}" for k, v in d_obj["part_topk"].items())
        lines.append(
            f"  - {d_name}: {d_obj['score']:5.1f}  (质量 {d_obj['quality_score']:4.1f} / 深度 {d_obj['depth_score']:4.1f}) | [{pk_str}]"
        )

    lines.append("")
    lines.append(TEXTS["report"]["sec_arch"])
    arch_str = " | ".join(f"{k} {v:.1f}" for k, v in sorted(res["archetypes"].items(), key=lambda x: -x[1]))
    lines.append(f"  契合度: {arch_str}")
    lines.append(f"  定级: 【{res['tier']}】  {acc.get('naming', '')}")
    for tg in acc.get("tags", []):
        lines.append(f"  标签: • {tg}")
    km = acc.get("key_metrics", {})
    if km:
        lines.append(
            f"  极速核查: 17+速 {km['spd_ge17_all']}件(手工 {km['spd_ge17_craft_only']}) | "
            f"18+速 {km['spd_ge18_all']}件(手工 {km['spd_ge18_craft_only']}) | "
            f"21+速 {km['spd_ge21_all']}件(手工 {km['spd_ge21_craft_only']}) | "
            f"23+速 {km['spd_ge23_all']}件(手工 {km['spd_ge23_craft_only']}) | "
            f"25+速 {km['spd_ge25_all']}件(手工 {km['spd_ge25_craft_only']})"
        )

    lines.append("")
    lines.append(TEXTS["report"]["sec_sub"])
    sb = sub["sandbox"]
    for t in sb["teams"]:
        lines.append(f"  [沙盘 #{t['rank']}速] {t['formula']} (含活动88装 {t['event_88_used']} 件, IDs={t['item_ids']})")
    if sb["craft_only_top1_formula"]:
        lines.append(f"  [纯手工一速对照] {sb['craft_only_top1_formula']}")

    cap_parts = [
        f"{s}:{v['total']}件(可凑{v['max_full_sets']}套)"
        for s, v in list(sub["set_capacity"].items())[:6]
    ]
    lines.append("  [主力套装容量] " + " | ".join(cap_parts))

    hm = sub["heatmap_6x6"]
    weak_txt = ", ".join(f"{w['part']}-{w['dim']}({w['top3_avg']})" for w in hm["weakest_5"]) or "无"
    lines.append(f"  [6×6木桶最弱5格] {weak_txt}")

    act = sub["action_lists"]
    lines.append(
        f"  [行动清单] 待重铸85潜力金矿: {act['reforge_goldmine_count']} 件 | "
        f"已穿戴低效/高分歪胚: {act['inefficient_equipped_count']} 件"
    )
    return "\n".join(lines)


def _discover_selftest_files(explicit: list[str]) -> list[Path]:
    """按约定顺序查找自检样本：显式参数 → debug/装备扫描_*.json 最新两个 → 当前目录同名文件。"""
    if explicit:
        return [Path(p) for p in explicit]

    roots = [Path.cwd(), Path(__file__).resolve().parent]
    seen: set[Path] = set()
    debug_files: list[Path] = []
    cwd_files: list[Path] = []

    for r in roots:
        d = r / "debug"
        if d.is_dir():
            for p in d.glob("装备扫描_*.json"):
                rp = p.resolve()
                if rp not in seen:
                    seen.add(rp)
                    debug_files.append(p)

    if debug_files:
        debug_files.sort(key=lambda p: p.name, reverse=True)
        if len(debug_files) >= 2:
            return debug_files[:2]

    for r in roots:
        for p in r.glob("装备扫描_*.json"):
            rp = p.resolve()
            if rp not in seen:
                seen.add(rp)
                cwd_files.append(p)

    combined = debug_files + sorted(cwd_files, key=lambda p: p.name, reverse=True)
    return combined[:2]


def _make_selftest_compact_view(res: dict[str, Any]) -> dict[str, Any]:
    """生成稳定、确定性的 --selftest 输出结构（保留全部必选契约字段，精简长列表为摘要数字）。"""
    sub = res["submodules"]
    act = sub["action_lists"]
    return {
        "input": res["input"],
        "dims": res["dims"],
        "archetypes": res["archetypes"],
        "tier": res["tier"],
        "account": res["account"],
        "submodules": {
            "sandbox": sub["sandbox"],
            "set_capacity": sub["set_capacity"],
            "right_three_matrix": sub["right_three_matrix"],
            "heatmap_6x6": sub["heatmap_6x6"],
            "action_lists": {
                "reforge_goldmine_count": act["reforge_goldmine_count"],
                "inefficient_equipped_count": act["inefficient_equipped_count"],
                "reforge_goldmine_sample": act["reforge_goldmine_top"][:5],
                "inefficient_equipped_sample": act["inefficient_equipped_top"][:5],
            },
        },
    }


def main(argv: list[str] | None = None) -> int:
    _setup_console_encoding()
    parser = argparse.ArgumentParser(description="E7Pilot 背包装备离线分析引擎")
    parser.add_argument("--json", dest="json_path", help="指定单个装备扫描 JSON 文件输出可读分析报告")
    parser.add_argument(
        "--selftest",
        nargs="*",
        help="运行确定性 JSON 自检（可传 1~N 个路径；不传则自动查找最新两份 装备扫描_*.json）",
    )
    args = parser.parse_args(argv)

    if args.selftest is not None:
        files = _discover_selftest_files(args.selftest)
        if not files:
            print(json.dumps({"error": TEXTS["report"]["no_sample"]}, ensure_ascii=False, indent=2))
            return 1
        results = [_make_selftest_compact_view(analyze_file(f)) for f in files]
        out_obj: Any = results[0] if len(results) == 1 else {"samples": results}
        print(json.dumps(out_obj, ensure_ascii=False, indent=2), flush=True)
        return 0

    if args.json_path:
        res = analyze_file(Path(args.json_path))
        print(format_human_report(res), flush=True)
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
