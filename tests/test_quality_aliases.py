import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from quality_profiles import QUALITY_PROFILES,QUALITY_NAMES,infer_quality
from official_rolls import distribution
from hero_picker import load_catalog,search_heroes
ROOT=Path(__file__).resolve().parents[1]

class QualityAliases(unittest.TestCase):
    def test_color_and_level_profiles(self):
        self.assertTrue({'红85','紫85','红88','紫88','红90','紫90','蓝85'}.issubset(QUALITY_NAMES))
        for name,p in QUALITY_PROFILES.items():
            self.assertEqual(p['level'],int(name[1:]))
            if name[0] in {'红','紫'}:
                self.assertEqual(p['grade'],'英雄' if name[0]=='紫' else '史诗')
                self.assertEqual(infer_quality(p['level'],p['grade']),name)
        self.assertTrue(QUALITY_PROFILES['红90']['reforged'])
        self.assertTrue(QUALITY_PROFILES['紫90']['reforged'])

    def test_88_never_guessed_from_level(self):
        self.assertEqual(infer_quality(88,'史诗'),'红88')
        self.assertEqual(infer_quality(88,'英雄'),'紫88')
        self.assertIsNone(distribution(88,'史诗','hp_pct',QUALITY_PROFILES['红88']['roll_profile']))

    def test_player_nicknames_and_ambiguity(self):
        heroes=load_catalog(ROOT/'data/hero-catalog.json')['heroes']
        for query,english in [('水扇','Seaside Bellona'),('暗法','Specter Tenebria'),('光大姐','Conqueror Lilias'),('女帝','Harsetti'),('迪彩','Lisette'),('夏娜','Cermia'),('光夏娜','Lionheart Cermia'),('SSB','Seaside Bellona')]:
            with self.subTest(query=query):self.assertEqual(search_heroes(heroes,query)[0]['name_en'],english)
        self.assertEqual(search_heroes(heroes,'幻影的泰妮布里雅')[0]['name_en'],'Specter Tenebria')
        self.assertGreaterEqual(len(search_heroes(heroes,'水镰')),2)

if __name__=='__main__':unittest.main()
