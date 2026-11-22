import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

type Tone = 'good' | 'bad' | 'warn' | 'neutral';

const TONES: Record<string, Tone> = {
  up: 'good',
  running: 'good',
  healthy: 'good',
  clean: 'good',
  closed: 'good',
  down: 'bad',
  unhealthy: 'bad',
  dead: 'bad',
  unexpected: 'bad',
  open: 'bad',
  stale: 'warn',
  restarting: 'warn',
  starting: 'warn',
  paused: 'neutral',
  exited: 'neutral',
  removed: 'neutral',
};

/** Small coloured status label: UP, DOWN, running (healthy), ... */
@Component({
  selector: 'app-state-chip',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<span class="chip" [class]="tone()">{{ label() }}</span>`,
  styles: `
    .chip {
      display: inline-block;
      padding: 2px 10px;
      border-radius: 12px;
      font: var(--mat-sys-label-medium);
      white-space: nowrap;
      background: var(--mat-sys-surface-container-high);
      color: var(--mat-sys-on-surface-variant);
    }
    .good {
      background: light-dark(#d7f5dd, #0f3d1c);
      color: light-dark(#0b5d24, #9be7ad);
    }
    .bad {
      background: var(--mat-sys-error-container);
      color: var(--mat-sys-on-error-container);
    }
    .warn {
      background: light-dark(#fff0c2, #4a3a00);
      color: light-dark(#6b4f00, #ffdf80);
    }
  `,
})
export class StateChip {
  readonly state = input.required<string | null | undefined>();
  readonly text = input<string>();
  protected readonly label = computed(() => this.text() ?? this.state() ?? 'unknown');
  protected readonly tone = computed<Tone>(() => {
    const key = (this.state() ?? '').toLowerCase().split(' ')[0];
    const health = /\((\w+)\)/.exec(this.state() ?? '')?.[1];
    return TONES[health ?? ''] ?? TONES[key] ?? 'neutral';
  });
}
