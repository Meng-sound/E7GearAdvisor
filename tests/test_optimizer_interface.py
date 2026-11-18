import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from optimizer_interface import load_path,save_path,launch,validate_path

class LauncherTests(unittest.TestCase):
 def test_configuration_can_be_saved_and_cleared_without_starting(self):
  with tempfile.TemporaryDirectory() as folder:
   config=Path(folder)/'config.json';exe=Path(folder)/'tool.exe';exe.write_bytes(b'test fixture')
   save_path(config,str(exe));self.assertEqual(load_path(config),str(exe))
   save_path(config,'');self.assertEqual(load_path(config),'')
 def test_launches_only_explicit_executable_without_shell_or_arguments(self):
  with tempfile.TemporaryDirectory() as folder:
   exe=Path(folder)/'tool.exe';exe.write_bytes(b'test fixture')
   with patch('optimizer_interface.subprocess.Popen') as start:
    launch(str(exe));start.assert_called_once_with([str(exe)],cwd=str(exe.parent),shell=False)
 def test_invalid_paths_and_malformed_configuration(self):
  for value in ('','relative.exe','https://example.com/app.exe'):
   with self.assertRaises(ValueError):validate_path(value)
  with tempfile.TemporaryDirectory() as folder:
   config=Path(folder)/'config.json';config.write_text('[]','utf8');self.assertEqual(load_path(config),'')
   wrong=Path(folder)/'tool.cmd';wrong.write_text('test','utf8')
   with self.assertRaises(ValueError):validate_path(str(wrong))
