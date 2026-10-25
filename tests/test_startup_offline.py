"""Offline AST-only regression checks for visible startup and tray presence."""
from __future__ import annotations

import ast
import os
import time
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from tray_state import tray_identity, tray_readings


SOURCE = Path(os.environ.get(
    "EZ24G_SOURCE", Path(__file__).resolve().parents[1] / "my_devices.py"))


def method_node(tree: ast.Module, class_name: str, method_name: str) -> ast.FunctionDef:
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    return next(n for n in cls.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == method_name)


def function_node(tree: ast.Module, function_name: str) -> ast.FunctionDef:
    return next(n for n in tree.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == function_name)


def load_methods():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    tray_ns = {
        "NIM_DELETE": 2, "NIM_MODIFY": 1, "NIM_ADD": 0,
        "ctypes": SimpleNamespace(byref=lambda value: value),
        "shell32": SimpleNamespace(Shell_NotifyIconW=Mock()),
        "user32": SimpleNamespace(DestroyIcon=Mock()),
        "make_battery_icon": Mock(return_value=123),
        "tray_identity": tray_identity, "tray_readings": tray_readings,
        "GUID": lambda value: value, "NIF_GUID": 32,
    }
    app_ns = {}
    for owner, name, namespace in (
        ("Tray", "sync_icons", tray_ns),
        ("TrayApp", "run", app_ns),
    ):
        node = method_node(tree, owner, name)
        module = ast.Module(body=[node], type_ignores=[])
        ast.fix_missing_locations(module)
        exec(compile(module, str(SOURCE), "exec"), namespace)
    return tray_ns, app_ns


class StartupVisibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tray_ns, cls.app_ns = load_methods()

    def run_app(self, panel_only: bool, silent_start: bool = False):
        callbacks = []
        root = SimpleNamespace(
            after=Mock(side_effect=lambda delay, callback: callbacks.append(callback)),
            mainloop=Mock(side_effect=lambda: callbacks.pop(0)()), quit=Mock(),
            winfo_viewable=Mock(return_value=False))
        panel = SimpleNamespace(root=root, show=Mock(), render=Mock())
        tray = SimpleNamespace(start=Mock())
        monitor = SimpleNamespace(start=Mock(), stop=Mock(), join=Mock())
        app = SimpleNamespace(
            panel_only=panel_only, silent_start=silent_start,
            panel=None, root=None, tray=None,
            refresh=Mock(), _show_requested=False, _dirty=False, _stop=False,
            _rapoo_monitor=monitor, _drain_rapoo_updates=Mock())
        Panel = Mock(return_value=panel)
        Tray = Mock(return_value=tray)
        self.app_ns.update(Panel=Panel, Tray=Tray)
        self.app_ns["run"](app)
        return app, panel, tray, Panel, Tray, monitor, callbacks

    def test_default_start_shows_panel_and_starts_tray(self):
        app, panel, tray, _, Tray, monitor, _ = self.run_app(False)
        panel.show.assert_called_once_with()
        Tray.assert_called_once_with(app)
        tray.start.assert_called_once_with()
        app.refresh.assert_called_once_with()
        monitor.start.assert_called_once_with()
        monitor.stop.assert_called_once_with()
        monitor.join.assert_called_once_with()
        app._drain_rapoo_updates.assert_called_once_with()

    def test_panel_only_shows_panel_without_creating_tray(self):
        app, panel, _, _, Tray, monitor, _ = self.run_app(True)
        panel.show.assert_called_once_with()
        Tray.assert_not_called()
        app.refresh.assert_called_once_with()
        monitor.start.assert_called_once_with()
        monitor.stop.assert_called_once_with()
        monitor.join.assert_called_once_with()

    def test_silent_start_keeps_background_services_and_later_show_request(self):
        app, panel, tray, _, Tray, monitor, callbacks = self.run_app(
            False, silent_start=True)
        panel.show.assert_not_called()
        Tray.assert_called_once_with(app)
        tray.start.assert_called_once_with()
        app.refresh.assert_called_once_with()
        monitor.start.assert_called_once_with()
        monitor.stop.assert_called_once_with()
        monitor.join.assert_called_once_with()

        app._show_requested = True
        callbacks.pop(0)()
        panel.show.assert_called_once_with()

    def test_silent_start_does_not_reveal_existing_instance(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
        node = function_node(tree, "run_gui")
        namespace = {
            "UI_SCALE": 1.0, "register_app_identity": Mock(),
            "ctypes": SimpleNamespace(
                set_last_error=Mock(), get_last_error=Mock(return_value=183)),
            "wt": SimpleNamespace(UINT=int),
            "user32": SimpleNamespace(
                SetProcessDPIAware=Mock(), GetDpiForSystem=Mock(return_value=96),
                FindWindowW=Mock(return_value=123), PostMessageW=Mock()),
            "kernel32": SimpleNamespace(CreateMutexW=Mock(return_value=1)),
            "Tray": SimpleNamespace(CLASS_NAME="BatteryTrayWndDSH"),
            "WM_APP_SHOW": 0x8001, "TrayApp": Mock(),
        }
        module = ast.Module(body=[node], type_ignores=[])
        ast.fix_missing_locations(module)
        exec(compile(module, str(SOURCE), "exec"), namespace)

        result = namespace["run_gui"](silent_start=True)

        self.assertEqual(result, 0)
        namespace["user32"].FindWindowW.assert_called_once_with(
            "BatteryTrayWndDSH", None)
        namespace["user32"].PostMessageW.assert_not_called()

    def test_startup_shortcut_passes_silent_start_flag(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
        node = function_node(tree, "install_startup")
        namespace = {
            "startup_lnk": Mock(return_value="mock-startup.lnk"),
            "os": SimpleNamespace(
                makedirs=Mock(),
                path=SimpleNamespace(dirname=Mock(return_value="mock-startup"),
                                     isfile=Mock(return_value=True))),
            "create_shortcut": Mock(), "pythonw_path": Mock(return_value="pythonw.exe"),
            "script_path": Mock(return_value="C:/app/my_devices.py"),
            "project_dir": Mock(return_value="C:/app"),
        }
        module = ast.Module(body=[node], type_ignores=[])
        ast.fix_missing_locations(module)
        exec(compile(module, str(SOURCE), "exec"), namespace)

        self.assertTrue(namespace["install_startup"]())

        namespace["os"].makedirs.assert_called_once_with(
            "mock-startup", exist_ok=True)
        namespace["create_shortcut"].assert_called_once_with(
            "mock-startup.lnk", "pythonw.exe",
            '"C:/app/my_devices.py" --silent-start', "C:/app",
            "外设电量托盘", "pythonw.exe")


class TrayPresenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tray_ns, _ = load_methods()

    def make_tray(self, snapshot):
        self.tray_ns["shell32"].Shell_NotifyIconW.reset_mock()
        self.tray_ns["user32"].DestroyIcon.reset_mock()
        app = SimpleNamespace(snapshot=Mock(return_value=snapshot), theme_light=False)
        tray = SimpleNamespace(
            app=app, nids={}, icons={}, icon_keys={},
            _make_nid=Mock(side_effect=lambda uid: SimpleNamespace(uID=uid, uFlags=7)),
            _fill_icon=Mock())
        self.tray_ns["sync_icons"](tray)
        return tray

    def test_valid_rapoo_and_unknown_keyboard_only_show_rapoo(self):
        rapoo = SimpleNamespace(present=True, ok=True, level=54, stale=False)
        keyboard = SimpleNamespace(present=True, ok=False, level=None, stale=False)
        tray = self.make_tray({"rapoo": rapoo, "keyboard": keyboard})
        self.assertEqual(set(tray.nids), {1})
        tray._make_nid.assert_called_once_with(1)
        tray._fill_icon.assert_called_once_with(tray.nids[1], "rapoo")
        self.tray_ns["shell32"].Shell_NotifyIconW.assert_called_once()

    def test_two_valid_devices_get_two_icons(self):
        tray = self.make_tray({
            "rapoo": SimpleNamespace(present=True, ok=True, level=54, stale=False),
            "keyboard": SimpleNamespace(present=True, ok=True, level=81, stale=False),
        })
        self.assertEqual(set(tray.nids), {1, 2})
        self.assertEqual([call.args[1] for call in tray._fill_icon.call_args_list],
                         ["rapoo", "keyboard"])
        self.assertEqual(self.tray_ns["shell32"].Shell_NotifyIconW.call_count, 2)

    def test_absent_unknown_and_stale_readings_get_no_icon(self):
        tray = self.make_tray({
            "absent": SimpleNamespace(present=False, ok=True, level=50, stale=False),
            "unknown": SimpleNamespace(present=True, ok=False, level=None, stale=False),
            "stale": SimpleNamespace(present=True, ok=True, level=66, stale=True),
        })
        self.assertEqual(tray.nids, {})
        tray._make_nid.assert_not_called()
        tray._fill_icon.assert_not_called()
        self.tray_ns["shell32"].Shell_NotifyIconW.assert_not_called()

    def test_zero_percent_is_a_valid_tray_reading(self):
        tray = self.make_tray({
            "rapoo": SimpleNamespace(present=True, ok=True, level=0, stale=False),
        })
        self.assertEqual(set(tray.nids), {1})
        tray._fill_icon.assert_called_once_with(tray.nids[1], "rapoo")

    def test_keyboard_keeps_its_id_when_mouse_disappears_and_snapshot_reorders(self):
        good = SimpleNamespace(present=True, ok=True, level=54, stale=False)
        tray = self.make_tray({"rapoo": good, "keyboard": good})
        keyboard_nid = tray.nids[2]
        keyboard_guid = keyboard_nid.guidItem
        tray.app.snapshot.return_value = {"keyboard": good}
        self.tray_ns["sync_icons"](tray)
        self.assertEqual(set(tray.nids), {2})
        self.assertIs(tray.nids[2], keyboard_nid)
        self.assertEqual(tray.nids[2].guidItem, keyboard_guid)

    def test_short_keyboard_timeout_updates_icon_without_deleting_or_readding(self):
        good = SimpleNamespace(present=True, ok=True, level=100, stale=False)
        tray = self.make_tray({"keyboard": good})
        old = tray.nids[2]
        tray.app.snapshot.return_value = {"keyboard": SimpleNamespace(
            present=True, ok=True, level=100, stale=True, ts=time.time())}
        api = self.tray_ns["shell32"].Shell_NotifyIconW
        api.reset_mock()
        self.tray_ns["sync_icons"](tray)
        self.assertIs(tray.nids[2], old)
        self.assertEqual([c.args[0] for c in api.call_args_list], [1])

    def test_failed_add_is_retried_on_next_refresh(self):
        good = SimpleNamespace(present=True, ok=True, level=100, stale=False)
        api = self.tray_ns["shell32"].Shell_NotifyIconW
        api.return_value = False
        try:
            tray = self.make_tray({"keyboard": good})
            self.assertEqual(tray.nids, {})
            api.return_value = True
            self.tray_ns["sync_icons"](tray)
            self.assertEqual(set(tray.nids), {2})
        finally:
            api.return_value = True

    def test_failed_modify_recovers_missing_shell_icon(self):
        good = SimpleNamespace(present=True, ok=True, level=100, stale=False)
        tray = self.make_tray({"keyboard": good})
        api = self.tray_ns["shell32"].Shell_NotifyIconW
        api.reset_mock()
        api.side_effect = [False, True]
        try:
            self.tray_ns["sync_icons"](tray)
            self.assertEqual([c.args[0] for c in api.call_args_list], [1, 0])
        finally:
            api.side_effect = None

    def test_device_becoming_unknown_deletes_its_old_icon(self):
        snapshot = {
            "rapoo": SimpleNamespace(present=True, ok=True, level=54, stale=False),
            "keyboard": SimpleNamespace(present=True, ok=False, level=None, stale=False),
        }
        tray = SimpleNamespace(
            app=SimpleNamespace(snapshot=Mock(return_value=snapshot), theme_light=False),
            nids={uid: SimpleNamespace(uID=uid) for uid in range(1, 3)},
            icons={uid: 100 + uid for uid in range(1, 3)},
            icon_keys={uid: ("old",) for uid in range(1, 3)},
            _fill_icon=Mock())
        self.tray_ns["shell32"].Shell_NotifyIconW.reset_mock()
        self.tray_ns["user32"].DestroyIcon.reset_mock()
        self.tray_ns["sync_icons"](tray)
        self.assertEqual(set(tray.nids), {1})
        self.assertEqual(set(tray.icons), {1})
        self.assertEqual(set(tray.icon_keys), {1})
        self.assertEqual(self.tray_ns["shell32"].Shell_NotifyIconW.call_count, 2)
        self.assertEqual(self.tray_ns["user32"].DestroyIcon.call_count, 1)
        deleted = [call.args[1].uID for call in
                   self.tray_ns["shell32"].Shell_NotifyIconW.call_args_list
                   if call.args[0] == self.tray_ns["NIM_DELETE"]]
        self.assertEqual(deleted, [2])


if __name__ == "__main__":
    unittest.main()
