import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { catchError, throwError } from 'rxjs';
import { Api } from '../api/api';
import { login, logout, me } from '../api/functions';
import { UserOut } from '../api/models';

@Injectable({ providedIn: 'root' })
export class Auth {
  private readonly api = inject(Api);
  readonly user = signal<UserOut | null>(null);

  async login(email: string, password: string): Promise<void> {
    this.user.set(await this.api.invoke(login, { body: { email, password } }));
  }

  async logout(): Promise<void> {
    try {
      await this.api.invoke(logout);
    } finally {
      this.user.set(null);
    }
  }

  /** Resolve the current user once per page load; false when not logged in. */
  async check(): Promise<boolean> {
    if (this.user()) return true;
    try {
      this.user.set(await this.api.invoke(me));
      return true;
    } catch {
      return false;
    }
  }
}

export const authGuard: CanActivateFn = async (_route, state) => {
  const router = inject(Router);
  return (await inject(Auth).check())
    ? true
    : router.createUrlTree(['/login'], { queryParams: { next: state.url } });
};

/** Any 401 outside the auth endpoints means the session expired: go back to the login page. */
export const sessionExpiredInterceptor: HttpInterceptorFn = (req, next) => {
  const router = inject(Router);
  const auth = inject(Auth);
  return next(req).pipe(
    catchError((error: unknown) => {
      if (
        error instanceof HttpErrorResponse &&
        error.status === 401 &&
        !req.url.includes('/api/v1/auth/')
      ) {
        auth.user.set(null);
        void router.navigate(['/login'], { queryParams: { next: router.url } });
      }
      return throwError(() => error);
    }),
  );
};
