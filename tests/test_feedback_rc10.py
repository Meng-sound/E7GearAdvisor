import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from core import Gear,Stat
from advice import evaluate_advice
from craft_window import crafted_decision
from character_loadout import artifact_progression,artifacts,artifact_level_near_name
from hero_imprints import profiles,imprint_value,read_active_imprint,read_popup_profiles,save_profiles
from window_capture import capture_client,visible_client_image,intersects

CATALOG=json.loads((Path(__file__).resolve().parents[1]/'data/hero-catalog.json').read_text('utf8'))['heroes']
FURIOUS=next(h for h in CATALOG if h['name_en']=='Furious')

class ImprintProfileTests(unittest.TestCase):
 def test_furious_matches_user_screenshot(self):
  self.assertEqual(profiles(FURIOUS)['team']['grades'],dict(B=6,A=8,S=10,SS=12,SSS=13))
  self.assertEqual(imprint_value(FURIOUS,'self','SSS')['value'],18)
  self.assertEqual(imprint_value(FURIOUS,'team','B')['value'],6)
 def test_locked_and_team_not_self(self):
  self.assertEqual(read_active_imprint('锁定\n暴击率%\n额外效果',FURIOUS)['mode'],'locked')
  row=read_active_imprint('SSS\n暴击率%',FURIOUS)
  self.assertEqual(row['mode'],'team');self.assertEqual(row['value']['scope'],'team')
  self.assertEqual(read_active_imprint('自身刻印\nB',FURIOUS)['value']['value'],9)
 def test_popup_all_ranks_does_not_select_sss(self):
  result=read_active_imprint('刻印记忆效果 开放型刻印 自身刻印 B A S SS SSS',FURIOUS)
  self.assertEqual(result['mode'],'unknown');self.assertNotIn('value',result)
 def test_two_popup_columns_are_independent(self):
  words=[dict(text='开放型刻印',x=430,y=400,w=180,h=25),dict(text='自身刻印',x=980,y=400,w=180,h=25)]
  for index,(rank,t,s) in enumerate([('B',6,9),('A',8,12),('S',10,14),('SS',12,16),('SSS',13,18)]):
   y=580+index*70
   for x,label,value in [(440,'暴击率',t),(990,'攻击力',s)]:
    words.extend([dict(text=rank,x=x,y=y,w=60,h=25),dict(text=f'{label} +{value}%',x=x+85,y=y,w=170,h=25)])
  result=read_popup_profiles(words,1821,FURIOUS)
  self.assertEqual(result['team']['grades']['SSS'],13)
  self.assertEqual(result['self']['grades']['B'],9)
 def test_read_tables_override_only_selected_hero(self):
  with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'E7_ADVISOR_HOME':directory}):
   before=profiles(CATALOG[0])
   record={'team':dict(key='crit',percent=True,grades={'B':6,'SSS':13},source='test screenshot')}
   save_profiles(Path(directory)/'hero-imprints.json',FURIOUS,record)
   self.assertEqual(profiles(FURIOUS)['team']['source'],'test screenshot')
   self.assertEqual(profiles(CATALOG[0]),before)
 def test_every_bundled_hero_has_self_profile(self):
  self.assertTrue(all(profiles(h).get('self',{}).get('grades') for h in CATALOG))

class ArtifactProgressionTests(unittest.TestCase):
 def test_all_levels_and_actual_deltas(self):
  for code in artifacts():
   rows=artifact_progression(code);self.assertEqual(len(rows),31)
   self.assertEqual(rows[0]['level'],0);self.assertEqual(rows[-1]['level'],30)
   for a,b in zip(rows,rows[1:]):
    self.assertAlmostEqual(b['atk']-a['atk'],b['delta_atk']);self.assertAlmostEqual(b['hp']-a['hp'],b['delta_hp'])
 def test_nearby_level_not_other_equipment(self):
  words=[dict(text='塔克赫尔古书',x=100,y=200,w=140,h=25),dict(text='+24',x=245,y=200,w=40,h=25),dict(text='+15',x=700,y=200,w=40,h=25)]
  self.assertEqual(artifact_level_near_name(words,['塔克赫尔古书']),24)
  words[1]['text']='+31';self.assertIsNone(artifact_level_near_name(words,['塔克赫尔古书']))

class RetentionTests(unittest.TestCase):
 def gear(self,grade='史诗',speed=3,enhance=0):
  return Gear(slot='武器',set_name='速度',grade=grade,level=85,enhance=enhance,main=Stat('atk',100),subs=[Stat('atk_pct',4),Stat('hp_pct',7),Stat('crit',3),Stat('spd',speed)])
 def test_user_21_8_red_weapon_not_discarded(self):
  g=self.gear();r=crafted_decision(g,{},'gs')
  self.assertAlmostEqual(r['score'],21.8);self.assertEqual(r['category'],'keep');self.assertTrue(r['advice']['speed_retention'])
 def test_purple_three_red_any_speed(self):
  for grade,speed,expected in [('英雄',2,False),('英雄',3,True),('史诗',1,True),('史诗',2,True),('史诗',3,True)]:
   with self.subTest(grade=grade,speed=speed):
    self.assertEqual(bool(evaluate_advice(self.gear(grade,speed)).get('speed_retention')),expected)
 def test_finished_and_fixed_main_not_whitelisted(self):
  self.assertFalse(evaluate_advice(self.gear(enhance=6)).get('speed_retention'))
  g=self.gear();g.slot='戒指';g.main=Stat('atk',100)
  self.assertEqual(evaluate_advice(g)['kind'],'discard')
  g=self.gear('稀有');self.assertEqual(evaluate_advice(g)['kind'],'discard')
 def test_craft_obeys_selected_scoring_mode(self):
  g=self.gear();g.subs[0]=Stat('atk',40)
  a=crafted_decision(g,{'atk':800,'hp':5000,'def':500},'role')
  b=crafted_decision(g,{'atk':800,'hp':5000,'def':500},'gs')
  self.assertNotEqual(a['score'],b['score'])

class CaptureCompatibilityTests(unittest.TestCase):
 def test_background_success_does_not_read_desktop(self):
  image=object()
  with patch('window_capture.client_image',return_value=image),patch('window_capture.visible_client_image') as visible:
   self.assertIs(capture_client(1,2,'Epic Seven'),image);visible.assert_not_called()
 def test_auto_falls_back_and_strict_background_does_not(self):
  image=object()
  with patch('window_capture.client_image',side_effect=RuntimeError('renderer unsupported')),patch('window_capture.visible_client_image',return_value=image) as visible:
   self.assertIs(capture_client(1,2,'Epic Seven'),image)
   with self.assertRaisesRegex(RuntimeError,'renderer'):capture_client(1,2,'Epic Seven','background')
   self.assertEqual(visible.call_count,1)
 def test_occluded_window_not_grabbed(self):
  with patch('window_capture.visible_client_bounds',side_effect=RuntimeError('covered')),patch('PIL.ImageGrab.grab') as grab:
   with self.assertRaisesRegex(RuntimeError,'covered'):visible_client_image(1,2,'Epic Seven')
   grab.assert_not_called()
 def test_movement_invalidates_capture(self):
  with patch('window_capture.visible_client_bounds',side_effect=[(0,0,80,60),(1,0,81,60)]),patch('PIL.ImageGrab.grab',return_value=Image.new('RGB',(80,60))):
   with self.assertRaisesRegex(RuntimeError,'移动'):visible_client_image(1,2,'Epic Seven')
 def test_intersection_checks_entire_client(self):
  self.assertTrue(intersects((0,0,100,100),(40,40,50,50)))
  self.assertFalse(intersects((0,0,100,100),(100,0,110,10)))

if __name__=='__main__':unittest.main()
