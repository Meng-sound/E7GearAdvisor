import unittest,tempfile,json,threading
from pathlib import Path
from resumable_sync import ResumableSync,FetchError,load_config,DEFAULT_CONFIG,CacheLock

def payload(name,spd=220):
 return {'data':[{'unitName':name,'atk':2000,'hp':15000,'def':1200,'spd':spd,'chc':85,'chd':250,'eff':0,'efr':20,'sets':{'set_speed':4,'set_cri':2},'artifactCode':'efa10'}]}

class ResumeTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.bundle=self.root/'refs.json';cfg=json.loads(DEFAULT_CONFIG.read_text(encoding='utf8'));cfg.update(interval_sec=0,jitter_sec=0);cfg['retry_500']['delay_sec']=0;cfg['backoff_403_sec']=[0,0,0,0];self.config=self.root/'config.json';self.config.write_text(json.dumps(cfg));self.now=1800000000
 def tearDown(self):self.temp.cleanup()
 def job(self,fetch):return ResumableSync(self.root,self.bundle,self.config,fetcher=fetch,clock=lambda:self.now)
 def test_cancel_then_resume_does_not_repeat_completed_hero(self):
  calls=[];cancel=threading.Event()
  def fetch(name,*_):calls.append(name);return {'status':200,'payload':payload(name),'etag':'v1'}
  def progress(data):
   if data['saved']==1:cancel.set()
  first=self.job(fetch).run(['Cermia','Beehoo'],progress,cancel);self.assertEqual(first['remaining'],1)
  second=self.job(fetch).run(['Cermia','Beehoo']);self.assertTrue(second['completed']);self.assertEqual(calls,['Cermia','Beehoo']);self.assertEqual(len(json.loads(self.bundle.read_text())['heroes']),2)
 def test_fresh_is_skipped_expired_is_conditional(self):
  calls=[]
  def fetch(name,headers,_):calls.append(headers);return {'status':200,'payload':payload(name),'etag':'v1'}
  self.job(fetch).run(['Cermia']);self.job(fetch).run(['Cermia']);self.assertEqual(len(calls),1)
  self.now+=8*86400;self.job(fetch).run(['Cermia']);self.assertEqual(calls[-1],{'If-None-Match':'v1'})
 def test_not_modified_and_unchanged_payload(self):
  self.job(lambda name,*_:{'status':200,'payload':payload(name),'etag':'v1'}).run(['Cermia'])
  self.now+=8*86400;r=self.job(lambda *_:{'status':304}).run(['Cermia']);self.assertEqual(r['unchanged'],1);self.assertTrue(r['completed'])
  self.now+=8*86400;r=self.job(lambda name,*_:{'status':200,'payload':payload(name)}).run(['Cermia']);self.assertEqual(r['unchanged'],1)
 def test_500_has_two_retries_then_commits(self):
  count=[]
  def fetch(name,*_):
   count.append(name)
   if len(count)<3:raise FetchError(500)
   return {'status':200,'payload':payload(name)}
  r=self.job(fetch).run(['Cermia']);self.assertEqual(len(count),3);self.assertTrue(r['completed'])
 def test_403_retains_pending_and_persists_cooldown(self):
  calls=[]
  def fetch(name,*_):calls.append(name);raise FetchError(403)
  r=self.job(fetch).run(['Cermia','Beehoo']);state=json.loads((self.root/'e7-hero-cache/_checkpoint.json').read_text());self.assertEqual(len(calls),3);self.assertEqual(r['remaining'],2);self.assertEqual(state['cooldown_until'],self.now+900);self.assertEqual(r['failed'],1)
 def test_recovers_raw_cache_if_aggregate_file_is_lost(self):
  self.job(lambda name,*_:{'status':200,'payload':payload(name)}).run(['Cermia']);self.bundle.unlink()
  def no_fetch(*_):raise AssertionError('should recover raw cache')
  r=self.job(no_fetch).run(['Cermia']);self.assertTrue(r['completed']);self.assertIn('Cermia',self.job(no_fetch).bundle['heroes'])
 def test_empty_samples_are_fresh_and_not_retried(self):
  calls=[]
  def fetch(name,*_):calls.append(name);return {'status':200,'payload':{'data':[]}}
  r=self.job(fetch).run(['Cermia']);self.assertEqual(r['empty'],1);self.job(fetch).run(['Cermia']);self.assertEqual(len(calls),1)
 def test_invalid_data_never_overwrites_valid_reference(self):
  self.job(lambda name,*_:{'status':200,'payload':payload(name)}).run(['Cermia']);old=self.bundle.read_bytes();self.now+=8*86400
  r=self.job(lambda *_:{'status':200,'payload':{'data':[{'bad':True}]}}).run(['Cermia']);self.assertEqual(r['failed'],1);self.assertEqual(self.bundle.read_bytes(),old)
 def test_single_writer_and_endpoint_guard(self):
  job=self.job(lambda *_:None)
  with CacheLock(job.folder/'_sync.lock'):
   with self.assertRaises(ValueError):job.run(['Cermia'])
  config=json.loads(self.config.read_text());config['endpoint']='https://example.com/telemetry';self.config.write_text(json.dumps(config))
  with self.assertRaises(ValueError):load_config(self.config)

if __name__=='__main__':unittest.main()
