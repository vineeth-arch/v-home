import type { Snapshot } from './model'

export interface CacheStore { name: string; get(): Promise<Snapshot | null>; set(s: Snapshot): Promise<void>; clear(): Promise<void> }
const KEY = 'vhome.snapshot.v2' // bumped when the snapshot shape grew; older caches are simply ignored

export const memoryStore = (): CacheStore => {
  let v: Snapshot | null = null
  return { name: 'memory', get: async () => v, set: async (s) => { v = s }, clear: async () => { v = null } }
}

export const localStorageStore = (ls: Storage = localStorage): CacheStore => ({
  name: 'localStorage',
  get: async () => { const raw = ls.getItem(KEY); return raw ? (JSON.parse(raw) as Snapshot) : null },
  set: async (s) => ls.setItem(KEY, JSON.stringify(s)),
  clear: async () => ls.removeItem(KEY),
})

export const indexedDbStore = (idb: IDBFactory = indexedDB): CacheStore => {
  const open = () => new Promise<IDBDatabase>((res, rej) => {
    const r = idb.open('vhome', 1)
    r.onupgradeneeded = () => r.result.createObjectStore('kv')
    r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error)
  })
  const tx = async <T,>(mode: IDBTransactionMode, f: (s: IDBObjectStore) => IDBRequest<T>) => {
    const db = await open()
    return new Promise<T>((res, rej) => { const r = f(db.transaction('kv', mode).objectStore('kv')); r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error) })
  }
  return {
    name: 'indexedDB',
    get: async () => ((await tx('readonly', (s) => s.get(KEY))) as Snapshot | undefined) ?? null,
    set: async (s) => { await tx('readwrite', (st) => st.put(s, KEY)) },
    clear: async () => { await tx('readwrite', (st) => st.delete(KEY)) },
  }
}

/** Try each store with a round trip; first that works wins. Falls back silently but reports which backend is live. */
export async function pickStore(candidates: (() => CacheStore)[] = [indexedDbStore, localStorageStore, memoryStore]): Promise<CacheStore> {
  for (const make of candidates) {
    try {
      const s = make()
      await s.get()
      return s
    } catch { /* try next */ }
  }
  return memoryStore()
}
