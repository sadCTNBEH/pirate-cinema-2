import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  downloadBackup,
  restoreBackup,
  defaultTranslate,
  BackupRestoreDeps,
} from '../src/services/backupRestore';

test('native pywebview backup: success reports saved path', async () => {
  const deps: BackupRestoreDeps = {
    window: {
      pywebview: {
        api: {
          save_backup: async () => ({
            saved: true,
            path: 'C:/Users/test/pirate_backup.zip',
          }),
        },
      },
    },
  };

  const hint = await downloadBackup(defaultTranslate, deps);
  assert.equal(hint.isError, undefined);
  assert.equal(hint.text, 'Бэкап сохранён: C:/Users/test/pirate_backup.zip');
});

test('native pywebview backup: user cancellation is reported without error flag', async () => {
  const deps: BackupRestoreDeps = {
    window: {
      pywebview: {
        api: {
          save_backup: async () => ({
            saved: false,
            cancelled: true,
          }),
        },
      },
    },
  };

  const hint = await downloadBackup(defaultTranslate, deps);
  assert.equal(hint.isError, undefined);
  assert.equal(hint.text, 'Сохранение бэкапа отменено');
});

test('native pywebview backup: save failure returns error hint', async () => {
  const deps: BackupRestoreDeps = {
    window: {
      pywebview: {
        api: {
          save_backup: async () => ({
            saved: false,
            error: 'Недостаточно места на диске',
          }),
        },
      },
    },
  };

  const hint = await downloadBackup(defaultTranslate, deps);
  assert.equal(hint.isError, true);
  assert.equal(hint.text, 'Недостаточно места на диске');
});

test('native pywebview backup: unexpected exception returns error hint', async () => {
  const deps: BackupRestoreDeps = {
    window: {
      pywebview: {
        api: {
          save_backup: async () => {
            throw new Error('IPC connection closed');
          },
        },
      },
    },
  };

  const hint = await downloadBackup(defaultTranslate, deps);
  assert.equal(hint.isError, true);
  assert.equal(hint.text, 'IPC connection closed');
});

test('browser fallback backup: downloads zip via blob url and revokes it', async () => {
  let createdBlob: Blob | null = null;
  let clicked = false;
  let removed = false;
  let revokedUrl = '';

  const mockBlob = new Blob(['mock-zip-content'], { type: 'application/zip' });
  const mockLink = {
    href: '',
    download: '',
    click: () => {
      clicked = true;
    },
    remove: () => {
      removed = true;
    },
  };

  const deps: BackupRestoreDeps = {
    api: {
      downloadBackup: async () => mockBlob,
      restoreBackup: async () => {},
    },
    document: {
      createElement: (tag: string) => {
        assert.equal(tag, 'a');
        return mockLink;
      },
      body: {
        appendChild: (node: unknown) => {
          assert.equal(node, mockLink);
          return node;
        },
      },
    },
    url: {
      createObjectURL: (blob: Blob) => {
        createdBlob = blob;
        return 'blob:http://localhost/mock-uuid';
      },
      revokeObjectURL: (url: string) => {
        revokedUrl = url;
      },
    },
    window: {
      setTimeout: (handler: () => void) => {
        handler();
        return 1;
      },
    },
  };

  const hint = await downloadBackup(defaultTranslate, deps);

  assert.equal(hint.isError, undefined);
  assert.equal(hint.text, 'Бэкап сохранён: downloads');
  assert.equal(createdBlob, mockBlob);
  assert.equal(mockLink.href, 'blob:http://localhost/mock-uuid');
  assert.equal(mockLink.download, 'pirate_cinema_backup.zip');
  assert.equal(clicked, true);
  assert.equal(removed, true);
  assert.equal(revokedUrl, 'blob:http://localhost/mock-uuid');
});

test('browser fallback backup: uses fallback string if translation key is missing', async () => {
  const mockLink = {
    href: '',
    download: '',
    click: () => {},
    remove: () => {},
  };

  const deps: BackupRestoreDeps = {
    api: {
      downloadBackup: async () => new Blob(['data']),
      restoreBackup: async () => {},
    },
    document: {
      createElement: () => mockLink,
      body: { appendChild: (n) => n },
    },
    url: {
      createObjectURL: () => 'blob:mock',
      revokeObjectURL: () => {},
    },
  };

  const customTranslate = (key: string) => (key === 'backup_saved' ? '' : key);
  const hint = await downloadBackup(customTranslate, deps);
  assert.equal(hint.isError, undefined);
  assert.equal(hint.text, 'Бэкап успешно скачан');
});

test('browser fallback backup: api failure returns error hint', async () => {
  const deps: BackupRestoreDeps = {
    api: {
      downloadBackup: async () => {
        throw new Error('500 Internal Server Error');
      },
      restoreBackup: async () => {},
    },
    document: {
      createElement: () => ({ href: '', download: '', click: () => {} }),
      body: { appendChild: (n) => n },
    },
    url: {
      createObjectURL: () => 'blob:mock',
      revokeObjectURL: () => {},
    },
  };

  const hint = await downloadBackup(defaultTranslate, deps);
  assert.equal(hint.isError, true);
  assert.equal(hint.text, '500 Internal Server Error');
});

test('restore backup: no file returns cancelled without calling confirm or api', async () => {
  let confirmCalled = false;
  let restoreCalled = false;

  const deps: BackupRestoreDeps = {
    api: {
      downloadBackup: async () => new Blob(),
      restoreBackup: async () => {
        restoreCalled = true;
      },
    },
    window: {
      confirm: () => {
        confirmCalled = true;
        return true;
      },
    },
  };

  const result = await restoreBackup(null, defaultTranslate, deps);
  assert.equal(result.success, false);
  assert.equal(result.cancelled, true);
  assert.equal(confirmCalled, false);
  assert.equal(restoreCalled, false);
});

test('restore backup: user cancellation in confirmation dialog stops restore', async () => {
  let restoreCalled = false;
  let confirmMessage = '';

  const deps: BackupRestoreDeps = {
    api: {
      downloadBackup: async () => new Blob(),
      restoreBackup: async () => {
        restoreCalled = true;
      },
    },
    window: {
      confirm: (msg?: string) => {
        confirmMessage = msg || '';
        return false;
      },
    },
  };

  const dummyFile = new File(['mock'], 'backup.zip', { type: 'application/zip' });
  const result = await restoreBackup(dummyFile, defaultTranslate, deps);

  assert.equal(result.success, false);
  assert.equal(result.cancelled, true);
  assert.equal(restoreCalled, false);
  assert.equal(confirmMessage, 'Восстановить конфигурацию из архива?');
});

test('restore backup: confirmed restore calls api, alerts success and reloads', async () => {
  let restoredFile: File | null = null;
  let alertMessage = '';
  let reloaded = false;

  const dummyFile = new File(['zip-data'], 'backup.zip', { type: 'application/zip' });
  const deps: BackupRestoreDeps = {
    api: {
      downloadBackup: async () => new Blob(),
      restoreBackup: async (file: File) => {
        restoredFile = file;
      },
    },
    window: {
      confirm: () => true,
      alert: (msg?: string) => {
        alertMessage = msg || '';
      },
      location: {
        reload: () => {
          reloaded = true;
        },
      },
    },
  };

  const result = await restoreBackup(dummyFile, defaultTranslate, deps);

  assert.equal(result.success, true);
  assert.equal(restoredFile, dummyFile);
  assert.equal(alertMessage, 'Данные восстановлены');
  assert.equal(reloaded, true);
});

test('restore backup: api error alerts message and does not reload', async () => {
  let alertMessage = '';
  let reloaded = false;

  const dummyFile = new File(['corrupted'], 'backup.zip', { type: 'application/zip' });
  const deps: BackupRestoreDeps = {
    api: {
      downloadBackup: async () => new Blob(),
      restoreBackup: async () => {
        throw new Error('Архив поврежден или имеет неверный формат');
      },
    },
    window: {
      confirm: () => true,
      alert: (msg?: string) => {
        alertMessage = msg || '';
      },
      location: {
        reload: () => {
          reloaded = true;
        },
      },
    },
  };

  const result = await restoreBackup(dummyFile, defaultTranslate, deps);

  assert.equal(result.success, false);
  assert.equal(result.error, 'Архив поврежден или имеет неверный формат');
  assert.equal(alertMessage, 'Архив поврежден или имеет неверный формат');
  assert.equal(reloaded, false);
});

test('restore backup: formats error with custom i18n restore_error template', async () => {
  let alertMessage = '';

  const dummyFile = new File(['corrupted'], 'backup.zip', { type: 'application/zip' });
  const deps: BackupRestoreDeps = {
    api: {
      downloadBackup: async () => new Blob(),
      restoreBackup: async () => {
        throw new Error('Некорректная база данных');
      },
    },
    window: {
      confirm: () => true,
      alert: (msg?: string) => {
        alertMessage = msg || '';
      },
    },
  };

  const customTranslate = (key: string, opts?: Record<string, string | number>) => {
    if (key === 'restore_error') return `Ошибка при восстановлении: ${opts?.error}`;
    return key;
  };

  const result = await restoreBackup(dummyFile, customTranslate, deps);
  assert.equal(result.success, false);
  assert.equal(alertMessage, 'Ошибка при восстановлении: Некорректная база данных');
});
