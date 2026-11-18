import sys,json,tempfile,copy,threading,urllib.error,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import adaptation_storage as storage,threshold_settings as gates,fribbels_sync as sync
from core import Gear,Stat,SLOTS
from advice import evaluate_advice
from vision_api import clean_gear,validate_config,save_config,load_config

ROOT=Path(__file__).resolve().parents[1]

class Extensions(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.catalog=json.loads((ROOT/'data/hero-catalog.json').read_text(encoding='utf8'));self.hero=next(h for h in self.catalog['heroes'] if h['name_en']=='Cermia');gates.configure(self.root/'gates.json');storage.configure(self.root/'adapt.json')
 def tearDown(self):
  gates.configure(self.root/'absent.json');storage.configure(self.root/'absent.json');self.temp.cleanup()
 def bundle(self,weights):return {'schema':1,'heroes':{'Cermia':{'hero_id':self.hero['id'],'weights':weights,'sets':['速度']}}}
 def test_import_rollback_and_backup(self):
  src=self.root/'incoming.json';dest=self.root/'adapt.json';src.write_text(json.dumps(self.bundle({'spd':1})));storage.import_file(src,dest,self.catalog);first=dest.read_bytes()
  src.write_text(json.dumps(self.bundle({'spd':2})));storage.import_file(src,dest,self.catalog);self.assertEqual(dest.with_suffix('.previous.json').read_bytes(),first)
  current=dest.read_bytes();bad=self.bundle({'spd':float('nan')});src.write_text(json.dumps(bad))
  with self.assertRaises(ValueError):storage.import_file(src,dest,self.catalog)
  self.assertEqual(dest.read_bytes(),current);storage.configure(dest,self.catalog);self.assertEqual(storage.overrides()['Cermia']['weights']['spd'],2)
 def test_duplicate_fields_rejected(self):
  p=self.root/'bad.json';p.write_text('{"schema":1,"schema":1}')
  with self.assertRaises(ValueError):storage.read_json(p)
 def test_export_roundtrip_statistical_artifacts(self):
  row={'panel':{'atk':1400,'hp':15000,'def':1400,'spd':250,'crit':15,'cdmg':150,'eff':0,'res':200},'artifact_rates':{'ef0001':.5},'variants':[]}
  result=storage.validate_bundle({'heroes':{'Cermia':row}},self.catalog);self.assertEqual(result['heroes']['Cermia']['artifact_rates']['ef0001'],.5)
 def test_gates_change_advice_and_unknown_quality_label(self):
  g=Gear(slot='武器',grade='英雄',level=85,enhance=0,main=Stat('atk',100),subs=[Stat('atk_pct',8),Stat('crit',4),Stat('res',6)])
  self.assertEqual(evaluate_advice(g,self.hero['base'])['kind'],'enhance')
  custom=gates.current();custom['left'].update(purple=30,red=31);gates.save(self.root/'gates.json',custom)
  self.assertEqual(evaluate_advice(g,self.hero['base'])['kind'],'discard');g.grade='';self.assertIn('紫30／红31',evaluate_advice(g,self.hero['base'])['threshold_text'])
 def test_right_fixed_main_and_blue_still_blocked(self):
  g=Gear(slot='戒指',grade='史诗',level=85,enhance=0,main=Stat('atk',100),subs=[Stat('atk_pct',30),Stat('crit',8),Stat('spd',8),Stat('res',8)])
  self.assertTrue(evaluate_advice(g,self.hero['base'])['blocked_fixed_main']);g.grade='稀有';self.assertEqual(evaluate_advice(g,self.hero['base'])['kind'],'discard')
 def test_sync_stops_on_denial_and_preserves_cache(self):
  p=self.root/'cache.json';sync.save_atomic(p,{'heroes':{'Cermia':{'weights':{'spd':1}}}})
  with patch.object(sync,'fetch_reference',side_effect=urllib.error.HTTPError(sync.BUILD_URL,403,'blocked',{},None)) as fetch:
   result=sync.sync_references(['Beehoo','Setsuka'],p);self.assertEqual(fetch.call_count,1);self.assertTrue(result['stopped']);self.assertIn('Cermia',json.loads(p.read_text())['heroes'])
 def test_base_sync_rejects_error_payload_before_overwriting(self):
  p=self.root/'herodata.json';p.write_text('{"original":true}');old=p.read_bytes()
  with patch.object(sync,'fetch_json',return_value={'message':'Forbidden'}):
   with self.assertRaises(ValueError):sync.refresh_base_cache(p)
  self.assertEqual(p.read_bytes(),old)
 def test_sync_resume_skip_saved_and_cancellation(self):
  p=self.root/'cache.json';sync.save_atomic(p,{'heroes':{'Cermia':{}}})
  with patch.object(sync,'fetch_reference',return_value={'weights':{'spd':1}}) as fetch:
   result=sync.sync_references(['Cermia','Beehoo'],p);fetch.assert_called_once_with('Beehoo');self.assertEqual(result['saved'],1)
   cancel=threading.Event();cancel.set();sync.sync_references(['Setsuka'],p,cancel=cancel);self.assertEqual(fetch.call_count,1)
 def test_url_strict_and_generation_model_rejected(self):
  self.assertEqual(sync.hero_from_url('https://fribbels.github.io/e7/hero-library.html?hero=Beehoo'),'Beehoo')
  with self.assertRaises(ValueError):sync.hero_from_url('https://example.com/?hero=Beehoo')
  with self.assertRaises(ValueError):validate_config({'endpoint':'https://example.com/images/generations','model':'seedream'})
 def test_api_rejects_guessed_invalid_fields(self):
  with self.assertRaises(ValueError):clean_gear({'subs':[{'key':'spd','value':True}]})
  with self.assertRaises(ValueError):clean_gear({'subs':[{'key':'spd','value':4},{'key':'spd','value':5}]})
 def test_key_is_protected_and_roundtrip(self):
  p=self.root/'api.json';save_config(p,{'endpoint':'https://example.com/v1','model':'vision-test','api_key':'fake-secret-for-local-test'})
  self.assertNotIn('fake-secret',p.read_text());self.assertEqual(load_config(p)['api_key'],'fake-secret-for-local-test')

if __name__=='__main__':unittest.main()
