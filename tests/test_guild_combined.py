import threading,unittest
from guild_combined import fetch_combined,merge_records

class CombinedTests(unittest.TestCase):
 def record(self,rows=(),**extra):return {'defense':['c1','c2','c3'],'offenses':list(rows),'source':'source','source_url':'https://example.org','complete':True,**extra}
 def row(self,team=('c4','c5','c6'),wins=90,losses=10):return {'heroes':list(team),'wins':wins,'losses':losses,'draws':0,'samples':wins+losses}
 def test_duplicate_teams_keep_each_source_counts_without_summing(self):
  a=self.record([self.row()],source='A');b=self.record([self.row(wins=110,losses=10)],source='B')
  record=merge_records(['c1','c2','c3'],[('A',a),('B',b)])
  row=record['offenses'][0];self.assertEqual(len(record['offenses']),1);self.assertEqual(row['samples'],120);self.assertEqual(row['wins'],110)
  self.assertEqual([r['samples'] for r in row['source_stats']],[120,100]);self.assertEqual(row['display_source'],'B')
 def test_teams_sort_by_samples_descending_regardless_of_win_rate(self):
  a=self.record([self.row(wins=95,losses=5),self.row(('c7','c8','c9'),wins=70,losses=130)])
  record=merge_records(['c1','c2','c3'],[('A',a)])
  self.assertEqual([r['samples'] for r in record['offenses']],[200,100])
 def test_guides_do_not_create_fake_battle_samples(self):
  guide={'id':1,'heroes':['c4','c5','c6'],'feedback_wins':123,'feedback_losses':2}
  record=merge_records(['c1','c2','c3'],[('Wiki',self.record(guides=[guide]))])
  self.assertEqual(record['offenses'],[]);self.assertNotIn('samples',record['guides'][0]);self.assertEqual(record['guides'][0]['feedback_wins'],123)
 def test_partial_failure_preserves_success_and_reports_the_failure(self):
  def fail():raise TimeoutError('timed out')
  result=fetch_combined(['c1','c2','c3'],{'up':lambda:self.record([self.row()]),'down':fail})
  self.assertEqual(len(result['offenses']),1);self.assertFalse(result['complete']);self.assertEqual(result['source_errors'][0]['provider'],'down')
 def test_all_failures_raise_instead_of_becoming_zero_results(self):
  def fail():raise TimeoutError('timed out')
  with self.assertRaisesRegex(ValueError,'所有在线来源'):fetch_combined(['c1','c2','c3'],{'down':fail})
 def test_sources_are_requested_concurrently(self):
  barrier=threading.Barrier(2)
  def read():barrier.wait(timeout=2);return self.record()
  result=fetch_combined(['c1','c2','c3'],{'A':read,'B':read});self.assertEqual(len(result['sources']),2)
 def test_other_defense_is_not_merged(self):
  with self.assertRaises(ValueError):merge_records(['c1','c2','c3'],[('bad',self.record(defense=['c1','c2','c9']))])
 def test_historical_source_is_labelled_and_ties_prefer_live_data(self):
  result=merge_records(['c1','c2','c3'],[('old',self.record([self.row()],historical=True)),('live',self.record([self.row()],source='Live'))])
  self.assertFalse(result['offenses'][0]['historical']);self.assertEqual(result['offenses'][0]['display_source'],'Live')
