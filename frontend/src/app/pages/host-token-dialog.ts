import { Clipboard } from '@angular/cdk/clipboard';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule } from '@angular/material/dialog';
import { HostWithToken } from '../api/models';
import { Icon } from '../shared/icon';

/** Shows a new agent token exactly once (the API only stores its hash). */
@Component({
  selector: 'app-host-token-dialog',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MatDialogModule, MatButtonModule, Icon],
  template: `
    <h2 mat-dialog-title>Agent token for {{ host.name }}</h2>
    <mat-dialog-content>
      <p>
        Put this token in <span class="mono">/usr/local/etc/homelab-agent.json</span> on the host.
        It is shown only now; rotate it if you lose it.
      </p>
      <p class="token mono">{{ host.agent_token }}</p>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button (click)="copy()">
        <app-icon name="content_copy" /> {{ copied() ? 'Copied' : 'Copy' }}
      </button>
      <button mat-flat-button mat-dialog-close>Done</button>
    </mat-dialog-actions>
  `,
  styles: `
    .token {
      word-break: break-all;
      padding: 12px;
      border-radius: 8px;
      background: var(--mat-sys-surface-container-high);
    }
  `,
})
export class HostTokenDialog {
  protected readonly host = inject<HostWithToken>(MAT_DIALOG_DATA);
  private readonly clipboard = inject(Clipboard);
  protected readonly copied = signal(false);

  copy(): void {
    this.copied.set(this.clipboard.copy(this.host.agent_token));
  }
}
