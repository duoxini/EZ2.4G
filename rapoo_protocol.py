"""Offline decoder for the documented Rapoo VT_nrf54L input report layout.

This module only interprets caller-supplied bytes. It performs no device
discovery or I/O. The report layout was derived from the official VT3S MAX
WebHID parser; test vectors are synthetic and are not captured device data.
"""
from __future__ import annotations

from dataclasses import dataclass


RAPOO_VID = 0x24AE
VT3S_MAX_PID = 0x4621
VT3S_MAX_RECEIVER_ALIAS_PID = 0x1421
VT3S_MAX_IDS = frozenset({(RAPOO_VID, VT3S_MAX_PID),
                          (RAPOO_VID, VT3S_MAX_RECEIVER_ALIAS_PID)})
VT3S_MAX_USAGE_PAGE = 0xFF00
VT_NRF54L_REPORT_ID = 0x07


@dataclass(frozen=True)
class Battery:
    """A validated battery value from one VT_nrf54L input report."""

    level: int
    status: str
    connection_mode: int


def decode_input_report(raw: bytes | bytearray | memoryview) -> Battery | None:
    """Decode one Windows HID input report, including its report-ID prefix.

    Windows ``ReadFile`` data begins with the report ID at raw[0]. The VT
    parser's payload offsets therefore map to raw[1:] (status at raw[7],
    percentage at raw[8]). Require all 12 payload bytes even though the
    battery fields occur earlier, so partial reports are never accepted.
    """
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        return None
    if len(raw) < 13 or raw[0] != VT_NRF54L_REPORT_ID:
        return None

    connection_mode = raw[1] & 0x0F
    if connection_mode not in (0, 1, 2):
        return None

    battery_status = raw[7]
    if battery_status not in (1, 2):
        return None

    level = raw[8]
    if not 0 <= level <= 100:
        return None

    status = "charging" if battery_status == 2 else "discharging"
    return Battery(level=level, status=status,
                   connection_mode=connection_mode)
