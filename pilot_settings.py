"""Native E7Pilot settings, with no host budget or policy overlays."""
import json,sys
from pathlib import Path

def defaults():
 path=Path(__file__).parent
 sys.path.insert(0,str(path/'neural'))
 import yaml
 return yaml.safe_load((path/'vendor/e7pilot/rules.yaml').read_text('utf8'))['settings']

def load(directory):
 settings=defaults();path=Path(directory)/'e7pilot-settings.json'
 if path.is_file():
  saved=json.loads(path.read_text('utf8'))
  if not isinstance(saved,dict):raise ValueError('原项目设置格式错误')
  settings.update(saved)
 return settings

def save(directory,settings):
 path=Path(directory)/'e7pilot-settings.json';temporary=path.with_suffix('.tmp')
 temporary.write_text(json.dumps(settings,ensure_ascii=False,indent=2),'utf8');temporary.replace(path)
