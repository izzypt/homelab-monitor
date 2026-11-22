import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { Api } from '../api/api';
import { createMonitor, updateMonitor } from '../api/functions';
import { MonitorCreate, MonitorOut } from '../api/models';
import { errorMessage } from '../shared/errors';

type MonitorType = MonitorCreate['type'];

const TARGET_HINTS: Record<MonitorType, string> = {
  http: 'https://example.com/health',
  dns: 'macmini.example.com',
  tcp: 'nas.local:22',
};

/** Build the type-specific config object the API expects from the form's flat fields. */
export function buildConfig(
  type: MonitorType,
  f: { method: string; expectedStatus: string; keyword: string; recordType: string },
): Record<string, unknown> {
  if (type === 'http') {
    const config: Record<string, unknown> = { method: f.method };
    const codes = f.expectedStatus
      .split(',')
      .map((c) => c.trim())
      .filter(Boolean)
      .map(Number);
    if (codes.length) config['expected_status'] = codes;
    if (f.keyword.trim()) config['keyword'] = f.keyword.trim();
    return config;
  }
  if (type === 'dns') return { record_type: f.recordType };
  return {};
}

@Component({
  selector: 'app-monitor-dialog',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    MatDialogModule,
    MatButtonModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatSlideToggleModule,
  ],
  template: `
    <h2 mat-dialog-title>{{ existing ? 'Edit monitor' : 'New monitor' }}</h2>
    <form [formGroup]="form" (ngSubmit)="save()">
      <mat-dialog-content>
        <mat-form-field appearance="outline">
          <mat-label>Name</mat-label>
          <input matInput formControlName="name" />
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>Type</mat-label>
          <mat-select formControlName="type">
            <mat-option value="http">HTTP(S)</mat-option>
            <mat-option value="dns">DNS</mat-option>
            <mat-option value="tcp">TCP port</mat-option>
          </mat-select>
          @if (existing) {
            <mat-hint>The type can't be changed after creation.</mat-hint>
          }
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>Target</mat-label>
          <input matInput formControlName="target" [placeholder]="hint()" />
        </mat-form-field>

        @switch (type()) {
          @case ('http') {
            <div class="row">
              <mat-form-field appearance="outline">
                <mat-label>Method</mat-label>
                <mat-select formControlName="method">
                  <mat-option value="GET">GET</mat-option>
                  <mat-option value="HEAD">HEAD</mat-option>
                </mat-select>
              </mat-form-field>
              <mat-form-field appearance="outline">
                <mat-label>Expected status</mat-label>
                <input matInput formControlName="expectedStatus" placeholder="200, 204" />
                <mat-hint>Empty = any 2xx/3xx</mat-hint>
              </mat-form-field>
            </div>
            <mat-form-field appearance="outline">
              <mat-label>Keyword in body (optional)</mat-label>
              <input matInput formControlName="keyword" />
            </mat-form-field>
          }
          @case ('dns') {
            <mat-form-field appearance="outline">
              <mat-label>Record type</mat-label>
              <mat-select formControlName="recordType">
                @for (r of recordTypes; track r) {
                  <mat-option [value]="r">{{ r }}</mat-option>
                }
              </mat-select>
            </mat-form-field>
          }
        }

        <div class="row">
          <mat-form-field appearance="outline">
            <mat-label>Interval (s)</mat-label>
            <input matInput type="number" formControlName="interval_s" min="15" />
          </mat-form-field>
          <mat-form-field appearance="outline">
            <mat-label>Timeout (s)</mat-label>
            <input matInput type="number" formControlName="timeout_s" min="1" />
          </mat-form-field>
          <mat-form-field appearance="outline">
            <mat-label>Failures before DOWN</mat-label>
            <input matInput type="number" formControlName="failure_threshold" min="1" max="10" />
          </mat-form-field>
        </div>
        <mat-slide-toggle formControlName="enabled">Enabled</mat-slide-toggle>
        @if (error()) {
          <p class="error" role="alert">{{ error() }}</p>
        }
      </mat-dialog-content>
      <mat-dialog-actions align="end">
        <button mat-button type="button" mat-dialog-close>Cancel</button>
        <button mat-flat-button type="submit" [disabled]="form.invalid || busy()">Save</button>
      </mat-dialog-actions>
    </form>
  `,
  styles: `
    mat-form-field {
      width: 100%;
    }
    .row {
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      > mat-form-field {
        flex: 1 1 140px;
      }
    }
    .error {
      color: var(--mat-sys-error);
    }
  `,
})
export class MonitorDialog {
  private readonly api = inject(Api);
  private readonly ref = inject(MatDialogRef<MonitorDialog, MonitorOut>);
  protected readonly existing = inject<MonitorOut | null>(MAT_DIALOG_DATA);
  protected readonly recordTypes = ['A', 'AAAA', 'CNAME', 'MX', 'TXT', 'NS'];
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);

  protected readonly form = inject(FormBuilder).nonNullable.group({
    name: [this.existing?.name ?? '', [Validators.required, Validators.maxLength(100)]],
    type: [{ value: (this.existing?.type ?? 'http') as MonitorType, disabled: !!this.existing }],
    target: [this.existing?.target ?? '', Validators.required],
    method: [String(this.existing?.config['method'] ?? 'GET')],
    expectedStatus: [((this.existing?.config['expected_status'] as number[]) ?? []).join(', ')],
    keyword: [String(this.existing?.config['keyword'] ?? '')],
    recordType: [String(this.existing?.config['record_type'] ?? 'A')],
    interval_s: [this.existing?.interval_s ?? 60, [Validators.required, Validators.min(15)]],
    timeout_s: [this.existing?.timeout_s ?? 10, [Validators.required, Validators.min(1)]],
    failure_threshold: [
      this.existing?.failure_threshold ?? 2,
      [Validators.required, Validators.min(1), Validators.max(10)],
    ],
    enabled: [this.existing?.enabled ?? true],
  });

  protected readonly type = toSignal(this.form.controls.type.valueChanges, {
    initialValue: this.form.controls.type.value,
  });
  protected hint(): string {
    return TARGET_HINTS[this.type()];
  }

  async save(): Promise<void> {
    if (this.form.invalid) return;
    const v = this.form.getRawValue();
    const common = {
      name: v.name.trim(),
      target: v.target.trim(),
      config: buildConfig(v.type, v),
      interval_s: v.interval_s,
      timeout_s: v.timeout_s,
      failure_threshold: v.failure_threshold,
      enabled: v.enabled,
    };
    this.busy.set(true);
    this.error.set(null);
    try {
      const saved = this.existing
        ? await this.api.invoke(updateMonitor, { monitor_id: this.existing.id, body: common })
        : await this.api.invoke(createMonitor, { body: { ...common, type: v.type } });
      this.ref.close(saved);
    } catch (e) {
      this.error.set(errorMessage(e));
    } finally {
      this.busy.set(false);
    }
  }
}
