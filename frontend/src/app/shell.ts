import { BreakpointObserver } from '@angular/cdk/layout';
import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatListModule } from '@angular/material/list';
import { MatSidenavModule } from '@angular/material/sidenav';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { map } from 'rxjs';
import { Auth } from './core/auth';
import { Icon } from './shared/icon';
import { IconName } from './shared/icons';

const NAV: { path: string; label: string; icon: IconName }[] = [
  { path: '/overview', label: 'Overview', icon: 'dashboard' },
  { path: '/monitors', label: 'Monitors', icon: 'monitor_heart' },
  { path: '/hosts', label: 'Hosts', icon: 'computer' },
  { path: '/containers', label: 'Containers', icon: 'deployed_code' },
  { path: '/incidents', label: 'Incidents', icon: 'report' },
];

@Component({
  selector: 'app-shell',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterOutlet,
    RouterLink,
    RouterLinkActive,
    MatToolbarModule,
    MatSidenavModule,
    MatListModule,
    MatButtonModule,
    MatTooltipModule,
    Icon,
  ],
  template: `
    <mat-sidenav-container class="container">
      <mat-sidenav
        #nav
        [mode]="wide() ? 'side' : 'over'"
        [opened]="wide()"
        [fixedInViewport]="!wide()"
      >
        <div class="brand">homelab-monitor</div>
        <mat-nav-list>
          @for (item of links; track item.path) {
            <a
              mat-list-item
              [routerLink]="item.path"
              routerLinkActive
              #rla="routerLinkActive"
              [activated]="rla.isActive"
              (click)="wide() || nav.close()"
            >
              <app-icon matListItemIcon [name]="item.icon" />
              <span matListItemTitle>{{ item.label }}</span>
            </a>
          }
        </mat-nav-list>
      </mat-sidenav>
      <mat-sidenav-content>
        <mat-toolbar>
          @if (!wide()) {
            <button mat-icon-button aria-label="Menu" (click)="nav.toggle()">
              <app-icon name="menu" />
            </button>
            <span class="title">homelab-monitor</span>
          }
          <span class="spacer"></span>
          <span class="user muted">{{ auth.user()?.email }}</span>
          <button mat-icon-button aria-label="Log out" matTooltip="Log out" (click)="logout()">
            <app-icon name="logout" />
          </button>
        </mat-toolbar>
        <main><router-outlet /></main>
      </mat-sidenav-content>
    </mat-sidenav-container>
  `,
  styles: `
    .container {
      height: 100%;
    }
    mat-sidenav {
      width: 220px;
    }
    .brand {
      font: var(--mat-sys-title-medium);
      padding: 20px 16px 8px;
    }
    .title {
      font: var(--mat-sys-title-medium);
    }
    .spacer {
      flex: 1;
    }
    .user {
      font: var(--mat-sys-body-small);
      margin-right: 8px;
    }
    @media (max-width: 599px) {
      .user {
        display: none;
      }
    }
  `,
})
export class Shell {
  protected readonly auth = inject(Auth);
  private readonly router = inject(Router);
  protected readonly links = NAV;
  private readonly breakpoint = toSignal(
    inject(BreakpointObserver)
      .observe('(min-width: 960px)')
      .pipe(map((s) => s.matches)),
    { initialValue: true },
  );
  protected readonly wide = computed(() => this.breakpoint());

  async logout(): Promise<void> {
    await this.auth.logout();
    await this.router.navigate(['/login']);
  }
}
