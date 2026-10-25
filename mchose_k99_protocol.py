"""Pure decoder for K99 V3's official GLW battery notifications.

No device I/O. See docs/MCHOSE_K99_V3_PROTOCOL_EVIDENCE.md. Test vectors
are synthetic; no live K99 V3 report has been collected.
"""
from __future__ import annotations

from dataclasses import dataclass

K99_V3_WIRED_IDS = frozenset({(0x3837, 0x2020)})
K99_V3_RECEIVER_ID = (0x3837, 0x3033)
K99_V3_RECEIVER_PRODUCT = "MCHOSE K99 V3 2.4G"
K99_V3_IDS = K99_V3_WIRED_IDS | {K99_V3_RECEIVER_ID}


def is_k99_v3(vid: int, pid: int, product: str = "") -> bool:
    """The receiver PID is shared; its product string is part of identity."""
    return ((vid, pid) in K99_V3_WIRED_IDS or
            ((vid, pid) == K99_V3_RECEIVER_ID and
             product == K99_V3_RECEIVER_PRODUCT))


@dataclass(frozen=True)
class BatteryNotification:
    level: int | None
    status: str


def decode_payload(payload: bytes | bytearray | memoryview) -> BatteryNotification | None:
    """Parse WebHID payload FA FB 07 <value> <charging>.

    The official handler emits a percentage only when charging == 0.
    When charging == 1 it emits only a charging event; value is not used.
    There is no evidenced checksum, fixed payload length or report ID check
    in that notification branch. Require all five referenced payload bytes.
    """
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        return None
    payload = bytes(payload)
    if len(payload) < 5 or payload[:3] != b"\xfa\xfb\x07":
        return None
    if payload[4] == 1:
        return BatteryNotification(None, "charging")
    if payload[4] != 0 or payload[3] > 100:
        return None
    return BatteryNotification(payload[3], "not_charging")


def decode_input_report(raw: bytes | bytearray | memoryview) -> BatteryNotification | None:
    """Windows ReadFile prefix is a report ID, separate from WebHID data.

    The official GLW handler does not filter event.reportId. Preserve that
    behavior instead of inventing an ID; native descriptor/ID awaits sampling.
    """
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        return None
    return decode_payload(bytes(raw)[1:])


@dataclass(frozen=True)
class GLWConfigRequest:
    """A range in the documented profile-0, function-5 configuration read."""

    offset: int
    size: int


GLW_CONFIG_REQUESTS = (
    GLWConfigRequest(offset=0, size=56),
    GLWConfigRequest(offset=56, size=8),
)
GLW_CONFIG_SIZE = 64
GLW_CONFIG_BATTERY_OFFSET = 32


@dataclass(frozen=True)
class GLWConfigBattery:
    level: int
    charging: bool


def _validate_config_request(request: GLWConfigRequest) -> None:
    if request not in GLW_CONFIG_REQUESTS:
        raise ValueError("unsupported GLW configuration request range")


def build_glw_config_request(request: GLWConfigRequest) -> bytes:
    """Build one native Windows HID report (report ID + 64-byte payload).

    Payload headers are the two statically verified profile-0 requests; the
    remainder of each 64-byte payload is zero padded.
    """
    _validate_config_request(request)
    end = request.offset + request.size
    header = bytes((0x55, 0x05, 0x00, end & 0xFF, request.size,
                    request.offset & 0xFF, (request.offset >> 8) & 0xFF, 0x00))
    payload = header + bytes(64 - len(header))
    return b"\x00" + payload


def build_config_request(request: GLWConfigRequest) -> bytes:
    """Main-program API alias for building a fixed GLW profile request."""
    return build_glw_config_request(request)


def parse_glw_config_response(
        raw: bytes | bytearray | memoryview,
        request: GLWConfigRequest) -> bytes:
    """Validate one native 65-byte response and return its data chunk.

    The response header is report ID 0, ``AA 05``, then reserved/end, size,
    little-endian offset, and an unchecked byte. Data begins at native raw[9].
    The official path does not validate a response checksum, so this helper
    deliberately does not invent one.
    """
    _validate_config_request(request)
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise ValueError("response must be bytes-like")
    raw = bytes(raw)
    if len(raw) != 65:
        raise ValueError("GLW response must be exactly 65 native bytes")
    if raw[0] != 0:
        raise ValueError("unexpected GLW report ID")
    if raw[1:3] != b"\xaa\x05":
        raise ValueError("unexpected GLW response command")
    size = raw[5]
    offset = raw[6] | (raw[7] << 8)
    if size != request.size:
        raise ValueError("GLW response size does not match request")
    if size > request.size:
        raise ValueError("GLW response exceeds requested range")
    if offset != request.offset:
        raise ValueError("GLW response offset does not match request")
    chunk = raw[9:9 + size]
    if len(chunk) != request.size:
        raise ValueError("truncated GLW response data")
    return chunk


def parse_config_response(
        raw: bytes | bytearray | memoryview,
        request: GLWConfigRequest) -> bytes | None:
    """Main-program read-loop API; malformed or mismatched reports are ignored."""
    try:
        return parse_glw_config_response(raw, request)
    except ValueError:
        return None


def decode_config64(config: bytes | bytearray | memoryview) -> GLWConfigBattery:
    """Decode profile config byte 32: low 7-bit percent, high charging bit."""
    if not isinstance(config, (bytes, bytearray, memoryview)):
        raise ValueError("configuration must be bytes-like")
    config = bytes(config)
    if len(config) != GLW_CONFIG_SIZE:
        raise ValueError("GLW configuration must be exactly 64 bytes")
    value = config[GLW_CONFIG_BATTERY_OFFSET]
    level = value & 0x7F
    if level > 100:
        raise ValueError("GLW battery percentage is outside 0..100")
    return GLWConfigBattery(level=level, charging=bool(value & 0x80))


def decode_config_battery(
        config: bytes | bytearray | memoryview) -> BatteryNotification | None:
    """Main-program API for config byte 32, returning None on invalid data."""
    try:
        battery = decode_config64(config)
    except ValueError:
        return None
    return BatteryNotification(
        battery.level, "charging" if battery.charging else "not_charging")
