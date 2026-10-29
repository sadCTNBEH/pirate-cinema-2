import React from 'react';
import { useApp } from '../../context/AppContext';
import { Select } from '../ui/UIComponents';

type Props = { audio: string[]; subtitles: string[]; onAudio: (values: string[]) => void; onSubtitles: (values: string[]) => void };

export const TrackLanguageSettings: React.FC<Props> = ({ audio, subtitles, onAudio, onSubtitles }) => {
  const { lang } = useApp();
  const en = lang === 'en';
  const labels: Record<string, string> = en
    ? { ru: 'Russian', en: 'English', original: 'Original language', auto: 'Automatically (MPV)', off: 'Off', '': 'No fallback' }
    : { ru: 'Русский', en: 'Английский', original: 'Оригинальный язык', auto: 'Автоматически (MPV)', off: 'Выключены', '': 'Без следующего языка' };
  const group = (name: string, id: string, values: string[], choices: string[], change: (values: string[]) => void) => {
    const terminal = values.findIndex(value => value === 'auto' || value === 'off');
    const count = terminal >= 0 ? terminal + 1 : Math.min(choices.length, values.length + 1);
    return <fieldset className="min-w-0 space-y-3">
      <legend className="text-sm font-semibold text-film-text mb-2">{name}</legend>
      {Array.from({ length: count }, (_, index) => <div className="space-y-2" key={index}>
        <label htmlFor={`${id}-${index}`} className="block text-xs text-film-muted">{index === 0 ? (en ? 'Preferred language' : 'Предпочтительный язык') : (en ? 'If unavailable' : 'Если недоступен')}</label>
        <Select id={`${id}-${index}`} value={values[index] || ''} onChange={event => change([...values.slice(0, index), ...(event.target.value ? [event.target.value] : [])])}>
          {index > 0 && <option value="">{labels['']}</option>}
          {choices.filter(value => !values.slice(0, index).includes(value) && !(index > 0 && value === 'off')).map(value => <option value={value} key={value}>{labels[value]}</option>)}
        </Select>
      </div>)}
    </fieldset>;
  };
  return <div className="space-y-3" aria-label={en ? 'Playback languages' : 'Языки воспроизведения'}>
    <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
      {group(en ? 'Audio' : 'Аудио', 'audio-language', audio, ['ru', 'en', 'original', 'auto'], onAudio)}
      {group(en ? 'Subtitles' : 'Субтитры', 'subtitle-language', subtitles, ['ru', 'en', 'auto', 'off'], onSubtitles)}
    </div>
    <p className="text-xs text-film-muted">{en ? 'Languages are tried in order. A remembered voice takes priority; changing its language order clears that choice. Original language requires a track marked as original.' : 'Языки проверяются по порядку. Запомненная озвучка важнее языка; изменение порядка сбросит её выбор. Оригинальный язык определяется по метке дорожки.'}</p>
  </div>;
};
