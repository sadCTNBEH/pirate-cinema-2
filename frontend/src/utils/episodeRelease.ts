export function formatEpisodeRelease(value: string | number | null | undefined, language = 'ru'): string {
  if (value == null || value === '') return '';
  const raw = String(value).trim();
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(raw);
  const numeric = /^\d{10}(?:\d{3})?$/.test(raw);
  const date = new Date(numeric ? Number(raw) * (raw.length === 10 ? 1000 : 1) : dateOnly ? `${raw}T00:00:00` : raw);
  if (!Number.isFinite(date.getTime())) return '';
  // Omitting timeZone deliberately uses the computer's current time zone.
  return new Intl.DateTimeFormat(language === 'en' ? 'en-GB' : 'ru-RU', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    ...(dateOnly ? {} : {hour: '2-digit', minute: '2-digit'} as const),
  }).format(date);
}
