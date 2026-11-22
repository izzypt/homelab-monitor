import { formatDuration, formatRelative } from './format';

describe('formatDuration', () => {
  it.each([
    [null, '—'],
    [42, '42s'],
    [125, '2m 5s'],
    [3 * 3600 + 120, '3h 2m'],
    [2 * 86400 + 5 * 3600, '2d 5h'],
  ])('%s -> %s', (seconds, expected) => {
    expect(formatDuration(seconds)).toBe(expected);
  });
});

describe('formatRelative', () => {
  const now = Date.parse('2026-11-22T12:00:00Z');
  it('handles past, future and missing values', () => {
    expect(formatRelative(null, now)).toBe('—');
    expect(formatRelative('2026-11-22T11:59:58Z', now)).toBe('just now');
    expect(formatRelative('2026-11-22T11:55:00Z', now)).toBe('5 minutes ago');
    expect(formatRelative('2026-11-20T12:00:00Z', now)).toBe('2 days ago');
    expect(formatRelative('2026-12-02T12:00:00Z', now)).toBe('in 10 days');
  });
});
