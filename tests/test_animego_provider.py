import asyncio
from unittest.mock import AsyncMock

import pytest

from backend.exceptions import ExternalServiceError, NotFoundError
from backend.services.online.animego_web import player_html
from backend.services.online.animego_worker import (
    AnimegoLookupError,
    card_url,
    parse_card,
    search_items,
)
from backend.services.online.providers.animego import AnimegoProvider, choose_match

# Minimal fragments of the actual animego.online markup, not the old .me markup.
SEARCH = '''<a class="poster-item grid-item" href="/390-ne-izdevajsja-nagatoro-l1.html">
<div class="animego-online-poster-item__title">Не издевайся, Нагаторо</div>
<div class="animego-online-poster-item__meta">2021 - TV Сериал</div></a>'''
CARD = '''<h1>Не издевайся, Нагаторо</h1><div class="animego-online-page__original">Ijiranaide, Nagatoro-san</div>
<div class="animego-online-poster-item__label"><span>12 серий</span>Вышел</div>
<li class="animego-online-page__details-list--voice"><a href="/anime/anidub/">AniDUB</a><a class="vm-more" href="#">ещё 9</a></li>
<div data-player-anime-id="390"><div data-player-slot="0" data-player-title="Плеер CVH"></div>
<div data-player-slot="1" data-player-title="Плеер AnimeGO Online"></div><div data-player-slot="2" data-player-title="Трейлер"></div><div data-player-slot="3" data-player-title="Kodik"></div></div>'''
URL = 'https://animego.online/390-ne-izdevajsja-nagatoro-l1.html'


def test_online_search_and_card_not_old_parser():
    item = search_items(SEARCH)[0]
    assert item['id'] == '390' and item['year'] == 2021
    card = parse_card(CARD, item['link'])
    assert card['total_episodes'] == 12 and len(card['episodes']) == 12
    assert card['episodes'][-1] == {'number':12, 'id':'390:12'}
    assert card['voices'] == [{'translation_id':'3','label':'Kodik','player':'Kodik'}]
    assert card['studios'] == ['AniDUB']
    with pytest.raises(AnimegoLookupError): parse_card(CARD, URL.replace('/390-', '/391-'))


def test_empty_search_differs_from_incompatible_markup():
    assert search_items('<p>По вашему запросу ничего не найдено</p>') == []
    with pytest.raises(AnimegoLookupError, match='страница поиска'):
        search_items('<html>Unexpected page</html>')


def test_card_url_never_guesses_slug_or_accepts_other_hosts():
    assert card_url('/390-ne-izdevajsja-nagatoro-l1.html') == URL
    for url in ('https://animego.me/390-title.html', 'https://evil.test/390-title.html', '/390', '//evil.test/390-title.html'):
        with pytest.raises(AnimegoLookupError): card_url(url)


def test_matching_checks_year_type_and_ambiguity():
    items = [{'id':'1','title':'Naruto','year':2002,'type':'series'}]
    meta = {'title':'Наруто','aliases':['Naruto'],'year':2002,'type':'series'}
    assert choose_match(items, meta)['id'] == '1'
    with pytest.raises(NotFoundError): choose_match(items, dict(meta, year=2007))
    with pytest.raises(NotFoundError): choose_match(items, dict(meta, type='movie'))
    with pytest.raises(ExternalServiceError): choose_match(items + [dict(items[0],id='2')],meta)


def test_original_title_is_read_from_card_and_catalog_has_no_playback_gate():
    provider = AnimegoProvider()
    provider._call = AsyncMock(side_effect=lambda method,data: search_items(SEARCH) if method == 'search' else parse_card(CARD, URL))
    result = asyncio.run(provider.catalog({'title':'Ijiranaide, Nagatoro-san','year':2021,'type':'series'}))
    assert result['anime_id'] == '390' and len(result['episodes']) == 12
    assert provider._call.await_count <= 3


def test_network_failure_is_not_absent_title():
    provider = AnimegoProvider()
    provider._call = AsyncMock(side_effect=ExternalServiceError('[blocked] AnimeGo',status_code=503))
    with pytest.raises(ExternalServiceError, match='blocked'):
        asyncio.run(provider.catalog({'title':'Нагаторо'}))


def test_no_matches_remains_distinct_from_network_failure():
    provider = AnimegoProvider()
    provider._call = AsyncMock(return_value=[])
    with pytest.raises(NotFoundError): asyncio.run(provider.catalog({'title':'missing'}))


def test_web_embed_does_not_invoke_native_streams():
    provider = AnimegoProvider()
    provider.cards['390'] = URL
    provider._call = AsyncMock(return_value={'config':{'kind':'iframe','src':'https://kodikplayer.com/serial/1'},'episode':2})
    result = asyncio.run(provider.embed('390',2,'3','Kodik'))
    assert result['url'].startswith('/api/online/animego/web/')
    with pytest.raises(ExternalServiceError, match='веб-плеере'):
        asyncio.run(provider.resolve_stream('old-playlist-item'))
    html = player_html({'config':{'kind':'iframe','src':'https://example.test/</script>'},'episode':2})
    assert 'example.test/</script>' not in html
    assert "event.source!==frame.contentWindow" in html
    assert 'hls' not in html.lower() and 'mpd' not in html.lower()


def test_no_kodik_does_not_hide_catalog_or_invent_alternative():
    card=parse_card(CARD.replace('data-player-title="Kodik"','data-player-title="Другой"'),URL)
    assert len(card['episodes'])==12 and not card['voices']
    assert 'не предоставляет Kodik' in card['notice']


def test_old_animego_site_player_is_rejected_before_loading(monkeypatch):
    monkeypatch.setattr('backend.services.online.providers.animego.MetadataCache',lambda:None)
    provider=AnimegoProvider()
    provider._call=AsyncMock()
    with pytest.raises(ExternalServiceError,match='только Kodik'):
        asyncio.run(provider.embed('390',1,'1','AnimeGO Online'))
    provider._call.assert_not_called()


def test_worker_uses_project_environment_even_from_global_python(monkeypatch):
    from pathlib import Path

    from backend.services.online.providers.animego import worker_command
    monkeypatch.setattr('backend.services.online.providers.animego.sys.executable', 'global-python.exe')
    monkeypatch.setattr(Path, 'is_file', lambda self: True)
    interpreter,args,cwd=worker_command()
    assert Path(interpreter).parent.name in ('Scripts','bin')
    assert Path(interpreter).parent.parent.name=='.venv'
    assert args==['-m','backend.services.online.animego_worker']
    assert Path(cwd)==Path(__file__).resolve().parents[1]


def test_frozen_worker_keeps_bundled_executable(monkeypatch):
    from backend.services.online.providers.animego import worker_command
    monkeypatch.setattr('backend.services.online.providers.animego.sys.frozen', True, raising=False)
    _interpreter,args,cwd=worker_command()
    assert args==['--animego-worker']
    assert cwd is None
