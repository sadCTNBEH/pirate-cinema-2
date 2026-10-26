/**
 * @file AutostartPromptModal.tsx
 * @description Модальное окно с предложением добавить Pirate Cinema в автозапуск
 * при первом запуске приложения.
 */

import React, { useState } from 'react';
import { useApp } from '../../context/AppContext';
import { API } from '../../services/api';
import { Button } from '../ui/UIComponents';
import { Rocket, Smartphone, EyeOff, Check, X } from 'lucide-react';

interface AutostartPromptModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const AutostartPromptModal: React.FC<AutostartPromptModalProps> = ({
  isOpen,
  onClose,
}) => {
  const { t } = useApp();
  const [loading, setLoading] = useState<boolean>(false);

  if (!isOpen) return null;

  const handleChoice = async (enableAutostart: boolean) => {
    setLoading(true);
    try {
      await API.saveSettings({
        autostart: enableAutostart,
        autostart_prompted: true,
      });
    } catch (err) {
      console.warn('Failed to save autostart choice:', err);
    } finally {
      setLoading(false);
      onClose();
    }
  };

  return (
    <div role="dialog" aria-modal="true" className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-fade-in">
      <div className="relative bg-[#0a0e18] border border-cyan-500/50 rounded-xl max-w-md w-full p-6 space-y-6 shadow-2xl shadow-cyan-950/50 overflow-hidden">
        {/* Декоративная фоновая подсветка */}
        <div className="absolute -top-12 -right-12 w-36 h-36 bg-cyan-500/10 rounded-full blur-2xl pointer-events-none" />
        <div className="absolute -bottom-12 -left-12 w-36 h-36 bg-blue-600/10 rounded-full blur-2xl pointer-events-none" />

        {/* Заголовок */}
        <div className="flex items-start gap-4">
          <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-cyan-500/20 to-blue-600/10 border border-cyan-500/40 flex items-center justify-center shrink-0 shadow-lg shadow-cyan-500/10">
            <Rocket className="w-6 h-6 text-cyan-400" />
          </div>
          <div className="min-w-0">
            <h3 className="text-base font-tech font-bold text-slate-100 uppercase tracking-wider">
              {t('autostart_modal_title') || 'Автозапуск при старте Windows'}
            </h3>
            <p className="text-xs text-slate-400 mt-1 leading-relaxed">
              {t('autostart_modal_desc') ||
                'Запускать Pirate Cinema автоматически при включении компьютера?'}
            </p>
          </div>
        </div>

        {/* Карточки преимуществ */}
        <div className="space-y-2.5 bg-[#060910] border border-slate-800/80 rounded-lg p-3.5 text-xs text-slate-300">
          <div className="flex items-center gap-2.5">
            <EyeOff className="w-4 h-4 text-cyan-400 shrink-0" />
            <span>Стартует свернутым в трей, не отвлекая при загрузке системы</span>
          </div>
          <div className="flex items-center gap-2.5">
            <Smartphone className="w-4 h-4 text-emerald-400 shrink-0" />
            <span>Всегда доступен для управления и запуска фильмов с телефона</span>
          </div>
        </div>

        {/* Кнопки действий */}
        <div className="flex items-center justify-end gap-3 pt-1">
          <Button
            variant="secondary"
            size="sm"
            icon={<X className="w-3.5 h-3.5" />}
            disabled={loading}
            data-dialog-close
            onClick={() => handleChoice(false)}
          >
            {t('autostart_not_now') || 'Не сейчас'}
          </Button>

          <Button
            variant="cyan"
            size="sm"
            icon={<Check className="w-3.5 h-3.5" />}
            loading={loading}
            onClick={() => handleChoice(true)}
          >
            {t('autostart_enable') || 'Включить автозапуск'}
          </Button>
        </div>
      </div>
    </div>
  );
};
