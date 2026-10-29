import type { TorrentResult } from '../types';
import { matchesSeason } from './torrentParser';

const normalize = (s: string) => s.toLocaleLowerCase().replace(/ё/g, 'е').replace(/[^\p{L}\p{N}]+/gu, ' ').trim();

export function rankReleases(releases: TorrentResult[], titles: string[], year: number | null,
  season?: number, episode?: number, requireIdentity = false): TorrentResult[] {
  const aliases = titles.filter(Boolean).map(normalize);
  return releases.map(release => {
    const parts = release.title.split(/[/|\[\]()]/).map(normalize);
    const titleMatch = parts.some(part => aliases.some(alias => part === alias ||
      (part.startsWith(alias + ' ') && /^(?:19\d{2}|20\d{2}|s\d|season|сезон|\d+ сезон|\d+x\d|1080|720|2160|web|bluray|bdrip|dvdrip|hdtv)/.test(part.slice(alias.length + 1)))));
    if (!titleMatch || (season !== undefined && !matchesSeason(release.title, season))) return null;
    const years = release.title.match(/\b(?:19|20)\d{2}\b/g)?.map(Number) || [];
    // A series pack can span release years, but a remake with a different first year cannot.
    if (year && years.length && years[0] !== year) return null;
    if (requireIdentity && year && !years.length) return null;
    if (season === undefined && /(?:\bs\d{1,2}(?:e\d|\b)|\bseason\b|сезон|\b\d+x\d+)/i.test(release.title)) return null;
    const ep = release.title.match(/(?:s\d+[ ._-]*e|\d+[xх])(\d+)(?:\s*[-–—]\s*(?:s\d+e|\d+[xх]|e)?(\d+))?/i);
    const numberedRange = release.title.match(/(?:\[|серии\s*|episodes?\s*)(\d+)\s*[-–—]\s*(\d+)\s*(?:из|of|\])/i);
    const span = ep || numberedRange;
    const range = span?.[2] !== undefined;
    if (episode !== undefined && span && (episode < Number(span[1]) || episode > Number(span[2] || span[1]))) return null;
    const resolution = Number(release.title.match(/\b(2160|1080|720|480)p?\b/i)?.[1] || 0);
    const score = (year && years.includes(year) ? 40 : 0) +
      (season !== undefined && /(?:s\d|сезон|season|\d+x\d)/i.test(release.title) ? 30 : 0) +
      (episode !== undefined && ep && !range && Number(ep[1]) === episode ? 20 : 0) +
      (resolution === 1080 ? 4 : resolution === 2160 ? 3 : resolution === 720 ? 2 : 0) +
      Math.min(2, Math.log10(1 + Math.max(0, release.seeders || 0)));
    return { release, score };
  }).filter((item): item is { release: TorrentResult; score: number } => item !== null)
    .sort((a, b) => b.score - a.score).map(item => item.release);
}
