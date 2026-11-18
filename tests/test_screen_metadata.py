import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from screen_metadata import official_score_lines
from core import Gear,Stat
from picture_algorithm import evaluate_picture

class MetadataRegression(unittest.TestCase):
    def test_no_next_line_zero_appended(self):
        self.assertEqual(official_score_lines('装备分数 59\n0 反击套装（1/4）'),59)
        self.assertEqual(official_score_lines('装备分数 43（+11）\n0'),43)
        self.assertIsNone(official_score_lines('装备分数\n59'))

    def test_score_visible_when_stage_unknown(self):
        g=Gear(slot='武器',set_name='反击',grade='史诗',level=85,enhance=None,main=Stat('atk',360),subs=[Stat('hp',189),Stat('hp_pct',9),Stat('spd',4),Stat('crit',13)])
        r=evaluate_picture(g)
        self.assertAlmostEqual(r['score'],41.58)
        self.assertTrue(r['errors']);self.assertEqual(r['kind'],'review')
        g.enhance=12;r=evaluate_picture(g)
        self.assertEqual(r['kind'],'backup');self.assertEqual(r['threshold'],46)

if __name__=='__main__':unittest.main()
