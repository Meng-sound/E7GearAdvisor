"""Verify public read buttons pass HWNDs rather than desktop rectangles."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from PIL import Image
from pc_app import PCCalculator
from guild_war_ui import GuildWarWindow

class Value:
 def __init__(self,value):self.value=value
 def get(self):return self.value

class CaptureRouteTests(unittest.TestCase):
 def app(self,automatic=True):
  return SimpleNamespace(busy=False,auto_window=Value(automatic),region=[1,2,301,202],vars={'slot':Value('头盔')},start_scan=Mock(),status=Mock(),stop_live=Mock())
 def test_single_continuous_and_batch_use_window_identity(self):
  window={'hwnd':123,'pid':456,'title':'第七史诗','rect':[0,0,1820,1050],'minimized':False}
  with patch('pc_app.find_game_windows',return_value=[window]):
   for mode in ('single','batch'):
    app=self.app();PCCalculator.read_screen(app,mode)
    request=app.start_scan.call_args.args[0]
    self.assertEqual(request['window'],window);self.assertNotIn('rect',request)
    self.assertEqual(request['mode'],mode)
 def test_manual_region_stays_explicit_screen_capture(self):
  app=self.app(False);PCCalculator.read_screen(app)
  self.assertEqual(app.start_scan.call_args.args[0]['rect'],app.region)
  self.assertNotIn('window',app.start_scan.call_args.args[0])
 def test_guild_capture_runs_same_background_backend(self):
  window={'hwnd':123,'pid':456,'title':'第七史诗','rect':[0,0,1820,1050],'minimized':False}
  board=SimpleNamespace(busy=False,run=Mock(),match_image=Mock(return_value=('recognized',{})))
  picture=Image.new('RGB',(1820,1020))
  with patch('guild_war_ui.find_game_windows',return_value=[window]),patch('window_capture.capture_game_window',return_value=picture) as capture:
   GuildWarWindow.capture(board);job=board.run.call_args.args[0]
   self.assertEqual(job(),('recognized',{}));capture.assert_called_once_with(window)
   board.match_image.assert_called_once_with(picture)
