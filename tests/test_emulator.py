"""Emulator recognition, content geometry and touch dispatch (no emulator needed)."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

import emulator
from desktop_capture import select_game_rectangle
from window_input import WindowInput


class IdentifyTests(unittest.TestCase):
    def test_pc_client_titles(self):
        for title in ('第七史诗', 'Epic Seven', 'EPIC SEVEN', ' epic seven '):
            with self.subTest(title=title):
                self.assertEqual(emulator.identify(title)['kind'], 'pc')

    def test_mumu_by_title_and_process(self):
        self.assertEqual(emulator.identify('MuMu安卓设备')['name'], 'MuMu')
        self.assertEqual(emulator.identify('MuMuNxDevice', 'Qt5156QWindowBits', 'MuMuNxDevice.exe')['kind'], 'emulator')
        self.assertEqual(emulator.identify('anything', '', 'mumuplayer.exe')['name'], 'MuMu')

    def test_other_emulators(self):
        for title, process, name in [('雷电模拟器', '', '雷电模拟器'), ('', 'dnplayer.exe', '雷电模拟器'),
                                     ('BlueStacks App Player', '', 'BlueStacks'), ('夜神模拟器', '', '夜神模拟器'),
                                     ('逍遥模拟器', '', '逍遥模拟器')]:
            with self.subTest(title=title or process):
                self.assertEqual(emulator.identify(title, '', process), {'kind': 'emulator', 'name': name})

    def test_unrelated_windows_rejected(self):
        for title in ('Notepad', 'MuMuManager', '', 'EpicSeven Helper'):
            with self.subTest(title=title):
                self.assertIsNone(emulator.identify(title))
        self.assertTrue(emulator.is_game_window('Epic Seven'))
        self.assertFalse(emulator.is_game_window('Steam'))


class ContentRectTests(unittest.TestCase):
    def test_mumu_tab_bar_is_trimmed(self):
        self.assertEqual(emulator.content_rect(1920, 1120), (0, 40, 1920, 1120))

    def test_exact_sixteen_by_nine_is_untouched(self):
        self.assertEqual(emulator.content_rect(1920, 1080), (0, 0, 1920, 1080))
        self.assertEqual(emulator.content_rect(1600, 900), (0, 0, 1600, 900))

    def test_side_toolbar_is_trimmed(self):
        self.assertEqual(emulator.content_rect(1950, 1080), (0, 0, 1920, 1080))

    def test_unknown_chrome_keeps_client(self):
        # A 10:16 portrait window is not a phone screen with chrome.
        self.assertEqual(emulator.content_rect(1080, 1920), (0, 0, 1080, 1920))
        self.assertEqual(emulator.content_rect(64, 64), (0, 0, 64, 64))

    def test_crop_content_keeps_metadata(self):
        image = Image.new('RGB', (1920, 1120), '#050b13')
        image.info['capture_backend'] = 'test'
        cropped = emulator.crop_content(image)
        self.assertEqual(cropped.size, (1920, 1080))
        self.assertEqual(cropped.info['capture_backend'], 'test')
        self.assertEqual(emulator.crop_content(Image.new('RGB', (1920, 1080))).size, (1920, 1080))


class FakeBackend:
    def __init__(self, size=(1920, 1080)):
        self._size = size
        self.taps, self.swipes, self.presses = [], [], []

    @property
    def size(self):
        return self._size

    def tap(self, x, y, hold=.08):
        self.taps.append((round(x), round(y)))

    def swipe(self, x1, y1, x2, y2, duration=.3):
        self.swipes.append((round(x1), round(y1), round(x2), round(y2)))

    def press_start(self, x, y):
        self.presses.append(('start', round(x), round(y)))

    def press_end(self):
        self.presses.append(('end',))

    def close(self):
        return None


def backend_for(emulated=True, size=(1920, 1080)):
    backend = WindowInput.__new__(WindowInput)
    backend.target = {'hwnd': 1, 'pid': 2, 'title': 'MuMu安卓设备'}
    backend.emulated = emulated
    backend.backend = FakeBackend(size) if emulated else None
    backend.check = lambda size: 1
    backend.emergency_pressed = lambda: False
    return backend


command = lambda kind, point=(.5, .5), delta=0: SimpleNamespace(kind=kind, point=point, delta=delta, reason='')


class EmulatorInputTests(unittest.TestCase):
    def test_click_maps_normalised_to_device_pixels(self):
        backend = backend_for()
        self.assertTrue(backend.perform(command('prepare', (.25, .75)), (1920, 1120), lambda: True))
        self.assertEqual(backend.backend.taps, [(480, 810)])

    def test_click_scales_with_device_resolution(self):
        backend = backend_for(size=(1280, 720))
        backend.perform(command('prepare', (.5, .5)), (1920, 1120), lambda: True)
        self.assertEqual(backend.backend.taps, [(640, 360)])

    def test_scroll_becomes_swipes(self):
        backend = backend_for()
        backend.perform(command('scroll', (.74, .56), -120), (1920, 1120), lambda: True)
        self.assertEqual(len(backend.backend.swipes), 1)
        x1, y1, x2, y2 = backend.backend.swipes[0]
        self.assertEqual(x1, 1421)
        self.assertGreater(y1, y2)  # wheel down: the finger travels up

    def test_seven_hundred_twenty_ticks_scrolls_to_top(self):
        backend = backend_for()
        backend.perform(command('scroll', (.74, .56), 720), (1920, 1120), lambda: True)
        self.assertEqual(len(backend.backend.swipes), 6)
        self.assertLess(backend.backend.swipes[0][1], backend.backend.swipes[0][3])

    def test_inspect_gear_holds_and_releases(self):
        backend = backend_for()
        frames = []
        with patch('window_input.time.sleep'):
            result = backend.inspect_gear(command('inspect_gear', (.5, .5)), (1920, 1120),
                                          lambda: frames.append(Image.new('RGB', (1920, 1120))) or frames[-1],
                                          lambda: True)
        self.assertEqual(len(result), 2)
        self.assertEqual(backend.backend.presses[0][0], 'start')
        self.assertEqual(backend.backend.presses[-1][0], 'end')

    def test_pc_target_keeps_window_messages(self):
        backend = WindowInput.__new__(WindowInput)
        backend.target = {'hwnd': 1, 'pid': 2, 'title': 'Epic Seven'}
        backend.emulated = False
        backend.backend = None
        backend.check = lambda size: 7
        backend.emergency_pressed = lambda: False
        messages = []
        backend.send = lambda *args: messages.append(args)
        with patch('window_input.time.sleep'):
            self.assertTrue(backend.perform(command('prepare', (.5, .5)), (1600, 900), lambda: True))
        self.assertEqual([m[1] for m in messages], [0x200, 0x201, 0x202])
        self.assertEqual(messages[1][-1], (800 & 65535) | ((450 & 65535) << 16))


class SelectionTests(unittest.TestCase):
    def test_minimized_emulator_is_selectable(self):
        window = {'hwnd': 1, 'pid': 2, 'title': 'MuMu安卓设备', 'rect': [-32000, -32000, -31840, -31972],
                  'minimized': True, 'source': 'emulator', 'emulator': 'MuMu'}
        self.assertEqual(select_game_rectangle([window]), window['rect'])

    def test_minimized_pc_client_still_requires_restore(self):
        window = {'hwnd': 1, 'pid': 2, 'title': '第七史诗', 'rect': [0, 0, 1600, 900],
                  'minimized': True, 'source': 'pc', 'emulator': ''}
        with self.assertRaisesRegex(ValueError, '最小化'):
            select_game_rectangle([window])


class InputModeTests(unittest.TestCase):
    def test_modes_map_to_supported_backends(self):
        self.assertEqual(set(emulator.INPUT_MODES.values()), {'auto', 'window', 'emulator'})
        for label in emulator.INPUT_MODES:
            self.assertIn(label, list(emulator.INPUT_MODES))

    def test_pc_target_never_opens_emulator_backend(self):
        with patch('emulator.identify', return_value={'kind': 'pc', 'name': '第七史诗客户端'}):
            self.assertIsNone(emulator.open_input({'title': '第七史诗', 'pid': 1}))


class CapturePreferenceTests(unittest.TestCase):
    def test_mumu_prefers_native_capture(self):
        self.assertTrue(emulator.prefers_native_capture('MuMu安卓设备'))
        self.assertTrue(emulator.prefers_native_capture('', process='mumuplayer.exe'))
        self.assertFalse(emulator.prefers_native_capture('雷电模拟器'))
        self.assertFalse(emulator.prefers_native_capture('第七史诗'))
        self.assertFalse(emulator.prefers_native_capture('Notepad'))

    def test_emulator_capture_takes_the_device_frame_first(self):
        import window_capture
        picture = Image.new('RGB', (1920, 1080))
        with patch('window_capture.device_image', return_value=picture) as native, \
                patch('graphics_capture.capture') as wgc:
            result = window_capture.capture_client(1, 2, 'MuMu安卓设备')
        self.assertIs(result, picture)
        native.assert_called_once()
        wgc.assert_not_called()

    def test_native_failure_falls_back_to_the_window(self):
        import window_capture
        window = Image.new('RGB', (1920, 1120))
        with patch('window_capture.device_image', side_effect=RuntimeError('no ipc')), \
                patch('graphics_capture.capture', return_value=window) as wgc:
            result = window_capture.capture_client(1, 2, 'MuMu安卓设备')
        wgc.assert_called_once()
        self.assertEqual(result.size, (1920, 1080))  # tab bar trimmed

    def test_pc_client_never_uses_the_device_frame(self):
        import window_capture
        window = Image.new('RGB', (1820, 1050))
        with patch('graphics_capture.capture', return_value=window) as wgc, \
                patch('window_capture.device_image') as native:
            result = window_capture.capture_client(1, 2, 'Epic Seven')
        self.assertIs(result, window)
        wgc.assert_called_once()
        native.assert_not_called()


if __name__ == '__main__':
    unittest.main()
