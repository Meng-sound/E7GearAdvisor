import copy,json,tempfile,unittest
from pathlib import Path
import threshold_settings as gates,scoring_settings as custom
from algorithm_modes import migrate_mode
from core import Gear,Stat
from picture_algorithm import breakdown,evaluate_picture,ROUTES
from character_bs import calculate_bs
from e7gw_source import parse_counters,counters_url
from guild_filters import attack_rows

class ModeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'gates.json';gates.configure(self.path);self.formulas=custom.current()
 def tearDown(self):
  gates.configure(Path(self.tmp.name)/'absent');custom.save(Path(self.tmp.name)/'custom.json',self.formulas);self.tmp.cleanup()
 def test_legacy_gate_migration_and_isolation_after_reload(self):
  old=copy.deepcopy(gates.DEFAULTS);old['left']['purple']=25;old['left']['red']=26;self.path.write_text(json.dumps(old));gates.configure(self.path)
  changed=gates.current('custom');changed['left']['purple']=28;changed['left']['red']=29;gates.save(self.path,changed,'custom');gates.configure(self.path)
  self.assertEqual(gates.current('gs')['left']['purple'],25);self.assertEqual(gates.current('role')['left']['purple'],25);self.assertEqual(gates.current('custom')['left']['purple'],28)
  gear=Gear(slot='武器',set_name='速度',grade='史诗',level=85,enhance=0,main=Stat('atk',100),subs=[Stat('hp_pct',24),Stat('atk_pct',1),Stat('eff',1),Stat('res',1)])
  self.assertEqual(evaluate_picture(gear,route=ROUTES[1],score_mode='gs')['kind'],'enhance')
  self.assertEqual(evaluate_picture(gear,route=ROUTES[1],score_mode='custom')['kind'],'discard')
 def test_explicit_custom_cannot_override_builtins(self):
  custom.save(Path(self.tmp.name)/'custom.json',{'enabled':True,'formulas':{'spd':'value*10'}})
  gear=Gear(subs=[Stat('spd',4)])
  self.assertEqual(breakdown(gear,score_mode='gs')[0]['score'],8);self.assertEqual(breakdown(gear,score_mode='role')[0]['score'],8);self.assertEqual(breakdown(gear,score_mode='custom')[0]['score'],40)
  self.assertEqual(migrate_mode({'score_mode':'role'},True),'custom');self.assertEqual(migrate_mode({'score_mode':'role','score_mode_schema':2},True),'role')

class BSTests(unittest.TestCase):
 def setUp(self):
  self.base={'atk':1000,'hp':5000,'def':500,'spd':100,'crit':15,'cdmg':150,'eff':0,'res':0}
  self.panel={'atk':3000,'hp':15000,'def':1000,'spd':250,'crit':100,'cdmg':300,'eff':65,'res':20}
 def test_fribbels_bs_includes_main_investment_with_known_addends(self):
  r=calculate_bs(self.panel,self.base,['速度','暴击']);self.assertAlmostEqual(r['raw_score'],1122.8);self.assertEqual(r['bs'],1122)
  r=calculate_bs(self.panel,self.base,['速度','暴击'],{'atk':100,'hp':500});self.assertEqual(r['bs'],1102)
 def test_overflow_caps_and_passive_corrections(self):
  panel={**self.panel,'crit':120,'cdmg':400};a=calculate_bs(panel,self.base,['速度']);b=calculate_bs({**panel,'crit':100,'cdmg':350},self.base,['速度']);self.assertEqual(a,b)
  corrected=calculate_bs({**self.panel,'atk':3100},self.base,corrections={'atk':100});self.assertEqual(corrected,calculate_bs(self.panel,self.base))
 def test_invalid_unknown_or_impossible_configuration(self):
  for kwargs in ({'sets':['速度','攻击']},{'sets':['未知']},{'artifact':{'atk':-1}},{'base':{**self.base,'atk':0}},{'panel':{**self.panel,'hp':float('nan')}}):
   args={'panel':self.panel,'base':self.base,**kwargs}
   with self.assertRaises(ValueError):calculate_bs(**args)

class E7GWTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.catalog=json.loads((Path(__file__).resolve().parents[1]/'data/hero-catalog.json').read_text('utf8'));cls.ids={h['name_en']:h['id'] for h in cls.catalog['heroes']};cls.defense=[cls.ids[n] for n in ('Notos','Rhianna and Luciella','Rinak')]
 def fixture(self):
  return '''<html><form><input name="d1" value="Notos"><input name="d2" value="Rhianna and Luciella"><input name="d3" value="Rinak"></form><p>e7bot report captured Nov 13, 2026 UTC (4 days ago)</p>
<table><thead><tr><th>#</th><th>OFFENSE TEAM</th><th>BATTLES</th><th>WINS</th><th>LOSSES</th><th>WIN RATE</th></tr></thead><tbody><tr data-filter-team="Setsuka|Assassin Cartuja|Lisette"><td>1</td><td>Setsuka / Assassin Cartuja / Lisette</td><td>710</td><td>710</td><td>0</td><td>100%</td></tr></tbody></table>
<div id="build-7" data-filter-team="Zio|Hecate|Birgitta"><div><a><img data-hero-tip="zio" class="size-7"></a><span class="min-w-36">Zio</span><span class="chip-gold">Top</span><span data-artifact-tip="efm32"><b>Mirrored Lotus Ring</b></span><img src="/img/sets/set_speed.png" alt="Speed"><span class="basis-full">Atk <span>5,250</span> · Spd <span>255</span></span></div></div></html>'''
 def test_observed_html_contract_without_withdrawn_community(self):
  r=parse_counters(self.fixture(),self.defense,self.catalog);self.assertEqual(r['offenses'][0]['wins'],710);self.assertEqual(r['report_date'],'2026-11-13');self.assertNotIn('members',r['offenses'][0]);self.assertEqual(r['community_solutions'],[])
 def test_structure_failure_not_empty_success(self):
  for html in ['<html>Access denied</html>',self.fixture().replace('<th>WINS</th>','<th>changed</th>'),self.fixture().replace('<td>710</td><td>0</td>','<td>700</td><td>0</td>')]:
   with self.assertRaises(ValueError):parse_counters(html,self.defense,self.catalog)
 def test_canonical_url_avoids_observed_redirect(self):
  self.assertEqual(counters_url(self.defense,self.catalog),'https://e7gw.xyz/counters?d1=Notos&d2=Rhianna%20and%20Luciella&d3=Rinak')
 def test_current_exact_defense_empty_state(self):
  html='<form><input name="d1" value="Notos"><input name="d2" value="Rhianna and Luciella"><input name="d3" value="Rinak"></form><p>No solution data for that exact defense yet.</p>'
  record=parse_counters(html,self.defense,self.catalog)
  self.assertEqual(record['offenses'],[]);self.assertTrue(record['complete']);self.assertIn('暂无',record['empty_reason'])
 def test_real_datalist_omitted_option_end_tags(self):
  options='<datalist>'+''.join(f'<option value="Hero {i}">' for i in range(400))+'</datalist>'
  record=parse_counters(self.fixture().replace('<table>',options+'<table>'),self.defense,self.catalog)
  self.assertEqual(record['offenses'][0]['wins'],710)
 def test_filter_partner_uses_canonical_hero_ids(self):
  rows={'offenses':[{'heroes':['a','b','c'],'samples':10,'wins':8,'losses':2},{'heroes':['d','e','f'],'samples':5,'wins':5,'losses':0}]}
  self.assertEqual(len(attack_rows(rows,partner=['b','x','y'])),1);self.assertEqual(attack_rows(rows,include=['c'],exclude=['b']),[])

if __name__=='__main__':unittest.main()
