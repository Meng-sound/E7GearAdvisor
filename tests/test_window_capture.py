import subprocess
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from PIL import Image
from window_capture import capture_game_window


class WindowCaptureTests(unittest.TestCase):
    target = dict(title='Epic Seven', hwnd=123, pid=456)

    def test_invalid_target_does_not_launch(self):
        for target in [dict(title='Other',hwnd=1,pid=1),dict(title='Epic Seven',hwnd=True,pid=1),
                       dict(title='Epic Seven',hwnd=1)]:
            with self.subTest(target=target), patch('window_capture.subprocess.run') as run:
                with self.assertRaises(ValueError):
                    capture_game_window(target)
                run.assert_not_called()

    def test_timeout_retries_once_with_a_longer_budget(self):
        # A cold worker (4K frame, antivirus scan) can miss the first budget.
        with patch('window_capture.subprocess.run',side_effect=subprocess.TimeoutExpired('synthetic worker',20)) as run:
            with self.assertRaisesRegex(RuntimeError,'超时'):
                capture_game_window(self.target)
            self.assertEqual(run.call_count,2)
            self.assertEqual(run.call_args_list[0].kwargs['timeout'],12)
            self.assertEqual(run.call_args_list[1].kwargs['timeout'],18)

    def test_cold_start_timeout_recovers_on_retry(self):
        calls=[]
        def fake_worker(arguments,**kwargs):
            calls.append(kwargs['timeout'])
            if len(calls)==1:raise subprocess.TimeoutExpired('synthetic worker',kwargs['timeout'])
            Image.new('RGB',(80,60),'red').save(arguments[-2])
            return SimpleNamespace(returncode=0,stderr='')
        with patch('window_capture.subprocess.run',side_effect=fake_worker):
            image=capture_game_window(self.target)
        self.assertEqual(image.getpixel((0,0)),(255,0,0))
        self.assertEqual(calls,[12,18])

    def test_failure_does_not_fallback(self):
        with patch('window_capture.subprocess.run',return_value=SimpleNamespace(returncode=1,stderr='black frame')) as run:
            with self.assertRaisesRegex(RuntimeError,'black frame'):
                capture_game_window(self.target)
            self.assertEqual(run.call_count,1)

    def test_missing_output(self):
        with patch('window_capture.subprocess.run',return_value=SimpleNamespace(returncode=0,stderr='')):
            with self.assertRaisesRegex(RuntimeError,'取图失败'):
                capture_game_window(self.target)

    def test_valid_output_is_loaded_and_temp_removed(self):
        paths=[]
        def fake_worker(arguments,**kwargs):
            paths.append(Path(arguments[-2]))
            Image.new('RGB',(80,60),'red').save(paths[-1])
            self.assertEqual(arguments[-5:-2],['123','456','Epic Seven'])
            self.assertEqual(arguments[-1],'')
            self.assertEqual(kwargs['timeout'],12)
            return SimpleNamespace(returncode=0,stderr='')
        with patch('window_capture.subprocess.run',side_effect=fake_worker):
            image=capture_game_window(self.target)
        self.assertEqual(image.getpixel((0,0)),(255,0,0))
        self.assertFalse(paths[0].exists())

    def test_emulator_process_is_forwarded_to_the_worker(self):
        seen={}
        def fake_worker(arguments,**kwargs):
            seen['argv']=arguments
            Image.new('RGB',(80,60),'red').save(arguments[-2])
            return SimpleNamespace(returncode=0,stderr='')
        target=dict(self.target,title='雷电模拟器',process='dnplayer.exe')
        with patch('window_capture.subprocess.run',side_effect=fake_worker):
            capture_game_window(target)
        self.assertEqual(seen['argv'][-1],'dnplayer.exe')


class DeviceFrameTests(unittest.TestCase):
    def test_black_device_frame_is_rejected_so_capture_can_fall_back(self):
        import window_capture
        class Backend:
            def capture(self):return Image.new('RGB',(1920,1080),'black')
            def close(self):return None
        with patch('emulator.open_input',return_value=Backend()):
            with self.assertRaisesRegex(RuntimeError,'黑屏'):
                window_capture.device_image({'title':'MuMu安卓设备'})


if __name__=='__main__':
    unittest.main()
