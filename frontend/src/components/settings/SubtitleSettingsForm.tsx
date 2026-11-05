import { useState, type FormEvent } from 'react';
import { API } from '../../services/api';
import type { SubtitleSettings } from '../../types';
import { Button, Input, Select } from '../ui/UIComponents';

const appearanceFields = [
  { name: 'font', label: 'Семейство шрифта', type: 'text', maxLength: 120 },
  { name: 'font_size', label: 'Размер шрифта', type: 'number', min: 1, max: 200 },
  { name: 'color', label: 'Цвет текста', type: 'color' },
  { name: 'border_color', label: 'Цвет обводки', type: 'color' },
  { name: 'border_size', label: 'Толщина обводки', type: 'number', min: 0, max: 20 },
  { name: 'shadow_offset', label: 'Смещение тени', type: 'number', min: 0, max: 20 },
  { name: 'position', label: 'Позиция по вертикали (%)', type: 'number', min: 0, max: 100 },
] as const;

const timingField = { name: 'speed', label: 'Множитель времени', type: 'number', min: 0.1, max: 10 } as const;
const timingPresets = [
  { label: 'Без поправки (1×)', value: 1 },
  { label: '23,976 → 25 FPS', value: (24000 / 1001) / 25 },
  { label: '25 → 23,976 FPS', value: 25 / (24000 / 1001) },
];

export function SubtitleSettingsForm({ initial }: { initial: SubtitleSettings }) {
  const [saved, setSaved] = useState(initial);
  const [draft, setDraft] = useState<Partial<Record<keyof SubtitleSettings, string>>>({});
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [failed, setFailed] = useState(false);

  const edit = (name: keyof SubtitleSettings, value: string) => {
    setDraft((current) => ({ ...current, [name]: value }));
    setFeedback('');
  };

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const patch = Object.fromEntries(
      [...appearanceFields, timingField].flatMap(({ name, type }) => {
        const raw = draft[name];
        if (raw === undefined) return [];
        return [[name, type === 'number' ? Number(raw) : raw.trim()]];
      }),
    );
    setSaving(true);
    setFailed(false);
    try {
      await API.saveSettings({ subtitle_settings: patch });
      setSaved({ ...saved, ...patch });
      setDraft({});
      setFeedback('Настройки субтитров сохранены.');
    } catch {
      setFailed(true);
      setFeedback('Не удалось сохранить настройки субтитров. Повторите попытку.');
    } finally {
      setSaving(false);
    }
  };

  const renderField = ({ name, label, type, ...limits }: (typeof appearanceFields)[number] | typeof timingField) => (
    <label key={name} className="block space-y-1 text-sm text-film-text">
      <span className="block">{label}</span>
      <Input
        type={type}
        required
        step={type === 'number' ? 'any' : undefined}
        pattern={type === 'text' ? '.*\\S.*' : undefined}
        className={type === 'color' ? 'h-10 max-w-24 cursor-pointer' : undefined}
        value={draft[name] ?? String(saved[name])}
        onChange={(event) => edit(name, event.target.value)}
        {...limits}
      />
    </label>
  );

  return (
    <details className="border-y border-film-line py-3">
      <summary className="cursor-pointer text-sm font-semibold text-film-text focus-visible:outline-film-accent">
        Оформление и тайминг субтитров
      </summary>
      <form onSubmit={save} className="mt-4 space-y-4">
        <fieldset disabled={saving} className="space-y-4">
          <p className="text-xs text-film-muted">
            Оформление рассчитано на обычные текстовые субтитры. ASS/SSA могут использовать свой стиль,
            а графические субтитры содержат готовые изображения. Позиция 100% соответствует нижнему краю.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">{appearanceFields.map(renderField)}</div>
          <h3 className="text-sm font-semibold text-film-text">Коррекция нарастающего рассинхрона</h3>
          <p className="text-xs text-film-muted">
            Для текстовых дорожек. Меньше 1 — реплики появляются раньше, больше 1 — позже. В пресете сначала указан FPS
            релиза субтитров, затем FPS видео. Постоянный сдвиг задаётся в меню синхронизации MPV.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            {renderField(timingField)}
            <label className="block space-y-1 text-sm text-film-text">
              <span className="block">Пересчёт по FPS</span>
              <Select className="w-full" value="" onChange={(event) => edit('speed', event.target.value)}>
                <option value="" disabled>Выбрать пресет</option>
                {timingPresets.map(({ label, value }) => <option key={label} value={value}>{label}</option>)}
              </Select>
            </label>
          </div>
        </fieldset>
        <p className="text-xs text-film-muted">
          Эти настройки действуют для всех видео и применяются сразу после сохранения.
        </p>
        <Button type="submit" variant="secondary" size="sm" loading={saving} disabled={!Object.keys(draft).length}>
          Сохранить настройки субтитров
        </Button>
        <p role="status" className={failed ? 'text-sm text-rose-400' : 'text-sm text-film-muted'}>{feedback}</p>
      </form>
    </details>
  );
}
