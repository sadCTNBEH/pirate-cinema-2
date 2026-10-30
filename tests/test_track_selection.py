from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from backend.api.schemas.settings import SettingsResponse, SettingsUpdate
from backend.core.settings import user
from backend.infrastructure.mpv.controller import MPVController
from backend.infrastructure.mpv.tracks import (
    TrackSelection,
    identity,
    language,
    match_track,
    preferred_track,
)
from backend.models.playback import PlaybackState
from backend.services.playback import PlaybackService
from backend.services.settings import SettingsService


def audio(id_=3, lang="rus", title="LostFilm AC3 5.1", **extra):
    return {"id": id_, "type": "audio", "lang": lang, "title": title, "codec": "ac3", **extra}


def policy(prefs=None, **explicit):
    commands, saved = [], []
    selector = TrackSelection(commands.append, saved.append)
    selector._schedule = lambda: None
    selector.configure(prefs or {}, **explicit)
    selector.options()
    selector.event("start-file")
    return selector, commands, saved


def ready(selector, tracks, aid=1, sid=False):
    selector.event("track-list", tracks)
    selector.event("aid", aid)
    selector.event("sid", sid)
    selector.event("file-loaded")
    selector.deadline = 0  # deterministically finish the initial discovery window
    selector.apply()


@pytest.mark.parametrize("code", ["ru", "rus", "RU-ru", "russian", "Русский"])
def test_language_aliases(code):
    assert language(code) == "ru"
    assert language("eng") == language("en-US") == "en"


def test_same_voice_matches_changed_id_codec_and_title_format():
    saved = identity(audio())
    assert match_track([audio(1, "eng", "Original"), audio(5, "ru", "Lost Film [AAC 2.0]", codec="aac")], saved) == 5
    assert match_track([audio(5, "ru", "NewStudio")], saved) is None
    assert match_track([audio(5), audio(7)], saved) is None
    assert match_track([audio(5, commentary=True)], saved) is None
    assert not identity(audio(title="Russian AAC 5.1"))["title"]


def test_language_fallback_and_reliable_original_only():
    tracks = [audio(1, "eng", "English"), audio(2, "ja", "Japanese", original=True)]
    assert preferred_track(tracks, ["ru", "en"]) == 1
    assert preferred_track(tracks, ["original", "en"]) == 2
    tracks[1].pop("original")
    assert preferred_track(tracks, ["original"]) is None
    assert preferred_track([audio(3), audio(4)], ["ru"]) is None
    assert preferred_track([audio(1, "ru", "Director commentary"), audio(2, "eng", "English")], ["ru", "en"]) == 2


def test_remembered_voice_applies_once_across_series_and_releases():
    selector, commands, saved = policy()
    ready(selector, [audio(3)], aid=3)
    selector.manual_command(["set_property", "aid", 3])
    assert saved[-1]["audio"]["studio"] == "lostfilm"
    prefs = {"track_preferences": saved[-1]}
    selector.configure(prefs)
    selector.options()
    selector.event("start-file")
    ready(selector, [audio(1, "eng", "Original"), audio(5)])
    assert commands == [["set_property", "aid", 5]]
    selector.event("aid", 5)
    selector.event("track-list", [audio(5), audio(8)])
    selector.apply()
    assert len(commands) == 1
    assert len(saved) == 1  # automatic changes must not rewrite the remembered choice


def test_missing_voice_falls_back_and_ambiguous_voice_is_not_guessed():
    prefs = {"track_preferences": {"audio": {"mode": "track", **identity(audio())}}, "audio_languages": ["ru", "en"]}
    selector, commands, _ = policy(prefs)
    ready(selector, [audio(4, "eng", "English")])
    assert commands == [["set_property", "aid", 4]]
    selector, commands, _ = policy(prefs)
    ready(selector, [audio(3), audio(4)])
    assert commands == []


def test_late_tracks_can_match_before_single_initial_selection():
    prefs = {"track_preferences": {"audio": {"mode": "track", **identity(audio())}}, "audio_languages": ["en"]}
    selector, commands, _ = policy(prefs)
    selector.event("track-list", [audio(1, "eng", "English")])
    selector.event("file-loaded")
    selector.apply()
    assert commands == []
    selector.event("track-list", [audio(1, "eng", "English"), audio(8)])
    selector.apply()
    assert commands == [["set_property", "aid", 8]]


def test_manual_choice_cancels_pending_auto_and_native_changes_are_remembered():
    prefs = {"track_preferences": {"audio": {"mode": "track", **identity(audio())}}}
    selector, commands, saved = policy(prefs)
    selector.event("track-list", [audio(1, "eng", "English"), audio(5)])
    selector.event("aid", 5)
    selector.event("file-loaded")
    selector.manual_command(["set_property", "aid", 1])
    selector.event("aid", 1)
    selector.apply()
    assert commands == []
    assert saved[-1]["audio"]["lang"] == "en"
    selector.event("aid", 5)  # native MPV keyboard path
    assert saved[-1]["audio"]["studio"] == "lostfilm"


@pytest.mark.parametrize("prefs", [{"subtitle_languages": ["off"]}, {"subtitle_languages": ["ru"], "track_preferences": {"sub": {"mode": "off"}}}])
def test_disabled_subtitles_stay_disabled_and_manual_enable_wins_current_file(prefs):
    selector, commands, saved = policy(prefs)
    subtitle = {"id": 7, "type": "sub", "lang": "ru", "title": "Russian"}
    ready(selector, [subtitle], sid=7)
    assert commands == [["set_property", "sid", "no"]]
    selector.event("sid", False)
    assert not saved  # own 'no' acknowledgement is not a manual choice
    selector.manual_command(["set_property", "sid", 7])
    selector.event("sid", 7)
    selector.apply()
    assert len(commands) == 1
    assert saved[-1]["sub"]["mode"] == "track"


def test_explicit_choice_precedes_remembered_voice_and_stale_timer_is_ignored():
    prefs = {"audio_languages": ["ru"], "track_preferences": {"audio": {"mode": "track", **identity(audio())}}}
    selector, commands, saved = policy(prefs, explicit_audio=1)
    ready(selector, [audio(1, "eng", "English"), audio(5)])
    assert not commands
    assert saved[-1]["audio"]["lang"] == "en"
    old_generation = selector.generation
    selector.configure(prefs)
    selector.options()
    selector.event("start-file")
    selector.event("file-loaded")
    selector.apply(old_generation)
    assert not commands
    selector.close()


def test_preferences_are_persisted_and_unrelated_settings_do_not_overwrite_them(tmp_path, monkeypatch):
    monkeypatch.setattr(user, "get_data_dir", lambda: tmp_path)
    user.save_settings({"audio_languages": ["ru", "en"], "subtitle_languages": ["off"], "minimize_to_tray": False})
    user.save_track_preferences({"audio": {"mode": "track", **identity(audio())}})
    service = SettingsService(MagicMock(), lambda: "http://localhost")
    service.save_settings({"track_preferences": {}, "player_path": "test"})
    reloaded = user.load_settings()
    assert reloaded["track_preferences"]["audio"]["studio"] == "lostfilm"
    assert reloaded["subtitle_languages"] == ["off"]
    assert not reloaded["minimize_to_tray"]
    SettingsResponse.model_validate(service.get_settings())
    service.update_settings({"subtitle_languages": ["ru", "en"]})
    assert user.load_settings()["track_preferences"]["audio"]["studio"] == "lostfilm"
    service.update_settings({"audio_languages": ["en"]})
    assert "audio" not in user.load_settings()["track_preferences"]
    assert user.load_settings()["audio_languages"] == ["en"]
    for invalid in (["ru", "ru"], ["off", "ru"], ["auto", "en"]):
        with pytest.raises(ValidationError):
            SettingsUpdate(subtitle_languages=invalid)


def test_controller_load_uses_language_lists_separately_and_resets_old_ids(monkeypatch):
    controller = MPVController()
    controller.is_running = True
    controller.configure_tracks({"audio_languages": ["ru", "en"], "subtitle_languages": ["off"]})
    sent = []
    monkeypatch.setattr(controller, "send_command", sent.append)
    controller.load_file("http://test/video", "Next")
    assert ["set_property", "alang", "ru,rus,en,eng"] in sent
    assert not any(command[:2] == ["set_property", "slang"] for command in sent)
    assert next(command for command in sent if command[0] == "loadfile")[-1] == "pause=no,start=0,sub-delay=0.0,audio-delay=0.0,aid=auto,sid=no"
    controller._tracks.close()
    controller._default_languages["alang"] = "ja,jpn,en,eng"
    controller.configure_tracks({})
    sent.clear()
    controller.load_file("http://test/other", "Other")
    assert ["set_property", "alang", "ja,jpn,en,eng"] in sent
    controller._tracks.close()


def test_api_and_remote_manual_commands_enter_same_track_policy():
    controller = MagicMock(is_running=True)
    service = PlaybackService(MagicMock(), MagicMock(), MagicMock(), lambda: controller, MagicMock(), lambda: "http://localhost")
    service.controllers["file"] = controller
    service.active_states["file"] = PlaybackState(hash="file", file_id=1)
    service.send_command(["set_property", "aid", 5])
    controller.manual_track_command.assert_called_once_with(["set_property", "aid", 5])
    controller.send_command.assert_called_once_with(["set_property", "aid", 5])


def test_manual_choice_before_start_is_not_discarded_and_auto_does_not_poll():
    selector, commands, saved = policy()
    selector.configure({"audio_languages": ["ru"]})
    selector.manual_command(["set_property", "aid", 8])
    assert selector.options()["aid"] == "8"
    selector.event("start-file")
    ready(selector, [audio(3), audio(8, "eng", "English")], aid=8)
    assert not commands
    assert saved[-1]["audio"]["lang"] == "en"
    selector, commands, saved = policy()
    ready(selector, [])
    assert selector.done == {"audio", "sub"}
    assert not commands
