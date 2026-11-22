import { DatePipe, DecimalPipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  numberAttribute,
  resource,
} from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTableModule } from '@angular/material/table';
import { RouterLink } from '@angular/router';
import { Api } from '../api/api';
import { getMonitor, listIncidents, listResults, uptime } from '../api/functions';
import { fetchPages } from '../core/paging';
import { autoReload } from '../core/polling';
import { errorMessage } from '../shared/errors';
import { RelativePipe } from '../shared/format';
import { Icon } from '../shared/icon';
import { LineChart, Series } from '../shared/line-chart';
import { StateChip } from '../shared/state-chip';

const DAY_MS = 86_400_000;

@Component({
  selector: 'app-monitor-detail-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    MatCardModule,
    MatButtonModule,
    MatTableModule,
    MatProgressBarModule,
    DatePipe,
    DecimalPipe,
    RelativePipe,
    StateChip,
    LineChart,
    Icon,
  ],
  template: `
    <div class="page">
      <div class="page-header">
        <a mat-icon-button routerLink="/monitors" aria-label="Back"
          ><app-icon name="arrow_back"
        /></a>
        @if (monitor.value(); as m) {
          <h1>{{ m.name }}</h1>
          <app-state-chip [state]="m.enabled ? m.state : 'paused'" />
        } @else {
          <h1>Monitor</h1>
        }
      </div>
      @if (monitor.error()) {
        <p class="error" role="alert">{{ message(monitor.error()) }}</p>
      }
      @if (monitor.value(); as m) {
        <p class="muted">
          {{ m.type.toUpperCase() }} <span class="mono">{{ m.target }}</span> · every
          {{ m.interval_s }} s · last check {{ m.last_checked_at | relative }}
          @if (m.tls_expires_at) {
            · TLS certificate expires {{ m.tls_expires_at | relative }}
          }
        </p>
      }

      <section class="grid">
        @for (u of uptimes.value() ?? []; track u.days) {
          <mat-card appearance="outlined" class="tile">
            <span class="value">{{
              u.uptime_pct == null ? '—' : (u.uptime_pct | number: '1.0-2') + '%'
            }}</span>
            <span class="muted">uptime, last {{ u.days === 1 ? '24 h' : u.days + ' days' }}</span>
            <span class="muted small">
              {{ u.checks_total }} checks · {{ u.checks_failed }} failed
              @if (u.avg_latency_ms != null) {
                · avg {{ u.avg_latency_ms | number: '1.0-0' }} ms
              }
            </span>
          </mat-card>
        }
      </section>

      <h2>Response time, last 24 h</h2>
      @if (results.value(); as r) {
        @if (r.length) {
          <app-line-chart [series]="latency()" unit=" ms" />
        } @else {
          <p class="muted">No checks in the last 24 hours.</p>
        }
      } @else if (results.isLoading()) {
        <mat-progress-bar mode="indeterminate" />
      }

      <h2>Recent failures</h2>
      <div class="table-wrap">
        <table mat-table [dataSource]="failures()">
          <ng-container matColumnDef="at">
            <th mat-header-cell *matHeaderCellDef>When</th>
            <td mat-cell *matCellDef="let r">{{ r.checked_at | date: 'short' }}</td>
          </ng-container>
          <ng-container matColumnDef="error">
            <th mat-header-cell *matHeaderCellDef>Error</th>
            <td mat-cell *matCellDef="let r" class="mono">
              {{ r.error ?? (r.status_code ? 'HTTP ' + r.status_code : 'failed') }}
            </td>
          </ng-container>
          <tr mat-header-row *matHeaderRowDef="['at', 'error']"></tr>
          <tr mat-row *matRowDef="let row; columns: ['at', 'error']"></tr>
          <tr class="mat-row" *matNoDataRow>
            <td class="mat-cell muted empty" colspan="2">No failed checks in the last 24 hours.</td>
          </tr>
        </table>
      </div>

      <h2>Incidents</h2>
      <div class="table-wrap">
        <table mat-table [dataSource]="incidents.value()?.items ?? []">
          <ng-container matColumnDef="kind">
            <th mat-header-cell *matHeaderCellDef>Kind</th>
            <td mat-cell *matCellDef="let i">
              <app-state-chip [state]="i.ended_at ? 'closed' : 'open'" [text]="i.kind" />
            </td>
          </ng-container>
          <ng-container matColumnDef="started">
            <th mat-header-cell *matHeaderCellDef>Started</th>
            <td mat-cell *matCellDef="let i">{{ i.started_at | date: 'short' }}</td>
          </ng-container>
          <ng-container matColumnDef="ended">
            <th mat-header-cell *matHeaderCellDef>Ended</th>
            <td mat-cell *matCellDef="let i">
              {{ i.ended_at ? (i.ended_at | date: 'short') : 'ongoing' }}
            </td>
          </ng-container>
          <ng-container matColumnDef="cause">
            <th mat-header-cell *matHeaderCellDef>Cause</th>
            <td mat-cell *matCellDef="let i" class="mono">{{ i.cause }}</td>
          </ng-container>
          <tr mat-header-row *matHeaderRowDef="incidentColumns"></tr>
          <tr mat-row *matRowDef="let row; columns: incidentColumns"></tr>
          <tr class="mat-row" *matNoDataRow>
            <td class="mat-cell muted empty" colspan="4">No incidents.</td>
          </tr>
        </table>
      </div>
    </div>
  `,
  styles: `
    .tile {
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .value {
      font: var(--mat-sys-headline-medium);
    }
    .small {
      font: var(--mat-sys-body-small);
    }
    h2 {
      font: var(--mat-sys-title-large);
      margin: 24px 0 12px;
    }
    .empty {
      padding: 16px;
    }
    .error {
      color: var(--mat-sys-error);
    }
  `,
})
export class MonitorDetailPage {
  private readonly api = inject(Api);
  readonly id = input.required({ transform: numberAttribute });
  protected readonly message = errorMessage;
  protected readonly incidentColumns = ['kind', 'started', 'ended', 'cause'];

  protected readonly monitor = resource({
    params: () => ({ monitor_id: this.id() }),
    loader: ({ params }) => this.api.invoke(getMonitor, params),
  });
  protected readonly uptimes = resource({
    params: () => this.id(),
    loader: ({ params: id }) =>
      Promise.all([1, 7, 30].map((days) => this.api.invoke(uptime, { monitor_id: id, days }))),
  });
  protected readonly results = resource({
    params: () => this.id(),
    loader: ({ params: id }) => {
      const from = new Date(Date.now() - DAY_MS).toISOString();
      return fetchPages((cursor) =>
        this.api.invoke(listResults, { monitor_id: id, from, cursor, limit: 500 }),
      ).then((items) => items.sort((a, b) => a.checked_at.localeCompare(b.checked_at)));
    },
  });
  protected readonly incidents = resource({
    params: () => this.id(),
    loader: ({ params: id }) => this.api.invoke(listIncidents, { monitor_id: id, limit: 20 }),
  });

  protected readonly latency = computed<Series[]>(() => [
    {
      name: 'Latency',
      points: (this.results.value() ?? []).map((r) => [
        r.checked_at,
        r.ok ? (r.latency_ms ?? null) : null,
      ]),
    },
  ]);
  protected readonly failures = computed(() =>
    (this.results.value() ?? [])
      .filter((r) => !r.ok)
      .reverse()
      .slice(0, 20),
  );

  constructor() {
    autoReload(this.monitor, 60_000);
    autoReload(this.results, 60_000);
  }
}
