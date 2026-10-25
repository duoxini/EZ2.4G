"""Tray identity and transient-failure regressions; no device or OS access."""
import time
from types import SimpleNamespace
import unittest
from tray_state import tray_identity, tray_readings, reading_summary


def reading(**kwargs):
    values = dict(present=True, ok=True, stale=False, level=100, ts=1000,
                  status="not_charging", detail="")
    values.update(kwargs)
    return SimpleNamespace(**values)


class TrayStateTests(unittest.TestCase):
    def test_identity_is_stable_when_other_devices_disappear_or_reorder(self):
        keyboard = tray_identity("keyboard")
        rapoo = tray_identity("rapoo")
        self.assertNotEqual(keyboard, rapoo)
        for keys in (("rapoo", "keyboard"), ("keyboard",), ("keyboard", "rapoo")):
            self.assertEqual(dict((k, tray_identity(k)) for k in keys)["keyboard"], keyboard)

    def test_transient_failure_retains_last_reading_but_expires_after_five_minutes(self):
        values = {"keyboard": reading(stale=True)}
        for now in (1000, 1001, 1299, 1300):
            self.assertIn("keyboard", tray_readings(values, now))
        self.assertEqual(tray_readings(values, 1301), {})

    def test_unplugged_unknown_and_invalid_do_not_get_grace(self):
        values = {"absent": reading(present=False), "unknown": reading(ok=False, level=None),
                  "invalid": reading(level=101), "future": reading(stale=True, ts=2000)}
        self.assertEqual(tray_readings(values, 1000), {})

    def test_timeout_status_never_calls_old_reading_realtime(self):
        title, detail = reading_summary(reading(stale=True, detail="配置读取超时"))
        self.assertIn("上次读数", title)
        self.assertNotIn("实时", title)
        self.assertIn("超时", detail)

    def test_success_and_charging_have_distinct_status(self):
        title, detail = reading_summary(reading())
        self.assertIn("实时电量", title)
        self.assertEqual(detail, "")
        self.assertIn("充电中", reading_summary(reading(status="charging"))[0])


if __name__ == "__main__":
    unittest.main()
