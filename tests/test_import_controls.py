import tempfile,unittest
from pathlib import Path
import local_json
from fribbels_sync import aggregate
from guild_war import validate_bundle
class ImportControls(unittest.TestCase):
 def test_size_limit_before_parse_and_large_valid_file(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);config=root/'settings.json';source=root/'payload.json'
   source.write_text(' '* (11*1024*1024)+'{"schema":1}','utf8')
   local_json.save_limit(config,10)
   with self.assertRaises(ValueError):local_json.read_json(source)
   local_json.save_limit(config,100);self.assertEqual(local_json.read_json(source),{'schema':1})
   for invalid in (0,257,True,100.5):
    with self.assertRaises(ValueError):local_json.save_limit(config,invalid)
   local_json.configure(root/'missing.json')
 def test_duplicate_nonfinite_or_deep_json_does_not_pass(self):
  with tempfile.TemporaryDirectory() as folder:
   source=Path(folder)/'payload.json'
   for data in ('{"a":1,"a":2}','{"score":NaN}','['*2000+']'*2000):
    source.write_text(data,'utf8')
    with self.assertRaises(ValueError):local_json.read_json(source)
 def test_reference_gs_follows_upstream_overflow_correction(self):
  row={'atk':3000,'hp':12000,'def':1000,'spd':250,'chc':120,'chd':400,'eff':0,'efr':0,'gs':450,'sets':{'set_speed':4},'unitName':'Example'}
  result=aggregate('Example',{'data':[row]*6});self.assertEqual(result['gear_score'],361)
 def test_imported_community_cannot_open_external_schemes(self):
  data={'defense':['c1','c2','c3'],'community_solutions':[{'heroes':['c4','c5','c6'],'members':[],'source_url':'file:///C:/unrelated.exe'}]}
  with self.assertRaises(ValueError):validate_bundle(data)
