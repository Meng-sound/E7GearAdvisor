import io,json,queue,unittest
from types import SimpleNamespace
from pilot_runner import PilotRunner
from task_replay import Config

class RunnerControlTests(unittest.TestCase):
 def test_pause_resume_stop_commands_do_not_touch_mouse(self):
  runner=PilotRunner({},Config(mode='story'),queue.Queue())
  pipe=io.StringIO();runner.process=SimpleNamespace(stdin=pipe,poll=lambda:None)
  runner.pause();self.assertTrue(runner.paused.is_set())
  runner.resume();self.assertFalse(runner.paused.is_set())
  runner.stop();self.assertTrue(runner.cancel.is_set())
  self.assertEqual([json.loads(line) for line in pipe.getvalue().splitlines()],[{'pause':True},{'pause':False},{'stop':True}])
 def test_host_time_limits_are_not_applied_to_native_engine(self):
  self.assertIsNone(PilotRunner({},Config(mode='theater',max_seconds=30),queue.Queue(),seconds=60).seconds)
