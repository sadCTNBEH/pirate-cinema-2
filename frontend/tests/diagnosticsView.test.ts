import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  sanitizeText,
  buildReportText,
  copyTextToClipboard,
} from '../src/components/diagnostics/DiagnosticsReport';
import { formatMb } from '../src/components/diagnostics/SqliteCard';
import { DiagnosticsResponse } from '../src/types';

const mockDiagnostics: DiagnosticsResponse = {
  status: 'healthy',
  version: '0.4.5',
  checked_at: '2026-10-30T12:00:00Z',
  response_time_ms: 12,
  torrserver: {
    state: 'running',
    running: true,
    port: 18765,
    pid: 1234,
    path: 'C:/tools/torrserver.exe',
    version: 'MatriX.133',
    managed: true,
    last_error: null,
    can_restart: true,
    log_path: 'C:/logs/ts.log',
  },
  mpv: {
    state: 'running',
    available: true,
    version: '0.38.0',
    path: 'C:/tools/mpv.exe',
    last_error: null,
  },
  db: {
    ok: true,
    size_mb: 42.5,
  },
  disk: {
    data_dir: 'C:/Users/user/.pirate-cinema',
    used_mb: 2048,
    free_mb: 4096,
  },
  last_errors: [
    {
      timestamp: '2026-10-30 11:59:00',
      component: 'torrserver',
      error_type: 'TimeoutError',
      message: 'Failed token=secret123 to connect',
    },
  ],
};

test('sanitizeText masks tokens, passwords, secrets and bearer headers', () => {
  assert.equal(sanitizeText(''), '');
  assert.equal(sanitizeText(null), '');
  assert.equal(
    sanitizeText('http://user:pass123@example.com?api_key=mykey&token=topsecret'),
    'http://user:***@example.com?api_key=***&token=***'
  );
  assert.equal(sanitizeText('Bearer eyJhbGciOiJIUzI1NiJ9.test'), 'Bearer ***');
});

test('buildReportText formats concise status when debugMode is false', () => {
  const text = buildReportText(mockDiagnostics, false);
  assert.match(text, /Статус служб Pirate Cinema/);
  assert.match(text, /Версия приложения: 0\.4\.5/);
  assert.match(text, /TorrServer:\s+Состояние: Работает/);
  assert.match(text, /Видеоплеер \(MPV\):\s+Состояние: Воспроизводит/);
  assert.doesNotMatch(text, /Response time:/);
});

test('buildReportText formats detailed technical diagnostics when debugMode is true', () => {
  const text = buildReportText(mockDiagnostics, true);
  assert.match(text, /System Diagnostics/);
  assert.match(text, /Application version: 0\.4\.5/);
  assert.match(text, /Response time: 12 ms/);
  assert.match(text, /Port: 18765/);
  assert.match(text, /PID: 1234/);
  assert.match(text, /Version: MatriX\.133/);
  assert.match(text, /Database \(SQLite\):\s+Status: OK/);
  assert.match(text, /Total: 6\.0 GB \(33% used\)/);
  assert.match(text, /Failed token=\*\*\* to connect/);
});

test('formatMb handles null, undefined and formats MB vs GB', () => {
  const t = (k: string) => (k === 'gb' ? 'ГБ' : k === 'mb' ? 'МБ' : k);
  assert.equal(formatMb(null, t), '—');
  assert.equal(formatMb(undefined, t), '—');
  assert.equal(formatMb(NaN, t), '—');
  assert.equal(formatMb(512, t), '512.0 МБ');
  assert.equal(formatMb(2048, t), '2.0 ГБ');
});

test('copyTextToClipboard uses navigator.clipboard when available', async () => {
  let written = '';
  const origNav = globalThis.navigator;
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true,
    value: {
      clipboard: {
        writeText: async (text: string) => {
          written = text;
        },
      },
    },
  });

  try {
    const success = await copyTextToClipboard('diagnostic report payload');
    assert.equal(success, true);
    assert.equal(written, 'diagnostic report payload');
  } finally {
    Object.defineProperty(globalThis, 'navigator', { configurable: true, value: origNav });
  }
});
