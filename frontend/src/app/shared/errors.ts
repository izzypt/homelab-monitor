import { HttpErrorResponse } from '@angular/common/http';

/** Human-readable message from an RFC 9457 problem+json (or FastAPI validation) error. */
export function errorMessage(error: unknown): string {
  if (error instanceof HttpErrorResponse) {
    const body = error.error as { detail?: unknown; title?: string; errors?: unknown } | null;
    if (body && Array.isArray(body.errors) && body.errors.length) {
      const first = body.errors[0] as { msg?: string; loc?: unknown[] };
      if (first.msg) return first.msg.replace(/^Value error, /, '');
    }
    if (body && typeof body.detail === 'string') return body.detail;
    if (body?.title) return body.title;
    if (error.status === 0) return 'Cannot reach the server.';
    return `Request failed (${error.status}).`;
  }
  return 'Something went wrong.';
}
