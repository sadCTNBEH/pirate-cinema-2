"""Own animego.online HTML adapter, isolated from the application's event loop."""
import re
from urllib.parse import urljoin, urlsplit

BASE = 'https://animego.online'


def norm(value):
    return re.sub(r'[^\w]', '', str(value).casefold().replace('ё', 'е'))


class AnimegoLookupError(ValueError):
    def __init__(self, message, code, status=503):
        super().__init__(message)
        self.code, self.status = code, status


def card_url(value):
    url = urljoin(BASE, value)
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.netloc != 'animego.online' or not re.fullmatch(r'/\d+-[^/]+\.html', parsed.path) or parsed.query:
        raise AnimegoLookupError('AnimeGo: недопустимая карточка', 'markup')
    return url


def soup(content):
    from bs4 import BeautifulSoup
    return BeautifulSoup(content, 'html.parser')


def search_items(content):
    page = soup(content)
    items = {}
    for node in page.select('a.poster-item[href]'):
        title = node.select_one('.animego-online-poster-item__title')
        meta = node.select_one('.animego-online-poster-item__meta')
        if not title or not meta:
            raise AnimegoLookupError('AnimeGo: изменилась разметка результатов', 'markup')
        url = card_url(node['href'])
        text = meta.get_text(' ', strip=True)
        year = re.search(r'\b(19\d{2}|20\d{2})\b', text)
        ident = re.match(r'/(\d+)-', urlsplit(url).path)[1]
        items[ident] = {'id': ident, 'link': url, 'title': title.get_text(strip=True),
            'year': int(year[1]) if year else None, 'type': 'movie' if 'фильм' in text.lower() else 'series'}
    if not items and not any(x in page.get_text().lower() for x in ('ничего не найдено', 'не дал результатов', 'по вашему запросу')):
        raise AnimegoLookupError('AnimeGo: несовместимая страница поиска', 'markup')
    return list(items.values())


def parse_card(content, url):
    page = soup(content)
    root = page.select_one('[data-player-anime-id]')
    heading = page.select_one('h1')
    if not root or not heading:
        raise AnimegoLookupError('AnimeGo: несовместимая карточка', 'markup')
    ident = root['data-player-anime-id']
    if not ident.isdigit() or re.match(r'/(\d+)-', urlsplit(card_url(url)).path)[1] != ident:
        raise AnimegoLookupError('AnimeGo: ID карточки и плеера различаются', 'markup')
    label = page.select_one('.animego-online-poster-item__label')
    count = re.search(r'(\d+)\s*сери', label.get_text(' ', strip=True) if label else '', re.IGNORECASE)
    original = page.select_one('.animego-online-page__original')
    voices = page.select_one('.animego-online-page__details-list--voice')
    studios = [a.get_text(strip=True) for a in voices.select('a[href]:not(.vm-more)')] if voices else []
    players = []
    for slot in root.select('[data-player-slot]'):
        title = slot.get('data-player-title', '')
        if 'kodik' not in title.lower():
            continue
        name = 'Kodik'
        players.append({'translation_id': slot['data-player-slot'], 'label': name, 'player': name})
    seasons = []
    for a in page.select('a[href]'):
        if 'franchise' in ' '.join(a.parent.get('class', [])):
            try:
                seasons.append({'title': (a.select_one('.animego-online-poster-item__title') or a).get_text(' ', strip=True), 'url': card_url(a['href'])})
            except AnimegoLookupError:
                pass
    total = int(count[1]) if count else 0
    return {'anime_id': ident, 'title': heading.get_text(strip=True), 'url': url,
        'original_title': original.get_text(strip=True) if original else '',
        'total_episodes': total, 'episodes': [{'number': n, 'id': f'{ident}:{n}'} for n in range(1, total + 1)],
        'voices': players, 'studios': studios, 'seasons': seasons,
        'notice': 'Озвучка выбирается внутри Kodik.' if players else 'AnimeGo не предоставляет Kodik для этого тайтла. Выберите другой источник.'}


def fetch(session, url, **kwargs):
    import requests
    try:
        response = session.get(url, timeout=(5, 15), **kwargs)
    except requests.RequestException as error:
        raise AnimegoLookupError(f'AnimeGo: сетевая ошибка ({type(error).__name__})', 'network') from None
    response.encoding = 'utf-8'
    if response.status_code in (403, 429, 503) or 'challenge-platform' in response.text:
        raise AnimegoLookupError('AnimeGo: сайт ограничил доступ', 'blocked')
    if response.status_code != 200:
        raise AnimegoLookupError(f'AnimeGo: HTTP {response.status_code}', 'network')
    return response


def handle(payload, session):
    session.headers.update({'User-Agent': 'Mozilla/5.0'})
    method, data = payload['method'], payload['data']
    if method == 'search':
        return search_items(fetch(session, BASE + '/index.php', params={'do': 'search', 'subaction': 'search', 'story': data['query']}).text)
    url = card_url(data['url'])
    card = parse_card(fetch(session, url).text, url)
    if method == 'card':
        return card
    if method != 'embed':
        raise AnimegoLookupError('AnimeGo поддерживает только веб-плеер', 'playback', 422)
    slot = next((p for p in card['voices'] if p['translation_id'] == str(data['translation_id']) and p['player'] == data['player']), None)
    if not slot or not 1 <= int(data['episode']) <= card['total_episodes']:
        raise AnimegoLookupError('AnimeGo: серия или плеер отсутствуют в карточке', 'playback', 404)
    response = fetch(session, BASE + '/engine/ajax/controller.php', params={'mod': 'player', 'id': card['anime_id'], 'slot': slot['translation_id']},
        headers={'Referer': url, 'X-Requested-With': 'XMLHttpRequest'})
    config = response.json()
    if not config.get('status') or not isinstance(config.get('data'), dict):
        raise AnimegoLookupError('AnimeGo: выбранный плеер недоступен', 'playback')
    config = config['data']
    src = urlsplit(config.get('src', ''))
    if config.get('kind') != 'iframe' or src.scheme != 'https' or src.username or src.password or not re.fullmatch(r'(?:[a-z0-9-]+\.)*kodik(?:player)?\.(?:com|info|biz|cc)', src.hostname or ''):
        raise AnimegoLookupError('AnimeGo: сайт не вернул совместимый плеер Kodik', 'playback')
    return {'config': config, 'episode': int(data['episode']), 'player': slot['player']}


def run_worker():
    import json
    import sys
    if sys.stdin is None or sys.stdout is None:
        import ctypes
        import msvcrt
        import os
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetStdHandle.restype = ctypes.c_void_p
        if sys.stdin is None:
            sys.stdin = os.fdopen(msvcrt.open_osfhandle(kernel.GetStdHandle(-10), os.O_RDONLY), 'r', encoding='utf-8')
        if sys.stdout is None:
            sys.stdout = os.fdopen(msvcrt.open_osfhandle(kernel.GetStdHandle(-11), os.O_WRONLY), 'w', encoding='utf-8')
    try:
        payload = json.load(sys.stdin)
        import requests
        with requests.Session() as session:
            session.trust_env = False
            result = handle(payload, session)
        output = {'result': result}
    except ImportError:
        output = {'error': 'AnimeGo: в Python запуска приложения отсутствует requests или beautifulsoup4. Запустите приложение из .venv.', 'code': 'dependency', 'status': 503}
    except AnimegoLookupError as error:
        output = {'error': str(error), 'code': error.code, 'status': error.status}
    except ValueError as error:
        output = {'error': str(error), 'code': 'playback', 'status': 503}
    except Exception:  # noqa: BLE001
        output = {'error': 'AnimeGo: ошибка сети, разметки или выбранного плеера', 'code': 'upstream', 'status': 503}
    print(json.dumps(output, ensure_ascii=True))
    return 1 if 'error' in output else 0


if __name__ == '__main__':
    import sys
    sys.exit(run_worker())
