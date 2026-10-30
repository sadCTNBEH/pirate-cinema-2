"""Suppress only the known Windows socket-shutdown reset callback."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.infrastructure import asyncio_errors


def reset_context(callback_name='_ProactorBasePipeTransport._call_connection_lost', winerror=10054):
    error = ConnectionResetError('peer reset')
    error.winerror = winerror
    def callback():
        pass
    callback.__qualname__ = callback_name
    return {'exception': error, 'handle': SimpleNamespace(_callback=callback)}


def test_windows_shutdown_reset_is_expected_and_handler_is_restored(monkeypatch):
    monkeypatch.setattr(asyncio_errors.sys, 'platform', 'win32')
    loop = MagicMock()
    previous = loop.get_exception_handler.return_value
    with asyncio_errors.windows_transport_cleanup(loop):
        handler = loop.set_exception_handler.call_args.args[0]
        handler(loop, reset_context())
        previous.assert_not_called()
        loop.default_exception_handler.assert_not_called()
        # Other callbacks and error codes must still reach the existing handler.
        other = reset_context('application_callback')
        handler(loop, other)
        previous.assert_called_once_with(loop, other)
        handler(loop, reset_context(winerror=10053))
        assert previous.call_count == 2
    loop.set_exception_handler.assert_called_with(previous)


def test_unrelated_errors_keep_default_reporting(monkeypatch):
    monkeypatch.setattr(asyncio_errors.sys, 'platform', 'win32')
    loop = MagicMock()
    loop.get_exception_handler.return_value = None
    with asyncio_errors.windows_transport_cleanup(loop):
        handler = loop.set_exception_handler.call_args.args[0]
        context = {'exception': RuntimeError('unexpected failure')}
        handler(loop, context)
        loop.default_exception_handler.assert_called_once_with(context)


def test_other_platforms_do_not_replace_handler(monkeypatch):
    monkeypatch.setattr(asyncio_errors.sys, 'platform', 'linux')
    loop = MagicMock()
    with asyncio_errors.windows_transport_cleanup(loop):
        pass
    loop.set_exception_handler.assert_not_called()
