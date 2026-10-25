"""Synthetic battery transitions and Windows notification hand-off; no HID access."""
import ast
import ctypes
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from battery_alerts import LowBatteryAlerts, clamp_threshold


def reading(level, **kwargs):
    values = dict(level=level, present=True, ok=True, stale=False,
                  status="not_charging", name="K99 V3")
    values.update(kwargs)
    return SimpleNamespace(**values)


class BatteryAlertTests(unittest.TestCase):
    def test_strict_threshold_and_zero_percent(self):
        policy = LowBatteryAlerts(20)
        values = {"boundary": reading(20), "low": reading(19), "empty": reading(0)}
        self.assertEqual(set(policy.pending(values)), {"low", "empty"})

    def test_invalid_stale_disconnected_and_charging_do_not_alert(self):
        values = {
            "stale": reading(10, stale=True), "absent": reading(10, present=False),
            "failed": reading(10, ok=False), "unknown": reading(None),
            "charging": reading(10, status="charging"),
            "wired": reading(10, status="wired"), "invalid": reading(101),
        }
        self.assertEqual(LowBatteryAlerts().pending(values), {})

    def test_no_repeat_during_low_battery_or_small_boundary_fluctuations(self):
        policy = LowBatteryAlerts()
        policy.mark_sent(policy.pending({"keyboard": reading(19)}))
        for level in (18, 0, 20, 22, 19):
            self.assertEqual(policy.pending({"keyboard": reading(level)}), {})
        policy.pending({"keyboard": reading(23)})
        self.assertIn("keyboard", policy.pending({"keyboard": reading(19)}))

    def test_charging_rearms_and_unknown_does_not_clear_latch(self):
        policy = LowBatteryAlerts()
        policy.mark_sent({"keyboard": reading(19)})
        policy.pending({"keyboard": reading(None)})
        self.assertEqual(policy.pending({"keyboard": reading(18)}), {})
        policy.pending({"keyboard": reading(18, status="charging")})
        self.assertIn("keyboard", policy.pending({"keyboard": reading(18)}))

    def test_devices_are_independent(self):
        policy = LowBatteryAlerts()
        policy.mark_sent({"keyboard": reading(19)})
        self.assertEqual(set(policy.pending({"keyboard": reading(18), "rapoo": reading(12)})),
                         {"rapoo"})

    def test_change_disable_and_invalid_threshold(self):
        policy = LowBatteryAlerts()
        policy.mark_sent({"keyboard": reading(19)})
        policy.set_threshold(0)
        self.assertEqual(policy.pending({"keyboard": reading(0)}), {})
        policy.set_threshold(30)
        self.assertIn("keyboard", policy.pending({"keyboard": reading(25)}))
        self.assertEqual(clamp_threshold("bad"), 20)
        self.assertEqual(clamp_threshold(200), 100)
        self.assertEqual(clamp_threshold(-1), 0)


def method(owner, name, namespace):
    source = Path(__file__).resolve().parents[1] / "my_devices.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == owner)
    node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), namespace)
    return namespace[name]


class NotificationIntegrationTests(unittest.TestCase):
    def test_test_request_submission_does_not_claim_notification_was_shown(self):
        post = Mock(return_value=1)
        request = method("TrayApp", "request_test_notification", {
            "user32": SimpleNamespace(PostMessageW=post), "WM_APP_TEST_NOTIFY": 0x8005,
        })
        app = SimpleNamespace(_test_notification_pending=False, notification_test_status="",
                              tray=SimpleNamespace(hwnd=99))
        request(app)
        self.assertTrue(app._test_notification_pending)
        self.assertEqual(app.notification_test_status, "正在发送测试通知…")
        post.assert_called_once_with(99, 0x8005, 0, 0)
        request(app)
        self.assertEqual(post.call_count, 1)

    def test_only_windows_show_callback_confirms_test_display(self):
        proc = method("Tray", "_proc", {
            "WM_TRAYICON": 0x8001, "NIN_BALLOONSHOW": 0x402,
            "WM_RBUTTONUP": 0x205, "WM_LBUTTONUP": 0x202,
        })
        app = SimpleNamespace(_test_notification_pending=True,
                              notification_test_status="测试已提交，等待 Windows 显示…")
        tray = SimpleNamespace(app=app)
        proc(tray, 99, 0x8001, 1, 0x403)
        self.assertTrue(app._test_notification_pending)
        proc(tray, 99, 0x8001, 1, 0x402)
        self.assertFalse(app._test_notification_pending)
        self.assertEqual(app.notification_test_status, "Windows 已反馈：测试通知已显示")

    def test_failed_delivery_is_not_latched_and_success_is_not_repeated(self):
        app = SimpleNamespace(_lock=threading.Lock(), _low_alerts=LowBatteryAlerts(),
                              tray=SimpleNamespace(notify=Mock(return_value=False)))
        check = method("TrayApp", "_check_low_battery", {})
        values = {"keyboard": reading(19), "rapoo": reading(10, name="Rapoo")}
        check(app, values)
        self.assertFalse(app._low_alerts.alerted)
        app.tray.notify.return_value = True
        check(app, values)
        check(app, values)
        self.assertEqual(app.tray.notify.call_count, 2)
        text, title = app.tray.notify.call_args.args
        self.assertIn("19%", text)
        self.assertIn("10%", text)
        self.assertEqual(title, "外设低电量提醒")
        self.assertTrue(app.tray.notify.call_args.kwargs["warning"])

    def test_threshold_saved_without_removing_existing_configuration(self):
        saved = {}
        app = SimpleNamespace(_lock=threading.Lock(), _low_alerts=LowBatteryAlerts(),
                              tray=None)
        setter = method("TrayApp", "set_low_battery_threshold", {
            "load_config": lambda: {"interval": 60, "names": {"keyboard": "K99"}},
            "save_config": saved.update,
        })
        self.assertEqual(setter(app, 15), 15)
        self.assertEqual(saved, {"interval": 60, "names": {"keyboard": "K99"},
                                 "low_battery_threshold": 15})

    def test_native_body_is_populated_and_live_icon_is_not_modified(self):
        class IconData(ctypes.Structure):
            _fields_ = [("hIcon", ctypes.c_size_t), ("uFlags", ctypes.c_uint),
                        ("uVersion", ctypes.c_uint), ("szInfo", ctypes.c_wchar * 256),
                        ("szInfoTitle", ctypes.c_wchar * 64),
                        ("dwInfoFlags", ctypes.c_uint), ("hBalloonIcon", ctypes.c_size_t)]
        delivered = []

        def send(action, pointer):
            delivered.append(IconData.from_buffer_copy(bytes(pointer._obj)))
            return True

        notify = method("Tray", "notify", {
            "NOTIFYICONDATAW": IconData, "ctypes": ctypes,
            "NIF_INFO": 16, "NIF_ICON": 2, "NIF_MESSAGE": 1, "NIF_TIP": 4,
            "NIF_GUID": 32,
            "NIIF_WARNING": 2, "NIIF_USER": 4, "NIIF_LARGE_ICON": 32,
            "NIM_MODIFY": 1, "shell32": SimpleNamespace(Shell_NotifyIconW=send),
        })
        live = IconData(hIcon=44, uFlags=7)
        tray = SimpleNamespace(nids={1: live}, _big_icon=99)
        self.assertTrue(notify(tray, "K99 剩余 19%", "低电量", warning=True))
        self.assertEqual(delivered[0].szInfo, "K99 剩余 19%")
        self.assertEqual(delivered[0].dwInfoFlags, 2)
        self.assertEqual(delivered[0].uFlags, 16)
        self.assertEqual(delivered[0].hIcon, 44)
        self.assertEqual(live.szInfo, "")
        self.assertEqual(live.hIcon, 44)
        self.assertEqual(live.uFlags, 7)
        live.uFlags = 7 | 32
        self.assertTrue(notify(tray, "GUID notification", warning=True))
        self.assertEqual(delivered[-1].uFlags, 16 | 32)


if __name__ == "__main__":
    unittest.main()
