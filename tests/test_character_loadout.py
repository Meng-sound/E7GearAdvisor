import copy
import unittest
from character_loadout import artifacts,artifact_stats,read_loadout_text,read_imprint_text,equipped_total


class ArtifactTests(unittest.TestCase):
    def test_artifact_levels_use_actual_base(self):
        self.assertGreater(len(artifacts()),250)
        code=next(iter(artifacts()));base=artifacts()[code]
        self.assertEqual(artifact_stats(code,0),{'atk':base['atk'],'hp':base['hp']})
        for key in ('atk','hp'):
            self.assertAlmostEqual(artifact_stats(code,30)[key],base[key]*13)
            self.assertAlmostEqual(artifact_stats(code,15)[key],base[key]*7)
    def test_level_cannot_be_guessed(self):
        code=next(iter(artifacts()))
        for level in (True,-1,31,15.5):
            with self.assertRaises(ValueError):artifact_stats(code,level)
        with self.assertRaises(ValueError):artifact_stats('unknown',30)
    def test_named_artifact_with_level(self):
        record=read_loadout_text('塔克赫尔古书 +15\n速度套装(4/4)\n命中套装(2/2)')
        self.assertEqual(record['sets'],['速度','命中'])
        self.assertEqual(record['artifact']['level'],15)
        self.assertIn('atk',record['artifact'])
    def test_unrelated_equipment_plus15_not_artifact_level(self):
        record=read_loadout_text('塔克赫尔古书\n武器 +15')
        self.assertIsNone(record['artifact']['level'])
        self.assertNotIn('atk',record['artifact'])
    def test_incomplete_set_not_activated(self):
        self.assertFalse(read_loadout_text('速度套装(3/4)')['sets'])
    def test_self_imprint_only_explicit(self):
        self.assertIsNone(read_loadout_text('SSS\n攻击力18%')['imprint'])
        self.assertIsNone(read_loadout_text('刻印效果\n攻击力18%')['imprint'])
        value=read_loadout_text('刻印集中\n攻击力 +18%')['imprint']
        self.assertEqual(value,{'key':'atk','value':18,'percent':True,'scope':'self'})


class EquippedTotalTests(unittest.TestCase):
    hero={'id':'c1','name':'角色一','name_en':'Hero One'}
    panel={'crit':100,'cdmg':350}
    def data(self):
        subs=[{'type':'AttackPercent','value':10},{'type':'HealthPercent','value':10},{'type':'DefensePercent','value':10},{'type':'Speed','value':5}]
        return {'heroes':[{'id':'owner-1','name':'Hero One'}],
                'items':[dict(id=str(i),gear=slot,equippedBy='owner-1',substats=copy.deepcopy(subs)) for i,slot in enumerate(['Weapon','Helmet','Armor','Necklace','Ring','Boots'])]}
    def test_exact_bound_items_and_overflow(self):
        data=self.data()
        self.assertEqual(equipped_total(data,self.hero,self.panel)['gear_score'],240)
        self.assertEqual(equipped_total(data,self.hero,{'crit':110,'cdmg':350})['gear_score'],224)
    def test_unbound_items_not_counted(self):
        data=self.data();data['items'][0]['equippedBy']='other'
        with self.assertRaises(ValueError):equipped_total(data,self.hero,self.panel)
    def test_duplicate_slots_or_stat_rejected(self):
        data=self.data();data['items'][0]['gear']='Boots'
        with self.assertRaises(ValueError):equipped_total(data,self.hero,self.panel)
        data=self.data();data['items'][0]['substats'][1]['type']='AttackPercent'
        with self.assertRaises(ValueError):equipped_total(data,self.hero,self.panel)
    def test_incomplete_panel_rejected(self):
        with self.assertRaises(ValueError):equipped_total(self.data(),self.hero,{'crit':100})

    def test_breakdown_and_fractional_overflow_match_reference(self):
        result=equipped_total(self.data(),self.hero,{'crit':100.5,'cdmg':350.5})
        self.assertEqual(result['gear_score'],239)
        self.assertEqual(sum(row['score'] for row in result['item_scores']),240)
        self.assertAlmostEqual(result['crit_penalty'],.8)
        self.assertAlmostEqual(result['cdmg_penalty'],.57)


class ImprintTests(unittest.TestCase):
    def test_all_panel_types_and_split_ocr_lines(self):
        for label,key,unit in [('攻击力','atk','%'),('生命值','hp','%'),('防御力','def','%'),('速度','spd',''),('暴击率','crit','%'),('暴击伤害','cdmg','%'),('效果命中','eff','%'),('效果抗性','res','%')]:
            with self.subTest(label=label):
                self.assertEqual(read_imprint_text(f'刻印集中\nSSS\n{label}\n+12{unit}'),{'key':key,'value':12.,'percent':bool(unit),'scope':'self'})
    def test_traditional_labels_and_fullwidth_symbols(self):
        self.assertEqual(read_imprint_text('刻印集中\n暴擊傷害 ＋16.8％')['value'],16.8)
        self.assertEqual(read_imprint_text('刻印集中 防禦力 ＋18％')['key'],'def')
    def test_team_section_and_conflicting_values_not_used(self):
        for text in ('刻印效果\n速度 +10','SSS\n攻击力18%','刻印集中\nSSS\n刻印释放\n攻击力18%','刻印集中\n攻击力18%\n生命值18%','刻印集中\n效果命中18','刻印集中\n速度18%'):
            with self.subTest(text=text):self.assertIsNone(read_imprint_text(text))
    def test_self_value_stops_before_team_section(self):
        self.assertEqual(read_imprint_text('刻印集中\n攻击力18%\n刻印效果\n生命值12%')['key'],'atk')


if __name__=='__main__':unittest.main()
