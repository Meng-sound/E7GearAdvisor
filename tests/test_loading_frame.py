import unittest
from types import SimpleNamespace
from loading_frame import wait_for_picture

class LoadingTests(unittest.TestCase):
 def test_black_frames_wait_and_resume_without_restarting_capture(self):
  frames=iter([SimpleNamespace(info={'loading':True}),SimpleNamespace(info={'loading':True}),SimpleNamespace(info={})])
  events=[];waits=[]
  result=wait_for_picture(lambda:next(frames),lambda:None,lambda:events.append('loading'),lambda:events.append('ready'),waits.append)
  self.assertFalse(result.info.get('loading',False));self.assertEqual(events,['loading','ready']);self.assertEqual(waits,[.15,.15])
 def test_stop_remains_available_during_loading(self):
  calls=[]
  def guard():
   calls.append(1)
   if len(calls)==3:raise InterruptedError('stop')
  with self.assertRaises(InterruptedError):wait_for_picture(lambda:SimpleNamespace(info={'loading':True}),guard,wait=lambda seconds:None)
 def test_actual_capture_errors_are_not_hidden_as_loading(self):
  def capture():raise RuntimeError('window closed')
  with self.assertRaisesRegex(RuntimeError,'window closed'):wait_for_picture(capture,lambda:None)
