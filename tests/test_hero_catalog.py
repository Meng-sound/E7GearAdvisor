import sys
import unittest
from pathlib import Path
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hero_picker import load_catalog,search_heroes
from core import Gear,Stat
from picture_algorithm import evaluate_picture
ROOT=Path(__file__).resolve().parents[1]

class HeroCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.catalog=load_catalog(ROOT/'data/hero-catalog.json');cls.heroes=cls.catalog['heroes']

    def test_consistent_state_and_unique_ids(self):
        self.assertEqual(len(self.heroes),393)
        self.assertEqual(len({h['id'] for h in self.heroes}),len(self.heroes))
        self.assertEqual(self.catalog['stats_field'],'calculatedStatus.lv60SixStarFullyAwakened')

    def test_all_portraits_available_offline(self):
        for h in self.heroes:
            with Image.open(ROOT/'data'/h['portrait']) as picture:
                picture.verify()

    def test_chinese_and_english_search(self):
        a=search_heroes(self.heroes,'洁若米亚');b=search_heroes(self.heroes,'cermia')
        self.assertTrue(any(h['name_en']=='Cermia' for h in a))
        self.assertEqual({h['id'] for h in a},{h['id'] for h in b})
        self.assertEqual(search_heroes(self.heroes,'不存在的角色xyz'),[])

    def test_selected_base_changes_flat_score_only(self):
        c=next(h for h in self.heroes if h['name_en']=='Cermia')
        self.assertEqual(c['base']['hp'],5542)
        g=Gear(slot='武器',set_name='反击',grade='史诗',level=85,enhance=12,main=Stat('atk',360),subs=[Stat('hp',189),Stat('hp_pct',9),Stat('spd',4),Stat('crit',13)])
        a=evaluate_picture(g);b=evaluate_picture(g,c['base'])
        self.assertAlmostEqual(a['score'],41.58)
        self.assertAlmostEqual(b['score'],189/5542*100+9+8+13*1.6)

if __name__=='__main__':unittest.main()
