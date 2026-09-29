export const MAX_IMAGES = 40
/** Which cached entries to drop so at most `max` remain, oldest first. Pure so the policy is testable. */
export function evictOldest(entries: { path: string; at: number }[], max = MAX_IMAGES): string[] {
  const extra = entries.length - max
  return extra > 0 ? [...entries].sort((a, b) => a.at - b.at).slice(0, extra).map((e) => e.path) : []
}

/** Offline copy of the TV's photos (IndexedDB, own DB so the snapshot cache schema is untouched). Every call fails soft. */
export function createImageCache(idb: IDBFactory | undefined = typeof indexedDB === 'undefined' ? undefined : indexedDB) {
  const open = () => new Promise<IDBDatabase>((res, rej) => {
    if (!idb) return rej(new Error('no indexedDB'))
    const r = idb.open('vhome-img', 1)
    r.onupgradeneeded = () => r.result.createObjectStore('img')
    r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error)
  })
  const req = <T,>(r: IDBRequest<T>) => new Promise<T>((res, rej) => { r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error) })
  return {
    async get(path: string): Promise<Blob | null> {
      try { const db = await open(); const v = (await req(db.transaction('img').objectStore('img').get(path))) as { blob: Blob } | undefined; return v?.blob ?? null } catch { return null }
    },
    async put(path: string, blob: Blob): Promise<void> {
      try {
        const db = await open(); const st = db.transaction('img', 'readwrite').objectStore('img')
        await req(st.put({ blob, at: Date.now() }, path))
        const keys = (await req(db.transaction('img').objectStore('img').getAllKeys())) as string[]
        const entries = await Promise.all(keys.map(async (k) => ({ path: k, at: ((await req(db.transaction('img').objectStore('img').get(k))) as { at: number }).at })))
        for (const p of evictOldest(entries)) await req(db.transaction('img', 'readwrite').objectStore('img').delete(p))
      } catch { /* cache is best effort */ }
    },
    async clear(): Promise<void> { try { const db = await open(); await req(db.transaction('img', 'readwrite').objectStore('img').clear()) } catch { /* ignore */ } },
  }
}
