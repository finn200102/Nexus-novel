/** Private browser data is partitioned by backend instance and immutable user id. */
export type AccountIdentity = number | string;
let accountId: AccountIdentity | null = null;
export const accountIdentity = (user: { id: number; storage_id?: string } | null | undefined) => user?.storage_id ?? user?.id ?? null;
let generation = 0;
const instance = encodeURIComponent(import.meta.env.VITE_API_URL || window.location.origin);
const listeners = new Set<() => void>();

export const storageGeneration = () => generation;
export const activeStorageAccount = () => accountId;
export const accountStorageKey = (key: string) =>
  `nexus-account:${instance}:${accountId ?? "signed-out"}:${key}`;
export const accountDatabaseName = () => accountStorageKey("reader-db");

export function activateAccountStorage(id: AccountIdentity | null): void {
  if (id === accountId) return;
  if (id !== null && (typeof id === "number"
    ? !Number.isSafeInteger(id) || id <= 0
    : !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(id))) throw new Error("Invalid account identity");
  accountId = id;
  generation += 1;
  // Legacy caches have no owner. Never assign them to the next person signing in.
  try {
    for (const key of Object.keys(localStorage)) {
      if (key.startsWith("nexus-reader-") || key.startsWith("nexus-story-typography-") || key === "nexus.activeLibrary") localStorage.removeItem(key);
    }
    indexedDB.deleteDatabase("nexus-reader");
    const scopedPrefix = `nexus-account:${instance}:${id ?? "signed-out"}:`;
    const identityMarker = `${scopedPrefix}chapter-cache-identity-version`;
    if (localStorage.getItem(identityMarker) !== "1") {
      for (const key of Object.keys(localStorage)) {
        if (!key.startsWith(scopedPrefix)) continue;
        const localKey = key.slice(scopedPrefix.length);
        if (localKey.startsWith("nexus-reader-audio-position-") && !localKey.startsWith("nexus-reader-audio-position-v2:")
            || localKey.startsWith("reader-chapter-index:") || localKey.startsWith("reader-chapter-neighbors:")) localStorage.removeItem(key);
      }
      // Pending progress is deliberately retained and marked for review by its
      // queue reader. Story/global preferences do not depend on chapter order.
      localStorage.setItem(identityMarker, "1");
    }

    if (typeof id === "string") {
      // Development/older clients used reusable numeric identities. Discard
      // those caches rather than assigning their content to a permanent UUID.
      const prefix = `nexus-account:${instance}:`;
      for (const key of Object.keys(localStorage)) {
        if (key.startsWith(prefix) && /^\d+:/.test(key.slice(prefix.length))) localStorage.removeItem(key);
      }
      if (typeof indexedDB.databases === "function") void indexedDB.databases().then(databases => {
        for (const database of databases) {
          if (database.name?.startsWith(prefix) && /^\d+:/.test(database.name.slice(prefix.length))) indexedDB.deleteDatabase(database.name);
        }
      }).catch(() => undefined);
    }
  } catch { /* Storage can be unavailable; scoped stores still isolate readers. */ }
  for (const listener of listeners) listener();
}

export const onAccountStorageChange = (listener: () => void) => {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
};

export async function clearAccountStorage(id: AccountIdentity | null = accountId): Promise<void> {
  const prefix = `nexus-account:${instance}:${id ?? "signed-out"}:`;
  const databaseName = `${prefix}reader-db`;
  try {
    for (const key of Object.keys(localStorage)) {
      if (key.startsWith(prefix)) localStorage.removeItem(key);
    }
    await new Promise<void>((resolve, reject) => {
      const request = indexedDB.deleteDatabase(databaseName);
      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
      request.onblocked = () => reject(new Error("Close other reader tabs to clear offline files"));
    });
  } finally {
    activateAccountStorage(null);
  }
}

export const accountStorage = {
  getItem: (key: string) => localStorage.getItem(accountStorageKey(key)),
  setItem: (key: string, value: string) => localStorage.setItem(accountStorageKey(key), value),
  removeItem: (key: string) => localStorage.removeItem(accountStorageKey(key)),
};
