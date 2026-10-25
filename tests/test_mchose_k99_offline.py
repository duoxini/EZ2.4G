"""Synthetic protocol and AST-only integration tests; no Win32/HID import."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

from mchose_k99_protocol import (
    K99_V3_IDS, K99_V3_WIRED_IDS, is_k99_v3,
    decode_payload, decode_input_report,
)
from test_dispatch_offline import load_selected_source, source_path


class K99ProtocolTests(unittest.TestCase):
    def test_exact_model_and_shared_receiver_identity(self):
        self.assertTrue(is_k99_v3(0x3837, 0x2020))
        self.assertTrue(is_k99_v3(0x3837, 0x3033, "MCHOSE K99 V3 2.4G"))
        for product in ("", "K99", "K99 V2", "MCHOSE K87S 2.4G"):
            self.assertFalse(is_k99_v3(0x3837, 0x3033, product))
        for pid in (0x2010, 0x201F, 0x2021):
            self.assertFalse(is_k99_v3(0x3837, pid, "MCHOSE K99 V3 2.4G"))

    def test_discharge_boundaries_and_native_prefix(self):
        for level in (0, 1, 48, 100):
            payload = bytes([0xFA, 0xFB, 7, level, 0])
            self.assertEqual(decode_payload(payload).level, level)
            for report_id in (0, 7, 0x4D, 0xFF):
                value = decode_input_report(bytes([report_id]) + payload + bytes(58))
                self.assertEqual((value.level, value.status), (level, "not_charging"))

    def test_charging_does_not_invent_a_percentage(self):
        for opaque_value in (0, 52, 100, 255):
            event = decode_payload(bytes([0xFA, 0xFB, 7, opaque_value, 1]))
            self.assertIsNone(event.level)
            self.assertEqual(event.status, "charging")

    def test_rejects_malformed_notification(self):
        valid = b"\xfa\xfb\x07\x32\x00"
        for length in range(5):
            self.assertIsNone(decode_payload(valid[:length]))
            self.assertIsNone(decode_input_report(b"\x00" + valid[:length]))
        for index in (0, 1, 2):
            altered = bytearray(valid)
            altered[index] ^= 1
            self.assertIsNone(decode_payload(altered))
        for percent in (101, 127, 255):
            self.assertIsNone(decode_payload(bytes([0xFA, 0xFB, 7, percent, 0])))
        for state in (2, 255):
            self.assertIsNone(decode_payload(bytes([0xFA, 0xFB, 7, 50, state])))

    def test_byteslike_only_and_distinct_api_framing(self):
        payload = b"\xfa\xfb\x07\x32\x00"
        for value in (payload, bytearray(payload), memoryview(payload)):
            self.assertEqual(decode_payload(value).level, 50)
        for value in (None, "fafb073200", list(payload), 0):
            self.assertIsNone(decode_payload(value))
            self.assertIsNone(decode_input_report(value))
        self.assertIsNone(decode_input_report(payload))
        self.assertIsNone(decode_payload(b"\x00" + payload))


class K99IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.ns = load_selected_source()
        path = source_path()
        tree = ast.parse(path.read_text(encoding='utf-8'))
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                 and n.name in {'read_k99_v3', 'main'}]
        self.ns.update(K99_V3_IDS=K99_V3_IDS, K99_V3_WIRED_IDS=K99_V3_WIRED_IDS,
                       is_k99_v3=is_k99_v3, decode_k99_input_report=decode_input_report)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), self.ns)

    def iface(self, **kwargs):
        data = dict(vid=0x3837, pid=0x3033, product='MCHOSE K99 V3 2.4G',
                    usage_page=1, usage=0, input_len=64, output_len=64,
                    feature_len=64, path='synthetic-k99', instance='SYNTHETIC')
        data.update(kwargs)
        return SimpleNamespace(**data)

    def clock(self):
        times = iter([0.0] * 4 + [0.01, 2.0])
        return SimpleNamespace(monotonic=lambda: next(times, 2.0))

    def test_valid_notification_uses_only_read_and_closes(self):
        device = mock.Mock()
        device.read_input.return_value = b'\x00\xfa\xfb\x07\x35\x00'
        factory = mock.Mock(return_value=device)
        with mock.patch.dict(self.ns, HidDevice=factory, time=self.clock()):
            result = self.ns['read_k99_v3']([self.iface()], seconds=0.1)
        self.assertEqual((result.ok, result.level), (True, 53))
        self.assertEqual(result.raw, b'')
        factory.assert_called_once_with('synthetic-k99', write=False)
        self.assertEqual([c[0] for c in device.method_calls], ['read_input', 'close'])
        self.assertLessEqual(device.read_input.call_args.args[1], 90)

    def test_no_open_for_wrong_model_boot_keyboard_collection_or_short_report(self):
        for iface in (self.iface(product='MCHOSE K87S 2.4G'),
                      self.iface(pid=0x2010), self.iface(pid=0x201F),
                      self.iface(usage=6), self.iface(usage_page=0xFF00, usage=1),
                      self.iface(input_len=5)):
            factory = mock.Mock(side_effect=AssertionError('device access forbidden'))
            with mock.patch.dict(self.ns, HidDevice=factory):
                result = self.ns['read_k99_v3']([iface])
            self.assertFalse(result.ok)
            factory.assert_not_called()

    def test_charging_notification_stays_unknown_percent(self):
        device = mock.Mock()
        device.read_input.return_value = b'\x00\xfa\xfb\x07\xff\x01'
        with mock.patch.dict(self.ns, HidDevice=mock.Mock(return_value=device), time=self.clock()):
            result = self.ns['read_k99_v3']([self.iface()], seconds=0.1)
        self.assertFalse(result.ok)
        self.assertIsNone(result.level)
        self.assertEqual(result.status, 'charging')
        self.assertIn('充电通知', result.detail)
        device.close.assert_called_once()

    def test_empty_and_malformed_reads_do_not_produce_battery(self):
        for data, count in ((None, 0), (b'\x00\xfa\xfb\x07\xff\x00', 1)):
            device = mock.Mock()
            device.read_input.return_value = data
            with mock.patch.dict(self.ns, HidDevice=mock.Mock(return_value=device), time=self.clock()):
                result = self.ns['read_k99_v3']([self.iface()], seconds=0.1)
            self.assertFalse(result.ok)
            self.assertIn(f'输入报告 {count} 份', result.detail)
            device.close.assert_called_once()

    def test_read_error_closes_device_and_preserves_diagnostic(self):
        device = mock.Mock()
        device.read_input.side_effect = self.ns['HidError']('synthetic failure')
        with mock.patch.dict(self.ns, HidDevice=mock.Mock(return_value=device), time=self.clock()):
            result = self.ns['read_k99_v3']([self.iface()], seconds=0.1)
        self.assertFalse(result.ok)
        self.assertIn('synthetic failure', result.detail)
        device.close.assert_called_once()

    def test_zero_budget_does_not_open(self):
        factory = mock.Mock(side_effect=AssertionError('device access forbidden'))
        with mock.patch.dict(self.ns, HidDevice=factory):
            result = self.ns['read_k99_v3']([self.iface()], seconds=0)
        self.assertFalse(result.ok)
        factory.assert_not_called()

    def test_k99_is_excluded_from_custom_and_generic_discovery(self):
        forbidden = mock.Mock(side_effect=AssertionError('fallback forbidden'))
        with mock.patch.dict(self.ns, custom_names=forbidden, user_protocols=forbidden,
                             _unknown_reading=forbidden, _read_user_protocol=forbidden):
            self.assertEqual(self.ns['discover_extras']([
                self.iface(), self.iface(pid=0x2020, product='MCHOSE K99 V3')]), {})
        forbidden.assert_not_called()
        self.assertIn((0x3837, 0x2020), self.ns['known_ids']())
        self.assertNotIn((0x3837, 0x3033), self.ns['known_ids']())

    def test_read_all_routes_exact_k99_identity(self):
        absent = self.ns['Reading'](present=False)
        keyboard = self.ns['Reading'](name='MCHOSE K99 V3')
        reader = mock.Mock(return_value=keyboard)
        with mock.patch.dict(self.ns, read_mouse=mock.Mock(return_value=absent),
                             read_headset=mock.Mock(return_value=absent),
                             read_k99_config=reader,
                             read_k99_v3=mock.Mock(side_effect=AssertionError('passive fallback forbidden')),
                             discover_extras=mock.Mock(return_value={})):
            result = self.ns['read_all']([self.iface()])
            self.assertIs(result['keyboard'], keyboard)
            self.ns['read_all']([self.iface(product='MCHOSE K87S 2.4G')])
        reader.assert_called_once()

    def test_k99_only_skips_other_readers_config_and_cache(self):
        forbidden = mock.Mock(side_effect=AssertionError('outside K99 scope'))
        enumerator = mock.Mock(return_value=[self.iface()])
        reader = mock.Mock(return_value=self.ns['Reading'](name='MCHOSE K99 V3'))
        with mock.patch.dict(self.ns, enumerate_hid=enumerator, read_k99_v3=reader,
                             read_all=forbidden, read_rapoo=forbidden, read_mouse=forbidden,
                             read_headset=forbidden, apply_last_known=forbidden,
                             load_config=forbidden, save_config=forbidden):
            self.ns['print_once'](k99_only=True)
        enumerator.assert_called_once_with(K99_V3_IDS)
        reader.assert_called_once_with(enumerator.return_value)
        forbidden.assert_not_called()

    def test_cli_rejects_conflicting_or_unbounded_scope_before_io(self):
        forbidden = mock.Mock(side_effect=AssertionError('device access forbidden'))
        with mock.patch.dict(self.ns, print_once=forbidden, list_devices=forbidden,
                             run_gui=forbidden, install_all=forbidden):
            for argv in (['--k99-only'], ['--list', '--k99-only'],
                         ['--once', '--rapoo-only', '--k99-only']):
                self.assertEqual(self.ns['main'](argv), 2)
        forbidden.assert_not_called()

    def test_cli_routes_k99_only_to_limited_entry(self):
        printer = mock.Mock()
        with mock.patch.dict(self.ns, print_once=printer):
            self.assertEqual(self.ns['main'](['--once', '--k99-only']), 0)
        printer.assert_called_once_with(rapoo_only=False, k99_only=True)


if __name__ == '__main__':
    unittest.main()
