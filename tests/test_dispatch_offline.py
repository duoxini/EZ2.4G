"""Offline regression tests for my_devices.py dispatch and one-shot output.

The production module initializes Win32 DLLs at import time, so these tests
extract only selected syntax-tree nodes and execute them in a stub namespace.
No production module import, device enumeration, or device I/O is performed.
"""
from __future__ import annotations

import ast
from mchose_k99_protocol import K99_V3_WIRED_IDS, is_k99_v3
import dataclasses
import os
from pathlib import Path
import time
import unittest
from unittest import mock


def source_path() -> Path:
    override = os.environ.get("EZ24G_SOURCE")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[1] / "my_devices.py"


def load_selected_source():
    path = source_path()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    wanted_functions = {
        "read_mouse", "read_headset", "read_all", "known_ids",
        "read_rapoo", "discover_extras", "print_once", "apply_last_known",
    }
    selected = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name in {"Reading", "DeviceSpec", "HidError"}:
            selected.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "DEVICES"
            for target in node.targets
        ):
            selected.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in wanted_functions:
            selected.append(node)
    found = {n.name for n in selected if isinstance(n, (ast.ClassDef, ast.FunctionDef))}
    missing = ({"Reading", "DeviceSpec", "HidError"} | wanted_functions) - found
    if missing:
        raise AssertionError(f"Missing expected source nodes: {sorted(missing)}")

    ns = {
        "dataclasses": dataclasses,
        "K99_V3_WIRED_IDS": K99_V3_WIRED_IDS,
        "is_k99_v3": is_k99_v3,
        "time": time,
        "Optional": __import__("typing").Optional,
        "HidIface": object,
        "RAPOO_IDS": frozenset({(0x24AE, 0x4621), (0x24AE, 0x1421)}),
        "print": mock.Mock(),
    }
    module = ast.Module(body=selected, type_ignores=[])
    exec(compile(module, str(path), "exec"), ns)
    return ns


class OfflineDispatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = load_selected_source()

    def iface(self, vid, pid, **overrides):
        values = dict(
            vid=vid, pid=pid, usage_page=0xFF00, usage=0x0E, input_len=64,
            output_len=64, feature_len=0, product="Synthetic HID",
            instance="SYNTHETIC", path="synthetic-only",
        )
        values.update(overrides)
        from types import SimpleNamespace
        return SimpleNamespace(**values)

    def test_legacy_device_readers_dispatch_to_vendor_protocols(self):
        mouse_spec, headset_spec = self.ns["DEVICES"]
        mouse_iface = self.iface(*mouse_spec.ids[0], usage_page=0xFF05)
        headset_iface = self.iface(*headset_spec.ids[0])
        mouse_result = self.ns["Reading"](ok=True, level=71)
        headset_result = self.ns["Reading"](ok=True, level=62)
        with mock.patch.dict(self.ns, {
            "atk_read_at": mock.Mock(return_value=mouse_result),
            "mchose_read": mock.Mock(return_value=headset_result),
            "jl_read": mock.Mock(),
            "read_standard_battery": mock.Mock(),
            "listen_battery": mock.Mock(),
        }):
            self.assertIs(self.ns["read_mouse"]([mouse_iface]), mouse_result)
            self.assertIs(self.ns["read_headset"]([headset_iface]), headset_result)
        self.assertEqual(mouse_result.level, 71)
        self.assertEqual(headset_result.level, 62)

    def test_known_ids_contains_dedicated_device_ids(self):
        expected = ({pair for spec in self.ns["DEVICES"] for pair in spec.ids}
                    | self.ns["RAPOO_IDS"] | K99_V3_WIRED_IDS)
        self.assertEqual(self.ns["known_ids"](), expected)

    def test_known_device_is_excluded_from_extra_discovery(self):
        spec = self.ns["DEVICES"][0]
        known_ifaces = [self.iface(*spec.ids[0]),
                        self.iface(0x24AE, 0x4621)]
        unknown_reading = mock.Mock()
        with mock.patch.dict(self.ns, {
            "known_ids": lambda: ({pair for item in self.ns["DEVICES"] for pair in item.ids}
                                   | self.ns["RAPOO_IDS"] | K99_V3_WIRED_IDS),
            "custom_names": mock.Mock(return_value={}),
            "user_protocols": mock.Mock(return_value={}),
            "_unknown_reading": unknown_reading,
        }):
            extras = self.ns["discover_extras"](known_ifaces)
        self.assertEqual(extras, {})
        unknown_reading.assert_not_called()

    def test_read_all_with_synthetic_ifaces_does_not_enumerate(self):
        fake_ifaces = []
        mouse = self.ns["Reading"](ok=False, present=False, name="")
        headset = self.ns["Reading"](ok=False, present=False, name="")
        enumerate_hid = mock.Mock(side_effect=AssertionError("enumeration forbidden"))
        discover_extras = mock.Mock(return_value={})
        with mock.patch.dict(self.ns, {
            "enumerate_hid": enumerate_hid,
            "read_mouse": mock.Mock(return_value=mouse),
            "read_headset": mock.Mock(return_value=headset),
            "custom_names": mock.Mock(return_value={}),
            "discover_extras": discover_extras,
        }):
            result = self.ns["read_all"](fake_ifaces)
        self.assertEqual(result, {"mouse": mouse, "headset": headset})
        enumerate_hid.assert_not_called()
        discover_extras.assert_called_once_with(fake_ifaces)

    def test_read_all_routes_only_rapoo_to_its_dedicated_reader(self):
        iface = self.iface(0x24AE, 0x4621)
        mouse = self.ns["Reading"](ok=False, present=False, name="")
        headset = self.ns["Reading"](ok=False, present=False, name="")
        rapoo = self.ns["Reading"](ok=False, present=True, name="Rapoo VT3S MAX")
        mouse_reader = mock.Mock(return_value=mouse)
        headset_reader = mock.Mock(return_value=headset)
        rapoo_reader = mock.Mock(return_value=rapoo)
        extras = mock.Mock(return_value={})
        with mock.patch.dict(self.ns, {
            "read_mouse": mouse_reader,
            "read_headset": headset_reader,
            "read_rapoo": rapoo_reader,
            "discover_extras": extras,
            "custom_names": mock.Mock(return_value={}),
        }):
            result = self.ns["read_all"]([iface])
        self.assertIs(result["rapoo"], rapoo)
        rapoo_reader.assert_called_once_with([iface])
        mouse_reader.assert_called_once()
        headset_reader.assert_called_once()
        extras.assert_called_once_with([iface])

    def test_read_rapoo_valid_report_opens_read_only_and_closes(self):
        iface = self.iface(0x24AE, 0x4621, path="synthetic-rapoo", input_len=13)
        device = mock.Mock()
        device.read_input.return_value = bytes([7, 0xA2, 0, 0, 0, 0, 0, 2, 43, 0, 0, 0, 0])
        battery = type("BatteryStub", (), {
            "level": 43, "status": "charging", "connection_mode": 2,
        })()
        factory = mock.Mock(return_value=device)
        decoder = mock.Mock(return_value=battery)
        with mock.patch.dict(self.ns, {
            "HidDevice": factory,
            "decode_input_report": decoder,
            "time": self.clock([0.0, 0.0, 0.0, 0.1]),
        }):
            result = self.ns["read_rapoo"]([iface], seconds=1.0)
        self.assertTrue(result.ok)
        self.assertEqual((result.level, result.status), (43, "charging"))
        factory.assert_called_once_with("synthetic-rapoo", write=False)
        device.read_input.assert_called_once_with(13, 250)
        device.close.assert_called_once_with()
        device.write_output.assert_not_called()
        device.set_output_report.assert_not_called()
        device.set_feature.assert_not_called()
        device.get_feature.assert_not_called()
        decoder.assert_called_once_with(device.read_input.return_value)

    def test_read_rapoo_rejects_malformed_report_and_closes(self):
        iface = self.iface(0x24AE, 0x1421, path="synthetic-rapoo", input_len=13)
        device = mock.Mock()
        device.read_input.return_value = b"malformed synthetic report"
        with mock.patch.dict(self.ns, {
            "HidDevice": mock.Mock(return_value=device),
            "decode_input_report": mock.Mock(return_value=None),
            "time": self.clock([0.0, 0.0, 0.0, 0.1, 2.0]),
        }):
            result = self.ns["read_rapoo"]([iface], seconds=1.0)
        self.assertFalse(result.ok)
        self.assertIsNone(result.level)
        device.close.assert_called_once_with()
        device.write_output.assert_not_called()
        device.set_feature.assert_not_called()

    def test_read_rapoo_does_not_open_unmatched_identity_or_usage(self):
        wrong_id = self.iface(0x1111, 0x2222)
        wrong_usage = self.iface(0x24AE, 0x4621, usage=0x01)
        wrong_page = self.iface(0x24AE, 0x4621, usage_page=0x0001)
        opener = mock.Mock()
        with mock.patch.dict(self.ns, {"HidDevice": opener}):
            no_identity = self.ns["read_rapoo"]([wrong_id])
            no_matching_iface = self.ns["read_rapoo"]([wrong_usage, wrong_page])
        self.assertFalse(no_identity.present)
        self.assertTrue(no_matching_iface.present)
        self.assertFalse(no_matching_iface.ok)
        opener.assert_not_called()

    def test_read_rapoo_hid_error_closes_open_device(self):
        iface = self.iface(0x24AE, 0x4621, path="synthetic-rapoo", input_len=13)
        device = mock.Mock()
        hid_error = type("HidError", (Exception,), {})
        device.read_input.side_effect = hid_error("synthetic read failure")
        with mock.patch.dict(self.ns, {
            "HidDevice": mock.Mock(return_value=device),
            "decode_input_report": mock.Mock(),
            "HidError": hid_error,
            "time": self.clock([0.0, 0.0, 0.0, 0.1]),
        }):
            result = self.ns["read_rapoo"]([iface], seconds=1.0)
        self.assertFalse(result.ok)
        self.assertIn("synthetic read failure", result.detail)
        device.close.assert_called_once_with()

    def test_read_rapoo_reports_count_and_unknown_reason_when_no_reports(self):
        iface = self.iface(0x24AE, 0x4621, path="synthetic-rapoo", input_len=13)
        device = mock.Mock()
        device.read_input.return_value = None
        with mock.patch.dict(self.ns, {
            "HidDevice": mock.Mock(return_value=device),
            "decode_input_report": mock.Mock(),
            "time": self.clock([0.0, 0.0, 0.0, 0.04, 2.0]),
        }):
            result = self.ns["read_rapoo"]([iface], seconds=0.1)
        self.assertFalse(result.ok)
        self.assertIn("0", result.detail)
        self.assertIn("\u5c1a\u672a\u786e\u5b9a", result.detail)
        device.read_input.assert_called_once()
        self.assertLessEqual(device.read_input.call_args.args[1], 60)
        device.close.assert_called_once_with()

    def test_read_rapoo_counts_malformed_reports_and_report_ids(self):
        iface = self.iface(0x24AE, 0x4621, path="synthetic-rapoo", input_len=13)
        device = mock.Mock()
        device.read_input.return_value = bytes([0x08]) + bytes(12)
        decoder = mock.Mock(return_value=None)
        with mock.patch.dict(self.ns, {
            "HidDevice": mock.Mock(return_value=device),
            "decode_input_report": decoder,
            "time": self.clock([0.0, 0.0, 0.0, 0.04, 2.0]),
        }):
            result = self.ns["read_rapoo"]([iface], seconds=0.1)
        self.assertFalse(result.ok)
        self.assertIn("1", result.detail)
        self.assertIn("0x08", result.detail)
        self.assertIn("\u5c1a\u672a\u786e\u5b9a", result.detail)
        decoder.assert_called_once_with(device.read_input.return_value)


    def test_rapoo_only_print_path_skips_generic_readers_and_config(self):
        rapoo = self.ns["Reading"](ok=False, present=True,
                                   name="Rapoo VT3S MAX", detail="synthetic")
        enumerate_hid = mock.Mock(return_value=[self.iface(0x24AE, 0x4621)])
        rapoo_reader = mock.Mock(return_value=rapoo)
        read_all = mock.Mock(side_effect=AssertionError("generic read forbidden"))
        read_mouse = mock.Mock(side_effect=AssertionError("mouse read forbidden"))
        read_headset = mock.Mock(side_effect=AssertionError("headset read forbidden"))
        apply_last_known = mock.Mock(side_effect=AssertionError("cache forbidden"))
        load_config = mock.Mock(side_effect=AssertionError("config access forbidden"))
        save_config = mock.Mock(side_effect=AssertionError("config write forbidden"))
        with mock.patch.dict(self.ns, {
            "RAPOO_IDS": frozenset({(0x24AE, 0x4621), (0x24AE, 0x1421)}),
            "enumerate_hid": enumerate_hid,
            "read_rapoo": rapoo_reader,
            "read_all": read_all,
            "read_mouse": read_mouse,
            "read_headset": read_headset,
            "apply_last_known": apply_last_known,
            "load_config": load_config,
            "save_config": save_config,
            "print": mock.Mock(),
        }):
            self.ns["print_once"](rapoo_only=True)
        enumerate_hid.assert_called_once_with(self.ns["RAPOO_IDS"])
        rapoo_reader.assert_called_once_with(enumerate_hid.return_value)
        read_all.assert_not_called()
        read_mouse.assert_not_called()
        read_headset.assert_not_called()
        apply_last_known.assert_not_called()
        load_config.assert_not_called()
        save_config.assert_not_called()

    @staticmethod
    def clock(values):
        iterator = iter(values)
        return type("Clock", (), {
            "monotonic": staticmethod(lambda: next(iterator, 2.0)),
        })()

    def test_print_once_reports_extra_devices_without_cache_fallback(self):
        stale = self.ns["Reading"](
            ok=True, level=88, stale=True, present=True,
            name="Synthetic extra", detail="cached value",
        )
        printer = mock.Mock()
        read_all = mock.Mock(return_value={"x12345678": stale})
        apply_last_known = mock.Mock(
            side_effect=AssertionError("cache fallback forbidden"))
        with mock.patch.dict(self.ns, {
            "read_all": read_all,
            "apply_last_known": apply_last_known,
            "print": printer,
        }):
            self.ns["print_once"]()
        read_all.assert_called_once_with()
        apply_last_known.assert_not_called()
        self.assertEqual(printer.call_count, 1)
        self.assertIn("Synthetic extra", printer.call_args.args[0])
        self.assertIn("实时", printer.call_args.args[0])
        self.assertNotIn("88%", printer.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
