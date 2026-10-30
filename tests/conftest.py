"""Portable in-memory transport for MPV IPC reader tests."""
import io

import pytest


@pytest.fixture
def mpv_ipc_stream():
    streams = []

    class MemoryIPC(io.BytesIO):
        def __init__(self, payload=b''):
            super().__init__(payload)
            self.readers = []

        def makefile(self, mode):
            assert mode == 'rb'
            reader = io.BytesIO(self.getvalue())
            self.readers.append(reader)
            return reader

        def sendall(self, payload):
            self.write(payload)

    def create(payload=b''):
        stream = MemoryIPC(payload)
        streams.append(stream)
        return stream

    yield create
    for stream in streams:
        for reader in stream.readers:
            reader.close()
        stream.close()
