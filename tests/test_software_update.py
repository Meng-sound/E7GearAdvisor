import hashlib,io,json,tempfile,unittest
from pathlib import Path
from software_update import repository,version_key,check_release,download_release

class UpdateTests(unittest.TestCase):
 def test_published_repository_and_complete_zip_preferred(self):
  from software_update import DEFAULT_REPOSITORY
  self.assertEqual(DEFAULT_REPOSITORY,'Meng-sound/E7GearAdvisor')
  data=self.release();data['assets'].append({**data['assets'][0],'name':'E7GearAdvisor-Windows.zip'})
  self.assertEqual(check_release('owner/repo',reader=lambda _:json.dumps(data).encode())['asset']['name'],'E7GearAdvisor-Windows.zip')
 def test_unpublished_repository_explains_release_requirement(self):
  import urllib.error
  def unavailable(url):raise urllib.error.HTTPError(url,404,'Not Found',{},None)
  with self.assertRaisesRegex(ValueError,'尚无公开正式版本'):check_release('owner/repo',reader=unavailable)
 def release(self,body=b'MZtest'):
  return {'tag_name':'v1.0.0','html_url':'https://github.com/owner/repo/releases/tag/v1.0.0','body':'notes','assets':[{'name':'装备强化计算器.exe','size':len(body),'digest':'sha256:'+hashlib.sha256(body).hexdigest(),'browser_download_url':'https://github.com/owner/repo/releases/download/v1.0.0/app.exe'}]}
 def test_versions_repo_and_release_selection(self):
  self.assertEqual(repository('https://github.com/owner/repo.git'),'owner/repo')
  self.assertGreater(version_key('1.0.0'),version_key('1.0.0-rc.2'))
  self.assertGreater(version_key('1.0.0-rc.10'),version_key('1.0.0-rc.2'))
  result=check_release('owner/repo','1.0.0-rc.2',lambda url:json.dumps(self.release()).encode());self.assertTrue(result['newer']);self.assertEqual(result['asset']['name'],'装备强化计算器.exe')
 def test_verified_download_and_bad_hash_cleanup(self):
  body=b'MZtest';release=check_release('owner/repo','0.9.0',lambda _:json.dumps(self.release(body)).encode())
  with tempfile.TemporaryDirectory() as folder:
   path=download_release(release,folder,opener=lambda _:io.BytesIO(body));self.assertEqual(path.read_bytes(),body)
   release['tag']='v1.0.1';release['asset']['digest']='sha256:'+'0'*64
   with self.assertRaises(ValueError):download_release(release,folder,opener=lambda _:io.BytesIO(body))
   self.assertFalse(list((Path(folder)/'v1.0.1').iterdir()))
 def test_cross_repository_and_non_github_redirects_rejected(self):
  data=self.release();data['assets'][0]['browser_download_url']='https://evil.example/app.exe'
  with self.assertRaises(ValueError):check_release('owner/repo',reader=lambda _:json.dumps(data).encode())
  from software_update import safe_url
  for url in ('http://github.com/a/b','https://evil.example/x','file:///x'):
   with self.assertRaises(ValueError):safe_url(url)
 def test_manifest_required_when_digest_missing(self):
  data=self.release();data['assets'][0].pop('digest');release=check_release('owner/repo',reader=lambda _:json.dumps(data).encode())
  with tempfile.TemporaryDirectory() as folder:
   with self.assertRaises(ValueError):download_release(release,folder)
