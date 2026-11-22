import { ChangeDetectionStrategy, Component, inject, input, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { Router } from '@angular/router';
import { Auth } from '../core/auth';
import { errorMessage } from '../shared/errors';

@Component({
  selector: 'app-login-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatProgressBarModule,
  ],
  template: `
    <mat-card appearance="outlined">
      @if (busy()) {
        <mat-progress-bar mode="indeterminate" />
      }
      <mat-card-header>
        <mat-card-title>homelab-monitor</mat-card-title>
        <mat-card-subtitle>Sign in to continue</mat-card-subtitle>
      </mat-card-header>
      <form [formGroup]="form" (ngSubmit)="submit()">
        <mat-card-content>
          <mat-form-field appearance="outline">
            <mat-label>Email</mat-label>
            <input matInput type="email" formControlName="email" autocomplete="username" />
          </mat-form-field>
          <mat-form-field appearance="outline">
            <mat-label>Password</mat-label>
            <input
              matInput
              type="password"
              formControlName="password"
              autocomplete="current-password"
            />
          </mat-form-field>
          @if (error()) {
            <p class="error" role="alert">{{ error() }}</p>
          }
        </mat-card-content>
        <mat-card-actions align="end">
          <button mat-flat-button type="submit" [disabled]="form.invalid || busy()">Sign in</button>
        </mat-card-actions>
      </form>
    </mat-card>
  `,
  styles: `
    :host {
      display: grid;
      place-items: center;
      min-height: 100%;
      padding: 16px;
      box-sizing: border-box;
    }
    mat-card {
      width: min(380px, 100%);
    }
    mat-form-field {
      width: 100%;
    }
    form {
      margin-top: 16px;
    }
    .error {
      color: var(--mat-sys-error);
      margin: 0;
    }
  `,
})
export class LoginPage {
  private readonly auth = inject(Auth);
  private readonly router = inject(Router);
  /** Where to go after signing in (set by the auth guard). */
  readonly next = input<string>();

  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly form = inject(FormBuilder).nonNullable.group({
    email: ['', [Validators.required, Validators.email]],
    password: ['', Validators.required],
  });

  async submit(): Promise<void> {
    if (this.form.invalid) return;
    this.busy.set(true);
    this.error.set(null);
    const { email, password } = this.form.getRawValue();
    try {
      await this.auth.login(email, password);
      const next = this.next();
      // Only follow same-app paths, never an absolute URL from the query string.
      await this.router.navigateByUrl(next?.startsWith('/') && !next.startsWith('//') ? next : '/');
    } catch (e) {
      this.error.set(errorMessage(e));
    } finally {
      this.busy.set(false);
    }
  }
}
