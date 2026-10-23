"""The mobile remote must display MPV's real mute and buffering states."""

from unittest.mock import MagicMock

from backend.models.playback import PlaybackState
from backend.services.playback import PlaybackService


def test_remote_mute_and_buffering_state():
    controller = MagicMock(is_running=True)
    service = PlaybackService(
        playback_repo=MagicMock(),
        history_repo=MagicMock(),
        metadata_repo=MagicMock(),
        mpv_controller_factory=lambda: controller,
        torrserver_client=MagicMock(),
        settings_provider=lambda: "http://localhost:8090",
    )
    service.controllers["hash"] = controller
    service.active_states["hash"] = PlaybackState(hash="hash", file_id=1)

    service._handle_progress("hash", "mute", True)
    service._handle_progress("hash", "paused-for-cache", True)
    state = service.get_active_playback()
    assert state["is_muted"] is True
    assert state["is_buffering"] is True

    service._handle_progress("hash", "mute", False)
    service._handle_progress("hash", "paused-for-cache", False)
    state = service.get_active_playback()
    assert state["is_muted"] is False
    assert state["is_buffering"] is False
