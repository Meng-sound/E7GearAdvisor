import tempfile,unittest,urllib.error,urllib.parse,uuid
from pathlib import Path
from unittest.mock import patch
from ep7_gw_source import fetch_ep7,client_key,read_public_json

class EP7Tests(unittest.TestCase):
 def setUp(self):
  self.catalog={'heroes':[{'id':'c'+str(i)} for i in range(1,130)]};self.defense=['c3','c1','c2']
 def row(self,start=4,**extra):return {'defenseHeroes':['c2','c3','c1'],'attackHeroes':['c'+str(i) for i in range(start,start+3)],'wins':212,'losses':8,'draws':1,'totalMatches':221,'updatedAt':'2026-10-21T00:47:03.498559',**extra}
 def page(self,rows,number=0,last=True,total=None):return {'content':rows,'number':number,'numberOfElements':len(rows),'last':last,'totalElements':len(rows) if total is None else total}
 def test_exact_ids_query_and_attack_perspective_counts(self):
  calls=[]
  def read(url,headers):calls.append((url,headers));return self.page([self.row()])
  record=fetch_ep7(self.defense,self.catalog,'stable-client',read);row=record['offenses'][0]
  self.assertEqual((row['wins'],row['losses'],row['draws'],row['samples']),(212,8,1,221))
  params=urllib.parse.parse_qs(urllib.parse.urlsplit(calls[0][0]).query)
  self.assertEqual(params['defenseHeroIds'],['c1','c2','c3']);self.assertEqual(params['minMatches'],['1'])
  self.assertEqual(calls[0][1],{'X-EP7-Client-Key':'stable-client'})
  self.assertEqual(record['date_kind'],'统计快照');self.assertNotIn('last_match',record)
 def test_all_pages_read_with_same_identity(self):
  calls=[]
  def read(url,headers):
   page=int(urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)['page'][0]);calls.append(headers)
   rows=[self.row(4+i*3) for i in range(30)] if page==0 else [self.row(94)]
   return self.page(rows,page,page==1,31)
  record=fetch_ep7(self.defense,self.catalog,'same-client',read)
  self.assertEqual(len(record['offenses']),31);self.assertTrue(record['complete']);self.assertEqual(calls,[calls[0]]*2)
 def test_response_error_is_not_empty_result(self):
  for data in ({'error':'down'},self.page([],total=1),self.page([self.row(totalMatches=999)]),self.page([self.row(attackHeroes=['unknown','c5','c6'])])):
   with self.subTest(data=data),self.assertRaises((ValueError,KeyError)):fetch_ep7(self.defense,self.catalog,'same',lambda *_:data)
 def test_wrong_defense_never_becomes_exact_counter(self):
  result=fetch_ep7(self.defense,self.catalog,'same',lambda *_:self.page([self.row(defenseHeroes=['c1','c2','c9'])]))
  self.assertEqual(result['offenses'],[])
 def test_duplicate_aggregate_is_never_added_twice(self):
  with self.assertRaisesRegex(ValueError,'重复'):fetch_ep7(self.defense,self.catalog,'same',lambda *_:self.page([self.row(),self.row()]))
 def test_genuine_empty_response_is_complete(self):
  record=fetch_ep7(self.defense,self.catalog,'same',lambda *_:self.page([]))
  self.assertEqual(record['offenses'],[]);self.assertTrue(record['complete'])
 def test_guest_identity_is_persistent_and_not_rotated_on_corruption(self):
  with tempfile.TemporaryDirectory() as folder:
   first=client_key(folder);uuid.UUID(first);self.assertEqual(first,client_key(folder))
   path=Path(folder)/'ep7-public-client-id.txt';path.write_text('invalid','ascii')
   with self.assertRaises(ValueError):client_key(folder)
   self.assertEqual(path.read_text('ascii'),'invalid')
 def test_quota_error_is_not_retried(self):
  from types import SimpleNamespace
  from unittest.mock import Mock
  opener=SimpleNamespace(open=Mock(side_effect=urllib.error.HTTPError('https://ep7guildwar.duckdns.org/api/v1/matchups',429,'Quota',{},None)))
  with patch('ep7_gw_source.urllib.request.build_opener',return_value=opener),self.assertRaisesRegex(ValueError,'额度'):read_public_json('https://ep7guildwar.duckdns.org/api/v1/matchups',{'X-EP7-Client-Key':'same'})
  self.assertEqual(opener.open.call_count,1)
 def test_identity_header_never_sent_to_other_hosts(self):
  with self.assertRaises(ValueError):read_public_json('https://other.example/api/v1/matchups',{'X-EP7-Client-Key':'same'})
