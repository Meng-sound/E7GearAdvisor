import io,json,tempfile,threading,unittest
from pathlib import Path
from PIL import Image
from skin_sync import update,manifest,blob_sha,TREE_URL
class SkinSyncTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name);self.bundled=self.folder/'bundled';self.bundled.mkdir();self.dest=self.folder/'user';self.catalog={'heroes':[{'id':'c1001'},{'id':'c1002'}]};self.files={}
  for i in (1,2):
   stream=io.BytesIO();Image.new('RGB',(64,64),(i*30,0,50)).save(stream,format='PNG');self.files[f'c100{i}_s01_s.png']=stream.getvalue()
  self.payload={'sha':'a'*40,'truncated':False,'tree':[{'path':'data/cachedimages/'+name,'sha':blob_sha(raw),'size':len(raw),'type':'blob'} for name,raw in self.files.items()]}
 def tearDown(self):self.temp.cleanup()
 def reader(self,url,limit):
  if url==TREE_URL:return json.dumps(self.payload).encode()
  return self.files[url.rsplit('/',1)[-1]]
 def test_skip_bundled_and_resume_only_missing(self):
  name=next(iter(self.files));(self.bundled/name).write_bytes(self.files[name]);first=update(self.catalog,self.bundled,self.dest,reader=self.reader);self.assertEqual((first['saved'],first['skipped']),(1,1))
  calls=[]
  def read(url,limit):calls.append(url);return self.reader(url,limit)
  second=update(self.catalog,self.bundled,self.dest,reader=read);self.assertEqual(second['saved'],0);self.assertEqual(calls,[TREE_URL])
 def test_interruption_preserves_first_file(self):
  cancel=threading.Event()
  def progress(done,*args):cancel.set()
  first=update(self.catalog,self.bundled,self.dest,progress,cancel,self.reader);self.assertTrue(first['cancelled']);self.assertEqual(first['saved'],1)
  second=update(self.catalog,self.bundled,self.dest,reader=self.reader);self.assertEqual((second['saved'],second['skipped']),(1,1))
 def test_corrupted_hash_never_replaces_existing(self):
  self.dest.mkdir();name=next(iter(self.files));old=b'original-keep';(self.dest/name).write_bytes(old)
  def read(url,limit):return self.reader(url,limit) if url==TREE_URL else b'bad'
  with self.assertRaises(ValueError):update(self.catalog,self.bundled,self.dest,reader=read)
  self.assertEqual((self.dest/name).read_bytes(),old)
 def test_truncated_or_traversal_manifest_not_used(self):
  with self.assertRaises(ValueError):manifest({**self.payload,'truncated':True},self.catalog)
  bad={**self.payload,'tree':[{'path':'data/cachedimages/../c1001_s01_s.png'}]};self.assertEqual(manifest(bad,self.catalog)[1],[])
