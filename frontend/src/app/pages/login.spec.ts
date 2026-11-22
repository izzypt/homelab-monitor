import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { LoginPage } from './login';

describe('LoginPage', () => {
  let http: HttpTestingController;
  let router: Router;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
  });

  async function submit(next?: string, status = 200) {
    const fixture = TestBed.createComponent(LoginPage);
    if (next) fixture.componentRef.setInput('next', next);
    const page = fixture.componentInstance as unknown as {
      form: { setValue(v: object): void };
      submit(): Promise<void>;
    };
    page.form.setValue({ email: 'admin@example.com', password: 'secret' });
    const navigate = vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    const done = page.submit();
    const req = http.expectOne('/api/v1/auth/login');
    expect(req.request.body).toEqual({ email: 'admin@example.com', password: 'secret' });
    if (status === 200) req.flush({ id: 1, email: 'admin@example.com' });
    else req.flush({ detail: 'Invalid email or password' }, { status, statusText: 'Unauthorized' });
    await done;
    fixture.detectChanges();
    return { navigate, el: fixture.nativeElement as HTMLElement };
  }

  it('goes to the requested page after login', async () => {
    const { navigate } = await submit('/monitors/3');
    expect(navigate).toHaveBeenCalledWith('/monitors/3');
  });

  it('never follows an external next URL', async () => {
    const { navigate } = await submit('//evil.example');
    expect(navigate).toHaveBeenCalledWith('/');
  });

  it('shows the API error', async () => {
    const { navigate, el } = await submit(undefined, 401);
    expect(navigate).not.toHaveBeenCalled();
    expect(el.querySelector('[role=alert]')?.textContent).toContain('Invalid email or password');
  });
});
