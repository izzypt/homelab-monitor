import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { ICONS, IconName } from './icons';

/** Inline SVG icon from the bundled Material Symbols subset (see icons.ts). */
@Component({
  selector: 'app-icon',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<svg viewBox="0 -960 960 960" aria-hidden="true" focusable="false">
    <path [attr.d]="path()" />
  </svg>`,
  styles: `
    :host {
      display: inline-flex;
      width: 24px;
      height: 24px;
      vertical-align: middle;
    }
    svg {
      width: 100%;
      height: 100%;
      fill: currentColor;
    }
  `,
})
export class Icon {
  readonly name = input.required<IconName>();
  protected readonly path = computed(() => ICONS[this.name()]);
}
