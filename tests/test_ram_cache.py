"""Effective settings and native file notifications, with isolated owned processes."""
import asyncio
import json
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from backend.infrastructure.mpv.controller import MPVController
from backend.infrastructure.torrserver import client, process

ROOT = Path(__file__).resolve().parents[1]


class FileEvents:
    """ReadDirectoryChangesW observes creation AND deletion of transient child files."""
    def __init__(self, directory):
        self.events = []
        self.directory = directory
        self.handle = None

    def __enter__(self):
        if os.name != 'nt':
            return self
        import ctypes
        from ctypes import wintypes
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                          ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        self.kernel.CreateFileW.restype = wintypes.HANDLE
        self.kernel.ReadDirectoryChangesW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
            wintypes.BOOL, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p, ctypes.c_void_p]
        self.kernel.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.CreateFileW(str(self.directory), 1, 7, None, 3, 0x02000000, None)
        assert self.handle != ctypes.c_void_p(-1).value
        self.ready = threading.Event()
        def watch():
            import struct
            buffer = ctypes.create_string_buffer(65536)
            count = wintypes.DWORD()
            while True:
                self.ready.set()
                if not self.kernel.ReadDirectoryChangesW(self.handle, buffer, len(buffer), True,
                                                        0x1f, ctypes.byref(count), None, None):
                    return
                offset = 0
                while offset < count.value:
                    next_offset, action, length = struct.unpack_from('III', buffer.raw, offset)
                    self.events.append((action, buffer.raw[offset+12:offset+12+length].decode('utf-16le')))
                    if not next_offset:
                        break
                    offset += next_offset
        self.thread = threading.Thread(target=watch, daemon=True)
        self.thread.start()
        assert self.ready.wait(2)
        return self

    def __exit__(self, *args):
        if self.handle:
            self.kernel.CancelIoEx(self.handle, None)
            self.thread.join(2)
            self.kernel.CloseHandle(self.handle)
            assert not self.thread.is_alive()


def test_managed_settings_preserve_unrelated_and_verify(monkeypatch):
    settings = {'UseDisk': True, 'CacheSize': 0, 'DisableUTP': True, 'EnableRutorSearch': False}
    transport = Mock()
    transport.post.return_value.json.side_effect = [settings.copy(), {'UseDisk': False, 'CacheSize': client.RAM_CACHE_LIMIT}]
    monkeypatch.setattr(process.httpx, 'Client', Mock(return_value=Mock(__enter__=Mock(return_value=transport), __exit__=Mock())))
    process._optimize_settings('http://localhost:8090')
    payload = transport.post.call_args_list[1].kwargs['json']['sets']
    assert payload == {**settings, 'UseDisk': False, 'CacheSize': client.RAM_CACHE_LIMIT}


@pytest.mark.parametrize('sets', [None, {}, {'UseDisk': True, 'CacheSize': 100},
    {'UseDisk': False, 'CacheSize': 0}, {'UseDisk': False, 'CacheSize': True},
    {'UseDisk': False, 'CacheSize': client.RAM_CACHE_LIMIT+1}])
def test_unverified_settings_rejected(sets):
    assert not client.ram_cache_verified(sets)


def test_external_server_gate_never_writes(monkeypatch):
    async def run():
        from backend.exceptions import ExternalServiceError
        calls = []
        async def respond(request):
            calls.append(json.loads(request.content))
            return httpx.Response(200, json={'UseDisk': True, 'CacheSize': 64*1024*1024})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            monkeypatch.setattr(client, 'get_client', lambda: http)
            with pytest.raises(ExternalServiceError, match='RAM-only'):
                await client.require_ram_cache('http://example.test')
        assert calls == [{'action': 'get'}]
    asyncio.run(run())


def test_real_torrserver_persistence_and_file_events(tmp_path, monkeypatch):
    binary = ROOT / 'vendor/torrserver' / ('torrserver.exe' if os.name == 'nt' else 'torrserver')
    if not binary.is_file():
        pytest.skip('TorrServer for host OS unavailable')
    with socket.socket() as available:
        available.bind(('127.0.0.1', 0))
        url = f'http://127.0.0.1:{available.getsockname()[1]}'
    monkeypatch.setattr(process, '_process', None)
    monkeypatch.setattr(process, '_managed_config', None)
    monkeypatch.setattr(process, '_monitor_stop', threading.Event())
    monkeypatch.setattr(process, '_stop_requested', threading.Event())
    data = tmp_path / 'server'
    data.mkdir()
    with FileEvents(tmp_path) as events:
        try:
            assert process.connect_or_start(url, binary, data)
            with httpx.Client(trust_env=False,timeout=20) as http:
                first = http.post(url+'/settings', json={'action': 'get'}).json()
                assert client.ram_cache_verified(first)
                assert first['CacheSize'] == client.RAM_CACHE_LIMIT
                with socket.socket() as available:
                    available.bind(('127.0.0.1',0))
                    torrent_port=available.getsockname()[1]
                first['PeersListenPort']=torrent_port
                http.post(url+'/settings',json={'action':'set','sets':first}).raise_for_status()
                first=http.post(url+'/settings',json={'action':'get'}).json()
            # Feed actual torrent payload from a loopback BitTorrent peer.
            import hashlib
            from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
            payload = bytes(range(256)) * 2048
            piece_length = 16384
            def bencode(value):
                if isinstance(value, int): return b'i'+str(value).encode()+b'e'
                if isinstance(value, bytes): return str(len(value)).encode()+b':'+value
                if isinstance(value, list): return b'l'+b''.join(map(bencode,value))+b'e'
                return b'd'+b''.join(bencode(k)+bencode(v) for k,v in sorted(value.items()))+b'e'
            info = {b'private': 1, b'name': b'fixture.mp4', b'length': len(payload), b'piece length': piece_length,
                    b'pieces': b''.join(hashlib.sha1(payload[i:i+piece_length]).digest()
                                        for i in range(0,len(payload),piece_length))}
            torrent = b''
            class Seed(BaseHTTPRequestHandler):
                def do_GET(self):
                    if self.path.startswith('/announce'):
                        import struct
                        body = bencode({b'interval': 10, b'complete': 1, b'incomplete': 0,
                            b'peers': socket.inet_aton('127.0.0.1')+struct.pack('!H', peer.getsockname()[1])})
                    else:
                        body = torrent if self.path.startswith('/fixture.torrent') else payload
                    range_header = self.headers.get('Range')
                    start, end = 0, len(body)-1
                    if range_header:
                        bounds = range_header.removeprefix('bytes=').split('-')
                        start = int(bounds[0]); end = int(bounds[1]) if bounds[1] else end
                        end = min(end,len(body)-1)
                    self.send_response(206 if range_header else 200)
                    self.send_header('Content-Length', str(end-start+1))
                    self.send_header('Accept-Ranges','bytes')
                    if range_header: self.send_header('Content-Range',f'bytes {start}-{end}/{len(body)}')
                    self.end_headers()
                    try: self.wfile.write(body[start:end+1])
                    except (BrokenPipeError,ConnectionResetError): pass
                def log_message(self,*args): pass
            import struct
            peer = socket.socket(); peer.bind(('127.0.0.1',0)); peer.listen(); peer.settimeout(.2)
            peer_stop = threading.Event()
            def seed_peer():
                def receive(conn,size):
                    result = b''
                    while len(result)<size:
                        chunk=conn.recv(size-len(result))
                        if not chunk: raise ConnectionError()
                        result+=chunk
                    return result
                while not peer_stop.is_set():
                    try:
                        conn=socket.create_connection(('127.0.0.1',torrent_port),timeout=.5)
                        conn.sendall(b'\x13BitTorrent protocol'+bytes(8)+hashlib.sha1(bencode(info)).digest()+b'-PC0001-123456789012')
                    except OSError:
                        time.sleep(.1)
                        continue
                    try:
                        conn.settimeout(3)
                        handshake=receive(conn,68)
                        if handshake[:20] != b'\x13BitTorrent protocol': continue
                        assert handshake[28:48] == hashlib.sha1(bencode(info)).digest()
                        count=len(payload)//piece_length
                        bitfield=bytes([255])*((count+7)//8)
                        conn.sendall(struct.pack('!IB',len(bitfield)+1,5)+bitfield+b'\x00\x00\x00\x01\x01')
                        while not peer_stop.is_set():
                            size=struct.unpack('!I',receive(conn,4))[0]
                            if not size: continue
                            msg=receive(conn,size)
                            if msg[0]==6:
                                index,begin,length=struct.unpack('!III',msg[1:])
                                block=payload[index*piece_length+begin:index*piece_length+begin+length]
                                conn.sendall(struct.pack('!IBII',9+len(block),7,index,begin)+block)
                    except (OSError,ConnectionError): pass
                    finally: conn.close()
            peer_worker=threading.Thread(target=seed_peer,daemon=True);peer_worker.start()
            with ThreadingHTTPServer(('127.0.0.1',0),Seed) as seed:
                seed_url = f'http://127.0.0.1:{seed.server_port}'
                torrent = bencode({b'info':info,b'announce':f'{seed_url}/announce'.encode()})
                worker = threading.Thread(target=seed.serve_forever,daemon=True); worker.start()
                try:
                    with httpx.Client(trust_env=False,timeout=15) as http:
                        added = http.post(url+'/torrents',json={'action':'add',
                            'link':seed_url+'/fixture.torrent','save_to_db':False})
                        added.raise_for_status()
                        hash_ = hashlib.sha1(bencode(info)).hexdigest()
                        result = http.get(url+f'/stream/fixture.mp4?link={hash_}&index=1&play',
                                          headers={'Range':'bytes=0-32767'})
                        result.raise_for_status()
                        assert result.content == payload[:32768]
                        cache = http.post(url+'/cache',json={'action':'get','hash':hash_}).json()
                        assert cache.get('Filled',cache.get('filled',0)) > 0, cache
                finally:
                    seed.shutdown(); worker.join(2)
                    peer_stop.set(); peer.close(); peer_worker.join(4)
            assert process.restart(url)
            with httpx.Client(trust_env=False,timeout=20) as http:
                second = http.post(url+'/settings', json={'action': 'get'}).json()
                assert client.ram_cache_verified(second)
                assert second == first
        finally:
            process.stop()
        time.sleep(.1)
    assert not [name for _,name in events.events if Path(name).suffix.lower() in
                {'.bgra', '.part', '.mkv', '.jpg', '.mp4', '.ts'}]
    assert {p.name for p in data.rglob('*') if p.is_file()} <= {'startup.log','config.db','settings.json'}
    if os.name == 'nt':
        # Include extensionless block files and create-then-delete files in this assertion.
        assert {name.replace('\\','/') for action,name in events.events if action in (1,5)} <= {
            'server/startup.log','server/config.db','server/settings.json'}


def test_real_mpv_policy_seek_pause_replace_restart_and_preview(tmp_path, monkeypatch):
    from backend.infrastructure.mpv.preview import PreviewSession
    binary = ROOT / 'mpv/mpv.com'
    mpv = str(binary) if binary.is_file() else shutil.which('mpv')
    ffmpeg = shutil.which('ffmpeg')
    if not mpv or not ffmpeg:
        pytest.skip('Host MPV/FFmpeg unavailable')
    source = tmp_path / 'fixture.mp4'
    subprocess.run([ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i',
                    'testsrc2=size=320x180:rate=5', '-t', '30', '-threads', '1', str(source)],
                   check=True, timeout=15)
    data = tmp_path / 'data'; data.mkdir()
    temporary = tmp_path / 'temp'; temporary.mkdir()
    monkeypatch.setenv('TEMP', str(temporary)); monkeypatch.setenv('TMP', str(temporary))
    monkeypatch.setattr('backend.infrastructure.mpv.controller.get_data_dir', lambda: data)
    args = [a for a in process.config.MPV_ARGS if a != '--fs'] + ['--vo=null', '--ao=null']
    monkeypatch.setattr(process.config, 'MPV_ARGS', args)
    c = MPVController()
    observed = {}
    c.on_progress = lambda name, value: observed.update({name: value})
    def until(predicate):
        deadline = time.monotonic()+5
        while not predicate():
            assert time.monotonic()<deadline, observed
            time.sleep(.02)
    with FileEvents(tmp_path) as events:
        try:
            for _ in range(2):
                observed.clear()
                c.launch(mpv, str(source), 'RAM cache integration')
                assert c._cache_policy_valid(), c._cache_properties
                until(lambda: (observed.get('duration') or 0)>0)
                c.send_command(['set_property', 'pause', True])
                until(lambda: observed.get('pause') is True)
                c.send_command(['seek', 20, 'absolute+exact'])
                until(lambda: abs((observed.get('time-pos') or 0)-20)<1)
                c.send_command(['seek', 5, 'absolute+exact'])
                until(lambda: abs((observed.get('time-pos') or 0)-5)<1)
                results, ready = [], threading.Event()
                session = PreviewSession(str(source), lambda *r, results=results, ready=ready: (results.append(r), ready.set()))
                try:
                    session.request('1', '10')
                    assert ready.wait(10) and results[0][1]
                finally:
                    session.close()
                c.load_file(str(source), 'Replacement', start_time=10)
                until(lambda: abs((observed.get('time-pos') or 0)-10)<2)
                c.stop()
        finally:
            c.stop()
        time.sleep(.1)
    assert not [name for _,name in events.events if Path(name).suffix.lower() in
                {'.bgra', '.part', '.mkv', '.jpg', '.mp4', '.ts'}]
    assert {p.name for p in data.iterdir()} == {'mpv_debug.log'}
    assert not list(temporary.iterdir())


def test_unix_socket_ipc_branch_on_host(monkeypatch):
    """Exercise the Unix IPC branch; this is not a Linux runtime test."""
    import types

    import backend.infrastructure.mpv.controller as module
    monkeypatch.setattr(module, 'os', types.SimpleNamespace(name='posix'))
    a,b=socket.socketpair()
    c=MPVController(); c.pipe=a; c.is_running=True
    try:
        c.send_command(['get_property','options/cache-on-disk'],request_id=8101)
        sent=json.loads(b.recv(1024))
        assert sent['request_id']==8101
        b.sendall((json.dumps({'request_id':8101,'error':'success','data':False})+'\n').encode())
        b.shutdown(socket.SHUT_WR)
        c._reader_loop()
        assert c._cache_properties[8101] is False
    finally:
        a.close(); b.close()


@pytest.mark.parametrize('disk,forward,back', [(True,128,32),(False,0,32),(False,129,32),(False,128,33)])
def test_mpv_unverified_policy_stops_before_loading(disk,forward,back):
    c=MPVController()
    values={8100:'yes',8101:disk,8102:forward*1024*1024,8103:back*1024*1024}
    def reply(command,request_id=None):
        c._cache_properties[request_id]=values[request_id]
        if len(c._cache_properties)==4: c._cache_ready.set()
    c.send_command=reply
    c.stop=Mock()
    with pytest.raises(RuntimeError,match='RAM-only'):
        c._verify_cache()
    c.stop.assert_called_once()


def test_service_blocks_unsafe_server_before_player_launch():
    from unittest.mock import AsyncMock, MagicMock

    from backend.exceptions import ExternalServiceError
    from backend.models.playback import PlayCommand
    from backend.services.playback import PlaybackService
    server=MagicMock(require_ram_cache=AsyncMock(side_effect=ExternalServiceError('unsafe',status_code=409)))
    factory=Mock()
    service=PlaybackService(MagicMock(),MagicMock(),MagicMock(),factory,server,lambda:'http://ts')
    with pytest.raises(ExternalServiceError,match='unsafe'):
        asyncio.run(service.launch(PlayCommand('a'*40,1,'film.mp4')))
    factory.assert_not_called()
    server.stream_url.assert_not_called()
