"""AST-only integration checks for GUI Rapoo monitor orchestration."""
from __future__ import annotations

import ast
import dataclasses
from pathlib import Path
import os
import queue
import threading
import unittest
from types import MethodType, SimpleNamespace
from unittest.mock import Mock
from typing import Optional


SOURCE = Path(os.environ.get(
    "EZ24G_SOURCE", Path(__file__).resolve().parents[1] / "my_devices.py"))


class FakeReading:
    def __init__(self, *, ok=False, level=None, status="unknown", name="",
                 source="", detail="", ts=0.0, raw=None, present=False,
                 stale=False, vid=0, pid=0, usage_page=0, hid_known=False):
        self.ok, self.level, self.status = ok, level, status
        self.name, self.source, self.detail = name, source, detail
        self.ts, self.raw, self.present, self.stale = ts, raw, present, stale
        self.vid, self.pid, self.usage_page = vid, pid, usage_page
        self.hid_known = hid_known


def iface():
    return SimpleNamespace(path="synthetic-rapoo", vid=0x24AE, pid=0x4621,
                           usage_page=0xFF00, usage=0x0E, input_len=13,
                           product="VT3S MAX")


def extract(tree, owner, name):
    if owner is None:
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == name)
    else:
        cls = next(n for n in tree.body
                   if isinstance(n, ast.ClassDef) and n.name == owner)
        node = next(n for n in cls.body if isinstance(n, ast.FunctionDef)
                    and n.name == name)
    return node


def load_source():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    specs = [SimpleNamespace(name="Mouse", ids=frozenset({(1, 1)})),
             SimpleNamespace(name="Headset", ids=frozenset({(2, 2)}))]
    ns = {
        "Optional": Optional, "HidIface": object, "Reading": FakeReading,
        "DEVICES": specs,
        "RAPOO_IDS": frozenset({(0x24AE, 0x4621), (0x24AE, 0x1421)}),
        "K99_V3_WIRED_IDS": frozenset(),
        "read_mouse": Mock(return_value=FakeReading(present=False)),
        "read_headset": Mock(return_value=FakeReading(present=False)),
        "custom_names": Mock(return_value={}),
        "is_k99_v3": Mock(return_value=False),
        "read_k99_v3": Mock(),
        "discover_extras": Mock(return_value={}),
        "read_rapoo": Mock(return_value=FakeReading(
            present=True, name="Rapoo VT3S MAX", detail="synthetic")),
        "enumerate_hid": Mock(),
        "apply_last_known": Mock(side_effect=lambda result: result),
        "queue": queue,
        "dataclasses": dataclasses,
        "user32": SimpleNamespace(PostMessageW=Mock()),
        "WM_APP_REFRESH": 0x8002,
    }
    nodes = [extract(tree, None, "read_all"),
             extract(tree, "TrayApp", "snapshot"),
             extract(tree, "TrayApp", "_worker"),
             extract(tree, "TrayApp", "_drain_rapoo_updates")]
    mod = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(mod)
    exec(compile(mod, str(SOURCE), "exec"), ns)
    ns["TrayApp__worker"] = ns["_worker"]
    ns["TrayApp__drain_rapoo_updates"] = ns["_drain_rapoo_updates"]
    return tree, ns


class RapooReadPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree, cls.ns = load_source()

    def setUp(self):
        for name in ("read_rapoo", "enumerate_hid", "apply_last_known",
                     "read_mouse", "read_headset", "discover_extras"):
            self.ns[name].reset_mock()
        self.ns["apply_last_known"].side_effect = lambda result: result

    def test_skip_rapoo_creates_placeholder_without_calling_reader(self):
        target = iface()
        result = self.ns["read_all"]([target], skip_rapoo=True)
        self.assertTrue(result["rapoo"].present)
        self.assertFalse(result["rapoo"].ok)
        self.ns["read_rapoo"].assert_not_called()

    def test_default_read_all_keeps_dedicated_three_second_reader_path(self):
        target = iface()
        result = self.ns["read_all"]([target])
        self.assertIs(result["rapoo"], self.ns["read_rapoo"].return_value)
        self.ns["read_rapoo"].assert_called_once_with([target])
        read_rapoo_node = extract(self.tree, None, "read_rapoo")
        defaults = read_rapoo_node.args.defaults
        self.assertEqual(ast.literal_eval(defaults[0]), 3.0)

    def test_gui_worker_configures_monitor_and_skips_short_rapoo_read(self):
        target = iface()
        self.ns["enumerate_hid"].return_value = [target]
        monitor = SimpleNamespace(configure=Mock())
        app = self.make_app(monitor, initial={})

        self.ns["TrayApp__worker"](app)

        monitor.configure.assert_called_once_with([target])
        self.ns["read_rapoo"].assert_not_called()
        self.assertTrue(app.snapshot()["rapoo"].present)
        self.assertFalse(app.snapshot()["rapoo"].ok)

    def make_app(self, monitor, initial):
        app = SimpleNamespace(
            _rapoo_monitor=monitor, _readings=initial, _lock=threading.Lock(),
            _refreshing=True, _dirty=False, tray=None,
            _check_full=Mock(),
        )
        app.snapshot = MethodType(self.ns["snapshot"], app)
        return app


class RapooQueueUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.ns = load_source()

    def setUp(self):
        self.ns["enumerate_hid"].reset_mock()
        self.ns["enumerate_hid"].side_effect = None
        self.ns["apply_last_known"].reset_mock()
        self.ns["apply_last_known"].side_effect = lambda result: result
        self.ns["read_rapoo"].reset_mock()

    def test_valid_report_updates_snapshot_at_original_receive_time(self):
        updates = queue.Queue()
        target = iface()
        battery = SimpleNamespace(level=54, status="discharging")
        raw = bytes((7, 0, 0, 0, 0, 0, 1, 1, 54, 0, 0, 0, 0))
        received_at = 1234.5
        updates.put(("reading", target, battery, raw, received_at))
        monitor = SimpleNamespace()
        app = SimpleNamespace(
            _rapoo_updates=updates, _readings={}, _lock=threading.Lock(),
            _dirty=False, tray=None, _check_full=Mock())
        self.ns["TrayApp__drain_rapoo_updates"](app)

        snapshot = self.ns["snapshot"](app)
        self.assertEqual(snapshot["rapoo"].level, 54)
        self.assertEqual(snapshot["rapoo"].ts, received_at)
        self.assertEqual(snapshot["rapoo"].raw, raw)
        self.assertTrue(snapshot["rapoo"].ok)
        self.assertFalse(snapshot["rapoo"].stale)
        app._check_full.assert_not_called()  # Tray thread checks after icons exist.
        self.assertTrue(updates.empty())
        self.assertFalse(hasattr(monitor, "open_device"))

    def test_fresh_live_value_survives_newer_timestamp_cached_placeholder(self):
        target = iface()
        current = FakeReading(ok=True, level=54, status="discharging",
                              present=True, stale=False, ts=100.0)
        placeholder = FakeReading(ok=True, level=40, present=True,
                                  stale=True, ts=9000.0)
        self.ns["enumerate_hid"].return_value = [target]
        monitor = SimpleNamespace(configure=Mock())
        self.ns["read_rapoo"].reset_mock()

        def cached_result(_res):
            return {"mouse": FakeReading(), "headset": FakeReading(),
                    "rapoo": placeholder}

        self.ns["apply_last_known"].side_effect = cached_result
        app = self.make_worker_app(monitor, {"rapoo": current})
        self.ns["TrayApp__worker"](app)
        self.assertIs(app.snapshot()["rapoo"], current)

    def test_listener_error_marks_existing_live_reading_stale_and_keeps_time(self):
        current = FakeReading(ok=True, level=54, status="discharging",
                              present=True, stale=False, ts=1234.5)
        updates = queue.Queue()
        updates.put(("error", iface(), "synthetic read failure"))
        app = SimpleNamespace(
            _rapoo_updates=updates, _readings={"rapoo": current},
            _lock=threading.Lock(), _dirty=False, tray=None)

        self.ns["TrayApp__drain_rapoo_updates"](app)

        result = self.ns["snapshot"](app)["rapoo"]
        self.assertIs(result, current)
        self.assertEqual(result.level, 54)
        self.assertEqual(result.ts, 1234.5)
        self.assertTrue(result.stale)
        self.assertTrue(result.ok)
        self.assertIn("synthetic read failure", result.detail)
        self.assertTrue(app._dirty)

    def test_worker_exception_preserves_live_rapoo_snapshot(self):
        current = FakeReading(ok=True, level=54, status="discharging",
                              present=True, stale=False, ts=1234.5)
        self.ns["enumerate_hid"].side_effect = RuntimeError("synthetic refresh failure")
        monitor = SimpleNamespace(configure=Mock())
        app = self.make_worker_app(monitor, {"rapoo": current})

        self.ns["TrayApp__worker"](app)

        self.assertIs(app.snapshot()["rapoo"], current)
        self.assertEqual(app.snapshot()["rapoo"].level, 54)
        self.assertFalse(app.snapshot()["rapoo"].stale)
        self.assertEqual(set(app.snapshot()), {"rapoo", "mouse", "headset"})
        monitor.configure.assert_not_called()
        self.assertFalse(app._refreshing)

    def test_enumeration_exception_keeps_keyboard_as_stale_instead_of_losing_device(self):
        @dataclasses.dataclass
        class KeyboardReading:
            ok: bool = True
            level: int = 100
            present: bool = True
            stale: bool = False
            ts: float = 1000
            detail: str = ""
        previous = KeyboardReading()
        self.ns["enumerate_hid"].side_effect = RuntimeError("synthetic enumeration failure")
        app = self.make_worker_app(SimpleNamespace(configure=Mock()), {"keyboard": previous})
        self.ns["TrayApp__worker"](app)
        current = app.snapshot()["keyboard"]
        self.assertTrue(current.stale)
        self.assertEqual((current.level, current.ts), (100, 1000))
        self.assertFalse(previous.stale)
        self.assertFalse(app._refreshing)

    def make_worker_app(self, monitor, readings):
        app = SimpleNamespace(
            _rapoo_monitor=monitor, _readings=readings, _lock=threading.Lock(),
            _refreshing=True, _dirty=False, tray=None,
            _check_full=Mock())
        app.snapshot = MethodType(self.ns["snapshot"], app)
        return app


if __name__ == "__main__":
    unittest.main()
