"""Resolve only confirmed anime identities; never merge on a similar title."""
from backend.exceptions import NotFoundError


def canonical_id(meta, fallback):
    shiki = meta.get('shikimori_id')
    if shiki and str(shiki).isdigit():
        return 'shikimori:' + str(shiki)
    ident = str(meta.get('id') or fallback)
    return ident if ident.startswith('shikimori:') else fallback


async def playback_identity(request, metadata, online):
    source, ident = request['source'], request['source_title_id']
    source_url = None
    if source == 'yummy':
        meta = await metadata.movie_meta('yummy:' + ident)
        canonical = canonical_id(meta, 'yummy:' + ident)
        card_id = canonical
    else:
        provider = online.get_provider('animego')
        source_url = provider.cards.get(ident)
        if not source_url:
            raise NotFoundError('Сначала найдите аниме и откройте плеер AnimeGo')
        card = await provider.catalog_card(source_url)
        if not any(e['number'] == request['episode'] for e in card['episodes']):
            raise NotFoundError('Серия отсутствует в выбранной карточке')
        if not request['media_id'].startswith(('shikimori:', 'yummy:')):
            raise NotFoundError('Нужна карточка аниме')
        base = await metadata.movie_meta(request['media_id'])
        matched = await provider.catalog(base)
        if str(matched['anime_id']) == ident:
            meta = base
            canonical = canonical_id(base, request['media_id'])
            card_id = canonical
        else:
            meta = {'title': card['title'], 'title_ru': card['title'], 'poster_url': card.get('poster_url'), 'type': 'series'}
            canonical = 'animego:' + ident
            card_id = request['media_id']
    return dict(request, media_id=canonical, card_media_id=card_id, source_url=source_url,
        title=meta.get('title_ru') or meta['title'], poster_url=meta.get('poster_local_url') or meta.get('poster_url'),
        year=meta.get('year'), media_type=meta.get('type') or 'series')
