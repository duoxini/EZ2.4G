"""Persistent passive Rapoo input monitor with injected device access.

This module never enumerates devices, writes reports, or accesses application
configuration. All device access is supplied by ``open_device``.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Iterable

from rapoo_protocol import VT3S_MAX_IDS as RAPOO_IDS, decode_input_report


RAPOO_USAGE_PAGE = 0xFF00
RAPOO_USAGES = frozenset({0x0E, 0x02})
MIN_INPUT_LEN = 13


class RapooInputMonitor:
    """Keep eligible Rapoo input handles open and publish valid reports.

    ``configure`` replaces the current interface snapshot. Handles for paths
    that remain eligible are retained; removed paths are closed, and newly
    eligible paths are opened read-only. A failed path is not reopened until a
    later configuration generation arrives.
    """

    def __init__(self, open_device: Callable, updates_queue):
        self._open_device = open_device
        self._updates = updates_queue
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._generation = 0
        self._ifaces = []
        self._thread: threading.Thread | None = None

    def start(self):
        with self._lock:
            if self._thread is not None:
                return
            self._thread = threading.Thread(
                target=self._worker, name="RapooInputMonitor", daemon=True)
            self._thread.start()
        self._wake.set()

    def configure(self, ifaces: Iterable):
        with self._lock:
            self._ifaces = list(ifaces)
            self._generation += 1
        self._wake.set()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def join(self, timeout=None):
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)

    @staticmethod
    def _eligible(iface) -> bool:
        return ((iface.vid, iface.pid) in RAPOO_IDS
                and iface.usage_page == RAPOO_USAGE_PAGE
                and iface.usage in RAPOO_USAGES
                and iface.input_len >= MIN_INPUT_LEN)

    def _emit_error(self, iface, message):
        self._updates.put(("error", iface, str(message)))

    def _close(self, iface, device):
        try:
            device.close()
        except Exception as exc:
            self._emit_error(iface, f"close failed: {exc}")

    def _worker(self):
        devices = {}  # path -> (iface, device)
        blocked = set()
        applied_generation = -1
        try:
            while not self._stop.is_set():
                with self._lock:
                    generation = self._generation
                    configured = list(self._ifaces)

                if generation != applied_generation:
                    eligible = {iface.path: iface for iface in configured
                                if self._eligible(iface)}
                    for path in list(devices):
                        if path not in eligible:
                            iface, device = devices.pop(path)
                            self._close(iface, device)
                    # A new snapshot is the explicit retry signal for paths
                    # that failed in the previous generation.
                    blocked.clear()
                    for path, iface in eligible.items():
                        if path in devices or path in blocked:
                            if path in devices:
                                devices[path] = (iface, devices[path][1])
                            continue
                        try:
                            device = self._open_device(iface.path, write=False)
                        except Exception as exc:
                            blocked.add(path)
                            self._emit_error(iface, f"open failed: {exc}")
                            continue
                        devices[path] = (iface, device)
                    applied_generation = generation

                if self._stop.is_set():
                    break
                if not devices:
                    self._wake.wait(0.05)
                    self._wake.clear()
                    continue

                for path, (iface, device) in list(devices.items()):
                    if self._stop.is_set():
                        break
                    with self._lock:
                        changed = self._generation != applied_generation
                    if changed:
                        break
                    try:
                        raw = device.read_input(iface.input_len, 100)
                    except Exception as exc:
                        devices.pop(path, None)
                        blocked.add(path)
                        self._close(iface, device)
                        self._emit_error(iface, f"read failed: {exc}")
                        continue
                    if not raw:
                        continue
                    battery = decode_input_report(raw)
                    if battery is not None:
                        self._updates.put(("reading", iface, battery, raw,
                                           time.time()))
                if not devices:
                    self._wake.wait(0.05)
                    self._wake.clear()
        finally:
            for iface, device in list(devices.values()):
                self._close(iface, device)
