import unittest
from e7wiki_source import BASE,fetch_e7wiki,read_public_json
from guild_filters import guide_rows

class WikiGuideTests(unittest.TestCase):
 def setUp(self):
  self.catalog={'heroes':[{'id':'c'+str(i)} for i in range(1,8)]}
  self.cards=[{'face_id':'c'+str(i),'code':'hero-'+str(i)} for i in range(1,8)]
  self.row={'id':842,'defenseHero1':'hero-3','defenseHero2':'hero-1','defenseHero3':'hero-2','offenseHero1':'hero-6','offenseHero2':'hero-4','offenseHero3':'hero-5','win':0,'lose':0,'author':'投稿作者','equipment':'装备甲\\n装备乙','artifact':'神器甲','strategy':'先手打法','note':'注意事项','updateTime':'2026-08-06 15:49:53'}
 def response(self,rows,page=1,total=None):return {'code':1000,'data':{'list':rows,'pagination':{'page':page,'size':50,'total':len(rows) if total is None else total}}}
 def reader(self,url,body=None):return {'code':1000,'data':self.cards} if url.endswith('card-list') else self.response([self.row])
 def test_face_ids_map_to_site_slugs_and_zero_feedback_does_not_hide_guide(self):
  calls=[]
  def reader(url,body=None):calls.append((url,body));return self.reader(url,body)
  record=fetch_e7wiki(['c3','c2','c1'],self.catalog,reader)
  self.assertEqual(calls[1][1]['keyWord'],'hero-1,hero-2,hero-3');self.assertEqual(calls[1][1]['searchType'],'defense')
  self.assertEqual(record['record_kind'],'community_guides');self.assertEqual(record['offenses'],[])
  guide=record['guides'][0];self.assertEqual(guide['heroes'],['c6','c4','c5']);self.assertEqual(guide['feedback_wins'],0)
  self.assertNotIn('samples',guide);self.assertNotIn('wins',guide);self.assertNotIn('last_match',record)
  self.assertEqual(guide['equipment'],'装备甲\n装备乙');self.assertEqual(guide['author'],'投稿作者')
  self.assertEqual(len(guide_rows(record)),1)
 def test_filters_and_cross_round_exclusions_still_apply(self):
  record=fetch_e7wiki(['c1','c2','c3'],self.catalog,self.reader)
  self.assertEqual(len(guide_rows(record,include=['c4'])),1)
  self.assertEqual(guide_rows(record,include=['c7']),[]);self.assertEqual(guide_rows(record,exclude=['c4']),[]);self.assertEqual(guide_rows(record,partner=['c5']),[])
 def test_pages_preserve_individual_authors_and_do_not_sum_feedback(self):
  def reader(url,body=None):
   if url.endswith('card-list'):return self.reader(url)
   page=body['page'];items=[{**self.row,'id':i} for i in (range(1,51) if page==1 else [51])]
   return self.response(items,page,51)
  record=fetch_e7wiki(['c1','c2','c3'],self.catalog,reader);self.assertEqual(len(record['guides']),51)
 def test_empty_is_different_from_api_error_or_truncated_page(self):
  def read(payload):return lambda url,body=None:self.reader(url) if body is None else payload
  empty=fetch_e7wiki(['c1','c2','c3'],self.catalog,read(self.response([])));self.assertEqual(empty['guides'],[])
  for payload in ({'code':401,'data':{'list':[]}},self.response([],total=1),{'code':1000,'data':{'rows':[]}}):
   with self.subTest(payload=payload),self.assertRaises((ValueError,KeyError)):fetch_e7wiki(['c1','c2','c3'],self.catalog,read(payload))
 def test_other_defense_and_unknown_heroes_are_not_displayed(self):
  for row in ({**self.row,'defenseHero1':'hero-7'},{**self.row,'offenseHero1':'unknown'}):
   with self.assertRaises(ValueError):fetch_e7wiki(['c1','c2','c3'],self.catalog,lambda u,b=None:self.reader(u) if b is None else self.response([row]))
 def test_missing_or_ambiguous_site_mapping_is_not_guessed(self):
  for cards in (self.cards[1:],self.cards+[{'face_id':'c1','code':'another-hero'}]):
   with self.assertRaises(ValueError):fetch_e7wiki(['c1','c2','c3'],self.catalog,lambda *_:{'code':1000,'data':cards})
 def test_feedback_votes_cannot_be_posted_through_reader(self):
  for url in (BASE+'gvg_homework/win_or_lose','https://other.example/api'):
   with self.assertRaises(ValueError):read_public_json(url,{'id':842,'type':'win'})
