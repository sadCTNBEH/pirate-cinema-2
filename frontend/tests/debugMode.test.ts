import test from 'node:test';
import assert from 'node:assert/strict';

/**
 * Log and text sanitizer mirror from DiagnosticsView
 */
function sanitizeText(text?: string | null): string {
  if (!text) return '';
  return text
    .replace(/(token|api[_-]?key|password|secret|auth)=([^\s&]+)/gi, '$1=***')
    .replace(/(Bearer\s+)[^\s]+/gi, '$1***')
    .replace(/([a-zA-Z]+:\/\/[^:]+:)[^@]+@/g, '$1***@');
}

/**
 * Status mapping mirror from InlinePlayer
 */
function getDisplayStatus(playbackStatusText: string, debugMode: boolean): string {
  if (debugMode) {
    return playbackStatusText || 'Буферизация видеопотока...';
  }
  const lower = (playbackStatusText || '').toLowerCase();
  if (lower.includes('dht') || lower.includes('метадан') || lower.includes('поиск')) {
    return 'Поиск раздачи...';
  }
  if (lower.includes('подключен') || lower.includes('добавлен') || lower.includes('торрент-сет')) {
    return 'Подключение...';
  }
  if (lower.includes('буфериз') || lower.includes('запуск') || lower.includes('подготовк') || lower.includes('инициализ')) {
    return 'Буферизация...';
  }
  return 'Буферизация...';
}

/**
 * Report builder mirror from DiagnosticsView
 */
function buildReportText(d: any, isDebug: boolean): string {
  if (!isDebug) {
    const tsStatus =
      d.torrserver.state === 'recovering'
        ? 'Восстанавливается'
        : d.torrserver.state === 'error'
        ? 'Ошибка'
        : d.torrserver.running
        ? 'Работает'
        : 'Не запущен';
    const mpvStatus =
      d.mpv.state === 'error'
        ? 'Ошибка воспроизведения'
        : d.mpv.state === 'starting'
        ? 'Запускается'
        : d.mpv.state === 'running'
        ? 'Воспроизводит'
        : d.mpv.available
        ? 'Доступен'
        : 'Не найден';

    return `Статус служб Pirate Cinema

Версия приложения: ${d.version}
Общее состояние: ${d.status === 'healthy' ? 'Работает' : d.status === 'degraded' ? 'Есть проблемы' : 'Ошибка'}
Проверено: ${d.checked_at ? '00:00:00' : '—'}

TorrServer:
  Состояние: ${tsStatus}
  ${d.torrserver.last_error ? `Сообщение: ${sanitizeText(d.torrserver.last_error)}` : 'Ошибок нет'}

Видеоплеер (MPV):
  Состояние: ${mpvStatus}
  ${d.mpv.last_error ? `Сообщение: ${sanitizeText(d.mpv.last_error)}` : 'Ошибок нет'}
`;
  }

  const tsRunning = d.torrserver.running ? 'Yes' : 'No';
  const mpvAvail = d.mpv.available ? 'Yes' : 'No';
  const dbOk = d.db.ok ? 'OK' : 'Error';

  return `Pirate Cinema System Diagnostics

General:
  Status: ${d.status.toUpperCase()}
  Version: ${d.version}
  Data dir: ${d.data_dir}

TorrServer:
  Running: ${tsRunning}
  PID: ${d.torrserver.pid ?? 'N/A'}
  Port: ${d.torrserver.port ?? 'N/A'}
  Version: ${d.torrserver.version || 'Unknown'}
  Binary: ${d.torrserver.binary_path || 'Not found'}
  Error: ${d.torrserver.last_error || 'None'}

MPV:
  Available: ${mpvAvail}
  Path: ${d.mpv.path || 'Not configured'}
  Version: ${d.mpv.version || 'Unknown'}

Database:
  Status: ${dbOk}
  Path: ${d.db.path}
`;
}

test('sanitizeText strips sensitive tokens, api keys, and passwords', () => {
  const sensitive1 = 'Connection failed: https://user:supersecret123@torrserver.local:8090/view';
  assert.equal(
    sanitizeText(sensitive1),
    'Connection failed: https://user:***@torrserver.local:8090/view'
  );

  const sensitive2 = 'Torznab error: http://localhost:9696/api?apikey=12345abcdef&cat=2000';
  assert.equal(
    sanitizeText(sensitive2),
    'Torznab error: http://localhost:9696/api?apikey=***&cat=2000'
  );

  const sensitive3 = 'Auth error: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.token123';
  assert.equal(
    sanitizeText(sensitive3),
    'Auth error: Bearer ***'
  );

  const sensitive4 = 'Error in service: token=secret-tok-99 and password=mypassword!';
  assert.equal(
    sanitizeText(sensitive4),
    'Error in service: token=*** and password=***'
  );
});

test('getDisplayStatus simplifies technical details when debugMode is OFF', () => {
  // Debug OFF
  assert.equal(getDisplayStatus('Поиск метаданных в DHT сети (0/30)...', false), 'Поиск раздачи...');
  assert.equal(getDisplayStatus('Подключение к торрент-сети и пирам...', false), 'Подключение...');
  assert.equal(getDisplayStatus('Инициализация MPV ipc-сокета...', false), 'Буферизация...');
  assert.equal(getDisplayStatus('Буферизация чанка 14 из 100...', false), 'Буферизация...');

  // Debug ON retains technical details
  assert.equal(getDisplayStatus('Поиск метаданных в DHT сети (0/30)...', true), 'Поиск метаданных в DHT сети (0/30)...');
  assert.equal(getDisplayStatus('Инициализация MPV ipc-сокета...', true), 'Инициализация MPV ipc-сокета...');
});

test('buildReportText generates clean report for Debug OFF vs technical for Debug ON', () => {
  const mockDiagnostics = {
    status: 'healthy',
    version: '2.0.0',
    checked_at: '2026-10-30T12:00:00Z',
    data_dir: '/app/data',
    torrserver: {
      running: true,
      state: 'running',
      pid: 12345,
      port: 8090,
      version: '1.2.3',
      binary_path: '/usr/local/bin/torrserver',
      last_error: 'Failed to auth api_key=supersecretpass',
    },
    mpv: {
      available: true,
      state: 'running',
      path: '/usr/bin/mpv',
      version: '0.38.0',
      last_error: null,
    },
    db: {
      ok: true,
      path: '/app/data/cinema.db',
    },
  };

  const simpleReport = buildReportText(mockDiagnostics, false);
  // Debug OFF must NOT include PID, binary_path, db path, or raw secrets
  assert.equal(simpleReport.includes('12345'), false);
  assert.equal(simpleReport.includes('/usr/local/bin/torrserver'), false);
  assert.equal(simpleReport.includes('/app/data/cinema.db'), false);
  assert.equal(simpleReport.includes('supersecretpass'), false);
  assert.equal(simpleReport.includes('api_key=***'), true);
  assert.equal(simpleReport.includes('Статус служб Pirate Cinema'), true);

  const debugReport = buildReportText(mockDiagnostics, true);
  // Debug ON includes PID, binary path, db path
  assert.equal(debugReport.includes('12345'), true);
  assert.equal(debugReport.includes('/usr/local/bin/torrserver'), true);
  assert.equal(debugReport.includes('/app/data/cinema.db'), true);
  assert.equal(debugReport.includes('Pirate Cinema System Diagnostics'), true);
});
