import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseCategories } from '../src/components/settings/useSettingsForm';
import { formatBytes } from '../src/components/settings/useAppUpdater';

test('parseCategories parses valid comma-separated category IDs', () => {
  const result = parseCategories('2000, 2010, 2020, 2030, 2040, 2045, 2050, 2060');
  assert.deepEqual(result, [2000, 2010, 2020, 2030, 2040, 2045, 2050, 2060]);
});

test('parseCategories ignores non-numeric tokens, extra whitespace and empty parts', () => {
  const result = parseCategories('  2000 , invalid, , 5000 , 6000, foo ');
  assert.deepEqual(result, [2000, 5000, 6000]);
});

test('parseCategories returns empty array for empty or non-numeric input', () => {
  assert.deepEqual(parseCategories(''), []);
  assert.deepEqual(parseCategories('   '), []);
  assert.deepEqual(parseCategories('abc, xyz'), []);
});

test('formatBytes handles zero, negative and missing values', () => {
  assert.equal(formatBytes(null), '0 МБ');
  assert.equal(formatBytes(undefined), '0 МБ');
  assert.equal(formatBytes(0), '0 МБ');
  assert.equal(formatBytes(-100), '0 МБ');
});

test('formatBytes correctly formats megabytes with one decimal digit', () => {
  assert.equal(formatBytes(1024 * 1024), '1.0 МБ');
  assert.equal(formatBytes(1024 * 1024 * 2.5), '2.5 МБ');
  assert.equal(formatBytes(1024 * 1024 * 100), '100.0 МБ');
});
