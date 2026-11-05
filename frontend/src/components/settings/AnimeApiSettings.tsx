/**
 * @file components/settings/AnimeApiSettings.tsx
 * @description Раздел настроек YummyAnime API (публичный и приватный ключи).
 */

import React from 'react';
import { Input } from '../ui/UIComponents';
import { Sparkles } from 'lucide-react';

export interface AnimeApiSettingsProps {
  publicKey: string;
  onPublicKeyChange: (key: string) => void;
  privateKey: string;
  onPrivateKeyChange: (key: string) => void;
}

export const AnimeApiSettings: React.FC<AnimeApiSettingsProps> = ({
  publicKey,
  onPublicKeyChange,
  privateKey,
  onPrivateKeyChange,
}) => {
  return (
    <div className="space-y-4 pt-1">
      <div className="space-y-1">
        <span className="font-sans text-sm text-film-text font-semibold flex items-center gap-1.5">
          <Sparkles className="w-4 h-4 text-film-accent" />
          YummyAnime API
        </span>
        <p className="text-xs text-film-muted font-sans">
          Ключи приложения для поиска и каталога аниме с YummyAnime (api.yani.tv).
        </p>
      </div>

      <div className="space-y-2">
        <span className="block font-sans text-xs text-film-muted font-medium">
          Публичный API ключ (X-Application)
        </span>
        <Input
          id="yummy-pub-key"
          type="text"
          value={publicKey}
          onChange={(e) => onPublicKeyChange(e.target.value)}
          placeholder="bz7uk_nr9bouyrn9"
        />
      </div>

      <div className="space-y-2">
        <span className="block font-sans text-xs text-film-muted font-medium">
          Приватный API ключ (Secret)
        </span>
        <Input
          id="yummy-priv-key"
          type="password"
          value={privateKey}
          onChange={(e) => onPrivateKeyChange(e.target.value)}
          placeholder="Необязательно (если получен в кабинете разработчика)"
        />
      </div>
    </div>
  );
};
