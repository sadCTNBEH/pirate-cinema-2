"""Regression coverage for MPV reads that remain pending during window changes."""

import ctypes
import os
import threading
from types import SimpleNamespace

import pytest

from backend.infrastructure.mpv import controller as mpv

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows overlapped IPC")


def make_pipe():
    pipe = mpv.WindowsPipe.__new__(mpv.WindowsPipe)
    pipe.handle = 1
    pipe._read_ov = mpv.OVERLAPPED()
    pipe._read_ov.hEvent = 2
    pipe._write_ov = mpv.OVERLAPPED()
    pipe._write_ov.hEvent = 3
    pipe._buf = bytearray()
    pipe._closed = False
    pipe._cancelled = False
    pipe._read_lock = threading.Lock()
    pipe._write_lock = threading.Lock()
    pipe._close_lock = threading.Lock()
    return pipe


def test_stop_cancellation_racing_writefile_cancels_the_new_operation():
    pipe = make_pipe()
    cancelled = []

    def write_file(*args):
        pipe.cancel_pending()  # Stop arrived after write() checked its flags.
        ctypes.set_last_error(997)
        return False

    def get_result(*args):
        assert any(item is not None for item in cancelled)
        ctypes.set_last_error(995)
        return False

    pipe.k32 = SimpleNamespace(
        ResetEvent=lambda event: True, WriteFile=write_file, GetOverlappedResult=get_result,
        CancelIoEx=lambda handle, operation: cancelled.append(operation), CloseHandle=lambda handle: None,
    )
    with pytest.raises(OSError):
        pipe.write(b'test')
    pipe.close()


@pytest.mark.parametrize("cancel", [False, True])
def test_pending_read_keeps_buffer_until_completion(cancel):
    pipe = make_pipe()
    pending = threading.Event()
    complete = threading.Event()
    closed_handles = []
    buffers = []

    def read_file(handle, buffer, size, count, overlapped):
        buffers.append(buffer)
        ctypes.set_last_error(997)
        return False

    def get_result(handle, overlapped, count, wait):
        assert wait is True
        pending.set()
        assert complete.wait(3)
        if pipe._closed:
            return False
        buffers[0].value = b"event\n"
        count._obj.value = 6
        return True

    def cancel_io(handle, overlapped):
        complete.set()
        return True

    pipe.k32 = SimpleNamespace(
        ResetEvent=lambda event: True,
        ReadFile=read_file,
        GetOverlappedResult=get_result,
        CancelIoEx=cancel_io,
        CloseHandle=closed_handles.append,
    )
    result = []
    reader = threading.Thread(target=lambda: result.append(pipe.readline()), daemon=True)
    reader.start()
    try:
        assert pending.wait(3)
        if cancel:
            pipe.close()
        else:
            complete.set()
        reader.join(3)
        assert not reader.is_alive()
        assert len(buffers) == 1
        assert result == ([b""] if cancel else [b"event\n"])
        pipe.close()
        pipe.close()
        assert closed_handles == [1, 2, 3]
    finally:
        complete.set()
        reader.join(3)
