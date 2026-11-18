import tempfile,unittest,urllib.parse
from guild_war import fetch_fribbels,fribbels_team_url
from guild_war import normalize_rows,team_key,validate_bundle,GWStore,fetch_ark

class GWTests(unittest.TestCase):
 def test_fribbels_body_and_win_loss_match_official_frontend(self):
  calls=[]
  def reader(url,headers,body):
   calls.append((url,body));return {'data':{'c6,c4,c5':{'w':738,'l':7}}}
  record=fetch_fribbels(['c3','c1','c2'],reader)
  self.assertEqual(calls[0][1],b'c1,c2,c3');self.assertTrue(calls[0][0].endswith('/getDef'))
  self.assertEqual(record['offenses'][0]['wins'],738);self.assertEqual(record['offenses'][0]['losses'],7)
 def test_fribbels_null_data_is_no_results_but_bad_response_is_error(self):
  for payload in ({'data':None},{'data':{}}):self.assertEqual(fetch_fribbels(['c1','c2','c3'],lambda *_:payload)['offenses'],[])
  for payload in ({'error':'upstream failed'},{'data':'error'}):
   with self.assertRaises(ValueError):fetch_fribbels(['c1','c2','c3'],lambda *_:payload)
 def test_fribbels_web_url_uses_names_not_artwork_or_hero_ids(self):
  url=fribbels_team_url(['c3','c1','c2'],self.catalog())
  self.assertEqual(urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)['def'],['Hero 1,Hero 2,Hero 3'])
 def catalog(self):return {'heroes':[{'id':'c'+str(i),'name_en':'Hero '+str(i)} for i in range(1,10)]}
 def row(self,outcome='loss',identity=1):
  return {'id':identity,'defense_hero1':'Hero 1','defense_hero2':'Hero 2','defense_hero3':'Hero 3','offense_hero1':'Hero 4','offense_hero2':'Hero 5','offense_hero3':'Hero 6','outcome':outcome,'match_timestamp':'2025-09-15T00:00:00Z'}
 def test_defense_perspective_is_inverted_and_team_order_is_irrelevant(self):
  rows=[self.row('loss',1),self.row('loss',2),self.row('win',3),self.row('draw',4)]
  result=normalize_rows(rows,['c3','c1','c2'],self.catalog())
  self.assertEqual((result['offenses'][0]['wins'],result['offenses'][0]['losses'],result['offenses'][0]['draws']),(2,1,1))
 def test_duplicates_unknown_results_and_other_defenses_are_not_counted(self):
  other={**self.row(identity=3),'defense_hero1':'Hero 9'}
  result=normalize_rows([self.row(),self.row(),self.row('unknown',2),other],['c1','c2','c3'],self.catalog())
  self.assertEqual(result['offenses'][0]['samples'],1);self.assertEqual(result['invalid_rows'],1)
 def test_invalid_counts_and_duplicate_hero_teams_are_rejected(self):
  for bad in (True,-1,1.5,'417'):
   with self.assertRaises(ValueError):validate_bundle({'defense':['c1','c2','c3'],'offenses':[{'heroes':['c4','c5','c6'],'wins':bad,'losses':0}]})
  with self.assertRaises(ValueError):team_key(['c1','c1','c2'])
 def test_paging_and_exact_server_filter(self):
  calls=[]
  def read(url,headers):
   params=urllib.parse.parse_qs(urllib.parse.urlsplit(url).query);calls.append(params)
   if params['offset']==['0']:return [self.row(identity=i) for i in range(1000)]
   return [self.row('win',1001)]
  result=fetch_ark(['c1','c2','c3'],self.catalog(),reader=read)
  self.assertEqual(result['offenses'][0]['samples'],1001);self.assertEqual(len(calls),2)
  self.assertEqual(calls[0]['defense_hero1'],['in.("Hero 1","Hero 2","Hero 3")'])
  self.assertIn('outcome',calls[0]['select'][0]);self.assertNotIn('email',calls[0]['select'][0])
 def test_cache_is_separate_for_provider_and_defense(self):
  with tempfile.TemporaryDirectory() as folder:
   store=GWStore(folder);record=normalize_rows([self.row()],['c1','c2','c3'],self.catalog())
   store.save(record,'Ark');self.assertIsNotNone(store.load(['c3','c2','c1'],'Ark'))
   self.assertIsNone(store.load(['c1','c2','c3'],'Local'));self.assertIsNone(store.load(['c1','c2','c9'],'Ark'))
 def test_no_results_remains_empty_not_fabricated_zero_teams(self):
  result=normalize_rows([],['c1','c2','c3'],self.catalog());self.assertEqual(result['offenses'],[])
