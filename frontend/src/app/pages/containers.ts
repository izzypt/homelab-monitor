import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, resource, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatTableModule } from '@angular/material/table';
import { Api } from '../api/api';
import { listContainers, listEvents } from '../api/functions';
import { ContainerEventOut, ContainerOut } from '../api/models';
import { autoReload } from '../core/polling';
import { errorMessage } from '../shared/errors';
import { RelativePipe } from '../shared/format';
import { StateChip } from '../shared/state-chip';

@Component({
  selector: 'app-containers-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    MatTableModule,
    MatSlideToggleModule,
    MatButtonModule,
    DatePipe,
    RelativePipe,
    StateChip,
  ],
  template: `
    <div class="page">
      <div class="page-header">
        <h1>Containers</h1>
        <mat-slide-toggle
          [checked]="includeRemoved()"
          (change)="includeRemoved.set($event.checked)"
        >
          Show removed
        </mat-slide-toggle>
      </div>
      <p class="muted">
        Recorded every minute through the read-only Docker proxy. Container changes are shown here
        but never emailed.
      </p>
      @if (containers.error()) {
        <p class="error" role="alert">{{ message(containers.error()) }}</p>
      }
      <div class="table-wrap">
        <table mat-table [dataSource]="containers.value() ?? []" multiTemplateDataRows>
          <ng-container matColumnDef="state">
            <th mat-header-cell *matHeaderCellDef>State</th>
            <td mat-cell *matCellDef="let c">
              <app-state-chip [state]="status(c)" />
            </td>
          </ng-container>
          <ng-container matColumnDef="name">
            <th mat-header-cell *matHeaderCellDef>Name</th>
            <td mat-cell *matCellDef="let c">{{ c.name }}</td>
          </ng-container>
          <ng-container matColumnDef="image">
            <th mat-header-cell *matHeaderCellDef>Image</th>
            <td mat-cell *matCellDef="let c" class="mono">{{ c.image }}</td>
          </ng-container>
          <ng-container matColumnDef="created">
            <th mat-header-cell *matHeaderCellDef>Created</th>
            <td mat-cell *matCellDef="let c">{{ c.started_at | relative }}</td>
          </ng-container>
          <ng-container matColumnDef="history">
            <th mat-header-cell *matHeaderCellDef></th>
            <td mat-cell *matCellDef="let c">
              <button mat-button (click)="toggle(c)">
                {{ open() === c.id ? 'Hide' : 'History' }}
              </button>
            </td>
          </ng-container>
          <ng-container matColumnDef="events">
            <td mat-cell *matCellDef="let c" [attr.colspan]="columns.length" class="events">
              @if (open() === c.id) {
                <ul>
                  @for (e of events.value() ?? []; track e.id) {
                    <li>
                      <span class="muted">{{ e.at | date: 'short' }}</span>
                      {{ e.from_state ?? 'first seen' }} → <app-state-chip [state]="e.to_state" />
                    </li>
                  } @empty {
                    <li class="muted">
                      {{ events.isLoading() ? 'Loading…' : 'No changes recorded.' }}
                    </li>
                  }
                </ul>
              }
            </td>
          </ng-container>
          <tr mat-header-row *matHeaderRowDef="columns"></tr>
          <tr mat-row *matRowDef="let row; columns: columns"></tr>
          <tr
            mat-row
            *matRowDef="let row; columns: ['events']"
            class="events-row"
            [class.hidden]="open() !== row.id"
          ></tr>
          <tr class="mat-row" *matNoDataRow>
            <td class="mat-cell muted empty" [attr.colspan]="columns.length">
              No containers recorded yet. They appear once the host named in DOCKER_HOST_NAME is
              registered.
            </td>
          </tr>
        </table>
      </div>
    </div>
  `,
  styles: `
    .events-row.hidden {
      display: none;
    }
    .events ul {
      margin: 8px 0;
      padding-left: 16px;
      li {
        margin: 4px 0;
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
export class ContainersPage {
  private readonly api = inject(Api);
  protected readonly columns = ['state', 'name', 'image', 'created', 'history'];
  protected readonly includeRemoved = signal(false);
  protected readonly open = signal<number | null>(null);
  protected readonly message = errorMessage;

  protected readonly containers = resource({
    params: () => ({ include_removed: this.includeRemoved() }),
    loader: ({ params }) => this.api.invoke(listContainers, params),
  });
  protected readonly events = resource<ContainerEventOut[], number | undefined>({
    params: () => this.open() ?? undefined,
    loader: ({ params: id }) => this.api.invoke(listEvents, { container_id: id, limit: 50 }),
  });

  constructor() {
    autoReload(this.containers, 60_000);
  }

  protected status(c: ContainerOut): string {
    if (c.removed_at) return 'removed';
    return c.health ? `${c.state} (${c.health})` : c.state;
  }

  protected toggle(c: ContainerOut): void {
    this.open.update((id) => (id === c.id ? null : c.id));
  }
}
