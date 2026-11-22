import { Routes } from '@angular/router';
import { authGuard } from './core/auth';
import { Shell } from './shell';

export const routes: Routes = [
  { path: 'login', loadComponent: () => import('./pages/login').then((m) => m.LoginPage) },
  {
    path: '',
    component: Shell,
    canActivate: [authGuard],
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'overview' },
      {
        path: 'overview',
        title: 'Overview · homelab-monitor',
        loadComponent: () => import('./pages/overview').then((m) => m.OverviewPage),
      },
      {
        path: 'monitors',
        title: 'Monitors · homelab-monitor',
        loadComponent: () => import('./pages/monitors').then((m) => m.MonitorsPage),
      },
      {
        path: 'monitors/:id',
        title: 'Monitor · homelab-monitor',
        loadComponent: () => import('./pages/monitor-detail').then((m) => m.MonitorDetailPage),
      },
      {
        path: 'hosts',
        title: 'Hosts · homelab-monitor',
        loadComponent: () => import('./pages/hosts').then((m) => m.HostsPage),
      },
      {
        path: 'hosts/:id',
        title: 'Host · homelab-monitor',
        loadComponent: () => import('./pages/host-detail').then((m) => m.HostDetailPage),
      },
      {
        path: 'containers',
        title: 'Containers · homelab-monitor',
        loadComponent: () => import('./pages/containers').then((m) => m.ContainersPage),
      },
      {
        path: 'incidents',
        title: 'Incidents · homelab-monitor',
        loadComponent: () => import('./pages/incidents').then((m) => m.IncidentsPage),
      },
    ],
  },
  { path: '**', redirectTo: '' },
];
