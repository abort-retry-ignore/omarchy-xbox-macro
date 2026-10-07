"""Offline controller regression tests; no root, hardware or uinput needed."""
import errno
import importlib.machinery
import importlib.util
from pathlib import Path
import socket
import threading
import time
import tomllib
from types import SimpleNamespace as NS
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('hd2', str(ROOT / 'hd2-macro'))
m = importlib.util.module_from_spec(importlib.util.spec_from_loader('hd2', loader))
loader.exec_module(m)
e = m.e


class FakeUI:
    def __init__(self):
        self.values = {}
        self.syncs = 0

    def write(self, kind, code, value):
        self.values[kind, code] = value

    def syn(self):
        self.syncs += 1


def pad():
    p = object.__new__(m.Pad)
    p.ui = FakeUI()
    p.lock = threading.RLock()
    p.phys, p.macro, p.sent = {}, {}, {}
    return p


def device(name, vid, pid, path, axes):
    d = NS(name=name, path=path, info=NS(vendor=vid, product=pid, bustype=5))
    d.capabilities = lambda: {
        e.EV_ABS: [(code, NS(min=lo, max=hi)) for code, lo, hi in axes]
    }
    d.read = lambda: []
    d.ungrab = mock.Mock()
    d.close = mock.Mock()
    return d


def report(**values):
    data = bytearray(17)
    offsets = {'up': 0, 'right': 1, 'down': 2, 'left': 3,
               'a': 4, 'lt': 10, 'rt': 11, 'menu': 12}
    for name, value in values.items():
        data[offsets[name]] = value
    return bytes(data)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        # Never open any real raw device, even when run on a user's desktop.
        patch = mock.patch.object(m.NimbusHID, 'node_for',
                                  side_effect=FileNotFoundError(errno.ENOENT, 'offline'))
        patch.start()
        self.addCleanup(patch.stop)
        self.pad = pad()
        self.cfg = tomllib.loads((ROOT / 'config.example.toml').read_text())
        self.nimbus = device('Nimbus', 0x0111, 0x1420, '/dev/input/event21', [
            (e.ABS_X, -127, 127), (e.ABS_Y, -127, 127),
            (e.ABS_Z, -127, 127), (e.ABS_RZ, -127, 127),
            (e.ABS_HAT0X, -1, 1), (e.ABS_HAT0Y, -1, 1)])
        self.xbox = device('Xbox Wireless Controller', 0x045e, 0x0b12,
                           '/dev/input/event30', [
            (e.ABS_X, -32768, 32767), (e.ABS_Y, -32768, 32767),
            (e.ABS_RX, -32768, 32767), (e.ABS_RY, -32768, 32767),
            (e.ABS_Z, 0, 1023), (e.ABS_RZ, 0, 1023),
            (e.ABS_HAT0X, -1, 1), (e.ABS_HAT0Y, -1, 1)])
        self.log = mock.Mock()
        self.pt = m.Passthrough(self.pad, self.cfg, log=self.log)
        self.pt.devs = {d.path: d for d in (self.nimbus, self.xbox)}
        self.pt.configure()
        self.log.reset_mock()

    def send(self, dev, kind, code, value):
        dev.read = lambda: [NS(type=kind, code=code, value=value)]
        self.assertTrue(self.pt.pump(dev))

    def value(self, code, kind=e.EV_ABS):
        with self.pad.lock:
            return self.pad.ui.values.get((kind, code), 0)

    def wait_value(self, code, value):
        end = time.monotonic() + 2
        while time.monotonic() < end:
            if self.value(code) == value:
                return
            time.sleep(0.005)
        self.fail(f'axis {code} did not become {value}; got {self.value(code)}')

    def reader(self):
        read_sock, write_sock = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
        read_sock.setblocking(False)
        fd = read_sock.detach()
        with mock.patch.object(m.NimbusHID, 'node_for', return_value='/dev/offline-hidraw'), \
                mock.patch.object(m.os, 'open', return_value=fd):
            reader = m.NimbusHID(self.nimbus, self.pad, log=self.log)
        self.addCleanup(write_sock.close)
        self.addCleanup(reader.close)
        return reader, write_sock

    def test_raw_direction_bytes(self):
        for name, axis, expected in [('up', e.ABS_HAT0Y, -1),
                                     ('down', e.ABS_HAT0Y, 1),
                                     ('left', e.ABS_HAT0X, -1),
                                     ('right', e.ABS_HAT0X, 1)]:
            with self.subTest(direction=name):
                self.assertEqual(m.NimbusHID.decode(report(**{name: 14}))[axis], expected)
        self.assertEqual(m.NimbusHID.decode(report())[e.ABS_HAT0Y], 0)

    def test_diagonals_and_opposing_directions(self):
        vals = m.NimbusHID.decode(report(up=90, right=255))
        self.assertEqual((vals[e.ABS_HAT0X], vals[e.ABS_HAT0Y]), (1, -1))
        vals = m.NimbusHID.decode(report(up=90, down=255, left=2, right=1))
        self.assertEqual((vals[e.ABS_HAT0X], vals[e.ABS_HAT0Y]), (0, 0))

    def test_analog_trigger_pressure(self):
        for pressure in (0, 11, 49, 144, 163, 255):
            vals = m.NimbusHID.decode(report(lt=pressure, rt=255-pressure))
            self.assertEqual(vals[e.ABS_Z], pressure)
            self.assertEqual(vals[e.ABS_RZ], 255-pressure)

    def test_rejects_wrong_report_lengths(self):
        for length in (0, 4, 16, 18, 64):
            self.assertIsNone(m.NimbusHID.decode(bytes(length)))

    def test_profiles_do_not_change_xbox_axes(self):
        self.send(self.nimbus, e.EV_ABS, e.ABS_Y, 127)
        self.assertEqual(self.value(e.ABS_Y), -32768)
        self.send(self.nimbus, e.EV_ABS, e.ABS_Z, 127)
        self.assertEqual(self.value(e.ABS_RX), 32767)
        self.pad.drop(self.nimbus.path)
        self.send(self.xbox, e.EV_ABS, e.ABS_Y, -32768)
        self.assertEqual(self.value(e.ABS_Y), -32768)
        self.send(self.xbox, e.EV_ABS, e.ABS_Z, 1023)
        self.assertEqual(self.value(e.ABS_Z), 255)
        self.assertFalse(self.pt.wants_raw(self.xbox))

    def test_kernel_nimbus_hat_is_ignored_but_xbox_hat_works(self):
        self.send(self.nimbus, e.EV_ABS, e.ABS_HAT0Y, -1)
        self.assertEqual(self.value(e.ABS_HAT0Y), 0)
        self.send(self.xbox, e.EV_ABS, e.ABS_HAT0Y, -1)
        self.assertEqual(self.value(e.ABS_HAT0Y), -1)

    def test_button_mapping(self):
        pairs = [(e.BTN_A, e.BTN_A), (e.BTN_B, e.BTN_B),
                 (e.BTN_C, e.BTN_X), (e.BTN_NORTH, e.BTN_Y),
                 (e.BTN_WEST, e.BTN_TL), (e.BTN_Z, e.BTN_TR)]
        for src, dst in pairs:
            self.send(self.nimbus, e.EV_KEY, src, 1)
            self.assertEqual(self.value(dst, e.EV_KEY), 1)
            self.send(self.nimbus, e.EV_KEY, src, 0)
            self.assertEqual(self.value(dst, e.EV_KEY), 0)

    def test_menu_alone_is_deferred_and_pulsed_on_release(self):
        self.send(self.nimbus, e.EV_KEY, e.KEY_HOMEPAGE, 1)
        self.assertEqual(self.value(e.BTN_SELECT, e.EV_KEY), 0)
        self.send(self.nimbus, e.EV_KEY, e.KEY_HOMEPAGE, 0)
        self.assertEqual(self.value(e.BTN_SELECT, e.EV_KEY), 1)
        chords = self.pt.chords[self.nimbus.path]
        self.assertLessEqual(self.pt.timeout(), 0.08)
        self.assertGreater(self.pt.timeout(), 0)
        chords.tick(chords.deadline - 0.001)
        self.assertEqual(self.value(e.BTN_SELECT, e.EV_KEY), 1)
        with mock.patch.object(m.time, 'monotonic', return_value=chords.deadline + 0.001):
            self.pt.tick()
        self.assertEqual(self.value(e.BTN_SELECT, e.EV_KEY), 0)
        self.assertEqual(self.pt.timeout(), 1.0)

    def test_menu_bumper_combinations_hold_clicks_without_back_or_bumpers(self):
        for physical, bumper, target in [(e.BTN_WEST, e.BTN_TL, e.BTN_THUMBL),
                                         (e.BTN_Z, e.BTN_TR, e.BTN_THUMBR)]:
            with self.subTest(target=target):
                self.send(self.nimbus, e.EV_KEY, e.KEY_HOMEPAGE, 1)
                self.send(self.nimbus, e.EV_KEY, physical, 1)
                self.assertEqual(self.value(target, e.EV_KEY), 1)
                self.assertEqual(self.value(bumper, e.EV_KEY), 0)
                self.assertEqual(self.value(e.BTN_SELECT, e.EV_KEY), 0)
                self.send(self.nimbus, e.EV_KEY, physical, 0)
                self.assertEqual(self.value(target, e.EV_KEY), 0)
                self.send(self.nimbus, e.EV_KEY, e.KEY_HOMEPAGE, 0)
                self.assertEqual(self.value(e.BTN_SELECT, e.EV_KEY), 0)
                self.assertIsNone(self.pt.chords[self.nimbus.path].deadline)

    def test_menu_y_emulates_start_without_back_or_y_in_both_release_orders(self):
        for menu_first in (False, True):
            with self.subTest(menu_released_first=menu_first):
                self.send(self.nimbus, e.EV_KEY, e.KEY_HOMEPAGE, 1)
                self.send(self.nimbus, e.EV_KEY, e.BTN_NORTH, 1)
                self.assertEqual(self.value(e.BTN_START, e.EV_KEY), 1)
                self.assertEqual(self.value(e.BTN_SELECT, e.EV_KEY), 0)
                self.assertEqual(self.value(e.BTN_Y, e.EV_KEY), 0)
                first = e.KEY_HOMEPAGE if menu_first else e.BTN_NORTH
                second = e.BTN_NORTH if menu_first else e.KEY_HOMEPAGE
                self.send(self.nimbus, e.EV_KEY, first, 0)
                self.assertEqual(self.value(e.BTN_START, e.EV_KEY), 0)
                self.assertEqual(self.value(e.BTN_Y, e.EV_KEY), 0)
                self.send(self.nimbus, e.EV_KEY, second, 0)
                self.assertEqual(self.value(e.BTN_SELECT, e.EV_KEY), 0)
                self.assertEqual(self.value(e.BTN_Y, e.EV_KEY), 0)
                self.assertIsNone(self.pt.chords[self.nimbus.path].deadline)
                self.send(self.nimbus, e.EV_KEY, e.BTN_NORTH, 1)
                self.assertEqual(self.value(e.BTN_Y, e.EV_KEY), 1)
                self.assertEqual(self.value(e.BTN_START, e.EV_KEY), 0)
                self.send(self.nimbus, e.EV_KEY, e.BTN_NORTH, 0)

    def test_menu_y_does_not_invoke_y_macro_hotkey(self):
        hit = mock.Mock()
        self.pt.hotkeys = {e.BTN_Y: 'y-macro'}
        self.pt.on_button = hit
        self.send(self.nimbus, e.EV_KEY, e.KEY_HOMEPAGE, 1)
        self.send(self.nimbus, e.EV_KEY, e.BTN_NORTH, 1)
        hit.assert_not_called()
        self.assertEqual(self.value(e.BTN_START, e.EV_KEY), 1)

    def test_modifier_released_first_does_not_leak_held_bumper(self):
        self.send(self.nimbus, e.EV_KEY, e.KEY_HOMEPAGE, 1)
        self.send(self.nimbus, e.EV_KEY, e.BTN_WEST, 1)
        self.send(self.nimbus, e.EV_KEY, e.KEY_HOMEPAGE, 0)
        self.assertEqual(self.value(e.BTN_THUMBL, e.EV_KEY), 0)
        self.assertEqual(self.value(e.BTN_TL, e.EV_KEY), 0)
        self.assertEqual(self.value(e.BTN_SELECT, e.EV_KEY), 0)
        self.send(self.nimbus, e.EV_KEY, e.BTN_WEST, 2)  # autorepeat stays consumed
        self.assertEqual(self.value(e.BTN_TL, e.EV_KEY), 0)
        self.send(self.nimbus, e.EV_KEY, e.BTN_WEST, 0)
        self.send(self.nimbus, e.EV_KEY, e.BTN_WEST, 1)  # new ordinary press works
        self.assertEqual(self.value(e.BTN_TL, e.EV_KEY), 1)

    def test_both_clicks_can_be_held_and_released_independently(self):
        self.send(self.nimbus, e.EV_KEY, e.KEY_HOMEPAGE, 1)
        self.send(self.nimbus, e.EV_KEY, e.BTN_WEST, 1)
        self.send(self.nimbus, e.EV_KEY, e.BTN_Z, 1)
        self.assertEqual(self.value(e.BTN_THUMBL, e.EV_KEY), 1)
        self.assertEqual(self.value(e.BTN_THUMBR, e.EV_KEY), 1)
        self.send(self.nimbus, e.EV_KEY, e.BTN_WEST, 0)
        self.assertEqual(self.value(e.BTN_THUMBL, e.EV_KEY), 0)
        self.assertEqual(self.value(e.BTN_THUMBR, e.EV_KEY), 1)
        self.send(self.nimbus, e.EV_KEY, e.KEY_HOMEPAGE, 0)
        self.assertEqual(self.value(e.BTN_THUMBR, e.EV_KEY), 0)
        self.assertEqual(self.value(e.BTN_SELECT, e.EV_KEY), 0)
        self.send(self.nimbus, e.EV_KEY, e.BTN_Z, 0)
        self.assertEqual(self.value(e.BTN_TR, e.EV_KEY), 0)

    def test_bumper_first_is_released_when_menu_substitutes_click(self):
        self.send(self.nimbus, e.EV_KEY, e.BTN_WEST, 1)
        self.assertEqual(self.value(e.BTN_TL, e.EV_KEY), 1)
        self.send(self.nimbus, e.EV_KEY, e.KEY_HOMEPAGE, 1)
        self.assertEqual(self.value(e.BTN_TL, e.EV_KEY), 0)
        self.assertEqual(self.value(e.BTN_THUMBL, e.EV_KEY), 1)
        self.send(self.nimbus, e.EV_KEY, e.BTN_WEST, 0)
        self.send(self.nimbus, e.EV_KEY, e.KEY_HOMEPAGE, 0)
        self.assertEqual(self.value(e.BTN_SELECT, e.EV_KEY), 0)

    def test_menu_repeats_and_orphan_releases_do_not_generate_extra_actions(self):
        self.send(self.nimbus, e.EV_KEY, e.KEY_HOMEPAGE, 0)
        self.assertEqual(self.value(e.BTN_SELECT, e.EV_KEY), 0)
        self.send(self.nimbus, e.EV_KEY, e.KEY_HOMEPAGE, 1)
        self.send(self.nimbus, e.EV_KEY, e.BTN_WEST, 1)
        self.send(self.nimbus, e.EV_KEY, e.KEY_HOMEPAGE, 2)
        self.send(self.nimbus, e.EV_KEY, e.KEY_HOMEPAGE, 1)
        self.send(self.nimbus, e.EV_KEY, e.KEY_HOMEPAGE, 0)
        self.assertEqual(self.value(e.BTN_SELECT, e.EV_KEY), 0)
        self.assertEqual(self.value(e.BTN_THUMBL, e.EV_KEY), 0)

    def test_same_profile_reload_preserves_held_combination(self):
        self.send(self.nimbus, e.EV_KEY, e.KEY_HOMEPAGE, 1)
        self.send(self.nimbus, e.EV_KEY, e.BTN_WEST, 1)
        old = self.pt.chords[self.nimbus.path]
        self.pt.configure()
        self.assertIs(self.pt.chords[self.nimbus.path], old)
        self.assertEqual(self.value(e.BTN_THUMBL, e.EV_KEY), 1)
        self.send(self.nimbus, e.EV_KEY, e.BTN_WEST, 0)
        self.send(self.nimbus, e.EV_KEY, e.KEY_HOMEPAGE, 0)
        self.assertEqual(self.value(e.BTN_SELECT, e.EV_KEY), 0)

    def test_removing_chords_clears_held_click(self):
        self.send(self.nimbus, e.EV_KEY, e.KEY_HOMEPAGE, 1)
        self.send(self.nimbus, e.EV_KEY, e.BTN_WEST, 1)
        self.cfg['passthrough']['profile'][0].pop('chords')
        self.pt.configure()
        self.assertNotIn(self.nimbus.path, self.pt.chords)
        self.assertEqual(self.value(e.BTN_THUMBL, e.EV_KEY), 0)
        self.send(self.nimbus, e.EV_KEY, e.KEY_HOMEPAGE, 0)
        self.assertEqual(self.value(e.BTN_SELECT, e.EV_KEY), 0)

    def test_disconnect_cancels_click_and_pending_menu_tap(self):
        self.send(self.nimbus, e.EV_KEY, e.KEY_HOMEPAGE, 1)
        self.send(self.nimbus, e.EV_KEY, e.BTN_WEST, 1)
        self.pt.release(self.nimbus)
        self.assertEqual(self.value(e.BTN_THUMBL, e.EV_KEY), 0)
        self.assertEqual(self.value(e.BTN_SELECT, e.EV_KEY), 0)
        self.assertNotIn(self.nimbus.path, self.pt.chords)
        self.pt.devs[self.nimbus.path] = self.nimbus
        self.pt.configure()
        self.send(self.nimbus, e.EV_KEY, e.KEY_HOMEPAGE, 1)
        self.send(self.nimbus, e.EV_KEY, e.KEY_HOMEPAGE, 0)
        self.assertEqual(self.value(e.BTN_SELECT, e.EV_KEY), 1)
        self.pt.release(self.nimbus)
        self.assertEqual(self.value(e.BTN_SELECT, e.EV_KEY), 0)
        self.pt.tick()
        self.assertEqual(self.value(e.BTN_SELECT, e.EV_KEY), 0)

    def test_chords_do_not_invoke_bumper_macro_hotkeys(self):
        hit = mock.Mock()
        self.pt.hotkeys = {e.BTN_TL: 'left-bumper-macro'}
        self.pt.on_button = hit
        self.send(self.nimbus, e.EV_KEY, e.KEY_HOMEPAGE, 1)
        self.send(self.nimbus, e.EV_KEY, e.BTN_WEST, 1)
        hit.assert_not_called()
        self.assertEqual(self.value(e.BTN_THUMBL, e.EV_KEY), 1)

    def test_xbox_view_and_bumpers_remain_immediate(self):
        self.assertNotIn(self.xbox.path, self.pt.chords)
        self.send(self.xbox, e.EV_KEY, e.BTN_SELECT, 1)
        self.assertEqual(self.value(e.BTN_SELECT, e.EV_KEY), 1)
        self.send(self.xbox, e.EV_KEY, e.BTN_TL, 1)
        self.assertEqual(self.value(e.BTN_TL, e.EV_KEY), 1)
        self.assertEqual(self.value(e.BTN_THUMBL, e.EV_KEY), 0)

    def test_xbox_stick_clicks_pass_through(self):
        for button in (e.BTN_THUMBL, e.BTN_THUMBR):
            self.send(self.xbox, e.EV_KEY, button, 1)
            self.assertEqual(self.value(button, e.EV_KEY), 1)
            self.send(self.xbox, e.EV_KEY, button, 0)
            self.assertEqual(self.value(button, e.EV_KEY), 0)

    def test_mapped_hotkeys(self):
        hit = mock.Mock()
        self.pt.hotkeys = {e.BTN_Y: 'y-hotkey'}
        self.pt.on_button = hit
        self.send(self.nimbus, e.EV_KEY, e.BTN_NORTH, 1)
        hit.assert_called_once_with('y-hotkey')
        self.assertEqual(self.value(e.BTN_Y, e.EV_KEY), 0)
        hit.reset_mock()
        self.send(self.nimbus, e.EV_KEY, e.BTN_WEST, 1)
        hit.assert_not_called()
        self.assertEqual(self.value(e.BTN_TL, e.EV_KEY), 1)

    def test_digital_trigger_fallback_without_raw_access(self):
        self.send(self.nimbus, e.EV_KEY, e.BTN_TL, 1)
        self.assertEqual(self.value(e.ABS_Z), 255)
        self.send(self.nimbus, e.EV_KEY, e.BTN_TL, 0)
        self.assertEqual(self.value(e.ABS_Z), 0)

    def test_evdev_does_not_overwrite_raw_pressure(self):
        self.pt.raw[self.nimbus.path] = NS(alive=True)
        self.pad.feed_axes({e.ABS_Z: 49}, self.nimbus.path)
        self.send(self.nimbus, e.EV_KEY, e.BTN_TL, 1)
        self.assertEqual(self.value(e.ABS_Z), 49)
        self.send(self.nimbus, e.EV_KEY, e.BTN_TL, 0)
        self.assertEqual(self.value(e.ABS_Z), 49)
        self.send(self.xbox, e.EV_ABS, e.ABS_Z, 1023)
        self.assertEqual(self.value(e.ABS_Z), 255)
        self.pad.drop(self.xbox.path)
        self.assertEqual(self.value(e.ABS_Z), 49)

    def test_atomic_diagonal_and_multi_pad_merge(self):
        self.pad.feed_axes({e.ABS_HAT0X: 1, e.ABS_HAT0Y: -1}, self.nimbus.path)
        self.assertEqual(self.pad.ui.syncs, 1)
        self.pad.feed_axes({e.ABS_HAT0X: 0, e.ABS_HAT0Y: 0}, self.xbox.path)
        self.assertEqual(self.value(e.ABS_HAT0Y), -1)
        self.pad.drop(self.nimbus.path)
        self.assertEqual(self.value(e.ABS_HAT0X), 0)
        self.assertEqual(self.value(e.ABS_HAT0Y), 0)

    def test_shared_buttons_and_macro_override(self):
        self.send(self.nimbus, e.EV_KEY, e.BTN_A, 1)
        self.send(self.xbox, e.EV_KEY, e.BTN_A, 1)
        self.send(self.nimbus, e.EV_KEY, e.BTN_A, 0)
        self.assertEqual(self.value(e.BTN_A, e.EV_KEY), 1)
        self.pad.drop(self.xbox.path)
        self.assertEqual(self.value(e.BTN_A, e.EV_KEY), 0)
        self.pad.set('UP', True)
        self.pad.feed_axes({e.ABS_HAT0Y: 1}, self.nimbus.path)
        self.assertEqual(self.value(e.ABS_HAT0Y), -1)
        self.pad.set('UP', False)
        self.assertEqual(self.value(e.ABS_HAT0Y), 1)

    def test_reader_with_no_idle_reports_then_press_and_release(self):
        reader, writer = self.reader()
        reader.start()
        time.sleep(0.02)  # Bluetooth idle silence must not terminate the reader
        self.assertTrue(reader.alive)
        writer.send(report(up=90, right=99, lt=49, rt=163))
        self.wait_value(e.ABS_Z, 49)
        self.assertEqual(self.value(e.ABS_HAT0X), 1)
        self.assertEqual(self.value(e.ABS_HAT0Y), -1)
        self.assertEqual(self.value(e.ABS_RZ), 163)
        writer.send(report())
        self.wait_value(e.ABS_Z, 0)
        self.assertEqual(self.value(e.ABS_HAT0Y), 0)

    def test_release_stops_reader_and_clears_held_input(self):
        reader, writer = self.reader()
        self.pt.raw[self.nimbus.path] = reader
        reader.start()
        writer.send(report(left=255, lt=255))
        self.wait_value(e.ABS_Z, 255)
        self.pt.release(self.nimbus)
        self.assertFalse(reader.alive)
        self.assertEqual(self.value(e.ABS_Z), 0)
        self.assertEqual(self.value(e.ABS_HAT0X), 0)
        self.assertNotIn(self.nimbus.path, self.pt.raw)

    def test_permission_retry_and_recovery_without_restart(self):
        raw = NS(alive=True, node='/dev/offline-hidraw', start=mock.Mock(), close=mock.Mock())
        error = PermissionError(errno.EACCES, 'Permission denied', raw.node)
        with mock.patch.object(m, 'NimbusHID', side_effect=[error, error, raw]):
            self.pt.rescan_raw()
            self.pt.rescan_raw()
            self.assertEqual(self.log.call_count, 1, 'do not spam permission errors')
            self.pt.rescan_raw()
        self.assertIs(self.pt.raw[self.nimbus.path], raw)
        raw.start.assert_called_once()
        self.cfg['passthrough']['profile'][0].pop('raw')
        self.pt.rescan_raw()
        raw.close.assert_called_once()
        self.assertNotIn(self.nimbus.path, self.pt.raw)


if __name__ == '__main__':
    unittest.main()
