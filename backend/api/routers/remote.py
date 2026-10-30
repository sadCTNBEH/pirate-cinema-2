"""FastAPI router for Web Remote control and remote playback launch."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from backend.api import deps
from backend.exceptions import AppException
from backend.models.playback import PlayCommand
from backend.repositories.history import HistoryRepository
from backend.repositories.playback import PlaybackRepository
from backend.services.library import LibraryService
from backend.services.magnet import MagnetService
from backend.services.mobile import MobileSession, check_request, mobile_access, probe
from backend.services.playback import PlaybackService
from backend.services.remote import get_remote_info

logger = logging.getLogger(__name__)

remote_router = APIRouter(prefix="/api/remote", tags=["remote"])


class RemotePlayRequest(BaseModel):
    hash: str | None = None
    magnet: str | None = None
    title: str = ""
    file_id: int | None = None
    file_name: str | None = None
    fullscreen: bool | None = False


@remote_router.get("/info")
async def get_info(request: Request):
    """Return local LAN IP, port, remote URL and QR code SVG."""
    import ipaddress
    check_request(request)
    # QR is the pairing capability; it must never be readable by an anonymous LAN peer.
    if not ipaddress.ip_address(request.client.host).is_loopback:
        mobile_access.authorize(request)
    return get_remote_info()


class PairRequest(BaseModel):
    code: str


@remote_router.post('/pair')
async def pair(request: Request, body: PairRequest, response: Response):
    token = mobile_access.pair(request, body.code)
    response.delete_cookie('pc_remote', path='/api/remote')
    response.set_cookie('pc_remote', token, httponly=True, samesite='lax',
                        max_age=43200, path='/')
    response.headers['Cache-Control'] = 'no-store'
    return {'paired': True, 'token': token}


class MobilePlayRequest(RemotePlayRequest):
    season: int | None = None
    episode: int | None = None
    absolute: int | None = None


@remote_router.post('/mobile')
async def mobile_play(
    request: Request, body: MobilePlayRequest,
    playback: Annotated[PlaybackService, Depends(deps.get_playback_service)],
    magnet: Annotated[MagnetService, Depends(deps.get_magnet_service)],
    history: Annotated[HistoryRepository, Depends(deps.get_history_repo)],
    repo: Annotated[PlaybackRepository, Depends(deps.get_playback_repo)],
):
    import asyncio
    import secrets

    from backend.infrastructure.torrserver import client as ts
    from backend.infrastructure.torrserver.client import normalize_hash
    from backend.models.playback import PlaybackState
    from backend.services.torrent_selection import next_file

    owner = mobile_access.authorize(request)
    if len(mobile_access.sessions) >= 32:
        raise HTTPException(429, 'Слишком много сессий видео')
    async with mobile_access.preparing:
        await ts.require_ram_cache(deps.get_torrserver_url())
        hash_ = normalize_hash(body.hash or '')
        if body.magnet:
            if not body.magnet.startswith('magnet:?xt=urn:btih:'):
                raise HTTPException(422, 'Допустима только magnet-ссылка из каталога')
            result = await magnet.add_magnet(body.magnet, body.title)
            hash_ = hash_ or normalize_hash(result.get('hash', ''))
        if not hash_:
            raise HTTPException(422, 'Выберите торрент из каталога')
        selection = await playback.select_torrent_file(hash_, season=body.season, episode=body.episode,
            absolute=body.absolute, file_id=body.file_id, release_title=body.title)
        chosen = selection['file']
        if not chosen:
            return {'choose_file': True, 'files': selection['candidates'], 'reason': selection['reason']}
        source = ts.stream_url(deps.get_torrserver_url(), hash_, chosen['id'], chosen['name'])
        meta = await probe(source)
        mode = 'direct'
        duration = 0.0
        if isinstance(meta, dict):
            mode = meta.get('mode', 'direct')
            raw_dur = meta.get('duration', 0.0)
            if isinstance(raw_dur, (int, float)):
                duration = float(raw_dur)
            elif isinstance(raw_dur, str):
                try:
                    duration = float(raw_dur)
                except ValueError:
                    duration = 0.0

        # Check active PC player state first, then previous progress in DB
        active_state = None
        if hasattr(playback, 'active_states') and isinstance(playback.active_states, dict):
            st = playback.active_states.get(hash_)
            if st and getattr(st, 'file_id', None) == chosen['id']:
                active_state = st

        previous = await asyncio.to_thread(repo.get_previous_progress, hash_, chosen['id'])
        resume = 0
        if active_state and getattr(active_state, 'hash', None) == hash_ and getattr(active_state, 'file_id', None) == chosen['id'] and getattr(active_state, 'timecode', 0) > 0:
            resume = int(active_state.timecode)
        elif previous and not previous['is_watched'] and previous['playback_timecode'] and previous['playback_timecode'] > 0:
            resume = int(previous['playback_timecode'])
        else:
            logical = await asyncio.to_thread(
                repo.logical_progress, hash_, chosen.get('season'), chosen.get('episode'), latest=True
            )
            if logical and not logical.get('is_watched') and (logical.get('playback_timecode') or 0) > 0:
                resume = int(logical['playback_timecode'])
        state = PlaybackState(hash=hash_, file_id=chosen['id'], file_name=chosen['name'],
                              audio_track=previous['audio_track'] if previous else 0,
                              subtitle_track=previous['subtitle_track'] if previous else 0)
        await asyncio.to_thread(history.mark_played, hash_, chosen['id'], chosen['name'],
                                chosen.get('path'), chosen.get('season'), chosen.get('episode'))
        # Replace only this phone's resources, never the PC player.
        for token, old in list(mobile_access.sessions.items()):
            if old.owner == owner:
                mobile_access.sessions.pop(token)
                await old.close()
        token = secrets.token_urlsafe(32)
        session = MobileSession(
            owner=owner,
            host=request.client.host,
            source=source,
            state=state,
            size=chosen.get('length', 0),
            mode=mode,
            duration=duration,
            audio_track_idx=max(0, (state.audio_track or 1) - 1),
        )
        mobile_access.sessions[token] = session
        files = await ts.torrent_video_files(deps.get_torrserver_url(), hash_)
        following = next_file(files, chosen['id'])

        stream_url = (
            f'/api/remote/mobile/{token}/media'
            if mode == 'direct'
            else f'/api/remote/mobile/{token}/hls/playlist.m3u8'
        )
        stream_url += '?auth=' + owner
        return {
            'token': token,
            'url': stream_url,
            'mode': mode,
            'duration': duration,
            'hash': hash_,
            'file_id': chosen['id'],
            'file_name': chosen['name'],
            'resume': resume,
            'next': following,
            'expires_in': 180,
        }


@remote_router.api_route('/mobile/{token}/media', methods=['GET', 'HEAD'])
async def mobile_media(request: Request, token: str):
    return await mobile_access.media(request, token)


@remote_router.api_route('/mobile/{token}/hls/playlist.m3u8', methods=['GET', 'HEAD'])
async def mobile_hls_playlist(request: Request, token: str):
    return await mobile_access.hls_playlist(request, token)


@remote_router.api_route('/mobile/{token}/hls/{name}', methods=['GET', 'HEAD'])
async def mobile_hls_segment(request: Request, token: str, name: str):
    return await mobile_access.hls_segment(request, token, name)


@remote_router.put('/mobile/{token}/hls_sink/{name}')
async def mobile_hls_sink(request: Request, token: str, name: str):
    return await mobile_access.hls_sink(request, token, name)


class MobileProgress(BaseModel):
    sequence: int
    position: float = 0
    duration: float = 0
    close: bool = False


@remote_router.post('/mobile/{token}/progress')
async def mobile_progress(request: Request, token: str, body: MobileProgress,
                          repo: Annotated[PlaybackRepository, Depends(deps.get_playback_repo)]):
    import asyncio
    import math
    import time
    session = mobile_access.session(request, token)
    async with session.progress_lock:
        if not all(math.isfinite(v) and 0 <= v <= 604800 for v in (body.position, body.duration)):
            raise HTTPException(422, 'Некорректная позиция')
        fresh = body.sequence > session.sequence
        if fresh:
            session.sequence = body.sequence
            session.expires = time.monotonic() + 180
            # Never overwrite saved progress with 0 or negative position on error/close
            if body.duration >= 1 and body.position > 0:
                state = session.state
                state.timecode, state.duration = int(body.position), int(body.duration)
                state.is_watched = state.timecode / state.duration >= .9
                # Save a snapshot: later events cannot mutate an in-flight DB write.
                from dataclasses import replace
                await asyncio.to_thread(repo.save_progress, replace(state))
        if body.close and fresh:
            mobile_access.sessions.pop(token, None)
            await session.close()
    return {'ok': True}


@remote_router.post("/play")
async def remote_play(
    request: RemotePlayRequest,
    playback_service: Annotated[PlaybackService, Depends(deps.get_playback_service)],
    magnet_service: Annotated[MagnetService, Depends(deps.get_magnet_service)],
    library_service: Annotated[LibraryService, Depends(deps.get_library_service)],
) -> dict[str, Any]:
    """Launch playback on the host PC from the smartphone remote."""
    target_hash = request.hash
    link = request.magnet or target_hash
    if not link:
        raise HTTPException(status_code=400, detail="Missing torrent hash or magnet")

    try:
        add_res = await magnet_service.add_magnet(link, request.title)
        if not target_hash and add_res:
            target_hash = add_res.get("hash")
    except AppException as e:
        logger.warning("Failed to ensure magnet/hash in TorrServer: %s", e)

    if not target_hash:
        target_hash = request.hash

    target_file_id = request.file_id
    target_file_name = request.file_name or request.title or "Video"

    # Auto-detect best video file if file_id is not specified
    if target_file_id is None:
        try:
            files_data = await library_service.get_torrent_files_structure(
                target_hash, title=request.title
            )
            candidates: list[dict[str, Any]] = []
            if files_data.get("seasons"):
                seasons = files_data["seasons"]
                sorted_keys = sorted(
                    seasons.keys(),
                    key=lambda k: int(k) if str(k).isdigit() else 999,
                )
                for k in sorted_keys:
                    if seasons[k]:
                        candidates = seasons[k]
                        break
            elif files_data.get("movies"):
                candidates = files_data["movies"]
            elif files_data.get("files"):
                candidates = files_data["files"]
            elif files_data.get("flat_files"):
                candidates = files_data["flat_files"]

            if candidates:
                # If movies / single video, choose largest file
                if files_data.get("type") == "movie" or not files_data.get("seasons"):
                    chosen = max(candidates, key=lambda f: f.get("length", 0))
                else:
                    chosen = candidates[0]
                target_file_id = chosen.get("id", 0)
                target_file_name = chosen.get("name", target_file_name)
            else:
                target_file_id = 0
        except (AppException, ValueError, TypeError) as e:
            logger.debug("Auto-detect video file error in remote play: %s", e)
            target_file_id = 0

    cmd = PlayCommand(
        hash=target_hash,
        file_id=target_file_id,
        file_name=target_file_name,
        start_time=0,
    )

    try:
        status = await playback_service.launch(cmd)
    except Exception as e:
        logger.exception("Failed to launch playback from remote")
        raise HTTPException(status_code=500, detail=str(e)) from e

    # Unhide / restore PC window if minimized to tray
    try:
        from backend.gui import window_api

        window_api.show()
    except Exception:
        logger.exception("Failed to show window after remote playback launch")

    if request.fullscreen:
        try:
            from backend.gui import window_api

            window_api.set_fullscreen(True)
        except Exception:
            logger.exception("Failed to enter fullscreen after remote playback launch")

    return {
        "status": status,
        "hash": target_hash,
        "file_id": target_file_id,
        "file_name": target_file_name,
    }
