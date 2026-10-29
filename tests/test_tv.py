import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from backend.models.playback import PlaybackState
from backend.services.tv import Relay, DLNA, private, xml
from backend.services.tv_session import TVSession, direct_play_type


class TVTests(unittest.IsolatedAsyncioTestCase):
    async def test_osd_receiver_error_is_reported_without_traceback(self):
        from backend.services.playback import PlaybackService
        p = MagicMock()
        p.active_states = {'h': PlaybackState('h', 1)}
        p.tv.command = AsyncMock(side_effect=ValueError('ТВ отключён'))
        await PlaybackService._handle_osd_action(p, 'h', ['cycle', 'pause'])
        self.assertEqual(p.tv.error, 'ТВ отключён')
        p.tv.publish.assert_called_once()

    async def test_transient_stopped_does_not_close_relay(self):
        session = TVSession(MagicMock(controllers={}))
        session.state = PlaybackState('h', 1, timecode=123, duration=500)
        session.receiver = MagicMock()
        session.receiver.name = 'TV'
        relay = MagicMock(last_error=None, media_requested=True, close=AsyncMock())
        session.relay = relay
        statuses = iter([(0, 'STOPPED'), (125, 'PLAYING')])
        async def status():
            relay.close.assert_not_awaited()
            try: return next(statuses)
            except StopIteration: raise ConnectionError()
        session.receiver.status = status
        with patch('backend.services.tv_session.asyncio.sleep', new=AsyncMock()):
            await session.poll()
        self.assertEqual(session.state.timecode, 125)
        relay.close.assert_awaited_once()
        self.assertNotIn('заверш', session.error)

    def test_dlna_advertised_mkv_can_be_attempted(self):
        device = DLNA('192.168.1.5', 'TV', {})
        device.formats = ['video/x-matroska']
        tracks = [{'type':'video', 'codec':'hevc'}, {'type':'audio', 'codec':'ac3'}]
        self.assertEqual(direct_play_type(device, 'matroska,webm', tracks, 'film.mkv'), 'video/x-matroska')
        self.assertEqual(direct_play_type(device, 'mkv', tracks, 'film.mkv'), 'video/x-matroska')
        device.formats = ['video/mp4']
        with self.assertRaisesRegex(ValueError, 'hevc / ac3'):
            direct_play_type(device, 'matroska,webm', tracks, 'film.mkv')

    def test_cast_profiles_are_container_specific(self):
        device = MagicMock(kind='Google Cast', formats=['video/mp4','video/webm'])
        with self.assertRaises(ValueError):
            direct_play_type(device, 'mp4', [{'type':'video','codec':'vp9'}])
        self.assertEqual(direct_play_type(device, 'matroska,webm', [{'type':'video','codec':'vp9'}], 'film.webm'), 'video/webm')

    async def test_discover_again_finds_newly_enabled_tv(self):
        session = TVSession(MagicMock(controllers={}))
        device = MagicMock()
        device.id, device.name, device.kind = 'cast:tv', 'Living room', 'Google Cast'
        device.close = AsyncMock()
        with patch('backend.services.tv_session.discover_cast', new=AsyncMock(side_effect=[[], [device]])) as cast, \
             patch('backend.services.tv_session.discover_dlna', new=AsyncMock(return_value=[])) as dlna:
            session.error = 'previous error'
            self.assertEqual((await session.discover())['devices'], [])
            info = await session.discover()
            self.assertEqual(info['devices'][0]['id'], 'cast:tv')
            self.assertIsNone(info['error'])
            self.assertFalse(info['scanning'])
            self.assertEqual(cast.await_count, 2)
            self.assertEqual(dlna.await_count, 2)

    async def test_range_head_and_access(self):
        relay = Relay('http://127.0.0.1/video?passkey=secret', '192.168.1.5', 'video/mp4')
        seen = []
        def origin(request):
            seen.append(request)
            return httpx.Response(206, headers={'Content-Range': 'bytes 2-4/10', 'Content-Length': '3'}, stream=httpx.ByteStream(b'234'))
        await relay.client.aclose()
        relay.client = httpx.AsyncClient(transport=httpx.MockTransport(origin))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=relay.app, client=('192.168.1.5', 1)), base_url='http://relay') as c:
            r = await c.get('/media/'+relay.token, headers={'Range': 'bytes=2-4'})
            self.assertEqual((r.status_code, r.content), (206, b'234'))
            self.assertEqual(seen[0].headers['range'], 'bytes=2-4')
            self.assertNotIn('passkey', str(r.headers))
            self.assertEqual((await c.head('/media/'+relay.token)).content, b'')
            self.assertEqual((await c.get('/media/wrong')).status_code, 403)
            self.assertEqual((await c.get('/media/'+relay.token, headers={'Range':'bytes=1-2,4-5'})).status_code,416)
            relay.expires = 0
            self.assertEqual((await c.get('/media/'+relay.token)).status_code,403)
        await relay.close()

    async def test_non_receiver_denied(self):
        relay = Relay('http://localhost/video', '192.168.1.5', 'video/mp4')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=relay.app, client=('192.168.1.6',1)), base_url='http://relay') as c:
            self.assertEqual((await c.get('/media/'+relay.token)).status_code,403)
        await relay.close()

    async def test_commands_return_and_cleanup(self):
        p = MagicMock()
        p.controllers = {'h': MagicMock(is_running=True)}
        session = TVSession(p)
        state = PlaybackState('h', 1, timecode=123, duration=500)
        session.state = state
        session.receiver = MagicMock()
        session.receiver.name = 'TV'
        session.receiver.command = AsyncMock()
        session.relay = MagicMock()
        session.relay.close = AsyncMock()
        await session.command(['seek',10,'relative'])
        session.receiver.command.assert_awaited_with('seek',133)
        await session.finish(resume=True)
        p.controllers['h'].send_command.assert_any_call(['seek',123,'absolute+exact'])
        p.controllers['h'].send_command.assert_any_call(['set_property','pause',False])
        self.assertIsNone(session.task)
        self.assertIsNone(session.relay)

    async def test_disconnect_preserves_position(self):
        p = MagicMock(controllers={})
        session = TVSession(p)
        session.state = PlaybackState('h',1,timecode=123)
        session.receiver = MagicMock()
        session.receiver.name = 'TV'
        session.receiver.status = AsyncMock(side_effect=ConnectionError())
        session.relay = MagicMock(close=AsyncMock())
        await session.poll()
        self.assertEqual(session.state.timecode,123)
        self.assertIsNone(session.relay)
        self.assertTrue(session.error)

    async def test_unsupported_format_and_unknown_device(self):
        p = MagicMock()
        p.active_states={'h': PlaybackState('h',1)}
        p.controllers={'h': MagicMock(is_running=True, media_format='matroska')}
        session=TVSession(p)
        with self.assertRaises(ValueError): await session.start('missing')
        session.devices={'tv':MagicMock()}
        with self.assertRaises(ValueError): await session.start('tv')
        self.assertIsNone(session.relay)

    async def test_dlna_capabilities(self):
        d=DLNA('192.168.1.5','TV',{})
        d.actions={'AVTransport':{'Play','Stop'}}
        d.call=AsyncMock()
        with self.assertRaises(ValueError): await d.command('seek',10)
        await d.command('play',0)
        d.call.assert_awaited_with('AVTransport','Play',InstanceID=0,Speed=1)

    async def test_dlna_metadata_and_confirmed_start_before_seek(self):
        d = DLNA('192.168.1.5', 'TV', {})
        d.formats = ['video/mp4']
        d.actions = {'AVTransport': {'Play', 'Stop', 'Seek'}}
        async def call_device(service, action, **args):
            return {'CurrentTransportState': 'PLAYING'} if action == 'GetTransportInfo' else {}
        d.call = AsyncMock(side_effect=call_device)
        await d.start('http://192.168.1.2/media/token', 'video/mp4', 123)
        calls = d.call.await_args_list
        metadata = calls[0].kwargs['CurrentURIMetaData']
        self.assertIn('object.item.videoItem.movie', metadata)
        self.assertIn('http-get:*:video/mp4:*', metadata)
        self.assertEqual([c.args[1] for c in calls], ['SetAVTransportURI', 'Play', 'GetTransportInfo', 'Seek'])

    async def test_dlna_rejected_playback_is_not_success(self):
        d = DLNA('192.168.1.5', 'TV', {})
        d.formats = ['video/mp4']
        d.actions = {'AVTransport': {'Play', 'Stop'}}
        d.call = AsyncMock(return_value={'CurrentTransportStatus': 'ERROR_OCCURRED'})
        with self.assertRaisesRegex(ValueError, 'ошибке открытия'):
            await d.start('http://192.168.1.2/media/token', 'video/mp4', 0)

    async def test_optional_dlna_position(self):
        d = DLNA('192.168.1.5', 'TV', {})
        d.actions = {'AVTransport': {'GetTransportInfo'}}
        d.call = AsyncMock(return_value={'CurrentTransportState': 'PLAYING'})
        self.assertEqual(await d.status(), (None, 'PLAYING'))

    async def test_start_failure_restores_pc_and_publishes_error(self):
        state = PlaybackState('h', 1, timecode=123, track_list=[{'type':'video','codec':'h264'}])
        controller = MagicMock(is_running=True, media_url='http://localhost/video', media_format='mp4')
        p = MagicMock(controllers={'h':controller}, active_states={'h':state})
        session = TVSession(p)
        device = MagicMock(formats=['video/mp4'], host='192.168.1.5')
        device.name = 'TV'
        device.id, device.kind = 'tv', 'DLNA'
        device.start = AsyncMock(side_effect=ValueError('DLNA: rejected video'))
        device.command = AsyncMock()
        session.devices['tv'] = device
        with patch('backend.services.tv_session.Relay') as relay:
            relay.return_value.start = AsyncMock(return_value='http://192.168.1.2/media/token')
            relay.return_value.close = AsyncMock()
            with self.assertRaisesRegex(ValueError, 'rejected video'): await session.start('tv')
        self.assertIsNone(session.state)
        self.assertIsNone(session.relay)
        self.assertEqual(session.info()['connection'], 'error')
        self.assertIn('rejected video', session.info()['error'])
        controller.send_command.assert_any_call(['set_property','pause',False])

    def test_lan_and_xml(self):
        for host in ['127.0.0.1','8.8.8.8','169.254.1.1','::1']: self.assertFalse(private(host))
        self.assertTrue(private('192.168.1.5'))
        with self.assertRaises(ValueError): xml(b'<!DOCTYPE x><x/>')
