"""Offline lifecycle tests for the injected Rapoo passive monitor."""
from __future__ import annotations

from collections import deque
from pathlib import Path
import queue
import sys
import threading
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rapoo_monitor import RapooInputMonitor  # noqa: E402


def iface(path="rapoo-a", *, vid=0x24AE, pid=0x4621, page=0xFF00,
          usage=0x0E, input_len=13):
    return SimpleNamespace(path=path, vid=vid, pid=pid, usage_page=page,
                           usage=usage, input_len=input_len)


def valid_report(level=54):
    raw = bytearray(13)
    raw[0] = 0x07
    raw[1] = 0x00
    raw[7] = 1
    raw[8] = level
    return bytes(raw)


class FakeDevice:
    def __init__(self, responses=()):
        self.responses = deque(responses)
        self.read_calls = []
        self.read_seen = threading.Event()
        self.release = threading.Event()
        self.closed = threading.Event()

    def read_input(self, length, timeout):
        self.read_calls.append((length, timeout))
        self.read_seen.set()
        if self.responses:
            result = self.responses.popleft()
            if isinstance(result, BaseException):
                raise result
            return result
        self.release.wait(min(timeout / 1000, 0.05))
        return None

    def close(self):
        self.closed.set()


class RapooMonitorTests(unittest.TestCase):
    def setUp(self):
        self.updates = queue.Queue()
        self.open_calls = []
        self.devices = {}

        def opener(path, *, write):
            self.open_calls.append((path, write))
            return self.devices[path].popleft()

        self.monitor = RapooInputMonitor(opener, self.updates)

    def tearDown(self):
        self.monitor.stop()
        self.monitor.join(1)

    def test_handle_persists_through_empty_reads_then_publishes_valid_packet(self):
        dev = FakeDevice((None, b"", valid_report(54)))
        self.devices["rapoo-a"] = deque((dev,))
        target = iface()
        self.monitor.configure([target])
        self.monitor.start()

        event = self.updates.get(timeout=1)
        self.assertEqual(event[0], "reading")
        self.assertIs(event[1], target)
        self.assertEqual(event[2].level, 54)
        self.assertEqual(event[3], valid_report(54))
        self.assertIsInstance(event[4], float)
        self.assertGreaterEqual(len(dev.read_calls), 3)
        self.assertEqual(self.open_calls, [("rapoo-a", False)])
        self.assertTrue(all(length == 13 and timeout == 100
                            for length, timeout in dev.read_calls))

    def test_invalid_report_id_is_ignored(self):
        wrong_id = bytearray(valid_report())
        wrong_id[0] = 0x08
        dev = FakeDevice((bytes(wrong_id), valid_report(61)))
        self.devices["rapoo-a"] = deque((dev,))
        target = iface()
        self.monitor.configure([target])
        self.monitor.start()
        event = self.updates.get(timeout=1)
        self.assertEqual(event[0], "reading")
        self.assertEqual(event[2].level, 61)
        self.assertTrue(self.updates.empty())

    def test_filters_identity_collection_and_length_before_open(self):
        good = iface()
        invalid = [
            iface("wrong-vid", vid=1),
            iface("wrong-pid", pid=3),
            iface("wrong-page", page=1),
            iface("wrong-usage", usage=9),
            iface("short", input_len=12),
        ]
        dev = FakeDevice()
        self.devices[good.path] = deque((dev,))
        self.monitor.configure([*invalid, good])
        self.monitor.start()
        self.assertTrue(dev.read_seen.wait(1))
        self.assertEqual(self.open_calls, [(good.path, False)])

    def test_reconfigure_closes_removed_handle_and_stop_closes_remaining(self):
        first_iface, second_iface = iface("first"), iface("second", pid=0x1421)
        first, second = FakeDevice(), FakeDevice()
        self.devices["first"] = deque((first,))
        self.devices["second"] = deque((second,))
        self.monitor.configure([first_iface])
        self.monitor.start()
        self.assertTrue(first.read_seen.wait(1))

        self.monitor.configure([second_iface])
        self.assertTrue(first.closed.wait(1))
        self.assertTrue(second.read_seen.wait(1))
        self.assertEqual(self.open_calls,
                         [("first", False), ("second", False)])

        self.monitor.stop()
        self.monitor.join(1)
        self.assertTrue(second.closed.is_set())
        self.assertFalse(self.monitor._thread.is_alive())

    def test_read_error_does_not_busy_reopen_until_next_configuration(self):
        target = iface()
        broken = FakeDevice((OSError("synthetic read failure"),))
        recovered = FakeDevice()
        self.devices[target.path] = deque((broken, recovered))
        self.monitor.configure([target])
        self.monitor.start()

        error = self.updates.get(timeout=1)
        self.assertEqual(error[:2], ("error", target))
        self.assertIn("synthetic read failure", error[2])
        self.assertTrue(broken.closed.wait(1))
        self.assertEqual(self.open_calls, [(target.path, False)])

        self.monitor.configure([target])
        self.assertTrue(recovered.read_seen.wait(1))
        self.assertEqual(self.open_calls,
                         [(target.path, False), (target.path, False)])


if __name__ == "__main__":
    unittest.main()
