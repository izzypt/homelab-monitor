import { ChangeDetectionStrategy, Component, inject, resource, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatTableModule } from '@angular/material/table';
import { RouterLink } from '@angular/router';
import { Api } from '../api/api';
import { createHost, listHosts } from '../api/functions';
import { autoReload } from '../core/polling';
import { errorMessage } from '../shared/errors';
import { RelativePipe } from '../shared/format';
import { Icon } from '../shared/icon';
import { StateChip } from '../shared/state-chip';
import { HostTokenDialog } from './host-token-dialog';

@Component({
  selector: 'app-hosts-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    RouterLink,
    MatTableModule,
    MatButtonModule,
    MatFormFieldModule,
    MatInputModule,
    RelativePipe,
    StateChip,
    Icon,
  ],
  template: `
    <div class="page">
      <div class="page-header"><h1>Hosts</h1></div>
      @if (hosts.error()) {
        <p class="error" role="alert">{{ message(hosts.error()) }}</p>
      }
      <div class="table-wrap">
        <table mat-table [dataSource]="hosts.value() ?? []">
          <ng-container matColumnDef="status">
            <th mat-header-cell *matHeaderCellDef>Status</th>
            <td mat-cell *matCellDef="let h"><app-state-chip [state]="h.status" /></td>
          </ng-container>
          <ng-container matColumnDef="name">
            <th mat-header-cell *matHeaderCellDef>Name</th>
            <td mat-cell *matCellDef="let h">
              <a [routerLink]="['/hosts', h.id]">{{ h.name }}</a>
            </td>
          </ng-container>
          <ng-container matColumnDef="seen">
            <th mat-header-cell *matHeaderCellDef>Last heartbeat</th>
            <td mat-cell *matCellDef="let h">{{ h.last_seen_at | relative }}</td>
          </ng-container>
          <ng-container matColumnDef="boot">
            <th mat-header-cell *matHeaderCellDef>Booted</th>
            <td mat-cell *matCellDef="let h">{{ h.current_boot_time | relative }}</td>
          </ng-container>
          <ng-container matColumnDef="agent">
            <th mat-header-cell *matHeaderCellDef>Agent</th>
            <td mat-cell *matCellDef="let h" class="muted">{{ h.agent_version ?? '—' }}</td>
          </ng-container>
          <tr mat-header-row *matHeaderRowDef="columns"></tr>
          <tr mat-row *matRowDef="let row; columns: columns"></tr>
          <tr class="mat-row" *matNoDataRow>
            <td class="mat-cell muted empty" [attr.colspan]="columns.length">No hosts yet.</td>
          </tr>
        </table>
      </div>

      <h2>Register a host</h2>
      <form class="register" (ngSubmit)="register()">
        <mat-form-field appearance="outline">
          <mat-label>Host name</mat-label>
          <input matInput name="name" [(ngModel)]="name" pattern="[A-Za-z0-9._-]+" required />
          <mat-hint>Containers are recorded under the host named in DOCKER_HOST_NAME.</mat-hint>
        </mat-form-field>
        <button mat-flat-button type="submit" [disabled]="!name || busy()">
          <app-icon name="key" /> Register and show token
        </button>
      </form>
      @if (error()) {
        <p class="error" role="alert">{{ error() }}</p>
      }
    </div>
  `,
  styles: `
    h2 {
      font: var(--mat-sys-title-large);
      margin: 32px 0 12px;
    }
    .register {
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      align-items: flex-start;
      mat-form-field {
        flex: 1 1 260px;
      }
      button {
        margin-top: 8px;
      }
    }
    .empty {
      padding: 16px;
    }
    .error {
      color: var(--mat-sys-error);
    }
  `,
})
export class HostsPage {
  private readonly api = inject(Api);
  private readonly dialog = inject(MatDialog);
  protected readonly columns = ['status', 'name', 'seen', 'boot', 'agent'];
  protected readonly hosts = resource({ loader: () => this.api.invoke(listHosts) });
  protected readonly message = errorMessage;
  protected name = '';
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);

  constructor() {
    autoReload(this.hosts);
  }

  async register(): Promise<void> {
    this.busy.set(true);
    this.error.set(null);
    try {
      const host = await this.api.invoke(createHost, { body: { name: this.name.trim() } });
      this.name = '';
      this.hosts.reload();
      this.dialog.open(HostTokenDialog, { data: host, disableClose: true, width: '520px' });
    } catch (e) {
      this.error.set(errorMessage(e));
    } finally {
      this.busy.set(false);
    }
  }
}
