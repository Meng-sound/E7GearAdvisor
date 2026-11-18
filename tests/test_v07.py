import unittest,sys
from pathlib import Path
from copy import deepcopy
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Gear,Stat,SETS
from picture_algorithm import breakdown
from advice import evaluate_advice
from panel_reader import augment_names,color_grade
class V07Tests(unittest.TestCase):
    def gear(self):return Gear(slot='武器',set_name='反击',level=85,enhance=12,grade='史诗',main=Stat('atk',360),subs=[Stat('hp',189),Stat('hp_pct',9),Stat('spd',4),Stat('crit',13)])
    def test_gs_independent_of_hero_or_invalid_bases(self):
        g=self.gear()
        a=sum(x['score'] for x in breakdown(g,{'hp':5000},'gs'))
        b=sum(x['score'] for x in breakdown(g,{'hp':9000},'gs'))
        c=sum(x['score'] for x in breakdown(g,{'hp':'unused'},'gs'))
        self.assertAlmostEqual(a,189*3.09/174+9+8+13*1.6)
        self.assertEqual(a,b);self.assertEqual(b,c)
        self.assertNotEqual(sum(x['score'] for x in breakdown(g,{'hp':5000})),sum(x['score'] for x in breakdown(g,{'hp':9000})))
    def test_quality_and_set_missing_do_not_block_advice(self):
        g=self.gear();g.grade='';g.set_name=''
        r=evaluate_advice(g)
        self.assertFalse(r['errors']);self.assertEqual(r['kind'],'backup');self.assertAlmostEqual(r['score'],41.58)
        g.enhance=None;g.slot=''
        r=evaluate_advice(g)
        self.assertEqual(r['kind'],'conditional');self.assertTrue(r['reasons']);self.assertFalse(r['errors'])
    def test_inventory_stats(self):
        g=Gear(slot='铠甲',level=85,enhance=15,grade='史诗',main=Stat('def',300),subs=[Stat('hp_pct',22),Stat('def_pct',19),Stat('spd',3),Stat('eff',7)])
        for mode in ('role','gs'):
            r=evaluate_advice(g,score_mode=mode);self.assertEqual(r['score'],54);self.assertEqual(r['kind'],'reforge')
    def test_new_set_and_slot_names(self):
        from set_icons import canonical
        for name in ['开战','弱化','全力','回击','激流','穿透','追击']:
            self.assertIn(canonical(name),SETS)
            self.assertEqual(augment_names(Gear(),'传说靴子\n'+name+'套装(4/4)').set_name,canonical(name))
        self.assertEqual(augment_names(Gear(),'傳說鎧甲\n回擊套裝(4/4)').slot,'铠甲')
        self.assertEqual(augment_names(Gear(),'英雄盔甲\n未知新套装').set_name,'未知新')
    def test_icon_color_classifier(self):
        for color,grade in [((150,20,10),'史诗'),((150,20,140),'英雄'),((20,80,170),'稀有'),((20,120,40),'')]:
            self.assertEqual(color_grade(Image.new('RGB',(120,120),color),(0,0,120,120)),grade)
if __name__=='__main__':unittest.main()
