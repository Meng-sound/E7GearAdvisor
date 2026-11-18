import copy,json,tempfile,unittest
from pathlib import Path
from build_reference import merge_reference_snapshot,configure_cache,references,primary_reference
from resumable_sync import ResumableSync,DEFAULT_CONFIG

class ReferenceMigrationTests(unittest.TestCase):
 def test_equal_or_older_legacy_cache_cannot_erase_complete_snapshot(self):
  base={'updated_at':'2026-11-16T12:00:00Z','gear_score':431,'panel':{'atk':3882},'variants':[{'panel':{'atk':3882},'gear_score':431}]}
  legacy=copy.deepcopy(base);legacy.pop('gear_score');legacy['variants'][0].pop('gear_score')
  self.assertEqual(merge_reference_snapshot(base,legacy),base)
  legacy['updated_at']='2026-11-15T12:00:00Z';self.assertEqual(merge_reference_snapshot(base,legacy),base)
 def test_newer_cache_is_a_coherent_snapshot_not_mixed_with_old_scores(self):
  base={'updated_at':'2026-11-16T12:00:00Z','gear_score':431,'panel':{'atk':3882}}
  current={'updated_at':'2026-11-17T12:00:00Z','panel':{'atk':4000}}
  self.assertEqual(merge_reference_snapshot(base,current),current)
 def test_shipped_laika_score_works_without_any_user_cache(self):
  try:
   with tempfile.TemporaryDirectory() as folder:
    configure_cache(Path(folder)/'missing.json');record=primary_reference(references()['heroes']['Architect Laika'])
    self.assertEqual(record['gear_score'],431)
  finally:configure_cache(Path('nonexistent-test-cache.json'))
 def test_same_payload_and_304_upgrade_legacy_stored_summaries(self):
  for status in (200,304):
   with self.subTest(status=status),tempfile.TemporaryDirectory() as folder:
    root=Path(folder);bundle=root/'references.json';config=root/'sync.json';settings=json.loads(DEFAULT_CONFIG.read_text('utf8'));settings.update(interval_sec=0,jitter_sec=0);config.write_text(json.dumps(settings),'utf8')
    row={'unitName':'Test','atk':2000,'hp':10000,'def':1000,'spd':200,'chc':100,'chd':250,'eff':0,'efr':0,'gs':455,'sets':{'set_speed':4},'artifactCode':'efm34'}
    response={'status':200,'payload':{'data':[row]},'etag':'v1'}
    make=lambda fetch:ResumableSync(root,bundle,config,fetcher=fetch,clock=lambda:1800000000)
    make(lambda *_:response).run(['Test'])
    old=json.loads(bundle.read_text('utf8'));old['heroes']['Test'].pop('gear_score');bundle.write_text(json.dumps(old),'utf8')
    result=make(lambda *_:response if status==200 else {'status':304}).run(['Test'],force=True)
    self.assertEqual(result['unchanged'],1);self.assertEqual(json.loads(bundle.read_text('utf8'))['heroes']['Test']['gear_score'],455)
