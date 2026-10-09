/**
 * @file utils/torrentParser.ts
 * @description Утилиты для парсинга названий торрент-релизов,
 * извлечения информации об аудиодорожках (озвучке), форматирования размеров и времени.
 */

/**
 * Извлекает типы озвучки/перевода из названия торрента,
 * используя переданную функцию локализации t(key) из бэкенда.
 * 
 * @param titleStr Название раздачи
 * @param t Функция перевода t(k)
 * @returns Строка со списком озвучек (например: "Дубляж, Субтитры")
 */
export function parseTrans(titleStr: string, t: (k: string) => string): string {
  if (!titleStr) return t('unknown');
  const p = titleStr.split('|');
  if (p.length < 2) return t('unknown');
  const l = p[p.length - 1].trim();
  if (l.length > 20) return t('unknown');

  const res: string[] = [];
  for (let c of l.split(/[,+]/)) {
    c = c.trim().toUpperCase();
    if (c === 'D' || c === 'Д') {
      res.push(t('dubbing'));
    } else if (c.startsWith('P') || c.startsWith('П') || c === 'M' || c === 'М') {
      res.push(t('prof'));
    } else if (c.startsWith('A') || c.startsWith('Л') || c.startsWith('L')) {
      res.push(t('amateur'));
    } else if (c === 'O' || c === 'О') {
      res.push(t('original'));
    } else if (c.startsWith('S') || c.startsWith('С')) {
      res.push(t('subtitles'));
    } else if (c) {
      res.push(c);
    }
  }

  const unique = Array.from(new Set(res));
  return unique.join(', ') || t('unknown');
}

/**
 * Форматирует секунды в отображение HH:MM:SS или MM:SS
 * 
 * @param secs Время в секундах
 */
export function formatTime(secs: number): string {
  if (!secs || isNaN(secs) || secs <= 0) return '';
  const total = Math.floor(secs);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h
    ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
    : `${m}:${String(s).padStart(2, '0')}`;
}

/**
 * Форматирует размер файла в человекочитаемый вид,
 * используя единицы измерения из функции t(k).
 * 
 * @param bytes Размер в байтах
 * @param t Функция перевода t(k)
 */
export function formatSize(bytes: number | undefined | null, t: (k: string) => string): string {
  if (!bytes || isNaN(bytes)) return '';
  if (bytes > 1e9) return (bytes / 1e9).toFixed(1) + ' ' + (t('gb') || 'ГБ');
  if (bytes > 1e6) return (bytes / 1e6).toFixed(0) + ' ' + (t('mb') || 'МБ');
  return (bytes / 1e3).toFixed(0) + ' ' + (t('kb') || 'КБ');
}

/**
 * Безопасное экранирование строк
 */
export function esc(str: any): string {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
