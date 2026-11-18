"""Embed the verified full Windows ZIP in a single Windows executable."""
import argparse,hashlib,json,subprocess,zipfile
from pathlib import Path

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--payload',type=Path,required=True)
 parser.add_argument('--output',type=Path,required=True)
 args=parser.parse_args();payload=args.payload.resolve();output=args.output.resolve()
 if output.exists():raise SystemExit('Choose a new output path; existing releases are preserved.')
 with zipfile.ZipFile(payload) as archive:
  names=set(archive.namelist())
  if 'E7GearAdvisor/pc_app.py' not in names or any('/userdata/' in n or n.endswith('.sqlite3') for n in names):
   raise SystemExit('Expected a clean full Windows package, without personal data.')
  version_source=archive.read('E7GearAdvisor/app_version.py').decode('utf8')
  import ast
  version=next(ast.literal_eval(node.value) for node in ast.parse(version_source).body if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='VERSION' for t in node.targets))
 with payload.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
 tools=Path(__file__).resolve().parent
 template=(tools/'SingleFileLauncher.cs').read_text('utf8').replace('__PAYLOAD_SHA256__',digest).replace('__APP_VERSION__',version)
 output.parent.mkdir(parents=True,exist_ok=True)
 generated=output.with_suffix('.generated.cs');generated.write_text(template,'utf8')
 manifest=output.with_suffix('.manifest')
 manifest.write_text('''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3"><security><requestedPrivileges><requestedExecutionLevel level="asInvoker" uiAccess="false" /></requestedPrivileges></security></trustInfo>
  <application xmlns="urn:schemas-microsoft-com:asm.v3"><windowsSettings><longPathAware xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">true</longPathAware></windowsSettings></application>
</assembly>''','utf8')
 compiler=Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
 command=[str(compiler),'/nologo','/target:winexe','/optimize+','/platform:x64','/out:'+str(output),
  '/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll',
  '/reference:System.IO.Compression.dll','/reference:System.IO.Compression.FileSystem.dll',
  '/win32manifest:'+str(manifest),'/resource:'+str(payload)+',E7Payload.zip',str(generated)]
 icon=tools.parent/'data/diche.ico'
 if icon.is_file():command.insert(-1,'/win32icon:'+str(icon))
 subprocess.run(command,check=True)
 with output.open('rb') as stream:exe_hash=hashlib.file_digest(stream,'sha256').hexdigest()
 report={'version':version,'file':output.name,'size':output.stat().st_size,'sha256':exe_hash,'payload_sha256':digest,
  'cache_directory':version+'-'+digest[:16]}
 output.with_suffix('.build.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
 output.with_suffix('.sha256.txt').write_text(exe_hash+'  '+output.name+'\n','utf8')
 print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
