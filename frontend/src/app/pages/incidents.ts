import { DatePipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  resource,
  signal,
} from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatTableModule } from '@angular/material/table';
import { RouterLink } from '@angular/router';
import { Api } from '../api/api';
import { listIncidents, listMonitors } from '../api/functions';
import { IncidentOut } from '../api/models';
import { errorMessage } from '../shared/errors';
import { DurationPipe } from '../shared/format';
import { StateChip } from '../shared/state-chip';

type Status = 'open' | 'closed' | 'all';

const KIND_LABELS: Record<string, string> = {
  down: 'Down',
  tls_expiring: 'TLS expiring',
  stale: 'Host silent',
  disk_high: 'Disk > 90%',
  network_outage: 'Network outage',
};

@Component({
  selector: 'app-incidents-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    MatTableModule,
    MatButtonModule,
    MatButtonToggleModule,
    DatePipe,
    DurationPipe,
    StateChip,
  ],
  template: `
    <div class="page">
      <div class="page-header">
        <h1>Incidents</h1>
        <mat-button-toggle-group
          [value]="status()"
          (change)="setStatus($event.value)"
          aria-label="Filter"
        >
          <mat-button-toggle value="open">Open</mat-button-toggle>
          <mat-button-toggle value="closed">Closed</mat-button-toggle>
          <mat-button-toggle value="all">All</mat-button-toggle>
        </mat-button-toggle-group>
      </div>
      @if (error()) {
        <p class="error" role="alert">{{ error() }}</p>
      }
      <div class="table-wrap">
        <table mat-table [dataSource]="items()">
          <ng-container matColumnDef="kind">
            <th mat-header-cell *matHeaderCellDef>Kind</th>
            <td mat-cell *matCellDef="let i">
              <app-state-chip [state]="i.ended_at ? 'closed' : 'open'" [text]="label(i.kind)" />
            </td>
          </ng-container>
          <ng-container matColumnDef="subject">
            <th mat-header-cell *matHeaderCellDef>Subject</th>
            <td mat-cell *matCellDef="let i">
              @if (i.monitor_id) {
                <a [routerLink]="['/monitors', i.monitor_id]">{{ monitorName(i.monitor_id) }}</a>
              } @else if (i.host_id) {
                <a [routerLink]="['/hosts', i.host_id]">Host</a>
              }
            </td>
          </ng-container>
          <ng-container matColumnDef="started">
            <th mat-header-cell *matHeaderCellDef>Started</th>
            <td mat-cell *matCellDef="let i">{{ i.started_at | date: 'short' }}</td>
          </ng-container>
          <ng-container matColumnDef="duration">
            <th mat-header-cell *matHeaderCellDef>Duration</th>
            <td mat-cell *matCellDef="let i">
              {{ duration(i) | duration }}{{ i.ended_at ? '' : ' (ongoing)' }}
            </td>
          </ng-container>
          <ng-container matColumnDef="cause">
            <th mat-header-cell *matHeaderCellDef>Cause</th>
            <td mat-cell *matCellDef="let i" class="mono">{{ i.cause }}</td>
          </ng-container>
          <tr mat-header-row *matHeaderRowDef="columns"></tr>
          <tr mat-row *matRowDef="let row; columns: columns"></tr>
          <tr class="mat-row" *matNoDataRow>
            <td class="mat-cell muted empty" [attr.colspan]="columns.length">
              {{ loading() ? 'Loading…' : 'No incidents.' }}
            </td>
          </tr>
        </table>
      </div>
      @if (cursor() != null) {
        <div class="more">
          <button mat-stroked-button (click)="load()" [disabled]="loading()">Load more</button>
        </div>
      }
    </div>
  `,
  styles: `
    .empty {
      padding: 16px;
    }
    .more {
      display: flex;
      justify-content: center;
      margin: 16px;
    }
    .error {
      color: var(--mat-sys-error);
    }
  `,
})
export class IncidentsPage {
  private readonly api = inject(Api);
  protected readonly columns = ['kind', 'subject', 'started', 'duration', 'cause'];
  protected readonly status = signal<Status>('open');
  protected readonly items = signal<IncidentOut[]>([]);
  protected readonly cursor = signal<number | null>(null);
  protected readonly loading = signal(false);
  protected readonly error = signal<string | null>(null);

  private readonly monitors = resource({ loader: () => this.api.invoke(listMonitors) });
  private readonly names = computed(
    () => new Map((this.monitors.value() ?? []).map((m) => [m.id, m.name])),
  );

  constructor() {
    void this.load(true);
  }

  protected setStatus(status: Status): void {
    this.status.set(status);
    void this.load(true);
  }

  protected async load(reset = false): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      const page = await this.api.invoke(listIncidents, {
        status: this.status(),
        cursor: reset ? undefined : (this.cursor() ?? undefined),
        limit: 50,
      });
      this.items.update((items) => (reset ? page.items : [...items, ...page.items]));
      this.cursor.set(page.next_cursor ?? null);
    } catch (e) {
      this.error.set(errorMessage(e));
    } finally {
      this.loading.set(false);
    }
  }

  protected label(kind: string): string {
    return KIND_LABELS[kind] ?? kind;
  }

  protected monitorName(id: number): string {
    return this.names().get(id) ?? `Monitor ${id}`;
  }

  protected duration(i: IncidentOut): number {
    const end = i.ended_at ? new Date(i.ended_at).getTime() : Date.now();
    return (end - new Date(i.started_at).getTime()) / 1000;
  }
}
