import { HttpErrorResponse } from '@angular/common/http';
import { errorMessage } from './errors';

describe('errorMessage', () => {
  it('uses the problem+json detail', () => {
    const e = new HttpErrorResponse({
      status: 409,
      error: { detail: 'A monitor with this name exists' },
    });
    expect(errorMessage(e)).toBe('A monitor with this name exists');
  });

  it('prefers the first validation error over the generic detail', () => {
    const e = new HttpErrorResponse({
      status: 422,
      error: {
        detail: 'Request validation failed',
        errors: [{ loc: ['body'], msg: 'Value error, timeout_s must be smaller than interval_s' }],
      },
    });
    expect(errorMessage(e)).toBe('timeout_s must be smaller than interval_s');
  });

  it('explains network failures', () => {
    expect(errorMessage(new HttpErrorResponse({ status: 0 }))).toBe('Cannot reach the server.');
    expect(errorMessage(new Error('x'))).toBe('Something went wrong.');
  });
});
