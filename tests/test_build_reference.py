import unittest,sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from build_reference import panel_weights,enrich_profiles,references
from core import Gear,Stat
from hero_picker import load_catalog,filter_heroes
ROOT=Path(__file__).resolve().parents[1]

class BuildReferenceTests(unittest.TestCase):
    def test_noncrit_panel_does_not_value_crit(self):
        base={'atk':800,'hp':5000,'def':600,'spd':100,'crit':15,'cdmg':150,'eff':0,'res':0}
        w=panel_weights({'atk':1100,'hp':20000,'def':1500,'spd':220,'crit':15,'cdmg':150,'eff':0,'res':200},base,['速度','抵抗'])
        self.assertEqual(w['crit'],0);self.assertEqual(w['cdmg'],0);self.assertGreater(w['res'],0);self.assertGreater(w['hp_pct'],0)

    def test_references_are_anonymous_aggregates(self):
        data=references();self.assertIn('Abyssal Yufine',data['heroes'])
        ref=data['heroes']['Abyssal Yufine'];self.assertGreater(ref['sample_count'],100)
        self.assertGreater(ref['set_rates']['吸血'],.5)
        self.assertNotIn('artifactCode',ref);self.assertNotIn('unitName',ref)

    def test_custom_profile_has_priority(self):
        catalog=load_catalog(ROOT/'data/hero-catalog.json')
        h={'name':'Abyssal Yufine','archetype':'生存辅助','sets':['抵抗'],'custom_profile':True}
        profiles=enrich_profiles([h],catalog,Gear(set_name='吸血'))
        actual=next(p for p in profiles if p['name']==h['name']);self.assertEqual(actual['sets'],['抵抗']);self.assertNotIn('weights',actual)

    def test_sources_do_not_mutate_gear_or_catalog(self):
        catalog=load_catalog(ROOT/'data/hero-catalog.json');before=json.dumps(catalog,ensure_ascii=False)
        g=Gear(set_name='吸血',subs=[Stat('def_pct',20),Stat('crit',10)]);original=g.to_dict()
        rows=enrich_profiles([],catalog,g);h=next(h for h in rows if h['name']=='Abyssal Yufine')
        self.assertGreater(h['weights']['def_pct'],h['weights']['eff']);self.assertEqual(g.to_dict(),original)
        self.assertEqual(json.dumps(catalog,ensure_ascii=False),before)

if __name__=='__main__':unittest.main()
