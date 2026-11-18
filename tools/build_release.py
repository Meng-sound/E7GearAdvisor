"""Build clean repository and portable snapshots; never copy user profiles."""
import argparse,hashlib,json,shutil,sys,zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EXCLUDED={'__pycache__','.git','.venv','userdata','dist','release','reference'}
DEPENDENCIES={'runtime','neural','PIL','Pillow-LICENSES','pilot_dependencies','windows_capture','windows_capture-2.0.1.dist-info'}
LEGACY={'upstream_oracle.py','source_algorithm.py','test_source_algorithm.py','AUTOMATION_TEST.md','PENDING.md','data/upstream-info.json'}

def allowed(path,source=True):
 rel=path.relative_to(ROOT);parts=rel.parts;name=path.name
 if any(p in EXCLUDED for p in parts) or (source and parts[0] in DEPENDENCIES):return False
 if name in LEGACY or rel.as_posix() in LEGACY:return False
 if path.suffix.lower() in {'.pyc','.exe','.zip','.log','.sqlite','.sqlite3'}:return False
 if name.startswith('.env') or name.endswith(('.part','.bak')):return False
 if parts[0]=='vendor' and ('_before' in name or '_backup' in name or name in {'test_bg_click.py','selftest.py'}):return False
 if parts[0]=='data' and name.startswith('recognition-') and name.endswith('-times.json'):return False
 return True

def copy_tree(origin,destination):
 shutil.copytree(origin,destination,ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.log','*.part'),dirs_exist_ok=True)

def archive(folder,target):
 with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
  for path in sorted(folder.rglob('*')):
   if path.is_file():bundle.write(path,Path(folder.name)/path.relative_to(folder))
 with zipfile.ZipFile(target) as bundle:
  if bundle.testzip():raise RuntimeError('ZIP integrity check failed')

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--dependencies',type=Path,required=True,help='Known-working portable app directory, containing runtime and neural')
 parser.add_argument('--output',type=Path,required=True,help='New output directory; must not already exist')
 args=parser.parse_args();output=args.output.resolve();deps=args.dependencies.resolve()
 if output.exists():raise SystemExit('Output already exists; choose a new directory to preserve previous releases.')
 for folder in DEPENDENCIES:
  if not (deps/folder).is_dir():raise SystemExit('Missing runtime dependency: '+folder)
 sys.path.insert(0,str(ROOT))
 from app_version import VERSION
 from source_window import about_document
 repository=output/'GitHub-Source';app=output/'E7GearAdvisor'
 repository.mkdir(parents=True);app.mkdir()
 for path in ROOT.rglob('*'):
  if path.is_file() and allowed(path):
   target=repository/path.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
 (repository/'ABOUT.md').write_text(about_document(),'utf8')
 for path in repository.rglob('*'):
  if path.is_file() and path.relative_to(repository).parts[0] not in {'tests','tools','.github'}:
   target=app/path.relative_to(repository);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
 for folder in sorted(DEPENDENCIES):copy_tree(deps/folder,app/folder)
 # One maintained launcher. It is not a stand-alone executable.
 shutil.copy2(deps/'装备强化计算器.exe',app/'装备强化计算器.exe')
 launcher='@echo off\r\nsetlocal\r\ncd /d "%~dp0"\r\nstart "" "%~dp0runtime\\pythonw.exe" "%~dp0admin_start.py"\r\n'
 (app/'Start-Admin.cmd').write_bytes(launcher.encode('ascii'))
 # Keep an inventory so missing offline data is caught before upload.
 catalog=json.loads((app/'data/hero-catalog.json').read_text('utf8'))
 references=json.loads((app/'data/hero-build-references.json').read_text('utf8'))
 stats={'version':VERSION,'heroes':len(catalog['heroes']),'reference_heroes':len(references['heroes'])}
 if stats['reference_heroes']<300:raise RuntimeError('Incomplete offline reference snapshot')
 for name in ('hero-portraits','artifact-icons','set-icons'):
  stats[name]=sum(p.is_file() for p in (app/'data'/name).rglob('*'))
  if not stats[name]:raise RuntimeError('Missing assets: '+name)
 (output/'BUILD-REPORT.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),'utf8')
 archive(repository,output/'E7GearAdvisor-Source.zip');archive(app,output/'E7GearAdvisor-Windows.zip')
 sums=[]
 for path in sorted(output.glob('*.zip')):
  digest=hashlib.file_digest(path.open('rb'),'sha256').hexdigest();sums.append(digest+'  '+path.name)
 (output/'SHA256SUMS.txt').write_text('\n'.join(sums)+'\n','utf8')
 print(json.dumps(stats,ensure_ascii=False));print('READY',output)

if __name__=='__main__':main()
