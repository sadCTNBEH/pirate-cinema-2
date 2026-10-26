"""Keep HTTP transport diagnostics from disclosing private search URLs."""

import logging
from contextlib import contextmanager
from contextvars import ContextVar

_private_search = ContextVar("private_search_http", default=False)


class _SearchTransportFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if _private_search.get():
            record.msg = "Search HTTP transport event (details redacted)"
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return True


for _name in (
    "httpx",
    "httpcore.connection",
    "httpcore.http11",
    "httpcore.http2",
    "httpcore.proxy",
    "httpcore.socks",
):
    logging.getLogger(_name).addFilter(_SearchTransportFilter())


@contextmanager
def private_http_logging():
    # Context-local: concurrent unrelated HTTP requests keep their diagnostics.
    token = _private_search.set(True)
    try:
        yield
    finally:
        _private_search.reset(token)
