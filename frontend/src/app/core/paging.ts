/** Follow `next_cursor` until `maxPages` pages or the end; returns items oldest first. */
export async function fetchPages<T>(
  page: (cursor: number | undefined) => Promise<{ items: T[]; next_cursor?: number | null }>,
  maxPages = 3,
): Promise<T[]> {
  const items: T[] = [];
  let cursor: number | undefined;
  for (let i = 0; i < maxPages; i++) {
    const res = await page(cursor);
    items.push(...res.items);
    if (res.next_cursor == null) break;
    cursor = res.next_cursor;
  }
  return items.reverse();
}
