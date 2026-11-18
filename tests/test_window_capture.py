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

    def test_timeout_does_not_fallback(self):
        with patch('window_capture.subprocess.run',side_effect=subprocess.TimeoutExpired('synthetic worker',6)) as run:
            with self.assertRaisesRegex(RuntimeError,'超时'):
                capture_game_window(self.target)
            self.assertEqual(run.call_count,1)

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
            paths.append(Path(arguments[-1]))
            Image.new('RGB',(80,60),'red').save(paths[-1])
            self.assertEqual(arguments[-4:-1],['123','456','Epic Seven'])
            self.assertEqual(kwargs['timeout'],6)
            return SimpleNamespace(returncode=0,stderr='')
        with patch('window_capture.subprocess.run',side_effect=fake_worker):
            image=capture_game_window(self.target)
        self.assertEqual(image.getpixel((0,0)),(255,0,0))
        self.assertFalse(paths[0].exists())


if __name__=='__main__':
    unittest.main()
