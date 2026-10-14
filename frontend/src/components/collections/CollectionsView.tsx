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
    navigate('meta', {
      imdb: item.media_id,
      title: item.title_ru || item.title,
      type: item.media_type || 'movie',
      poster: item.poster_url || undefined,
    });
  };

  return (
    <div className="space-y-7 animate-fade-in pb-12">
      <header className="flex items-end gap-4 border-b border-slate-800 pb-5">
        <Button
          variant="secondary"
          size="sm"
          icon={<ArrowLeft className="h-4 w-4" />}
          onClick={goBack}
        >
          {t('back')}
        </Button>
        <div>
          <p className="font-code text-xs uppercase tracking-wider text-cyan-400">Pirate Cinema</p>
          <h1 className="mt-1 font-tech text-2xl font-bold uppercase tracking-wider text-slate-100">
            {listName === 'favorites' ? t('favorites') : t('watch_later')}
          </h1>
        </div>
      </header>

      {isLoading ? (
        <div className="py-16 text-center font-tech text-slate-400">
          <Loader2 className="mx-auto mb-3 h-7 w-7 animate-spin text-cyan-400" />
          {t('loading')}
        </div>
      ) : error ? (
        <div className="border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-300">{error}</div>
      ) : items.length === 0 ? (
        <div className="py-20 text-center text-slate-400">
          <Film className="mx-auto mb-3 h-10 w-10 text-slate-600" />
          <p className="font-tech text-sm uppercase tracking-wider">{t('collections_empty')}</p>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-5 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
          {items.map((item) => {
            const title = item.title_ru || item.title;
            const isSeries = item.media_type === 'series';
            return (
              <article
                key={item.media_id}
                onClick={() => openItem(item)}
                className="group cursor-pointer overflow-hidden rounded-lg border border-slate-800/80 bg-[#090d16] transition-colors hover:border-cyan-500/50 hover:bg-[#0c1220]"
              >
                <div className="relative aspect-[2/3] bg-slate-900">
                  {item.poster_url ? (
                    <img src={item.poster_url} alt={title} loading="lazy" className="h-full w-full object-cover transition-transform duration-200 group-hover:scale-105" />
                  ) : (
                    <div className="flex h-full items-center justify-center text-slate-600">
                      {isSeries ? <Tv className="h-10 w-10" /> : <Film className="h-10 w-10" />}
                    </div>
                  )}
                  <button
                    type="button"
                    title={t('delete')}
                    onClick={(event) => removeItem(event, item.media_id)}
                    className="absolute right-2 top-2 flex h-8 w-8 items-center justify-center rounded border border-slate-700/70 bg-[#060910]/85 text-slate-300 transition-colors hover:border-rose-500/50 hover:text-rose-400"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                  {item.rating !== null && item.rating !== undefined && (
                    <span className="absolute bottom-2 right-2 flex items-center gap-1 rounded border border-amber-500/40 bg-[#060910]/90 px-1.5 py-0.5 font-code text-[11px] font-bold text-amber-300">
                      <Star className="h-3 w-3 fill-current" />
                      {Number(item.rating).toFixed(1)}
                    </span>
                  )}
                </div>
                <div className="min-w-0 p-3">
                  <h2 className="truncate font-tech text-sm font-semibold text-slate-100 group-hover:text-cyan-400" title={title}>{title}</h2>
                  <p className="mt-1 font-code text-xs text-slate-400">{item.year || '\u2014'}</p>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
};
