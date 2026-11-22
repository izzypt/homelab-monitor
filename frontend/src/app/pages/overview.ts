import { DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, resource } from '@angular/core';
import { MatCardModule } from '@angular/material/card';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { RouterLink } from '@angular/router';
import { Api } from '../api/api';
import { getSummary } from '../api/functions';
import { autoReload } from '../core/polling';
import { errorMessage } from '../shared/errors';
import { DurationPipe, RelativePipe } from '../shared/format';
import { Icon } from '../shared/icon';
import { StateChip } from '../shared/state-chip';

@Component({
  selector: 'app-overview-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    MatCardModule,
    MatProgressBarModule,
    DecimalPipe,
    DurationPipe,
    RelativePipe,
    StateChip,
    Icon,
  ],
  template: `
    <div class="page">
      <div class="page-header"><h1>Overview</h1></div>

      @if (summary.error()) {
        <p class="banner bad" role="alert">{{ message(summary.error()) }}</p>
      }
      @if (summary.value(); as s) {
        @if (s.network_outage) {
          <p class="banner bad" role="alert">
            <app-icon name="cloud_off" /> Local network outage: the Mac mini can't reach the
            internet. Monitor emails are paused until it recovers.
          </p>
        }

        <section class="grid tiles">
          <a class="tile-link" routerLink="/monitors">
            <mat-card appearance="outlined" class="tile">
              <span class="value"
                >{{ s.monitors.up }}/{{ s.monitors.total - s.monitors.paused }}</span
              >
              <span class="label">monitors up</span>
              @if (s.monitors.down) {
                <app-state-chip state="DOWN" [text]="s.monitors.down + ' down'" />
              }
            </mat-card>
          </a>
          <a class="tile-link" routerLink="/incidents">
            <mat-card appearance="outlined" class="tile">
              <span class="value">{{ s.open_incidents }}</span>
              <span class="label">open incidents</span>
            </mat-card>
          </a>
          <a class="tile-link" routerLink="/containers">
            <mat-card appearance="outlined" class="tile">
              <span class="value">{{ s.containers.running }}/{{ s.containers.total }}</span>
              <span class="label">containers running</span>
              @if (s.containers.unhealthy) {
                <app-state-chip state="unhealthy" [text]="s.containers.unhealthy + ' unhealthy'" />
              }
            </mat-card>
          </a>
        </section>

        <h2>Hosts</h2>
        @for (h of s.hosts; track h.id) {
          <mat-card appearance="outlined" class="host">
            <mat-card-header>
              <mat-card-title>
                <a [routerLink]="['/hosts', h.id]">{{ h.name }}</a>
                <app-state-chip [state]="h.status" />
              </mat-card-title>
              <mat-card-subtitle>
                {{ h.os_version ?? 'macOS' }} · last heartbeat {{ h.last_seen_at | relative }}
              </mat-card-subtitle>
            </mat-card-header>
            <mat-card-content>
              <dl class="facts">
                <div>
                  <dt>Uptime</dt>
                  <dd>{{ h.uptime_s | duration }}</dd>
                </div>
                <div>
                  <dt>Last boot</dt>
                  <dd>{{ h.current_boot_time | relative }}</dd>
                </div>
                <div>
                  <dt>Last shutdown</dt>
                  <dd>
                    @if (h.last_boot; as b) {
                      <app-state-chip [state]="b.kind" />
                      @if (b.downtime_s != null) {
                        <span class="muted"> down {{ b.downtime_s | duration }}</span>
                      }
                    } @else {
                      <span class="muted">none recorded</span>
                    }
                  </dd>
                </div>
              </dl>
              @if (h.latest; as hb) {
                <div class="meters">
                  @for (m of meters; track m.key) {
                    @let value = hb[m.key];
                    <div class="meter">
                      <span>{{ m.label }}</span>
                      <mat-progress-bar
                        mode="determinate"
                        [value]="value ?? 0"
                        [class.high]="(value ?? 0) >= 90"
                      />
                      <span class="mono">{{
                        value == null ? '—' : (value | number: '1.0-0') + '%'
                      }}</span>
                    </div>
                  }
                  <div class="meter">
                    <span>Load (1 min)</span>
                    <span></span>
                    <span class="mono">{{
                      hb.load_1m == null ? '—' : (hb.load_1m | number: '1.2-2')
                    }}</span>
                  </div>
                </div>
                <div class="daemons">
                  @for (d of daemonList(hb.daemons); track d.name) {
                    <app-state-chip [state]="d.ok ? 'up' : 'down'" [text]="d.name" />
                  }
                </div>
              }
            </mat-card-content>
          </mat-card>
        } @empty {
          <p class="muted">
            No host registered yet. Register one on the <a routerLink="/hosts">Hosts</a> page and
            install the agent.
          </p>
        }
        <p class="muted updated">Updated {{ s.generated_at | relative }} · refreshes every 30 s</p>
      } @else if (summary.isLoading()) {
        <mat-progress-bar mode="indeterminate" />
      }
    </div>
  `,
  styles: `
    .banner {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 12px 16px;
      border-radius: 12px;
      background: var(--mat-sys-error-container);
      color: var(--mat-sys-on-error-container);
    }
    .tile-link {
      text-decoration: none;
      color: inherit;
    }
    .tile {
      height: 100%;
      box-sizing: border-box;
      display: flex;
      flex-direction: column;
      gap: 4px;
      padding: 16px;
      text-decoration: none;
      color: inherit;
    }
    .value {
      font: var(--mat-sys-display-small);
    }
    .label {
      color: var(--mat-sys-on-surface-variant);
    }
    h2 {
      font: var(--mat-sys-title-large);
      margin: 24px 0 12px;
    }
    .host {
      margin-bottom: 16px;
    }
    mat-card-subtitle {
      font: var(--mat-sys-body-medium);
    }
    mat-card-title {
      display: flex;
      align-items: center;
      gap: 8px;
      a {
        color: inherit;
      }
    }
    .facts {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 12px;
      margin: 16px 0;
      dt {
        color: var(--mat-sys-on-surface-variant);
        font: var(--mat-sys-label-medium);
      }
      dd {
        margin: 4px 0 0;
        font: var(--mat-sys-title-medium);
      }
    }
    .meters {
      display: grid;
      gap: 8px;
    }
    .meter {
      display: grid;
      grid-template-columns: 110px 1fr 56px;
      align-items: center;
      gap: 12px;
      .mono {
        text-align: right;
      }
    }
    .high {
      --mat-progress-bar-active-indicator-color: var(--mat-sys-error);
    }
    .daemons {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 16px;
    }
    .updated {
      font: var(--mat-sys-body-small);
    }
  `,
})
export class OverviewPage {
  private readonly api = inject(Api);
  protected readonly summary = resource({ loader: () => this.api.invoke(getSummary) });
  protected readonly meters = [
    { key: 'disk_used_pct', label: 'Disk' },
    { key: 'mem_used_pct', label: 'Memory' },
  ] as const;
  protected readonly message = errorMessage;

  constructor() {
    autoReload(this.summary);
  }

  protected daemonList(daemons: Record<string, unknown>) {
    return Object.entries(daemons).map(([name, ok]) => ({ name, ok: ok === true }));
  }
}
