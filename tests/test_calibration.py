import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import DEFAULT_RULES, Gear, Stat, compare_observation, parse_stat, parse_text, validate, evaluate, import_heroes
from vision import cosine, signature, match_icon, number_mask, template_number
from PIL import Image,ImageDraw

ROOT=Path(__file__).resolve().parents[1]


class RealLayoutTests(unittest.TestCase):
    def test_count_current_delta_are_separate(self):
        self.assertEqual(parse_stat('暴击伤害（1） 14%（+7%）'),Stat('cdmg',14))
        self.assertIsNone(parse_stat('暴击伤害（1）'))

    def test_legendary_label_and_score_not_substat(self):
        g=parse_text('传说武器\n深渊龙兽骨刃剑\n85\n强化0\n攻击力100\n生命值7%\n速度3\n暴击率4%\n暴击伤害7%\n装备分数32\n速度套装(0/4)')
        self.assertEqual(g.grade,'史诗')
        self.assertEqual(g.name,'深渊龙兽骨刃剑')
        self.assertEqual(len(g.subs),4)
        self.assertEqual(validate(g),[])

    def test_observed_main_growth_separate_from_substat(self):
        before=Gear(name='测试武器',slot='武器',set_name='速度',grade='史诗',level=85,enhance=0,
                    main=Stat('atk',100),subs=[Stat('hp_pct',7),Stat('spd',3),Stat('crit',4),Stat('cdmg',7)],screen_score=32)
        after=copy.deepcopy(before);after.enhance=3;after.main.value=160;after.subs[-1].value=14;after.screen_score=43
        event=compare_observation(before,after)
        self.assertEqual(event['main_change']['delta'],60)
        self.assertEqual(event['changes'],[{'key':'cdmg','before':7,'after':14,'delta':7,'kind':'提升'}])
        self.assertEqual(event['screen_score_after'],43)
        # 游戏画面分与视频副属性分不得混合。
        self.assertAlmostEqual(evaluate(before,DEFAULT_RULES,confirmed=True)['score'],26.88)

    def test_blank_and_unmatched_icon_abstain(self):
        t=json.loads((ROOT/'data/icon-signatures.json').read_text(encoding='utf-8'))
        blank=Image.new('RGB',(32,30),(5,11,19))
        self.assertEqual(match_icon(blank,t['stats'])[0],None)
        self.assertEqual(template_number(blank,t['digits']),None)

    def test_resistance_and_crit_templates_differ(self):
        t=json.loads((ROOT/'data/icon-signatures.json').read_text(encoding='utf-8'))
        self.assertLess(cosine(t['stats']['res'][0],t['stats']['crit'][0]),.90)

    def test_full_community_snapshot_is_available_and_marked(self):
        heroes=import_heroes(json.loads((ROOT/'data/heroes.json').read_text(encoding='utf-8')))
        self.assertGreaterEqual(len(heroes),300)
        auto=[h for h in heroes if '自动分类' in h.get('basis','')]
        self.assertGreater(len(auto),250)


if __name__=='__main__':unittest.main(verbosity=2)
