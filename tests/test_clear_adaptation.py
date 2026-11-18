import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import adaptation_storage as store

class ClearAdaptationTests(unittest.TestCase):
 def setUp(self):
  self.previous=store.overrides()
 def tearDown(self):
  store._overrides=self.previous
 def test_clear_persists_restart_and_backup_can_be_imported(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'hero-adaptation.json'
   payload={'schema':1,'heroes':{'Test':{'hero_id':'test','weights':{'spd':1}}}}
   path.write_text(json.dumps(payload),'utf8');store.configure(path)
   count,backup=store.clear_custom(path)
   self.assertEqual(count,1);self.assertEqual(store.overrides(),{})
   self.assertEqual(json.loads(backup.read_text('utf8')),payload)
   catalog={'heroes':[{'id':'test','name':'测试','name_en':'Test'}]}
   store.configure(path,catalog);self.assertEqual(store.overrides(),{})
   self.assertEqual(store.import_file(backup,path,catalog),1)
   self.assertEqual(store.overrides()['Test']['weights'],{'spd':1})
 def test_backup_failure_does_not_clear_saved_or_loaded_data(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'hero-adaptation.json';raw='{"schema":1,"heroes":{"Test":{"weights":{"spd":1}}}}'
   path.write_text(raw,'utf8');store.configure(path)
   with patch('adaptation_storage.shutil.copy2',side_effect=OSError('disk error')):
    with self.assertRaises(OSError):store.clear_custom(path)
   self.assertEqual(path.read_text('utf8'),raw);self.assertIn('Test',store.overrides())
