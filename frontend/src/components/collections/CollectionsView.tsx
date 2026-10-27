import React, { useCallback, useEffect, useState } from 'react';
import { ArrowLeft, Film, Loader2, Star, Trash2, Tv } from 'lucide-react';

import { useApp } from '../../context/AppContext';
import { API } from '../../services/api';
import { CollectionItem, CollectionName } from '../../types';
import { Button } from '../ui/UIComponents';

export const CollectionsView: React.FC<{ listName: CollectionName }> = ({ listName }) => {
  const { goBack, navigate, t } = useApp();
  const [items, setItems] = useState<CollectionItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadItems = useCallback(async (listName: CollectionName) => {
    setIsLoading(true);
    setError(null);
    try {
      setItems(await API.getCollection(listName));
    } catch (err: any) {
      setItems([]);
      setError(err?.message || 'Ошибка загрузки списка');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadItems(listName);
  }, [listName, loadItems]);

  const removeItem = async (event: React.MouseEvent, mediaId: string) => {
    event.stopPropagation();
    try {
      await API.removeCollectionItem(listName, mediaId);
      setItems((current) => current.filter((item) => item.media_id !== mediaId));
    } catch (err: any) {
      setError(err?.message || 'Ошибка удаления из списка');
    }
  };

  const openItem = (item: CollectionItem) => {
    if (item.media_id.startsWith('search:')) {
      navigate('search', { query: item.title });
      return;
    }
    navigate('meta', {
      imdb: item.media_id,
      title: item.title_ru || item.title,
      type: item.media_type || 'movie',
      poster: item.poster_url || undefined,
    });
  };

  return (
    <div className="ui-page collectionsview space-y-7 animate-fade-in pb-12">
      <header className="flex items-end gap-4 border-b border-film-line pb-5">
        <Button
          variant="secondary"
          size="sm"
          icon={<ArrowLeft className="h-4 w-4" />}
          onClick={goBack}
        >
          {t('back')}
        </Button>
        <div>
          <h1 className="mt-1 font-sans text-2xl font-semibold text-film-text">
            {listName === 'favorites' ? t('favorites') : t('watch_later')}
          </h1>
        </div>
      </header>

      {isLoading ? (
        <div className="py-16 text-center font-sans text-film-muted">
          <Loader2 className="mx-auto mb-3 h-7 w-7 animate-spin text-film-accent" />
          {t('loading')}
        </div>
      ) : error ? (
        <div className="border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-300">{error}</div>
      ) : items.length === 0 ? (
        <div className="py-20 text-center text-film-muted">
          <Film className="mx-auto mb-3 h-10 w-10 text-film-muted" />
          <p className="font-sans text-sm">{t('collections_empty')}</p>
        </div>
      ) : (
        <div className="cinema-poster-grid ui-collection-grid">
          {items.map((item) => {
            const title = item.title_ru || item.title;
            const isSeries = item.media_type === 'series';
            return (
              <article
                key={item.media_id}
                className="ui-collection-item group cursor-pointer overflow-hidden rounded-md border border-film-line bg-film-base transition-colors hover:border-film-line hover:bg-film-base"
              >
                <div className="ui-media-image relative aspect-[2/3] bg-film-surface">
                  <button type="button" className="absolute inset-0 w-full h-full cursor-pointer" aria-label={`Открыть: ${title}`} onClick={() => openItem(item)}>
                  {item.poster_url ? (
                    <img src={item.poster_url} alt={title} loading="lazy" className="h-full w-full object-cover transition-transform duration-200" />
                  ) : (
                    <div className="flex h-full items-center justify-center text-film-muted">
                      {isSeries ? <Tv className="h-10 w-10" /> : <Film className="h-10 w-10" />}
                    </div>
                  )}
                  </button>
                  <button
                    type="button"
                    title={t('delete')}
                    onClick={(event) => removeItem(event, item.media_id)}
                    className="absolute right-2 top-2 flex h-8 w-8 items-center justify-center rounded border border-film-line bg-film-base text-film-text transition-colors hover:border-rose-500/50 hover:text-rose-400"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                  {item.rating !== null && item.rating !== undefined && (
                    <span className="absolute bottom-2 right-2 flex items-center gap-1 rounded border border-amber-500/40 bg-film-base px-1.5 py-0.5 font-sans text-[11px] font-semibold text-amber-300">
                      <Star className="h-3 w-3 fill-current" />
                      {Number(item.rating).toFixed(1)}
                    </span>
                  )}
                </div>
                <div className="ui-media-copy min-w-0 p-3">
                  <h2 className="font-sans text-sm font-medium text-film-text"><button type="button" onClick={() => openItem(item)} className="text-left cursor-pointer hover:text-film-accent" title={title}>{title}</button></h2>
                  <p className="mt-1 font-sans text-xs text-film-muted">{item.year || '\u2014'}</p>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
};
