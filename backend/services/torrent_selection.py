"""Conservative torrent file matching; ambiguity is a user decision."""
import re
from pathlib import PurePosixPath

from backend.core.enums import VideoExtension


def episode_info(path: str) -> dict:
    text = path.replace('\\', '/').lower()
    base = PurePosixPath(text).stem
    season = None
    seasons = re.findall(r'(?<!\w)(?:s|season[ ._]*|сезон[ ._]*)(\d{1,2})(?!\d)', text)
    if seasons and len(set(seasons)) == 1:
        season = int(seasons[0])
    if re.search(r'(?:s\d{1,2}|seasons?[ ._]*\d{1,2}|сезоны?[ ._]*\d{1,2})[ ._]*[-–][ ._]*s?\d', text):
        season = None
    match = re.search(r'(?<!\w)(?:s(\d{1,2})[ ._-]*e|([0-9]{1,2})x)(\d{1,4})', text)
    if match:
        season, episode = int(match[1] or match[2]), int(match[3])
        tail = text[match.end():]
    else:
        match = re.search(r'(?<!\w)(?:episode|ep|e|серия)[ ._-]*(\d{1,4})(?!\d)', base)
        if not match:
            # Bare anime numbers only in unambiguous positions, never codec/year/resolution.
            match = re.search(r'^(\d{1,3})(?:v\d)?(?:$|[ ._-])|(?:^| - |\] )(\d{2,3})(?:v\d)?(?:$|[ ._\[-])', base)
        episode = int(next(g for g in match.groups() if g is not None)) if match else None
        tail = base[match.end():] if match else ''
    multiple = bool(re.match(r'(?:[ ._]*e\d|[ ._]*[-–~][ ._]*(?:s\d+e|e)?\d)', tail))
    end = re.match(r'[ ._]*[-–~][ ._]*(?:s\d+e|e)?(\d+)', tail)
    episodes = [episode] if episode is not None else []
    if end and episode is not None and episode <= int(end[1]) <= episode + 1000:
        episodes = list(range(episode, int(end[1]) + 1))
    elif multiple:
        episodes += [int(n) for n in re.findall(r'e(\d+)', tail)]
    special = bool(re.search(r'(?<!\w)(?:ova|specials?|спецвыпуск)(?!\w)', text)) or season == 0
    return {'season': season, 'episode': episode, 'multiple': multiple, 'special': special, 'episodes': episodes}


def playable(file: dict) -> bool:
    path = (file.get('path') or file.get('name') or '').replace('\\', '/')
    if PurePosixPath(path).suffix.lower() not in VideoExtension.values():
        return False
    # Boundaries include underscores, paths and punctuation, but not letters in titles.
    junk = r'(?:samples?|trailers?|preview|extras?|bonus|opening|ending|creditless|ncop|nced|op|ed|promo|промо|трейлер|бонус)'
    if re.search(r'(?<![^\W_])' + junk + r'(?:\d{1,2})?(?![^\W_])', path.lower()):
        return False
    size = file.get('length') or 0
    return not (0 < size < 5 * 1024 * 1024)


def select_files(files: list[dict], *, season: int | None = None,
                 episode: int | None = None, absolute: int | None = None,
                 release_title: str = '') -> dict:
    release = episode_info(release_title)
    exact, uncertain = [], []
    for raw in files:
        if not playable(raw):
            continue
        info = episode_info(raw.get('path') or raw.get('name', ''))
        file = {**raw, **info}
        if info['special'] and not (season == 0 or (season is None and release['special'])):
            continue
        fs, ep = info['season'], info['episode']
        if fs is None and release['season'] is not None:
            fs = release['season']
        if season is not None and fs is not None and fs != season:
            continue
        if episode is None:
            if season is None and ep is not None:
                uncertain.append(file)
            else:
                uncertain.append(file) if season is not None else exact.append(file)
            continue
        targets = {absolute} if fs is None and absolute is not None else {episode, absolute}
        if fs is None and absolute is None and season is not None:
            # An unlabelled 025 may be absolute numbering. Only the user can map it.
            uncertain.append(file)
            continue
        if ep is not None and not targets.intersection(info['episodes']):
            continue
        if ep is None or info['multiple'] or (fs is None and absolute is None and season is not None):
            uncertain.append(file)
        else:
            exact.append(file)
    candidates = exact or uncertain
    return {'file': exact[0] if len(exact) == 1 and not uncertain else None,
            'candidates': candidates,
            'reason': 'Выберите видеофайл' if candidates else 'Нужная серия или фильм не найдены. Выберите другую раздачу.'}


def next_file(files: list[dict], current_id: int, intent: dict | None = None,
              confirmed_id: int | None = None) -> dict | None:
    current = next((f for f in files if str(f.get('id')) == str(current_id)), None)
    if not current:
        return None
    info = episode_info(current.get('path') or current.get('name', ''))
    intent = intent or {}
    episode = intent.get('episode', info['episode'])
    if episode is None or info['multiple']:
        return None
    result = select_files(files, season=intent.get('season', info['season']), episode=episode + 1,
                          absolute=intent['absolute'] + 1 if intent.get('absolute') is not None else None,
                          release_title=intent.get('release_title', ''))
    return next((f for f in result['candidates'] if f['id'] == confirmed_id), result['file'])
