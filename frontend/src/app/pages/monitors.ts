import { ChangeDetectionStrategy, Component, inject, resource } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTableModule } from '@angular/material/table';
import { MatTooltipModule } from '@angular/material/tooltip';
import { RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { Api } from '../api/api';
import { checkNow, deleteMonitor, listMonitors, updateMonitor } from '../api/functions';
import { MonitorOut } from '../api/models';
import { autoReload } from '../core/polling';
import { ConfirmData, ConfirmDialog } from '../shared/confirm-dialog';
import { errorMessage } from '../shared/errors';
import { RelativePipe } from '../shared/format';
import { Icon } from '../shared/icon';
import { StateChip } from '../shared/state-chip';
import { MonitorDialog } from './monitor-dialog';

@Component({
  selector: 'app-monitors-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    MatTableModule,
    MatButtonModule,
    MatTooltipModule,
    MatProgressBarModule,
    RelativePipe,
    StateChip,
    Icon,
  ],
  template: `
    <div class="page">
      <div class="page-header">
        <h1>Monitors</h1>
        <button mat-flat-button (click)="edit(null)"><app-icon name="add" /> New monitor</button>
      </div>
      @if (monitors.isLoading() && !monitors.hasValue()) {
        <mat-progress-bar mode="indeterminate" />
      }
      @if (monitors.error()) {
        <p class="error" role="alert">{{ message(monitors.error()) }}</p>
      }
      @if (monitors.hasValue()) {
        <div class="table-wrap">
          <table mat-table [dataSource]="monitors.value()">
            <ng-container matColumnDef="state">
              <th mat-header-cell *matHeaderCellDef>State</th>
              <td mat-cell *matCellDef="let m">
                <app-state-chip [state]="m.enabled ? m.state : 'paused'" />
              </td>
            </ng-container>
            <ng-container matColumnDef="name">
              <th mat-header-cell *matHeaderCellDef>Name</th>
              <td mat-cell *matCellDef="let m">
                <a [routerLink]="['/monitors', m.id]">{{ m.name }}</a>
              </td>
            </ng-container>
            <ng-container matColumnDef="target">
              <th mat-header-cell *matHeaderCellDef>Target</th>
              <td mat-cell *matCellDef="let m">
                <span class="muted">{{ m.type.toUpperCase() }}</span>
                <span class="mono"> {{ m.target }}</span>
              </td>
            </ng-container>
            <ng-container matColumnDef="checked">
              <th mat-header-cell *matHeaderCellDef>Last check</th>
              <td mat-cell *matCellDef="let m">{{ m.last_checked_at | relative }}</td>
            </ng-container>
            <ng-container matColumnDef="tls">
              <th mat-header-cell *matHeaderCellDef>TLS expires</th>
              <td mat-cell *matCellDef="let m">{{ m.tls_expires_at | relative }}</td>
            </ng-container>
            <ng-container matColumnDef="actions">
              <th mat-header-cell *matHeaderCellDef></th>
              <td mat-cell *matCellDef="let m" class="actions">
                <button
                  mat-icon-button
                  matTooltip="Check now"
                  aria-label="Check now"
                  (click)="check(m)"
                >
                  <app-icon name="refresh" />
                </button>
                <button
                  mat-icon-button
                  [matTooltip]="m.enabled ? 'Pause' : 'Resume'"
                  [attr.aria-label]="m.enabled ? 'Pause' : 'Resume'"
                  (click)="toggle(m)"
                >
                  <app-icon [name]="m.enabled ? 'pause' : 'play_arrow'" />
                </button>
                <button mat-icon-button matTooltip="Edit" aria-label="Edit" (click)="edit(m)">
                  <app-icon name="edit" />
                </button>
                <button mat-icon-button matTooltip="Delete" aria-label="Delete" (click)="remove(m)">
                  <app-icon name="delete" />
                </button>
              </td>
            </ng-container>
            <tr mat-header-row *matHeaderRowDef="columns"></tr>
            <tr mat-row *matRowDef="let row; columns: columns"></tr>
            <tr class="mat-row" *matNoDataRow>
              <td class="mat-cell empty muted" [attr.colspan]="columns.length">
                No monitors yet. Add your first URL, DNS name or TCP port.
              </td>
            </tr>
          </table>
        </div>
      }
    </div>
  `,
  styles: `
    .actions {
      white-space: nowrap;
      text-align: right;
    }
    .empty {
      padding: 24px 16px;
    }
    .error {
      color: var(--mat-sys-error);
    }
  `,
})
export class MonitorsPage {
  private readonly api = inject(Api);
  private readonly dialog = inject(MatDialog);
  private readonly snack = inject(MatSnackBar);
  protected readonly columns = ['state', 'name', 'target', 'checked', 'tls', 'actions'];
  protected readonly monitors = resource({ loader: () => this.api.invoke(listMonitors) });
  protected readonly message = errorMessage;

  constructor() {
    autoReload(this.monitors);
  }

  async edit(monitor: MonitorOut | null): Promise<void> {
    const ref = this.dialog.open(MonitorDialog, { data: monitor, width: '560px' });
    if (await firstValueFrom(ref.afterClosed())) this.monitors.reload();
  }

  async toggle(m: MonitorOut): Promise<void> {
    await this.run(
      () => this.api.invoke(updateMonitor, { monitor_id: m.id, body: { enabled: !m.enabled } }),
      m.enabled ? `Paused ${m.name}` : `Resumed ${m.name}`,
    );
  }

  async check(m: MonitorOut): Promise<void> {
    await this.run(() => this.api.invoke(checkNow, { monitor_id: m.id }), `Checking ${m.name}…`);
  }

  async remove(m: MonitorOut): Promise<void> {
    const data: ConfirmData = {
      title: `Delete ${m.name}?`,
      message: 'Its results and incidents are deleted too. Pause it instead to keep history.',
      action: 'Delete',
    };
    const ok = await firstValueFrom(this.dialog.open(ConfirmDialog, { data }).afterClosed());
    if (ok) await this.run(() => this.api.invoke(deleteMonitor, { monitor_id: m.id }), 'Deleted');
  }

  private async run(action: () => Promise<unknown>, done: string): Promise<void> {
    try {
      await action();
      this.snack.open(done, undefined, { duration: 3000 });
      this.monitors.reload();
    } catch (e) {
      this.snack.open(errorMessage(e), 'Dismiss');
    }
  }
}
