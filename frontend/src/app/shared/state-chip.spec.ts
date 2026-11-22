import { TestBed } from '@angular/core/testing';
import { StateChip } from './state-chip';

function render(state: string, text?: string): HTMLElement {
  const fixture = TestBed.createComponent(StateChip);
  fixture.componentRef.setInput('state', state);
  if (text) fixture.componentRef.setInput('text', text);
  fixture.detectChanges();
  return fixture.nativeElement.querySelector('.chip');
}

describe('StateChip', () => {
  it('colours states by meaning', () => {
    expect(render('UP').className).toContain('good');
    expect(render('DOWN').className).toContain('bad');
    expect(render('STALE').className).toContain('warn');
    expect(render('paused').className).toContain('neutral');
  });

  it('uses the health in parentheses for containers', () => {
    expect(render('running (unhealthy)').className).toContain('bad');
    expect(render('running (healthy)').className).toContain('good');
  });

  it('shows a custom label', () => {
    expect(render('open', 'Network outage').textContent).toBe('Network outage');
  });
});
