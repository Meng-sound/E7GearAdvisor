import tempfile,unittest
from pathlib import Path
from pilot_settings import load,save,defaults

class NativeSettingsTests(unittest.TestCase):
 def test_defaults_are_native_and_legacy_host_file_is_ignored(self):
  with tempfile.TemporaryDirectory() as folder:
   (Path(folder)/'task-settings.json').write_text('{"gold_budget":1,"max_steps":1,"sky_floor":0}','utf8')
   self.assertEqual(load(folder),defaults())
   self.assertNotIn('gold_budget',load(folder))
   self.assertNotIn('max_steps',load(folder))
 def test_native_settings_roundtrip(self):
  with tempfile.TemporaryDirectory() as folder:
   value=load(folder);value.update(shop_stop_gold=2000000,gear_auto_buy=True)
   save(folder,value)
   self.assertEqual(load(folder),value)
