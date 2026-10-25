"""Synthetic offline tests for the Rapoo VT_nrf54L battery report decoder."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

_test_dir = Path(__file__).resolve().parent
for _candidate in (_test_dir, _test_dir.parent):
    if (_candidate / "rapoo_protocol.py").is_file():
        sys.path.insert(0, str(_candidate))
        break

from rapoo_protocol import (  # noqa: E402
    RAPOO_VID,
    VT3S_MAX_IDS,
    VT3S_MAX_PID,
    VT3S_MAX_RECEIVER_ALIAS_PID,
    VT3S_MAX_USAGE_PAGE,
    VT_NRF54L_REPORT_ID,
    decode_input_report,
)


def synthetic_report(*, mode=0, status=1, level=50, report_id=7,
                     minimum_length=13):
    """Build a synthetic Windows-format report (not captured bytes)."""
    data = bytearray(max(13, minimum_length))
    data[0] = report_id
    data[1] = (0xA0 | mode)  # mode is encoded in the low nibble
    data[7] = status
    data[8] = level
    return bytes(data)


class RapooProtocolTests(unittest.TestCase):
    def test_documented_device_ids(self):
        self.assertEqual(RAPOO_VID, 0x24AE)
        self.assertEqual(VT3S_MAX_PID, 0x4621)
        self.assertEqual(VT3S_MAX_RECEIVER_ALIAS_PID, 0x1421)
        self.assertEqual(VT3S_MAX_IDS, {(0x24AE, 0x4621), (0x24AE, 0x1421)})
        self.assertEqual(VT3S_MAX_USAGE_PAGE, 0xFF00)
        self.assertEqual(VT_NRF54L_REPORT_ID, 7)

    def test_percentage_boundaries_and_windows_prefix_offsets(self):
        low = decode_input_report(synthetic_report(mode=0, status=1, level=0))
        high = decode_input_report(synthetic_report(mode=1, status=1, level=100))
        self.assertEqual((low.level, low.status, low.connection_mode),
                         (0, "discharging", 0))
        self.assertEqual((high.level, high.status, high.connection_mode),
                         (100, "discharging", 1))
        # raw[0] is the Windows report ID; payload[6:8] is raw[7:9].
        report = synthetic_report(mode=2, status=2, level=37)
        self.assertEqual((report[0], report[7], report[8]), (7, 2, 37))
        decoded = decode_input_report(report)
        self.assertEqual((decoded.level, decoded.status, decoded.connection_mode),
                         (37, "charging", 2))

    def test_rejects_wrong_report_id_and_truncated_report(self):
        self.assertIsNone(decode_input_report(synthetic_report(report_id=8)))
        self.assertIsNone(decode_input_report(synthetic_report(minimum_length=12)[:12]))
        self.assertIsNone(decode_input_report(b""))

    def test_rejects_out_of_range_percent_without_clamping(self):
        self.assertIsNone(decode_input_report(synthetic_report(level=101)))
        self.assertIsNone(decode_input_report(synthetic_report(level=255)))

    def test_rejects_invalid_status_and_connection_mode(self):
        for status in (0, 3, 255):
            with self.subTest(status=status):
                self.assertIsNone(decode_input_report(synthetic_report(status=status)))
        for mode in (3, 15):
            with self.subTest(mode=mode):
                self.assertIsNone(decode_input_report(synthetic_report(mode=mode)))


if __name__ == "__main__":
    unittest.main()
