"""Device identities and presentation state, without Windows or HID access."""
import time
import uuid

STALE_ICON_SECONDS = 300


def tray_identity(key):
    guid = uuid.uuid5(uuid.NAMESPACE_DNS, "batterytray.local.device." + key)
    uid = {"rapoo": 1, "keyboard": 2, "mouse": 3, "headset": 4}.get(key)
    return uid if uid is not None else 256 + (guid.int & 0x7FFFFFFF), str(guid)


def tray_readings(readings, now=None):
    now = time.time() if now is None else now
    return {key: reading for key, reading in readings.items()
            if reading and reading.present and reading.ok
            and reading.level is not None and 0 <= reading.level <= 100
            and (not reading.stale or
                 0 <= now - getattr(reading, "ts", 0) <= STALE_ICON_SECONDS)}


def reading_summary(reading):
    if not reading.present:
        return "未连接", "连接设备后会自动检测"
    stamp = time.strftime("%H:%M:%S", time.localtime(reading.ts))
    if reading.stale:
        reason = "读取超时" if "超时" in reading.detail else "本轮未读到有效电量"
        return "上次读数 · " + stamp, reason + "，等待下次自动刷新"
    if reading.ok and reading.level is not None:
        state = "充电中" if reading.status == "charging" else "实时电量"
        return state + " · " + stamp, ""
    if "超时" in reading.detail:
        return "读取超时", "等待下次自动刷新，可点击底部状态手动刷新"
    return "电量未知", "已发现设备，等待有效电量数据"
