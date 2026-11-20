"""In-place updater: install shape, prompt policy, staging and the swap helper."""
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import auto_update

ZIP_ASSET = {'name': 'E7GearAdvisor-Windows.zip', 'size': 10}
EXE_ASSET = {'name': 'E7GearAdvisor.exe', 'size': 10}
RELEASE = {'tag': 'v9.9.9', 'newer': True, 'page': 'https://example.invalid',
           'asset': ZIP_ASSET, 'assets': [ZIP_ASSET, EXE_ASSET],
           'notes': 'test'}


def make_zip(path, with_app=True):
    with zipfile.ZipFile(path, 'w') as bundle:
        if with_app:
            bundle.writestr('E7GearAdvisor/pc_app.py', 'print(1)\n')
            bundle.writestr('E7GearAdvisor/data/heroes.json', '{}\n')
        else:
            bundle.writestr('other/readme.txt', 'x')
    return path


class InstallShapeTests(unittest.TestCase):
    def test_single_when_payload_marker_exists(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / auto_update.MARKER).write_text('abc')
            with patch('auto_update.install_dir', return_value=Path(folder)):
                self.assertEqual(auto_update.install_mode(), 'single')

    def test_portable_when_runtime_sits_next_to_the_scripts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'runtime').mkdir()
            (root / 'runtime' / 'pythonw.exe').write_bytes(b'')
            (root / 'pc_app.py').write_text('')
            with patch('auto_update.install_dir', return_value=root):
                self.assertEqual(auto_update.install_mode(), 'portable')

    def test_source_checkout_is_not_updated_automatically(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch('auto_update.install_dir', return_value=Path(folder)):
                self.assertEqual(auto_update.install_mode(), 'source')
                self.assertFalse(auto_update.plan(RELEASE)['supported'])


class PlanTests(unittest.TestCase):
    def test_single_needs_the_launcher_path(self):
        with patch('auto_update.install_mode', return_value='single'), \
                patch('auto_update.launcher_exe', return_value=None):
            plan = auto_update.plan(RELEASE)
        self.assertFalse(plan['supported'])
        self.assertIn('手动下载', plan['reason'])

    def test_single_uses_the_outer_exe(self):
        with patch('auto_update.install_mode', return_value='single'), \
                patch('auto_update.launcher_exe', return_value=Path('C:/apps/游戏/E7GearAdvisor.exe')):
            plan = auto_update.plan(RELEASE)
        self.assertTrue(plan['supported'])
        self.assertEqual(plan['kind'], 'exe')

    def test_single_picks_the_exe_not_the_zip(self):
        # The Release prefers the ZIP for portable users; a packed install must
        # still download the EXE, otherwise the swap targets a .exe with a folder.
        with patch('auto_update.install_mode', return_value='single'), \
                patch('auto_update.launcher_exe', return_value=Path('C:/apps/E7GearAdvisor.exe')):
            plan = auto_update.plan(RELEASE)
        self.assertEqual(plan['asset']['name'], 'E7GearAdvisor.exe')

    def test_portable_picks_the_zip(self):
        with patch('auto_update.install_mode', return_value='portable'), \
                patch('auto_update.install_dir', return_value=Path('C:/game')):
            plan = auto_update.plan(RELEASE)
        self.assertEqual(plan['asset']['name'], 'E7GearAdvisor-Windows.zip')

    def test_single_without_an_exe_asset_is_refused(self):
        release = dict(RELEASE, assets=[ZIP_ASSET], asset=ZIP_ASSET)
        with patch('auto_update.install_mode', return_value='single'), \
                patch('auto_update.launcher_exe', return_value=Path('C:/apps/E7GearAdvisor.exe')):
            self.assertFalse(auto_update.plan(release)['supported'])

    def test_portable_replaces_the_folder(self):
        with patch('auto_update.install_mode', return_value='portable'), \
                patch('auto_update.install_dir', return_value=Path('C:/game')):
            plan = auto_update.plan(RELEASE)
        self.assertEqual((plan['kind'], plan['target']), ('zip', 'C:\\game'))

    def test_missing_asset_is_reported(self):
        with patch('auto_update.install_mode', return_value='portable'):
            self.assertFalse(auto_update.plan({'newer': True, 'asset': None})['supported'])


class PromptPolicyTests(unittest.TestCase):
    def test_new_version_prompts_once(self):
        self.assertTrue(auto_update.should_prompt(RELEASE, {}))
        self.assertFalse(auto_update.should_prompt(RELEASE, {'skipped_version': 'v9.9.9'}))
        self.assertTrue(auto_update.should_prompt(RELEASE, {'skipped_version': 'v9.9.8'}))

    def test_older_or_assetless_release_is_ignored(self):
        self.assertFalse(auto_update.should_prompt({**RELEASE, 'newer': False}, {}))
        self.assertFalse(auto_update.should_prompt({**RELEASE, 'asset': None}, {}))


class StagingTests(unittest.TestCase):
    def test_zip_is_unpacked_with_the_root_folder_stripped(self):
        with tempfile.TemporaryDirectory() as folder:
            payload = make_zip(Path(folder) / 'E7GearAdvisor-Windows.zip')
            with patch('auto_update.download_release', return_value=str(payload)):
                staged = auto_update.stage(RELEASE, Path(folder))
            self.assertEqual(staged['kind'], 'zip')
            self.assertTrue((staged['path'] / 'pc_app.py').is_file())
            self.assertTrue((staged['path'] / 'data' / 'heroes.json').is_file())

    def test_zip_without_the_app_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            payload = make_zip(Path(folder) / 'broken.zip', with_app=False)
            with patch('auto_update.download_release', return_value=str(payload)):
                with self.assertRaisesRegex(ValueError, 'pc_app.py'):
                    auto_update.stage(RELEASE, Path(folder))

    def test_exe_asset_is_passed_through(self):
        with tempfile.TemporaryDirectory() as folder:
            payload = Path(folder) / 'E7GearAdvisor.exe'
            payload.write_bytes(b'MZ')
            with patch('auto_update.download_release', return_value=str(payload)):
                staged = auto_update.stage(RELEASE, Path(folder))
            self.assertEqual((staged['kind'], staged['path']), ('exe', payload))


class HelperScriptTests(unittest.TestCase):
    def test_exe_swap_keeps_a_rollback_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / 'apply.ps1'
            auto_update.write_helper(
                script,
                {'kind': 'exe', 'target': r"C:\Program Files\E7\E7GearAdvisor.exe",
                 'new': r"C:\Temp\new.exe"},
                1234, [r"C:\Program Files\E7\E7GearAdvisor.exe"])
            text = script.read_text('utf-8-sig')
        self.assertIn("$targetPid = 1234", text)
        self.assertIn("Move-Item -LiteralPath $target -Destination $old -Force", text)
        self.assertIn('catch { Move-Item -LiteralPath $old -Destination $target -Force; throw }', text)
        self.assertIn("Start-Process -FilePath 'C:\\Program Files\\E7\\E7GearAdvisor.exe'", text)

    def test_folder_copy_protects_userdata(self):
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / 'apply.ps1'
            auto_update.write_helper(
                script, {'kind': 'zip', 'target': r"C:\game\E7GearAdvisor",
                         'source': r"C:\Temp\unpacked"},
                7, [r"C:\game\E7GearAdvisor\装备强化计算器.exe"])
            text = script.read_text('utf-8-sig')
        self.assertIn('robocopy $source $target /E', text)
        self.assertIn('/XD (Join-Path $target "userdata")', text)
        self.assertIn("'C:\\game\\E7GearAdvisor\\装备强化计算器.exe'", text)

    def test_quotes_in_paths_are_escaped(self):
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / 'apply.ps1'
            auto_update.write_helper(script, {'kind': 'exe', 'target': "C:/it's/here.exe",
                                              'new': 'C:/n.exe'}, 1, ['C:/it\'s/here.exe'])
            text = script.read_text('utf-8-sig')
        self.assertIn("'C:/it''s/here.exe'", text)


class ApplyTests(unittest.TestCase):
    def test_apply_starts_a_detached_helper_and_returns_its_script(self):
        with tempfile.TemporaryDirectory() as folder:
            staged = {'kind': 'exe', 'path': Path(folder) / 'new.exe'}
            staged['path'].write_bytes(b'MZ')
            with patch('auto_update.restart_command', return_value=[r"C:\app\E7GearAdvisor.exe"]), \
                    patch('auto_update.subprocess.Popen') as popen:
                script = auto_update.apply(staged, {'supported': True, 'kind': 'exe',
                                                    'target': r"C:\app\E7GearAdvisor.exe"})
            self.assertTrue(script.is_file())
            arguments = popen.call_args.args[0]
            self.assertEqual(arguments[:2], ['powershell', '-NoProfile'])
            self.assertIn(str(script), arguments)

    def test_unsupported_plan_refuses(self):
        with self.assertRaisesRegex(RuntimeError, '不支持'):
            auto_update.apply({'kind': 'exe', 'path': Path('x')}, {'supported': False, 'reason': '不支持'})

    def test_mismatched_artifact_is_refused_before_anything_changes(self):
        # A ZIP cannot overwrite an .exe path; refuse instead of failing after exit.
        with self.assertRaisesRegex(RuntimeError, '不匹配'):
            auto_update.apply({'kind': 'zip', 'path': Path('unpacked')},
                              {'supported': True, 'kind': 'exe', 'target': 'C:/app/E7GearAdvisor.exe'})


class StageSelectionTests(unittest.TestCase):
    def test_stage_downloads_the_asset_for_the_install_shape(self):
        seen = {}

        def fake_download(release, directory, progress):
            seen['asset'] = release['asset']['name']
            path = Path(directory) / 'E7GearAdvisor.exe'
            path.write_bytes(b'MZ')
            return str(path)

        with tempfile.TemporaryDirectory() as folder, \
                patch('auto_update.download_release', side_effect=fake_download):
            staged = auto_update.stage(RELEASE, Path(folder), asset=EXE_ASSET)
        self.assertEqual(seen['asset'], 'E7GearAdvisor.exe')
        self.assertEqual(staged['kind'], 'exe')


class HelperResilienceTests(unittest.TestCase):
    def test_helper_logs_and_always_restarts(self):
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / 'apply.ps1'
            auto_update.write_helper(script, {'kind': 'exe', 'target': r'C:\a\E7GearAdvisor.exe',
                                              'new': r'C:\t\new.exe'}, 3, [r'C:\a\E7GearAdvisor.exe'])
            text = script.read_text('utf-8-sig')
        self.assertIn('update.log', text)
        self.assertIn('function Log', text)
        self.assertIn('replace failed', text)
        self.assertIn('rolled back to the old exe', text)
        self.assertIn('Log "restarted"', text)
        # Restart happens after the try/catch, so a failed swap still relaunches.
        self.assertGreater(text.index('Log "restarted"'), text.index('} catch {'))


if __name__ == '__main__':
    unittest.main()
