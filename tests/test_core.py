import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import (DEFAULT_RULES, Gear, Stat, Store, compare_observation, evaluate,
                  import_heroes, parse_text, recommend, total_score, validate)
from ocr import reconstruct_lines

ROOT = Path(__file__).resolve().parents[1]


class GearTests(unittest.TestCase):
    def setUp(self):
        self.g = parse_text((ROOT / 'data/demo.txt').read_text(encoding='utf-8'))
        self.rules = copy.deepcopy(DEFAULT_RULES)

    def test_demo_parsing_and_score(self):
        self.assertEqual(validate(self.g), [])
        self.assertEqual(self.g.enhance, 0)
        self.assertEqual(self.g.main.key, 'cdmg')
        self.assertEqual(total_score(self.g, self.rules), 30.5)
        self.assertEqual(evaluate(self.g, self.rules, confirmed=True)['decision'], '可以试强')

    def test_unverified_never_gets_disposal(self):
        g = copy.deepcopy(self.g)
        g.enhance = 15
        self.assertEqual(evaluate(g, self.rules)['decision'], '待校对')

    def test_attribute_plus_not_enhance(self):
        g = parse_text('等级85\n项链\n史诗\n速度套装\n主属性：暴击伤害+7%\n攻击力+8%\n暴击率+5%\n速度+4\n生命值+7%')
        self.assertIsNone(g.enhance)

    def test_same_main_sub_rejected(self):
        self.g.subs[0] = Stat('cdmg', 5)
        self.assertTrue(any('主属性与副属性' in x for x in validate(self.g)))

    def test_missing_sub_and_illegal_slot_rejected(self):
        self.g.subs.pop()
        self.assertTrue(validate(self.g))
        self.g.slot = '武器'
        self.assertTrue(any('主属性类型' in x for x in validate(self.g)))

    def test_exact_roll(self):
        after = copy.deepcopy(self.g)
        after.enhance = 3
        after.subs[2].value += 3
        event = compare_observation(self.g, after)
        self.assertTrue(event['exact'])
        self.assertEqual(event['changes'][0]['delta'], 3)
        self.assertEqual(event['changes'][0]['key'], 'spd')

    def test_skipped_rolls_are_aggregate(self):
        after = copy.deepcopy(self.g)
        after.enhance = 9
        after.subs[2].value += 9
        event = compare_observation(self.g, after)
        self.assertFalse(event['exact'])
        self.assertEqual(event['steps'], 3)
        self.assertIn('逐跳顺序未知', event['note'])

    def test_impossible_single_roll_and_regression_rejected(self):
        after = copy.deepcopy(self.g)
        after.enhance = 3
        after.subs[2].value += 20
        with self.assertRaises(ValueError):
            compare_observation(self.g, after)
        after.subs[2].value = 2
        with self.assertRaises(ValueError):
            compare_observation(self.g, after)

    def test_heroic_new_substat(self):
        self.g.grade = '英雄'
        self.g.enhance = 9
        self.g.subs.pop()
        self.assertEqual(validate(self.g), [])
        after = copy.deepcopy(self.g)
        after.enhance = 12
        after.subs.append(Stat('res', 6))
        self.assertEqual(validate(after), [])
        self.assertEqual(compare_observation(self.g, after)['changes'][0]['kind'], '新增')

    def test_reforge_is_not_enhance_roll(self):
        self.g.enhance = 15
        after = copy.deepcopy(self.g)
        after.level = 90
        with self.assertRaises(ValueError):
            compare_observation(self.g, after)

    def test_no_event_when_unchanged(self):
        self.assertIsNone(compare_observation(self.g, copy.deepcopy(self.g)))

    def test_sql_persistence_dedup_export(self):
        with tempfile.TemporaryDirectory() as td:
            store = Store(Path(td) / 'test.sqlite3')
            item_id = store.create_item('同一件装备')
            store.record(item_id, self.g)
            self.assertIsNone(store.record(item_id, self.g))
            after = copy.deepcopy(self.g)
            after.enhance = 3
            after.subs[2].value += 3
            store.record(item_id, after)
            self.assertEqual(len(store.observations(item_id)), 2)
            store.export(Path(td) / 'out.json')
            output = json.loads((Path(td) / 'out.json').read_text(encoding='utf-8'))
            self.assertEqual(output['items'][0]['observations'][1]['event']['changes'][0]['delta'], 3)
            store.close()

    def test_hero_profiles_and_main_mismatch(self):
        heroes = import_heroes(json.loads((ROOT / 'data/heroes.json').read_text(encoding='utf-8')))
        recommendations = recommend(self.g, heroes, self.rules)
        cermia = next(r for r in recommendations if r['name_en'] == 'Cermia')
        frida = next(r for r in recommendations if r['name_en'] == 'Frida')
        self.assertGreater(cermia['effective'], frida['effective'])
        self.assertTrue(cermia['main_ok'])
        self.assertFalse(frida['main_ok'])
        self.assertEqual(recommend(self.g, heroes, self.rules, owned_only=True), [])

    def test_community_import_classifies_with_warning(self):
        imported = import_heroes([{'name': 'Test', 'role': 'Warrior', 'attack': '1000',
                                  'skill1': "Damage dealt increases proportional to the caster's max Health."}])
        self.assertEqual(imported[0]['archetype'], '生命暴击输出')
        self.assertIn('未核实', imported[0]['basis'])

    def test_no_nan(self):
        self.g.subs[0].value = float('nan')
        self.assertTrue(validate(self.g))
        with self.assertRaises(ValueError):
            import_heroes([{'name': 'bad', 'weights': {'spd': float('nan')}}])

    def test_ocr_rows_join_label_and_value(self):
        lines = [{'words': [{'text': '速度', 'x': 10, 'y': 20, 'w': 20, 'h': 15}]},
                 {'words': [{'text': '+4', 'x': 200, 'y': 21, 'w': 20, 'h': 15}]},
                 {'words': [{'text': '生命值', 'x': 10, 'y': 60, 'w': 20, 'h': 15},
                            {'text': '7%', 'x': 200, 'y': 61, 'w': 20, 'h': 15}]}]
        self.assertEqual(reconstruct_lines(lines), '速度 +4\n生命值 7%')


if __name__ == '__main__':
    unittest.main(verbosity=2)
