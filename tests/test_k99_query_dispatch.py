"""AST-only query integration: all HID objects are mocks, no device access."""
import ast
from types import SimpleNamespace
import unittest
from unittest import mock

from test_dispatch_offline import load_selected_source, source_path


class QueryDispatchTests(unittest.TestCase):
    def setUp(self):
        self.ns = load_selected_source()
        from mchose_k99_protocol import is_k99_v3, K99_V3_IDS
        self.ns.update(is_k99_v3=is_k99_v3, K99_V3_IDS=K99_V3_IDS)
        tree = ast.parse(source_path().read_text(encoding='utf-8'))
        selected = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name in {'read_k99_config', 'main'}]
        exec(compile(ast.Module(body=selected, type_ignores=[]), str(source_path()), 'exec'), self.ns)
        self.iface = SimpleNamespace(vid=0x3837, pid=0x3033,
            product='MCHOSE K99 V3 2.4G', usage_page=1, usage=0,
            input_len=65, output_len=65, path='synthetic-only')

    def test_only_explicit_cli_routes_to_query(self):
        printer = mock.Mock()
        with mock.patch.dict(self.ns, print_once=printer):
            for args in (['--k99-query'], ['--once', '--k99-query'],
                         ['--k99-only', '--k99-query'],
                         ['--once', '--k99-only', '--k99-query', '--rapoo-only']):
                self.assertEqual(self.ns['main'](args), 2)
            printer.assert_not_called()
            self.assertEqual(self.ns['main'](['--once', '--k99-only', '--k99-query']), 0)
        printer.assert_called_once_with(k99_only=True, k99_query=True)

    def test_requires_unique_exact_collection_and_lengths_before_open(self):
        factory = mock.Mock(side_effect=AssertionError('must not open'))
        invalid = SimpleNamespace(**{**vars(self.iface), 'output_len': 64})
        with mock.patch.dict(self.ns, HidDevice=factory):
            for interfaces in ([], [invalid], [self.iface, self.iface],
                               [SimpleNamespace(**{**vars(self.iface), 'usage': 6})]):
                result = self.ns['read_k99_config'](interfaces)
                self.assertFalse(result.ok)
        factory.assert_not_called()

    def test_two_exact_reads_assemble_percent_and_close(self):
        from mchose_k99_protocol import GLW_CONFIG_REQUESTS
        config = bytearray(64)
        config[32] = 0x80 | 100
        responses = []
        for req in GLW_CONFIG_REQUESTS:
            payload = bytearray(64)
            payload[:8] = bytes([0xAA, 5, 0, 0, req.size, req.offset & 255,
                                 req.offset >> 8, 0])
            payload[8:8+req.size] = config[req.offset:req.offset+req.size]
            responses.append(b'\x00' + payload)
        dev = mock.Mock(write_mode=True, rh=1)
        dev.write_output.return_value = 65
        dev.read_input.side_effect = responses
        factory = mock.Mock(return_value=dev)
        with mock.patch.dict(self.ns, HidDevice=factory):
            result = self.ns['read_k99_config']([self.iface])
        self.assertEqual((result.ok, result.level, result.status), (True, 100, 'charging'))
        self.assertEqual(result.raw, b'')
        factory.assert_called_once_with('synthetic-only', write=True)
        self.assertEqual([c[0] for c in dev.method_calls],
                         ['write_output', 'read_input', 'write_output', 'read_input', 'close'])

    def test_unavailable_write_handle_sends_nothing(self):
        dev = mock.Mock(write_mode=False, rh=1)
        with mock.patch.dict(self.ns, HidDevice=mock.Mock(return_value=dev)):
            result = self.ns['read_k99_config']([self.iface])
        self.assertFalse(result.ok)
        dev.write_output.assert_not_called()
        dev.close.assert_called_once()

    def test_timeout_no_resend_no_second_request(self):
        dev = mock.Mock(write_mode=True, rh=1)
        dev.write_output.return_value = 65
        clock = SimpleNamespace(monotonic=mock.Mock(side_effect=[0, 2]))
        with mock.patch.dict(self.ns, HidDevice=mock.Mock(return_value=dev), time=clock):
            result = self.ns['read_k99_config']([self.iface])
        self.assertFalse(result.ok)
        dev.write_output.assert_called_once()
        dev.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
