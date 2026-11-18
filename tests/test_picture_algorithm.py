import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Gear,Stat
from picture_algorithm import evaluate_picture,breakdown,ROUTES
from official_rolls import DATA,distribution,describe_roll,PROFILES,next_roll_note

def gear(stage=0,score=22,right=False,grade='史诗',speed=2):
    # Keep score exact by changing the HP% term, without main-stat collisions.
    g=Gear(name='边界样本',slot='戒指' if right else '武器',set_name='速度',level=85,enhance=stage,grade=grade,
           main=Stat('atk_pct' if right else 'atk',100 if not right else 10),
           subs=[Stat('spd',speed),Stat('crit',4),Stat('hp_pct',score-speed*2-6.4-4*8/7),Stat('cdmg',4)])
    if grade=='英雄' and stage<12:
        g.subs.remove(g.subs[-1]);g.subs[-1].value+=4*8/7
    return g

class PictureTests(unittest.TestCase):
    def test_current_user_screenshot(self):
        g=gear();g.subs=[Stat('spd',2),Stat('hp_pct',4),Stat('res',6),Stat('cdmg',7)];g.screen_score=26
        r=evaluate_picture(g)
        self.assertAlmostEqual(r['score'],22);self.assertEqual(r['kind'],'enhance')
        g.screen_score=99
        self.assertEqual(evaluate_picture(g)['kind'],'enhance')

    def test_flat_conversion(self):
        g=Gear(subs=[Stat('atk',44),Stat('hp',200),Stat('def',36)])
        b=breakdown(g)
        self.assertAlmostEqual(b[0]['score'],44/1200*100)
        self.assertEqual([x['score'] for x in b[1:]],[4,6])
        b=breakdown(g,{'hp':4361,'def':477})
        self.assertAlmostEqual(b[1]['score'],200/4361*100)
        with self.assertRaises(ValueError):breakdown(g,{'hp':0})
        with self.assertRaises(ValueError):breakdown(g,{'hp':float('nan')})

    def test_total_gates(self):
        for right in [False,True]:
            for stage,threshold in [(6,32 if right else 34),(9,38 if right else 40),(12,44 if right else 46),(15,50 if right else 52)]:
                with self.subTest(right=right,stage=stage):
                    r=evaluate_picture(gear(stage,threshold,right),route=ROUTES[1])
                    self.assertEqual(r['kind'],'reforge' if stage==15 else 'enhance')
                    r=evaluate_picture(gear(stage,threshold-.001,right),route=ROUTES[1])
                    self.assertEqual(r['kind'],'discard' if stage in {6,9} else 'usable' if stage==15 and right else 'backup')

    def test_entry_grades(self):
        for right in [False,True]:
            for grade in ['史诗','英雄']:
                t=(18 if right else 20)+(2 if grade=='史诗' else 0)
                self.assertEqual(evaluate_picture(gear(0,t,right,grade),route=ROUTES[1])['kind'],'enhance')
                self.assertEqual(evaluate_picture(gear(0,t-.001,right,grade),route=ROUTES[1])['kind'],'discard')

    def test_reforged_gates(self):
        for right,t in [(False,65),(True,63)]:
            g=gear(15,t,right);g.level=90
            self.assertEqual(evaluate_picture(g,route=ROUTES[1])['kind'],'excellent')
            g.subs[2].value-=.001
            self.assertEqual(evaluate_picture(g,route=ROUTES[1])['kind'],'usable')

    def test_speed_path_and_score_fallback(self):
        for stage,speed,score,expected in [(0,4,21,'enhance'),(0,3,21,'discard'),(0,2,21,'discard'),(6,10,33,'enhance'),(6,9,33,'discard'),(12,15,45,'enhance'),(12,14,39.9,'backup'),(12,14,40,'usable'),(12,14,45.99,'usable'),(12,14,46,'enhance'),(15,15,45,'reforge'),(15,14,45,'usable')]:
            with self.subTest(stage=stage,speed=speed,score=score):self.assertEqual(evaluate_picture(gear(stage,score,speed=speed),route=ROUTES[2])['kind'],expected)
        g=gear(15,65,speed=20);g.level=90
        self.assertEqual(evaluate_picture(g,route=ROUTES[2])['kind'],'excellent')

    def test_fixed_main_and_incomplete(self):
        g=gear(score=25,right=True);g.main=Stat('atk',100)
        self.assertEqual(evaluate_picture(g)['kind'],'discard')
        self.assertEqual(evaluate_picture(g,fixed_main_confirmed=True)['kind'],'discard')
        g.subs.pop()
        self.assertTrue(evaluate_picture(g)['errors'])

    def test_88_not_automatically_reforge(self):
        g=gear(15,55);g.level=88
        self.assertEqual(evaluate_picture(g,route=ROUTES[1])['kind'],'usable')

    def test_official_distribution(self):
        for tier,stats in DATA['tiers'].items():
            for key,grades in stats.items():
                for grade,pairs in grades.items():
                    self.assertAlmostEqual(sum(p for v,p in pairs),100,delta=.1)
                    self.assertTrue(all(p>=0 for v,p in pairs))
        self.assertEqual(max(v for v,p in distribution(85,'史诗','spd')),5)
        self.assertEqual(dict(distribution(85,'史诗','spd'))[5],.332)
        self.assertIsNone(distribution(88,'史诗','spd'))
        self.assertIsNone(distribution(90,'史诗','spd',PROFILES[1]))
        self.assertEqual(distribution(88,'史诗','spd',PROFILES[3]),distribution(85,'史诗','spd'))
        self.assertNotEqual(distribution(88,'史诗','hp_pct',PROFILES[3]),distribution(85,'史诗','hp_pct'))
        self.assertIn('满跳',describe_roll(85,'史诗','cdmg',7))
        self.assertIn('新增',next_roll_note(gear(9,40,grade='英雄')))

if __name__=='__main__':unittest.main()
