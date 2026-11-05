/**
 * @file components/settings/PlayerSettings.tsx
 * @description Раздел настроек видеоплеера MPV: шаг перемотки, AdGuard, аудиодорожки и субтитры, пропуск заставок.
 */

import React from 'react';
import { useApp } from '../../context/AppContext';
import { Select } from '../ui/UIComponents';
import { Film } from 'lucide-react';
import { AdguardSettings } from './AdguardSettings';
import { TrackLanguageSettings } from './TrackLanguageSettings';

export interface PlayerSettingsProps {
  seekStep: 5 | 10 | 15 | 30 | 60;
  onSeekStepChange: (step: 5 | 10 | 15 | 30 | 60) => void;
  isSaving?: boolean;
  audioLanguages: string[];
  onAudioLanguagesChange: (langs: string[]) => void;
  subtitleLanguages: string[];
  onSubtitleLanguagesChange: (langs: string[]) => void;
  autoSkipIntro: boolean;
  onAutoSkipIntroChange: (skip: boolean) => void;
}

export const PlayerSettings: React.FC<PlayerSettingsProps> = ({
  seekStep,
  onSeekStepChange,
  isSaving,
  audioLanguages,
  onAudioLanguagesChange,
  subtitleLanguages,
  onSubtitleLanguagesChange,
  autoSkipIntro,
  onAutoSkipIntroChange,
}) => {
  const { t } = useApp();

  return (
    <div className="ui-settings-section space-y-4">
      <h2 className="text-lg font-sans font-semibold text-film-text flex items-center gap-2">
        <Film className="w-5 h-5 text-film-accent" />
        {t('mpv_player') || 'Видеоплеер (MPV)'}
      </h2>

      <div className="space-y-2">
        <label htmlFor="seek-step" className="block font-sans text-sm text-film-text font-semibold">
          Шаг перемотки
        </label>
        <Select
          id="seek-step"
          aria-describedby="seek-step-hint"
          value={seekStep}
          disabled={isSaving}
          className="w-full sm:w-64 rounded-md border border-film-line bg-film-base p-3 text-film-text focus-visible:outline-2 focus-visible:outline-film-accent"
          onChange={(event) => {
            const step = Number(event.target.value) as 5 | 10 | 15 | 30 | 60;
            onSeekStepChange(step);
          }}
        >
          {[5, 10, 15, 30, 60].map((step) => (
            <option key={step} value={step}>
              {step} секунд
            </option>
          ))}
        </Select>
        <p id="seek-step-hint" className="font-sans text-xs text-film-muted">
          Для стрелок ←/→ и кнопок перемотки плеера. Применяется сразу.
        </p>
      </div>

      <AdguardSettings />

      <TrackLanguageSettings
        audio={audioLanguages}
        subtitles={subtitleLanguages}
        onAudio={onAudioLanguagesChange}
        onSubtitles={onSubtitleLanguagesChange}
      />

      <label className="flex items-center gap-3 text-sm text-film-text">
        <input
          type="checkbox"
          checked={autoSkipIntro}
          onChange={(event) => onAutoSkipIntroChange(event.target.checked)}
        />
        Автоматически пропускать заставки
      </label>
      <p className="text-xs text-film-muted">
        MPV покажет отсчёт 8 секунд с отменой. Только подтверждённые заставки и повторы; титры пропускаются вручную.
      </p>
    </div>
  );
};
