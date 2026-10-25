"""Offline tests for the HidDevice.read_input OVERLAPPED lifecycle."""
from __future__ import annotations

import ast
import ctypes
import ctypes.wintypes as wt
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock


SOURCE = Path(os.environ.get(
    "EZ24G_SOURCE", str(Path(__file__).resolve().parents[1] / "my_devices.py")
)).resolve()

REQUIRED_CONSTANTS = {
    "ERROR_IO_PENDING", "ERROR_OPERATION_ABORTED", "ERROR_NOT_FOUND",
    "WAIT_OBJECT_0", "WAIT_TIMEOUT", "WAIT_FAILED",
}


class OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_void_p),
        ("InternalHigh", ctypes.c_void_p),
        ("Offset", wt.DWORD),
        ("OffsetHigh", wt.DWORD),
        ("hEvent", wt.HANDLE),
    ]


def load_read_input():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    node = None
    constants = {}
    for top in tree.body:
        if isinstance(top, ast.Assign):
            try:
                value = ast.literal_eval(top.value)
            except (ValueError, TypeError):
                continue
            for target in top.targets:
                if isinstance(target, ast.Name) and target.id in REQUIRED_CONSTANTS:
                    constants[target.id] = value
        if isinstance(top, ast.ClassDef) and top.name == "HidDevice":
            node = next((child for child in top.body
                         if isinstance(child, ast.FunctionDef)
                         and child.name == "read_input"), None)
            break
    if node is None:
        raise AssertionError("HidDevice.read_input not found")
    missing = REQUIRED_CONSTANTS - constants.keys()
    if missing:
        raise AssertionError(
            f"Required transport constants missing from production AST: {sorted(missing)}")
    function = ast.FunctionDef(
        name="read_input_under_test", args=node.args, body=node.body,
        decorator_list=node.decorator_list, returns=node.returns,
        type_comment=node.type_comment,
    )
    ast.copy_location(function, node)
    ns = {
        "Optional": __import__("typing").Optional,
        "ctypes": None,
        "wt": wt,
        "OVERLAPPED": OVERLAPPED,
        "HidError": type("HidError", (Exception,), {}),
        "kernel32": None,
        **constants,
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]),
                 str(SOURCE), "exec"), ns)
    return ns


class ReadInputOfflineTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.last_error = 0
        self.payload = b"sample"
        self.got_values = []
        self.read_error = 997
        self.completion_error = 995
        self.wait_error = 6
        self.create_event_result = 101

        def set_got(pointer, value):
            ctypes.cast(pointer, ctypes.POINTER(wt.DWORD)).contents.value = value

        def read_file(_handle, buffer, _length, got_ptr, _ov_ptr):
            self.events.append("ReadFile")
            if self.read_file_result:
                ctypes.memmove(buffer, self.payload, len(self.payload))
                set_got(got_ptr, len(self.payload))
                return True
            self.last_error = self.read_error
            return False

        def get_overlapped(_handle, _ov_ptr, got_ptr, wait):
            self.events.append(("GetOverlappedResult", wait))
            if self.overlapped_result:
                ctypes.memmove(self.current_buffer, self.payload, len(self.payload))
                set_got(got_ptr, len(self.payload))
                return True
            self.last_error = self.completion_error
            return False

        def wait_for_single_object(_event, _timeout):
            self.events.append("WaitForSingleObject")
            result = self.wait_result
            if result == 0xFFFFFFFF:
                self.last_error = self.wait_error
            return result

        def create_event(*_args):
            self.events.append("CreateEvent")
            return self.create_event_result

        self.read_file_result = True
        self.overlapped_result = True
        self.wait_result = 0
        self.ctypes_proxy = SimpleNamespace(
            create_string_buffer=ctypes.create_string_buffer,
            byref=ctypes.byref,
            cast=ctypes.cast,
            POINTER=ctypes.POINTER,
            get_last_error=lambda: self.last_error,
        )
        self.kernel32 = SimpleNamespace(
            CreateEventW=mock.Mock(side_effect=create_event),
            ReadFile=mock.Mock(side_effect=read_file),
            WaitForSingleObject=mock.Mock(side_effect=wait_for_single_object),
            CancelIoEx=mock.Mock(side_effect=lambda *_: (self.events.append("CancelIoEx"), True)[1]),
            GetOverlappedResult=mock.Mock(side_effect=get_overlapped),
            CloseHandle=mock.Mock(side_effect=lambda *_: self.events.append("CloseHandle")),
        )
        self.ns = load_read_input()
        self.ns["ctypes"] = self.ctypes_proxy
        self.ns["kernel32"] = self.kernel32

        # Capture the created report buffer so the asynchronous mock can fill it.
        original_create = self.ctypes_proxy.create_string_buffer

        def create_buffer(*args):
            self.current_buffer = original_create(*args)
            return self.current_buffer

        self.ctypes_proxy.create_string_buffer = create_buffer
        self.device = SimpleNamespace(rh=55, read_open_error=0)

    def call(self, timeout=20):
        return self.ns["read_input_under_test"](self.device, 64, timeout)

    def pending_read(self):
        self.read_file_result = False
        self.read_error = self.ns["ERROR_IO_PENDING"]
        return None

    def test_synchronous_read_returns_bytes_without_wait(self):
        self.assertEqual(self.call(), self.payload)
        self.kernel32.WaitForSingleObject.assert_not_called()
        self.kernel32.GetOverlappedResult.assert_not_called()
        self.assertEqual(self.events[-1], "CloseHandle")

    def test_async_completion_waits_and_checks_result(self):
        self.pending_read()
        self.kernel32.WaitForSingleObject.return_value = 0
        self.assertEqual(self.call(), self.payload)
        self.kernel32.GetOverlappedResult.assert_called_once()
        self.assertTrue(self.kernel32.GetOverlappedResult.call_args.args[-1])
        self.assertLess(self.events.index(("GetOverlappedResult", True)),
                        len(self.events) - 1)

    def test_timeout_cancels_then_reaps_before_event_close(self):
        self.pending_read()
        self.wait_result = self.ns["WAIT_TIMEOUT"]
        self.overlapped_result = False
        self.completion_error = self.ns["ERROR_OPERATION_ABORTED"]
        self.assertIsNone(self.call())
        self.assertLess(self.events.index("CancelIoEx"),
                        self.events.index(("GetOverlappedResult", True)))
        self.assertLess(self.events.index(("GetOverlappedResult", True)),
                        self.events.index("CloseHandle"))

    def test_timeout_completion_race_returns_completed_data(self):
        self.pending_read()
        self.wait_result = self.ns["WAIT_TIMEOUT"]
        self.overlapped_result = True
        self.assertEqual(self.call(), self.payload)
        self.assertIn("CancelIoEx", self.events)
        self.assertLess(self.events.index(("GetOverlappedResult", True)),
                        self.events.index("CloseHandle"))

    def test_wait_failed_reaps_then_raises_with_wait_error(self):
        self.pending_read()
        self.wait_result = self.ns["WAIT_FAILED"]
        self.overlapped_result = False
        self.completion_error = self.ns["ERROR_OPERATION_ABORTED"]
        with self.assertRaisesRegex(self.ns["HidError"], "6"):
            self.call()
        self.assertLess(self.events.index(("GetOverlappedResult", True)),
                        self.events.index("CloseHandle"))

    def test_immediate_readfile_failure_raises_and_closes_event(self):
        self.pending_read()
        self.read_error = 5
        with self.assertRaisesRegex(self.ns["HidError"], "5"):
            self.call()
        self.kernel32.GetOverlappedResult.assert_not_called()
        self.assertEqual(self.events[-1], "CloseHandle")

    def test_create_event_failure_raises_with_error(self):
        self.create_event_result = 0
        self.last_error = 87
        with self.assertRaisesRegex(self.ns["HidError"], "87"):
            self.call()
        self.kernel32.ReadFile.assert_not_called()
        self.kernel32.CloseHandle.assert_not_called()

    def test_terminal_completion_failure_raises_and_closes(self):
        self.pending_read()
        self.wait_result = 0
        self.overlapped_result = False
        self.completion_error = 123
        with self.assertRaisesRegex(self.ns["HidError"], "123"):
            self.call()
        self.assertEqual(self.events[-1], "CloseHandle")

    def test_missing_overlapped_handle_reports_saved_open_error(self):
        self.device.rh = 0
        self.device.read_open_error = 5
        with self.assertRaisesRegex(self.ns["HidError"], "5"):
            self.call()
        self.kernel32.CreateEventW.assert_not_called()


if __name__ == "__main__":
    unittest.main()
