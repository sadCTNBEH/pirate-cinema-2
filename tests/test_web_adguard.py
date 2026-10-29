import json

import pytest

from backend.infrastructure.web_adguard import (
    VERSION,
    AdguardBridge,
    eligible_player,
    extension_files,
)


def test_supported_web_players_are_eligible():
    for name in ('Kodik','Плеер Kodik','CVH','Плеер CVH','AnimeGO Online','Alloha','Плеер Alloha'):
        assert eligible_player(name)
    for name in ('Aksor','Плеер Aksor','Rutube','torrent',''):
        assert not eligible_player(name)


def test_toggle_scope_and_stale_release_preserve_other_settings(tmp_path):
    values={'web_player_adguard':False,'player_path':'mpv.exe','language':'ru','other':{'keep':True}}
    saved=[]
    def save(update):
        values.update(update);saved.append(dict(update))
    class Extension:
        IsEnabled=False
        def EnableAsync(self,enabled): self.IsEnabled=enabled
    bridge=AdguardBridge(tmp_path,lambda:values,save)
    bridge.supported=True;bridge._ready.set();bridge.extension=Extension();bridge._installed=True
    bridge._ui=lambda operation:operation()
    assert bridge.set_enabled(True)['active']
    assert bridge.extension.IsEnabled
    assert bridge.scope('Alloha','alloha')['active']
    assert not bridge.scope('Rutube','old')['active']
    assert bridge.scope('Kodik','current')['active']
    assert bridge.release('old')['active']  # An old iframe cannot change a new player's scope.
    assert not bridge.set_enabled(False)['active']
    assert not bridge.extension.IsEnabled
    assert values['player_path']=='mpv.exe' and values['other']=={'keep':True}
    assert all(set(update)=={'web_player_adguard'} for update in saved)


def test_unsupported_runtime_never_claims_enabled(tmp_path):
    bridge=AdguardBridge(tmp_path,dict,lambda value:pytest.fail('must not persist failed enable'))
    state=bridge.set_enabled(True)
    assert state['error'] and not state['enabled'] and not state['active']


def test_incompatible_unpacked_build_is_rejected(tmp_path):
    path=tmp_path/'adguard'/VERSION;path.mkdir(parents=True)
    (path/'manifest.json').write_text(json.dumps({'version':VERSION,'manifest_version':2}))
    with pytest.raises(RuntimeError,match='манифест'):extension_files(tmp_path)


def test_player_cannot_replace_desktop_shell_with_external_page():
    from backend.infrastructure.web_player_events import shell_navigation_allowed
    app='http://127.0.0.1:8018/'
    assert shell_navigation_allowed(app,app+'api/online/animego/web/token')
    for url in ('https://alloha.yani.tv/','https://ads.test/','http://127.0.0.1:8019/','javascript:alert(1)','https://127.0.0.1:8018/','http://127.0.0.1:8018@ads.test/'):
        assert not shell_navigation_allowed(app,url)


def test_extension_welcome_never_opens_in_external_edge():
    from types import SimpleNamespace

    from backend.infrastructure.web_adguard import extension_safe_window_handler
    opened=[]
    handled=[]
    handler=extension_safe_window_handler(lambda owner,sender,args: opened.append(args.get_Uri()))
    args=SimpleNamespace(get_Uri=lambda:'chrome-extension://test/pages/thankyou.html',set_Handled=handled.append)
    handler(None,None,args)
    assert handled==[True] and opened==[]
    args.get_Uri=lambda:'https://example.org/'
    handler(None,None,args)
    assert opened==['https://example.org/']
