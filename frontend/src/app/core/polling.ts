import { DestroyRef, Resource, inject } from '@angular/core';

/**
 * Reload a resource every `ms` while the tab is visible. `reload()` keeps the current value
 * on screen while fetching (status "reloading"), so the page doesn't flicker.
 */
export function autoReload(
  res: Pick<Resource<unknown>, 'isLoading'> & { reload(): boolean },
  ms = 30_000,
) {
  const id = setInterval(() => {
    if (document.visibilityState === 'visible' && !res.isLoading()) res.reload();
  }, ms);
  inject(DestroyRef).onDestroy(() => clearInterval(id));
}
