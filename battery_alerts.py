"""Low-battery notification policy; no Windows or device access."""


def clamp_threshold(value) -> int:
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError, OverflowError):
        return 20


class LowBatteryAlerts:
    def __init__(self, threshold=20):
        self.threshold = clamp_threshold(threshold)
        self.alerted = set()

    def set_threshold(self, value):
        value = clamp_threshold(value)
        if value != self.threshold:
            self.threshold = value
            self.alerted.clear()
        return value

    def pending(self, readings):
        """Return fresh low readings. Remember them only after Windows accepts."""
        if self.threshold == 0:
            return {}
        result = {}
        for key, reading in readings.items():
            if (not reading or not reading.present or not reading.ok
                    or reading.stale or reading.level is None
                    or not 0 <= reading.level <= 100):
                continue
            if (reading.status in ("charging", "wired", "full")
                    or reading.level >= min(100, self.threshold + 3)):
                self.alerted.discard(key)
            elif reading.level < self.threshold and key not in self.alerted:
                result[key] = reading
        return result

    def mark_sent(self, readings):
        self.alerted.update(readings)
