import gzip,json,tempfile,unittest,hashlib
from pathlib import Path
from fribbels_sync import aggregate
from build_reference import configure_cache,references
import adaptation_storage

class ReferenceScoreTests(unittest.TestCase):
 def rows(self):
  base={'atk':3000,'hp':10000,'def':1000,'spd':200,'chc':100,'chd':250,'eff':0,'efr':0,'unitName':'Test'}
  return [{**base,'gs':450+2*i,'sets':{'set_speed':4},'artifactCode':'efm34'} for i in range(6)]+[{**base,'gs':400+2*i,'sets':{'set_counter':4},'artifactCode':'efm01'} for i in range(6)]
 def test_scores_and_artifacts_are_grouped_with_the_same_cohort(self):
  result=aggregate('Test',{'data':self.rows()})
  bysets={tuple(v['sets']):v for v in result['variants']}
  self.assertEqual(bysets[('速度',)]['gear_score'],455)
  self.assertEqual(bysets[('反击',)]['gear_score'],405)
  self.assertEqual(bysets[('速度',)]['artifact_rates'],{'efm34':1})
  self.assertEqual(bysets[('反击',)]['artifact_rates'],{'efm01':1})
  clean=adaptation_storage.record(result,'Test');self.assertEqual(clean['variants'][0]['gear_score_samples'],6)
 def test_bad_or_missing_score_does_not_become_zero_or_bs(self):
  rows=self.rows()[:6]
  for row,value in zip(rows,[None,True,float('nan'),-1,'455',float('inf')]):row['gs']=value;row['bs']=999
  result=aggregate('Test',{'data':rows})
  self.assertNotIn('gear_score',result);self.assertNotIn('gear_score',result['variants'][0])
 def test_old_summary_is_enriched_from_local_raw_cache_without_writing(self):
  try:
   with tempfile.TemporaryDirectory() as folder:
    root=Path(folder);cache=root/'hero-library-cache.json';rawdir=root/'e7-hero-cache';rawdir.mkdir()
    cache.write_text(json.dumps({'heroes':{'Test':{'sample_count':12,'updated_at':'2026-10-01','panel':{'atk':1}}}}),'utf8');before=cache.read_bytes()
    path=rawdir/(hashlib.sha256(b'Test').hexdigest()[:32]+'.json.gz')
    with gzip.open(path,'wt',encoding='utf8') as f:json.dump({'hero':'Test','payload':{'data':self.rows()}},f)
    configure_cache(cache);result=references()['heroes']['Test']
    self.assertEqual(result['updated_at'],'2026-10-01');self.assertIn('gear_score',result)
    self.assertEqual(cache.read_bytes(),before)
  finally:configure_cache(Path('nonexistent-test-cache.json'))
