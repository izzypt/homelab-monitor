import { Pipe, PipeTransform } from '@angular/core';

/** "3d 4h", "5h 12m", "42s": compact durations for uptime and downtime. */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return '—';
  const s = Math.max(0, Math.round(seconds));
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s % 60}s`;
  return `${s}s`;
}

/** "5 min ago", "in 2 days": relative to `now` (ms since epoch). */
export function formatRelative(value: string | null | undefined, now = Date.now()): string {
  if (!value) return '—';
  const diff = (new Date(value).getTime() - now) / 1000;
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ['day', 86400],
    ['hour', 3600],
    ['minute', 60],
  ];
  const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });
  for (const [unit, size] of units) {
    if (Math.abs(diff) >= size) return rtf.format(Math.round(diff / size), unit);
  }
  return Math.abs(diff) < 10 ? 'just now' : rtf.format(Math.round(diff), 'second');
}

@Pipe({ name: 'duration' })
export class DurationPipe implements PipeTransform {
  transform(seconds: number | null | undefined): string {
    return formatDuration(seconds);
  }
}

@Pipe({ name: 'relative' })
export class RelativePipe implements PipeTransform {
  transform(value: string | null | undefined): string {
    return formatRelative(value);
  }
}
