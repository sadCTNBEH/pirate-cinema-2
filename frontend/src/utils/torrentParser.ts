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

/**
 * Проверяет, подходит ли раздача под выбранный сезон сериала:
 * - Распознает диапазоны сезонов (S01-S03, 1-3 сезон, сезоны 1-4)
 * - Распознает одиночные сезоны (S01, S1, s01e05, 1x01, 1х01, сезон 1, 1 сезон)
 * - Распознает полные раздачи / паки (Complete, полный сезон, все сезоны)
 * - Раздачи без маркера сезона оставляются (общие раздачи)
 * - Явно чужой сезон (S02 при выбранном S01) отбрасывается
 */
export function matchesSeason(title: string | undefined | null, targetSeason: number): boolean {
  if (!title) return true;
  const t = title.toLowerCase();

  // 1. Полные раздачи / все сезоны
  if (/(?:complete|full\s*season|all\s*seasons|полный\s*сезон|все\s*сезоны|все\s*серии)/i.test(t)) {
    return true;
  }

  // 2. Диапазоны сезонов: S01-S03, s1-4, s01-03
  const sRange1 = t.match(/(?:^|[^a-z0-9])s(\d{1,2})\s*[-–—~]\s*s?(\d{1,2})(?![a-z0-9])/i);
  if (sRange1) {
    const from = parseInt(sRange1[1], 10);
    const to = parseInt(sRange1[2], 10);
    return targetSeason >= Math.min(from, to) && targetSeason <= Math.max(from, to);
  }

  // 1-3 сезон, 1-3 seasons, 1-3 сезоны
  const sRange2 = t.match(/(?:^|[^a-z0-9])(\d{1,2})\s*[-–—~]\s*(\d{1,2})\s*(?:сезон[а-я]*|season[s]?)(?![а-яёa-z0-9])/i);
  if (sRange2) {
    const from = parseInt(sRange2[1], 10);
    const to = parseInt(sRange2[2], 10);
    return targetSeason >= Math.min(from, to) && targetSeason <= Math.max(from, to);
  }

  // сезон(ы) 1-3, season(s) 1-3
  const sRange3 = t.match(/(?:сезон[а-я]*|season[s]?)[.:_\s]+(\d{1,2})\s*[-–—~]\s*(\d{1,2})(?![a-z0-9])/i);
  if (sRange3) {
    const from = parseInt(sRange3[1], 10);
    const to = parseInt(sRange3[2], 10);
    return targetSeason >= Math.min(from, to) && targetSeason <= Math.max(from, to);
  }

  // S01..S03
  const sRange4 = t.match(/(?:^|[^a-z0-9])s(\d{1,2})\s*\.\.\s*s?(\d{1,2})(?![a-z0-9])/i);
  if (sRange4) {
    const from = parseInt(sRange4[1], 10);
    const to = parseInt(sRange4[2], 10);
    return targetSeason >= Math.min(from, to) && targetSeason <= Math.max(from, to);
  }

  // Дискретные списки: сезоны 1, 2, 3
  const sList = t.match(/(?:сезон[а-я]*|season[s]?)[.:_\s]+([0-9,\s]+)/i);
  if (sList && sList[1].includes(',')) {
    const nums = sList[1].split(',').map((s) => parseInt(s.trim(), 10)).filter((n) => !isNaN(n));
    if (nums.length > 0) {
      return nums.includes(targetSeason);
    }
  }

  // 3. Одиночные сезоны
  let foundSeason: number | null = null;

  // 1x01, 1х01 (латиница и кириллица)
  const xMatch = t.match(/(?:^|[^a-z0-9])(\d{1,2})\s*[xх]\s*\d{1,3}(?![a-z0-9])/i);
  if (xMatch) {
    foundSeason = parseInt(xMatch[1], 10);
  }

  // S01, S1, s01e05, s01ep02
  if (foundSeason === null) {
    const sMatch = t.match(/(?:^|[^a-z0-9])s(\d{1,2})(?:e\d{1,3}|ep\d{1,3}|x\d{1,3}|(?![a-z0-9]))/i);
    if (sMatch) {
      foundSeason = parseInt(sMatch[1], 10);
    }
  }

  // сезон 1, Сезон.1, Сезон_1, Season 1
  if (foundSeason === null) {
    const sezMatch = t.match(/(?:сезон|season)[.:_\s]+(\d{1,2})(?![a-z0-9])/i);
    if (sezMatch) {
      foundSeason = parseInt(sezMatch[1], 10);
    }
  }

  // 1 сезон, 1-й сезон, 1-ый сезон, 1st season
  if (foundSeason === null) {
    const numSezMatch = t.match(/(?:^|[^a-z0-9])(\d{1,2})\s*(?:-?[ыийе]й\s*)?(?:сезон[а-я]*|season[s]?)(?![а-яёa-z0-9])/i);
    if (numSezMatch) {
      foundSeason = parseInt(numSezMatch[1], 10);
    }
  }

  if (foundSeason !== null) {
    return foundSeason === targetSeason;
  }

  // Без явного маркера сезона — оставляем (общая раздача / раздача без метки)
  return true;
}
