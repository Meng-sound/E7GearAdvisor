"""In-place update: download, verify, replace the install, restart.

Two install shapes must be handled:

* single file - the launcher extracted the payload to %LOCALAPPDATA% and exits,
  so the running app only has to replace the outer EXE; nothing is locked.
* portable folder - the app runs from that folder and its runtime DLLs are
  locked, so a detached helper waits for the process to exit and then copies
  the new files over the old ones (user data is never touched).

Nothing here runs on import; the UI calls it explicitly.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from app_version import VERSION
from software_update import download_release

MARKER = '.payload-sha256'
LAUNCHER_ENV = 'E7_ADVISOR_LAUNCHER_EXE'
PAYLOAD_ROOT = 'E7GearAdvisor'


def install_dir():
    return Path(__file__).resolve().parent


def install_mode():
    """'single' (packed EXE), 'portable' (folder) or 'source' (dev checkout)."""
    root = install_dir()
    if (root / MARKER).is_file():
        return 'single'
    if (root / 'runtime' / 'pythonw.exe').is_file() and (root / 'pc_app.py').is_file():
        return 'portable'
    return 'source'


def launcher_exe():
    """Outer EXE of the packed build, when the launcher told us where it is."""
    value = os.environ.get(LAUNCHER_ENV)
    if value and Path(value).is_file():
        return Path(value)
    return None


def restart_command():
    """How to start the freshly updated app from its install directory."""
    root = install_dir()
    for name in ('装备强化计算器.exe', 'E7GearAdvisor.exe'):
        candidate = root / name
        if candidate.is_file():
            return [str(candidate)]
    python = root / 'runtime' / 'pythonw.exe'
    if python.is_file():
        return [str(python), str(root / 'pc_app.py')]
    return [sys.executable, str(root / 'pc_app.py')]


def should_prompt(release, config):
    """One dialog per new version; '稍后' remembers the tag it was declined on."""
    if not release or not release.get('newer') or not release.get('asset'):
        return False
    return str(config.get('skipped_version') or '') != str(release.get('tag') or '')


def remember(config, **values):
    config = dict(config)
    config.update(values)
    return config


def choose_asset(release, mode):
    """Pick the artifact that matches how this copy is installed.

    A packed EXE must be replaced by the new EXE; the portable folder by the
    Windows ZIP. Using the ZIP on a packed install asked robocopy to overwrite
    an .exe path, which failed after the app had already exited.
    """
    assets = list((release or {}).get('assets') or [])
    installed = (release or {}).get('asset')
    if installed and all(a.get('name') != installed.get('name') for a in assets):
        assets.insert(0, installed)
    wanted = ('E7GearAdvisor.exe',) if mode == 'single' else ('E7GearAdvisor-Windows.zip',)
    for name in wanted:
        hit = next((a for a in assets if str(a.get('name')) == name), None)
        if hit:
            return hit
    return None


def plan(release):
    """What applying this release would do, without touching anything."""
    mode = install_mode()
    if mode == 'source':
        return {'mode': mode, 'supported': False,
                'reason': '当前是从源码目录运行，自动覆盖需要正式安装包。'}
    asset = choose_asset(release, mode)
    if asset is None:
        return {'mode': mode, 'supported': False,
                'reason': '该 Release 没有适用于当前安装方式的文件（单文件版需要 EXE，文件夹版需要 Windows ZIP）。'}
    kind = 'exe' if str(asset.get('name')).lower().endswith('.exe') else 'zip'
    if mode == 'single':
        target = launcher_exe()
        if target is None:
            return {'mode': mode, 'supported': False,
                    'reason': '检测不到启动器位置（旧版安装包）。请手动下载新版 EXE 覆盖一次，之后可自动更新。'}
        return {'mode': mode, 'supported': True, 'kind': kind, 'asset': asset, 'target': str(target)}
    return {'mode': mode, 'supported': True, 'kind': kind, 'asset': asset, 'target': str(install_dir())}


def stage(release, directory, progress=lambda done, total: None, asset=None):
    """Download + verify the right artifact, then unpack it when it is a ZIP."""
    chosen = asset or plan(release).get('asset') or (release or {}).get('asset')
    if chosen is None:
        raise RuntimeError('该 Release 没有适用于当前安装方式的文件')
    path = Path(download_release(dict(release, asset=chosen), directory, progress))
    if path.suffix.lower() != '.zip':
        return {'kind': 'exe', 'path': path}
    scratch = Path(directory) / (path.stem + '-unpacked')
    if scratch.exists():
        shutil.rmtree(scratch, ignore_errors=True)
    with zipfile.ZipFile(path) as archive:
        root = PAYLOAD_ROOT + '/'
        names = archive.namelist()
        if not any(name.startswith(root) for name in names):
            root = ''
        for name in names:
            relative = name[len(root):] if root and name.startswith(root) else name
            if not relative or relative.endswith('/'):
                continue
            destination = (scratch / relative).resolve()
            if scratch.resolve() not in destination.parents:
                raise ValueError('更新包包含无效路径')
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as source, destination.open('wb') as output:
                shutil.copyfileobj(source, output)
    if not (scratch / 'pc_app.py').is_file():
        raise ValueError('更新包内容不完整（缺少 pc_app.py）')
    return {'kind': 'zip', 'path': scratch}


def _ps_string(value):
    return "'" + str(value).replace("'", "''") + "'"


def write_helper(script, payload, process_id, restart, extra_cleanup=()):
    """A detached PowerShell script that finishes the swap after we exit.

    It always writes %LOCALAPPDATA%\\E7GearAdvisor\\update.log and always tries to
    start the app again, so a failed swap can never leave the user with "the
    window closed and nothing happened".
    """
    log = Path(os.environ.get('LOCALAPPDATA') or tempfile.gettempdir()) / 'E7GearAdvisor' / 'update.log'
    workdir = str(Path(restart[0]).parent) if payload['kind'] == 'exe' else str(install_dir())
    start = ('Start-Process -FilePath ' + _ps_string(restart[0]) +
             (' -ArgumentList ' + _ps_string(restart[1]) if len(restart) > 1 else '') +
             ' -WorkingDirectory ' + _ps_string(workdir))
    lines = [
        "$ErrorActionPreference = 'Stop'",
        f"$log = {_ps_string(log)}",
        'New-Item -ItemType Directory -Force -Path (Split-Path -Parent $log) | Out-Null',
        "function Log($m) { Add-Content -LiteralPath $log -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + '  ' + $m) -ErrorAction SilentlyContinue }",
        'Log "==== update helper started ===="',
        # $pid is a read-only automatic variable in PowerShell; never assigning to it.
        f"$targetPid = {int(process_id)}",
        'while (Get-Process -Id $targetPid -ErrorAction SilentlyContinue) { Start-Sleep -Milliseconds 400 }',
        'Start-Sleep -Milliseconds 400',
        'Log "app exited"',
    ]
    if payload['kind'] == 'exe':
        lines += [
            f"$target = {_ps_string(payload['target'])}",
            f"$new = {_ps_string(payload['new'])}",
            f"$old = $target + '.old'",
            'try {',
            '  if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old -Force -ErrorAction SilentlyContinue }',
            '  Move-Item -LiteralPath $target -Destination $old -Force',
            '  try { Move-Item -LiteralPath $new -Destination $target -Force }',
            '  catch { Move-Item -LiteralPath $old -Destination $target -Force; throw }',
            '  Log "exe replaced"',
            '} catch {',
            '  Log ("replace failed: " + $_.Exception.Message)',
            '  if ((Test-Path -LiteralPath $old) -and -not (Test-Path -LiteralPath $target)) {',
            '    Move-Item -LiteralPath $old -Destination $target -Force; Log "rolled back to the old exe"',
            '  }',
            '}',
        ]
    else:
        lines += [
            f"$source = {_ps_string(payload['source'])}",
            f"$target = {_ps_string(payload['target'])}",
            'try {',
            '  # /IS force-copies same-name files; /XD keeps the user profile inside the app folder.',
            '  robocopy $source $target /E /IS /XD (Join-Path $target "userdata") /R:1 /W:1 /NFL /NDL /NJH /NJS | Out-Null',
            '  Log ("files copied, robocopy exit " + $LASTEXITCODE)',
            '} catch {',
            '  Log ("copy failed: " + $_.Exception.Message)',
            '}',
        ]
    lines += [start, 'Log "restarted"']
    if payload['kind'] == 'exe':
        # Give the new EXE a moment to start, then drop the rollback copy.
        lines += ['Start-Sleep -Seconds 2',
                  'Remove-Item -LiteralPath $old -Force -ErrorAction SilentlyContinue']
    for item in [payload.get('new'), payload.get('source'), *extra_cleanup]:
        if item:
            lines.append(f"Remove-Item -LiteralPath {_ps_string(item)} -Recurse -Force -ErrorAction SilentlyContinue")
    lines.append(f"Remove-Item -LiteralPath {_ps_string(script)} -Force -ErrorAction SilentlyContinue")
    script.write_text('\r\n'.join(lines) + '\r\n', encoding='utf-8-sig')


def apply(staged, plan_entry, process_id=None):
    """Finish the update and restart; the caller must exit right afterwards."""
    if not plan_entry.get('supported'):
        raise RuntimeError(plan_entry.get('reason') or '当前安装方式不支持自动更新')
    if staged.get('kind') != plan_entry.get('kind'):
        raise RuntimeError('下载到的文件与安装方式不匹配，已取消更新（未改动任何文件）')
    process_id = os.getpid() if process_id is None else process_id
    directory = Path(tempfile.mkdtemp(prefix='e7-update-'))
    script = directory / 'apply-update.ps1'
    if staged['kind'] == 'exe':
        payload = {'kind': 'exe', 'target': plan_entry['target'], 'new': str(staged['path'])}
    else:
        payload = {'kind': 'zip', 'target': plan_entry['target'], 'source': str(staged['path'])}
    write_helper(script, payload, process_id, restart_command())
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) | 0x00000008  # DETACHED_PROCESS
    subprocess.Popen(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script)],
                     cwd=str(directory), creationflags=flags, close_fds=True)
    return script


def read_config(app):
    try:
        value = json.loads((app.user_dir / 'software-update.json').read_text('utf8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_config(app, config):
    (app.user_dir / 'software-update.json').write_text(
        json.dumps(config, ensure_ascii=False, indent=2), 'utf8')
