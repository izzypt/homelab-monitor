import { DatePipe } from '@angular/common';
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
import { MatDialog } from '@angular/material/dialog';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTableModule } from '@angular/material/table';
import { RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { Api } from '../api/api';
import { getHost, listBoots, listHeartbeats, rotateToken } from '../api/functions';
import { fetchPages } from '../core/paging';
import { autoReload } from '../core/polling';
import { ConfirmData, ConfirmDialog } from '../shared/confirm-dialog';
import { errorMessage } from '../shared/errors';
import { DurationPipe, RelativePipe } from '../shared/format';
import { Icon } from '../shared/icon';
import { LineChart, Series } from '../shared/line-chart';
import { StateChip } from '../shared/state-chip';
import { HostTokenDialog } from './host-token-dialog';

const DAY_MS = 86_400_000;

@Component({
  selector: 'app-host-detail-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    MatButtonModule,
    MatTableModule,
    MatProgressBarModule,
    DatePipe,
    DurationPipe,
    RelativePipe,
    StateChip,
    LineChart,
    Icon,
  ],
  template: `
    <div class="page">
      <div class="page-header">
        <a mat-icon-button routerLink="/hosts" aria-label="Back"><app-icon name="arrow_back" /></a>
        <h1>{{ host.value()?.name ?? 'Host' }}</h1>
        @if (host.value(); as h) {
          <app-state-chip [state]="h.status" />
          <button mat-stroked-button (click)="rotate()">
            <app-icon name="key" /> Rotate token
          </button>
        }
      </div>
      @if (host.error()) {
        <p class="error" role="alert">{{ message(host.error()) }}</p>
      }
      @if (host.value(); as h) {
        <p class="muted">
          {{ h.os_version ?? 'Unknown OS' }} · agent {{ h.agent_version ?? '—' }} · booted
          {{ h.current_boot_time | relative }} · last heartbeat {{ h.last_seen_at | relative }}
        </p>
      }

      <h2>Last 24 h</h2>
      @if (heartbeats.value(); as hb) {
        @if (hb.length) {
          <app-line-chart [series]="usage()" unit="%" [max]="100" />
          <app-line-chart [series]="load()" [height]="180" />
        } @else {
          <p class="muted">No heartbeats in the last 24 hours.</p>
        }
      } @else if (heartbeats.isLoading()) {
        <mat-progress-bar mode="indeterminate" />
      }

      <h2>Boots and shutdowns</h2>
      <div class="table-wrap">
        <table mat-table [dataSource]="boots.value() ?? []">
          <ng-container matColumnDef="boot">
            <th mat-header-cell *matHeaderCellDef>Booted</th>
            <td mat-cell *matCellDef="let b">{{ b.boot_time | date: 'medium' }}</td>
          </ng-container>
          <ng-container matColumnDef="kind">
            <th mat-header-cell *matHeaderCellDef>Previous shutdown</th>
            <td mat-cell *matCellDef="let b"><app-state-chip [state]="b.kind" /></td>
          </ng-container>
          <ng-container matColumnDef="seen">
            <th mat-header-cell *matHeaderCellDef>Last seen before</th>
            <td mat-cell *matCellDef="let b">
              {{ b.last_seen_before ? (b.last_seen_before | date: 'medium') : '—' }}
            </td>
          </ng-container>
          <ng-container matColumnDef="down">
            <th mat-header-cell *matHeaderCellDef>Downtime</th>
            <td mat-cell *matCellDef="let b">{{ b.downtime_s | duration }}</td>
          </ng-container>
          <tr mat-header-row *matHeaderRowDef="bootColumns"></tr>
          <tr mat-row *matRowDef="let row; columns: bootColumns"></tr>
          <tr class="mat-row" *matNoDataRow>
            <td class="mat-cell muted empty" colspan="4">No reboots recorded yet.</td>
          </tr>
        </table>
      </div>
    </div>
  `,
  styles: `
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
export class HostDetailPage {
  private readonly api = inject(Api);
  private readonly dialog = inject(MatDialog);
  private readonly snack = inject(MatSnackBar);
  readonly id = input.required({ transform: numberAttribute });
  protected readonly message = errorMessage;
  protected readonly bootColumns = ['boot', 'kind', 'seen', 'down'];

  protected readonly host = resource({
    params: () => ({ host_id: this.id() }),
    loader: ({ params }) => this.api.invoke(getHost, params),
  });
  protected readonly boots = resource({
    params: () => ({ host_id: this.id(), limit: 50 }),
    loader: ({ params }) => this.api.invoke(listBoots, params),
  });
  protected readonly heartbeats = resource({
    params: () => this.id(),
    loader: ({ params: id }) => {
      const from = new Date(Date.now() - DAY_MS).toISOString();
      return fetchPages((cursor) =>
        this.api.invoke(listHeartbeats, { host_id: id, from, cursor, limit: 1000 }),
      );
    },
  });

  protected readonly usage = computed<Series[]>(() => {
    const hb = this.heartbeats.value() ?? [];
    return [
      { name: 'Disk', points: hb.map((h) => [h.collected_at, h.disk_used_pct]) },
      { name: 'Memory', points: hb.map((h) => [h.collected_at, h.mem_used_pct]) },
    ];
  });
  protected readonly load = computed<Series[]>(() => [
    {
      name: 'Load (1 min)',
      points: (this.heartbeats.value() ?? []).map((h) => [h.collected_at, h.load_1m]),
    },
  ]);

  constructor() {
    autoReload(this.host, 60_000);
    autoReload(this.heartbeats, 60_000);
  }

  async rotate(): Promise<void> {
    const data: ConfirmData = {
      title: 'Rotate the agent token?',
      message: 'The current token stops working at once. Update the agent config right after.',
      action: 'Rotate',
    };
    if (!(await firstValueFrom(this.dialog.open(ConfirmDialog, { data }).afterClosed()))) return;
    try {
      const host = await this.api.invoke(rotateToken, { host_id: this.id() });
      this.dialog.open(HostTokenDialog, { data: host, disableClose: true, width: '520px' });
    } catch (e) {
      this.snack.open(errorMessage(e), 'Dismiss');
    }
  }
}
