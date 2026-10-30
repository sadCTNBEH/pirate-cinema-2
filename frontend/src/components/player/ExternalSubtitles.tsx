import React, { useEffect, useRef, useState } from 'react';
import { API } from '../../services/api';
import { Button, Input, Select } from '../ui/UIComponents';

type Result = { id: string; language: string; release: string };

export function ExternalSubtitles({ hash, fileId, title, season }: {
  hash: string; fileId: number; title: string; season?: number;
}) {
  const [query, setQuery] = useState(title);
  const [year, setYear] = useState('');
  const [seasonValue, setSeason] = useState(season?.toString() || '');
  const [episode, setEpisode] = useState('');
  const [language, setLanguage] = useState('RU,EN');
  const [results, setResults] = useState<Result[]>([]);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const run = async (operation: () => Promise<Result[]>, attached = false) => {
    setBusy(true); setMessage(''); setResults([]);
    try {
      const rows = await operation();
      if (alive.current) { setResults(rows); setMessage(rows.length ? 'Выберите файл субтитров' : attached ? 'Субтитры подключены' : 'Субтитры не найдены'); }
    } catch (error) { if (alive.current) setMessage(error instanceof Error ? error.message : 'Ошибка SubDL'); }
    finally { if (alive.current) setBusy(false); }
  };
  return <details className="external-subtitles">
    <summary tabIndex={0}>Внешние субтитры · SubDL</summary>
    <form className="subtitle-search-form" onSubmit={event => {
      event.preventDefault();
      void run(() => API.post<Result[]>('/api/player/subtitles/search', { hash, file_id: fileId, title: query,
        year: year ? Number(year) : null, season: seasonValue ? Number(seasonValue) : null,
        episode: episode ? Number(episode) : null, language }));
    }}>
      <label>Название<Input value={query} onChange={event => setQuery(event.target.value)} maxLength={300} required /></label>
      <label>Год<Input type="number" min={1880} max={2200} value={year} onChange={event => setYear(event.target.value)} /></label>
      <label>Сезон<Input type="number" min={0} max={1000} value={seasonValue} onChange={event => setSeason(event.target.value)} /></label>
      <label>Серия<Input type="number" min={0} max={10000} value={episode} onChange={event => setEpisode(event.target.value)} /></label>
      <label>Язык<Select value={language} onChange={event => setLanguage(event.target.value)}>
        <option value="RU,EN">Русский и английский</option><option value="RU">Русский</option><option value="EN">Английский</option>
      </Select></label>
      <Button type="submit" loading={busy}>Найти</Button>
    </form>
    <p className="text-xs text-film-muted">Необязательно: задайте SUBDL_API_KEY в локальном .env и перезапустите приложение. <a href="https://subdl.com/api-doc/" target="_blank" rel="noreferrer">Получить ключ SubDL</a></p>
    <p role="status" className="text-sm">{message}</p>
    {results.length > 0 && <div className="subtitle-results" role="group" aria-label="Найденные субтитры">
      {results.map(row => <Button key={row.id} variant="secondary" disabled={busy} title={row.release}
        onClick={() => void run(() => API.post<Result[]>('/api/player/subtitles/attach', { hash, file_id: fileId, token: row.id }), true)}>
        {row.language} · {row.release}
      </Button>)}
    </div>}
  </details>;
}
