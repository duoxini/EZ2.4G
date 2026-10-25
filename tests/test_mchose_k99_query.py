"""Synthetic-only tests for the opt-in GLW K99 V3 configuration helpers."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import mchose_k99_protocol as protocol


def response(request, data: bytes, *, report_id=0, command=b"\xaa\x05",
             size=None, offset=None, checksum=0xA5) -> bytes:
    size = request.size if size is None else size
    offset = request.offset if offset is None else offset
    header = bytes((report_id,)) + command + bytes((
        0, 0, size, offset & 0xFF, (offset >> 8) & 0xFF, checksum,
    ))
    return header + data + bytes(65 - len(header) - len(data))


class GLWConfigRequestTests(unittest.TestCase):
    def test_fixed_request_frames(self):
        first, second = protocol.GLW_CONFIG_REQUESTS
        expected_headers = (
            bytes.fromhex("00 55 05 00 38 38 00 00 00"),
            bytes.fromhex("00 55 05 00 40 08 38 00 00"),
        )
        for request, header in zip((first, second), expected_headers):
            with self.subTest(request=request):
                frame = protocol.build_config_request(request)
                self.assertEqual(len(frame), 65)
                self.assertEqual(frame[:len(header)], header)
                self.assertEqual(frame[len(header):], bytes(65 - len(header)))

    def test_parse_and_join_two_chunks(self):
        chunks = (bytes(range(56)), bytes(range(56, 64)))
        parsed = []
        for request, chunk in zip(protocol.GLW_CONFIG_REQUESTS, chunks):
            frame = response(request, chunk)
            self.assertEqual(protocol.parse_config_response(frame, request), chunk)
            parsed.append(protocol.parse_config_response(frame, request))
        self.assertEqual(b"".join(parsed), bytes(range(64)))

    def test_checksum_byte_is_not_interpreted(self):
        request = protocol.GLW_CONFIG_REQUESTS[0]
        frame = response(request, bytes(request.size), checksum=0x36)
        self.assertEqual(protocol.parse_config_response(frame, request), bytes(56))

    def test_invalid_or_mismatched_frames_are_ignored(self):
        request = protocol.GLW_CONFIG_REQUESTS[0]
        data = bytes(request.size)
        valid = response(request, data)
        cases = {
            "report id": response(request, data, report_id=1),
            "command": response(request, data, command=b"\xaa\x04"),
            "size": response(request, data, size=request.size - 1),
            "offset": response(request, data, offset=1),
            "truncated native frame": valid[:-1],
            "oversized native frame": valid + b"\x00",
        }
        for name, frame in cases.items():
            with self.subTest(name=name):
                self.assertIsNone(protocol.parse_config_response(frame, request))

    def test_config_battery_boundaries_and_charging_bit(self):
        config = bytearray(64)
        for packed, level, status in (
                (0, 0, "not_charging"),
                (100, 100, "not_charging"),
                (0x80, 0, "charging"),
                (0xE4, 100, "charging")):
            with self.subTest(packed=packed):
                config[32] = packed
                self.assertEqual(
                    protocol.decode_config_battery(config),
                    protocol.BatteryNotification(level, status))

    def test_invalid_config_length_or_percentage_returns_none(self):
        self.assertIsNone(protocol.decode_config_battery(bytes(63)))
        self.assertIsNone(protocol.decode_config_battery(bytes(65)))
        for packed in (101, 127):
            config = bytearray(64)
            config[32] = packed
            with self.subTest(packed=packed):
                self.assertIsNone(protocol.decode_config_battery(config))

    def test_passive_notification_decoder_remains_available(self):
        self.assertEqual(
            protocol.decode_input_report(b"\x00\xfa\xfb\x07\x36\x00"),
            protocol.BatteryNotification(54, "not_charging"))


if __name__ == "__main__":
    unittest.main()
