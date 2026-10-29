"""Direct-play receivers and a short-lived, receiver-bound media relay."""
import asyncio
import ipaddress
import secrets
import socket
import time
from contextlib import suppress
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

import httpx
import uvicorn
from fastapi import FastAPI, Request
from starlette.responses import Response, StreamingResponse


def private(host):
    try:
        ip = ipaddress.IPv4Address(host)
        return any(ip in ipaddress.ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
    except ValueError:
        return False


def xml(data):
    if len(data) > 512000 or b'<!' in data:
        raise ValueError('Invalid device description')
    return ET.fromstring(data)


class DLNA:
    def __init__(self, host, name, services):
        self.host, self.name, self.services = host, name, services
        self.id = 'dlna:' + host
        self.kind = 'DLNA'
        self.actions = {}
        self.formats = []

    async def call(self, service, action, **args):
        typ, control, _ = self.services[service]
        body = ''.join(f'<{k}>{escape(str(v))}</{k}>' for k, v in args.items())
        envelope = f'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body><u:{action} xmlns:u="{typ}">{body}</u:{action}></s:Body></s:Envelope>'
        async with httpx.AsyncClient(timeout=4, trust_env=False) as client:
            r = await client.post(control, content=envelope, headers={'Content-Type': 'text/xml; charset="utf-8"', 'SOAPAction': f'"{typ}#{action}"'})
            result = {e.tag.split('}')[-1]: e.text or '' for e in xml(r.content).iter()}
            if r.is_error or 'errorCode' in result:
                raise ValueError(f"DLNA {action}: {result.get('errorDescription', 'ТВ отклонил команду')} ({result.get('errorCode', r.status_code)})")
            return result

    async def prepare(self):
        async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
            for key, (_, _, scpd) in self.services.items():
                r = await client.get(scpd)
                r.raise_for_status()
                self.actions[key] = {e.findtext('{*}name') for e in xml(r.content).findall('.//{*}action')}
        if not {'SetAVTransportURI', 'Play', 'Stop'} <= self.actions.get('AVTransport', set()):
            raise ValueError('ТВ не поддерживает управление видео')
        info = await self.call('ConnectionManager', 'GetProtocolInfo')
        self.formats = [p.split(':')[2] for p in info.get('Sink', '').split(',') if len(p.split(':')) >= 4 and p.startswith('http-get:')]
        if not any(f.startswith('video/') for f in self.formats):
            raise ValueError('Устройство не объявляет поддержку видео')

    async def start(self, url, mime, position):
        if mime not in self.formats:
            raise ValueError('ТВ не поддерживает контейнер этого видео')
        if position and 'Seek' not in self.actions['AVTransport']:
            raise ValueError('ТВ не поддерживает продолжение с текущей позиции')
        metadata = (f'<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
                    f'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
                    f'<item id="0" parentID="-1" restricted="1"><dc:title>Pirate Cinema</dc:title>'
                    f'<upnp:class>object.item.videoItem.movie</upnp:class>'
                    f'<res protocolInfo="http-get:*:{mime}:*">{escape(url)}</res></item></DIDL-Lite>')
        await self.call('AVTransport', 'SetAVTransportURI', InstanceID=0, CurrentURI=url, CurrentURIMetaData=metadata)
        await self.command('play', 0)
        # Some renderers reject Seek until the asynchronous media load completes.
        deadline = time.monotonic()+15
        while True:
            info = await self.call('AVTransport', 'GetTransportInfo', InstanceID=0)
            status = info.get('CurrentTransportState')
            if info.get('CurrentTransportStatus') == 'ERROR_OCCURRED':
                raise ValueError('ТВ сообщил об ошибке открытия видео')
            if status in ('PLAYING', 'PAUSED_PLAYBACK'): break
            if time.monotonic() >= deadline:
                raise ValueError('ТВ не начал воспроизведение. Проверьте доступ к ПК в брандмауэре и формат видео.')
            await asyncio.sleep(.5)
        if position:
            await self.command('seek', position)

    async def command(self, action, value):
        name = {'play': 'Play', 'pause': 'Pause', 'stop': 'Stop', 'seek': 'Seek', 'volume': 'SetVolume'}[action]
        service = 'RenderingControl' if action == 'volume' else 'AVTransport'
        if name not in self.actions.get(service, set()):
            raise ValueError('Команда не поддерживается телевизором')
        args = {'InstanceID': 0}
        if action == 'play': args['Speed'] = 1
        if action == 'seek': args.update(Unit='REL_TIME', Target=f'{int(value)//3600:02}:{int(value)//60%60:02}:{int(value)%60:02}')
        if action == 'volume': args.update(Channel='Master', DesiredVolume=int(value))
        await self.call(service, name, **args)

    async def status(self):
        info = await self.call('AVTransport', 'GetTransportInfo', InstanceID=0)
        pos = {}
        if 'GetPositionInfo' in self.actions.get('AVTransport', set()):
            with suppress(ValueError):
                pos = await self.call('AVTransport', 'GetPositionInfo', InstanceID=0)
        parts = pos.get('RelTime', '').split(':')
        try:
            position = sum(float(v)*60**i for i, v in enumerate(reversed(parts))) if len(parts) == 3 else None
        except ValueError:
            position = None
        return position, info.get('CurrentTransportState', 'UNKNOWN')

    async def close(self): pass


async def discover_dlna():
    def search():
        found = set()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(2)
            sock.sendto(b'M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: "ssdp:discover"\r\nMX: 1\r\nST: urn:schemas-upnp-org:device:MediaRenderer:1\r\n\r\n', ('239.255.255.250', 1900))
            deadline = time.monotonic()+3
            while time.monotonic() < deadline and len(found) < 32:
                try: data, peer = sock.recvfrom(8192)
                except TimeoutError: break
                for line in data.decode('latin1').splitlines():
                    if line.lower().startswith('location:'):
                        url = line.split(':', 1)[1].strip()
                        if private(peer[0]) and urlsplit(url).hostname == peer[0]: found.add(url)
        return found
    result = []
    async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
        for url in await asyncio.to_thread(search):
            try:
                r = await client.get(url)
                root = xml(r.content)
                device = root.find('.//{*}device')
                if device is None or 'MediaRenderer:' not in device.findtext('{*}deviceType', ''): continue
                services = {}
                for s in device.findall('./{*}serviceList/{*}service'):
                    typ = s.findtext('{*}serviceType', '')
                    key = typ.split(':')[-2]
                    control, scpd = (urljoin(url, s.findtext('{*}'+tag, '')) for tag in ('controlURL', 'SCPDURL'))
                    if any(urlsplit(v).hostname != urlsplit(url).hostname or urlsplit(v).scheme != 'http' for v in (control, scpd)): continue
                    services[key] = (typ, control, scpd)
                receiver = DLNA(urlsplit(url).hostname, device.findtext('{*}friendlyName', 'TV'), services)
                await receiver.prepare()
                result.append(receiver)
            except (httpx.HTTPError, ValueError, KeyError, ET.ParseError): continue
    return result


class Cast:
    kind = 'Google Cast'
    formats = ('video/mp4', 'video/webm')
    def __init__(self, cast):
        self.cast = cast
        self.host, self.name = cast.cast_info.host, cast.cast_info.friendly_name
        self.id = 'cast:' + str(cast.cast_info.uuid)
    async def start(self, url, mime, position):
        await asyncio.to_thread(self.cast.wait, 5)
        await asyncio.to_thread(self.cast.media_controller.play_media, url, mime, current_time=position, stream_type='BUFFERED')
        await asyncio.to_thread(self.cast.media_controller.block_until_active, 8)
    async def command(self, action, value):
        mc = self.cast.media_controller
        if action == 'volume': await asyncio.to_thread(self.cast.set_volume, value/100)
        elif action == 'seek':
            if not mc.status.supports_seek: raise ValueError('ТВ не поддерживает перемотку')
            await asyncio.to_thread(mc.seek, value)
        else: await asyncio.to_thread(getattr(mc, action))
    async def status(self):
        mc = self.cast.media_controller
        if not self.cast.socket_client.is_connected: raise ConnectionError()
        await asyncio.to_thread(mc.update_status)
        if mc.status.idle_reason == 'ERROR': raise ValueError('ТВ отклонил формат видео')
        if mc.status.last_updated and (time.time()-mc.status.last_updated.timestamp()) > 15: raise ConnectionError()
        return mc.status.current_time, mc.status.player_state
    async def close(self): await asyncio.to_thread(self.cast.disconnect)


async def discover_cast():
    def search():
        from threading import Event

        import pychromecast
        import zeroconf
        zc = zeroconf.Zeroconf()
        browser = pychromecast.CastBrowser(pychromecast.SimpleCastListener(lambda *_: None), zc)
        try:
            browser.start_discovery()
            Event().wait(3)
            infos = list(browser.devices.values())
            return [Cast(pychromecast.get_chromecast_from_host((i.host, i.port, i.uuid, i.model_name, i.friendly_name), tries=1, timeout=4)) for i in infos if i.cast_type == 'cast' and private(i.host)]
        finally:
            browser.stop_discovery()
            zc.close()
    return await asyncio.to_thread(search)


class Relay:
    def __init__(self, source, receiver, mime):
        self.source, self.receiver, self.mime = source, receiver, mime
        self.token = secrets.token_urlsafe(32)
        self.media_requested = False
        self.last_error = None
        self.expires = time.monotonic()+60
        self.app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
        self.app.add_api_route('/media/{token}', self.media, methods=['GET', 'HEAD'])
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(30, connect=5), follow_redirects=True, trust_env=False)
        self.task = self.server = self.sock = None
    async def media(self, request: Request, token: str):
        if not request.client or request.client.host != self.receiver or not private(request.client.host) or time.monotonic() > self.expires or not secrets.compare_digest(token, self.token): return Response(status_code=403)
        if request.method == 'GET': self.media_requested = True
        import re
        headers = {'Accept-Encoding': 'identity'}
        if 'range' in request.headers:
            value = request.headers['range']
            if not re.fullmatch(r'bytes=(?:\d+-\d*|-\d+)', value): return Response(status_code=416)
            headers['Range'] = value
        try: upstream = await self.client.send(self.client.build_request(request.method, self.source, headers=headers), stream=True)
        except httpx.HTTPError:
            self.last_error = 'Не удалось получить исходный поток от TorrServer/провайдера'
            return Response(status_code=502)
        if upstream.status_code not in (200, 206, 416) or ('Range' in headers and upstream.status_code == 200):
            await upstream.aclose()
            self.last_error = 'Источник отклонил запрос видео или HTTP Range'
            return Response(status_code=502)
        out = {k: v for k, v in upstream.headers.items() if k in ('content-length', 'content-range', 'accept-ranges')}
        out.update({'content-type': self.mime, 'cache-control': 'no-store', 'transferMode.dlna.org': 'Streaming'})
        if request.method == 'HEAD':
            await upstream.aclose()
            return Response(headers=out, status_code=upstream.status_code)
        async def chunks():
            try:
                async for chunk in upstream.aiter_raw(65536):
                    if time.monotonic() > self.expires: break
                    yield chunk
            finally: await upstream.aclose()
        return StreamingResponse(chunks(), headers=out, status_code=upstream.status_code)
    async def start(self):
        if not private(self.receiver): raise ValueError('ТВ должно находиться в локальной IPv4-сети')
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
            route.connect((self.receiver, 8009))
            host = route.getsockname()[0]
        if not private(host): raise ValueError('Нет LAN-интерфейса для ТВ')
        self.sock = socket.socket()
        self.sock.bind((host, 0))
        self.sock.listen(16)
        self.server = uvicorn.Server(uvicorn.Config(self.app, lifespan='off', access_log=False, log_level='critical', proxy_headers=False, timeout_graceful_shutdown=1))
        self.task = asyncio.create_task(self.server.serve(sockets=[self.sock]))
        for _ in range(100):
            if self.server.started: return f'http://{host}:{self.sock.getsockname()[1]}/media/{self.token}'
            if self.task.done(): break
            await asyncio.sleep(.02)
        raise ValueError('Не удалось открыть медиапоток в LAN')
    async def close(self):
        self.expires = 0
        await self.client.aclose()
        if self.server: self.server.should_exit = True
        if self.task:
            with suppress(asyncio.CancelledError): await self.task
        if self.sock: self.sock.close()
