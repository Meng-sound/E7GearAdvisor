import unittest,tempfile,json,io
from pathlib import Path
from PIL import Image
from cloud_ocr import Client,CloudOCR,CloudOCRError,normalize,volc_headers,aliyun_headers,DEFAULTS,save_profiles,load_profiles

class CloudTests(unittest.TestCase):
 def config(self,provider):return {**DEFAULTS[provider],'access_key':'fake-ak','secret_key':'fake-secret'}
 def image(self):
  buffer=io.BytesIO();Image.new('RGB',(100,50)).save(buffer,format='PNG');return buffer.getvalue()
 def test_volc_uses_official_form_and_signs_without_exposing_secret(self):
  calls=[]
  def transport(url,body,headers):calls.append((url,body,headers));return {'code':10000,'data':{'line_texts':['速度6'],'line_rects':[{'x':10,'y':20,'width':60,'height':15}],'line_probs':[.99]}}
  result=Client('volcengine',self.config('volcengine'),transport).recognize(self.image());self.assertEqual(result['lines'][0]['words'][0]['x'],10);url,body,headers=calls[0];self.assertIn('Action=OCRNormal',url);self.assertIn(b'image_base64=',body);self.assertNotIn('fake-secret',str(headers));self.assertIn('/cn-north-1/cv/request',headers['Authorization'])
 def test_baidu_token_cached_and_high_accuracy_location_preserved(self):
  calls=[]
  def transport(url,body,headers):
   calls.append(url)
   if 'oauth' in url:return {'access_token':'fake-token','expires_in':3600}
   return {'words_result':[{'words':'攻击力19%','location':{'left':10,'top':20,'width':100,'height':30},'probability':{'average':.98}}]}
  client=Client('baidu',self.config('baidu'),transport);result=client.recognize(self.image());client.recognize(self.image());self.assertEqual(sum('oauth' in url for url in calls),1);self.assertIn('/accurate?',calls[-1]);self.assertTrue(result['positions_available']);self.assertEqual(result['lines'][0]['words'][0]['w'],100)
 def test_baidu_basic_does_not_invent_coordinates(self):
  result=normalize('baidu',{'words_result':[{'words':'速度6'}]});self.assertFalse(result['positions_available']);self.assertEqual(result['lines'][0]['words'],[])
 def test_aliyun_binary_body_and_string_data(self):
  calls=[]
  def transport(url,body,headers):calls.append((url,body,headers));return {'Data':json.dumps({'prism_wordsInfo':[{'word':'暴击率8%','prob':99,'pos':[{'x':2,'y':3},{'x':82,'y':3},{'x':82,'y':23},{'x':2,'y':23}]}]})}
  raw=self.image();r=Client('aliyun',self.config('aliyun'),transport).recognize(raw);self.assertEqual(calls[0][1],raw);self.assertEqual(calls[0][2]['x-acs-action'],'RecognizeAdvanced');self.assertEqual(r['lines'][0]['words'][0]['h'],20)
 def test_credentials_encrypted_at_rest(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'cloud.json';profiles={provider:self.config(provider) for provider in DEFAULTS};save_profiles(p,profiles);self.assertNotIn('fake-ak',p.read_text());self.assertNotIn('fake-secret',p.read_text());self.assertEqual(load_profiles(p)['baidu']['secret_key'],'fake-secret')
 def test_service_error_does_not_echo_secret_or_raw_response(self):
  client=Client('aliyun',self.config('aliyun'),lambda *_:{'Code':'Forbidden','Message':'fake-secret arbitrary response'})
  with self.assertRaises(CloudOCRError) as error:client.recognize(self.image())
  self.assertNotIn('fake-secret',str(error.exception))
 def test_cloud_cache_avoids_repeat_requests(self):
  calls=[]
  def transport(*_):calls.append(1);return {'code':10000,'data':{'line_texts':[]}}
  ocr=CloudOCR('volcengine',self.config('volcengine'),transport);image=Image.new('RGB',(100,50));ocr.read_image(image);ocr.read_image(image);self.assertEqual(len(calls),1)
 def test_signatures_are_deterministic_and_bind_payload(self):
  config=self.config('volcengine');one=volc_headers(config,b'a','20260101T000000Z');two=volc_headers(config,b'b','20260101T000000Z');self.assertNotEqual(one['Authorization'],two['Authorization']);self.assertEqual(one,volc_headers(config,b'a','20260101T000000Z'))
  config=self.config('aliyun');one=aliyun_headers(config,b'a','2026-01-01T00:00:00Z','nonce');two=aliyun_headers(config,b'b','2026-01-01T00:00:00Z','nonce');self.assertNotEqual(one['Authorization'],two['Authorization'])

if __name__=='__main__':unittest.main()
