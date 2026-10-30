"""Handle peer resets during Windows asyncio transport cleanup."""
import asyncio
import logging
import sys
from contextlib import contextmanager

logger = logging.getLogger(__name__)


@contextmanager
def windows_transport_cleanup(loop: asyncio.AbstractEventLoop):
    """Ignore only WinError 10054 from Proactor's socket shutdown callback."""
    if sys.platform != 'win32':
        yield
        return
    previous = loop.get_exception_handler()

    def handle_exception(event_loop, context):
        error = context.get('exception')
        callback = getattr(context.get('handle'), '_callback', None)
        if (isinstance(error, ConnectionResetError)
                and getattr(error, 'winerror', None) == 10054
                and getattr(callback, '__qualname__', '') == '_ProactorBasePipeTransport._call_connection_lost'):
            logger.debug('Peer reset an already-closing Windows transport')
            return
        if previous is not None:
            previous(event_loop, context)
        else:
            event_loop.default_exception_handler(context)

    loop.set_exception_handler(handle_exception)
    try:
        yield
    finally:
        loop.set_exception_handler(previous)
