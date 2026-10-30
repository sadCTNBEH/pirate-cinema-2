"""Pairing recovery must survive a new browser tab and a PC restart."""
import hashlib
import json
import time

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.models.playback import PlaybackState
from backend.services.mobile import MobileAccess, MobileSession


def request(*, host='192.168.1.5', token='', cookie=''):
    headers = [(b'host', b'192.168.1.2:8000')]
    if token:
        headers.append((b'x-remote-token', token.encode()))
    if cookie:
        headers.append((b'cookie', ('pc_remote=' + cookie).encode()))
    return Request({'type': 'http', 'method': 'POST', 'scheme': 'http', 'path': '/',
                    'query_string': b'', 'headers': headers, 'server': ('192.168.1.2', 8000),
                    'client': (host, 123)})


def test_pairing_survives_server_restart_without_storing_raw_token(tmp_path):
    path = tmp_path / 'remote-pairs.json'
    before = MobileAccess()
    before.enable_persistence(path)
    token = before.pair(request(), before.code)
    assert token not in path.read_text()
    after = MobileAccess()
    after.enable_persistence(path)
    assert after.authorize(request(token=token)) == token
    with pytest.raises(HTTPException) as error:
        after.authorize(request(host='192.168.1.6', token=token))
    assert error.value.status_code == 401


def test_expired_saved_pairing_is_rejected(tmp_path):
    path = tmp_path / 'remote-pairs.json'
    path.write_text(json.dumps({hashlib.sha256(b'expired').hexdigest(): {
        'host': '192.168.1.5', 'expires': time.time() - 1,
    }}))
    access = MobileAccess()
    access.enable_persistence(path)
    with pytest.raises(HTTPException) as error:
        access.authorize(request(token='expired'))
    assert error.value.status_code == 401


def test_stale_tab_header_does_not_override_valid_cookie():
    access = MobileAccess()
    token = access.pair(request(), access.code)
    req = request(token='old-tab-token', cookie=token)
    assert access.authorize(req) == token
    session = MobileSession(token, '192.168.1.5', 'http://127.0.0.1/source', PlaybackState('a' * 40, 1))
    access.sessions['video'] = session
    assert access.session(req, 'video') is session


def test_anonymous_request_still_needs_pairing():
    access = MobileAccess()
    access.pair(request(), access.code)
    with pytest.raises(HTTPException) as error:
        access.authorize(request())
    assert error.value.status_code == 401
