import axios from "axios";
import apiClient from "./apiClient";
import { accountStorage, accountStorageKey, activeStorageAccount, onAccountStorageChange, storageGeneration } from "./accountStorage";
import type { ReaderTypography } from "../components/reader/readerSettings";

import type { PreferenceWrite, ReaderPreferenceResponse, ReaderPreferenceValuesResponse } from "../generated/api";

export type PreferenceScope = "global" | `story:${number}`;
// Local typography accepts numeric controls before the existing sanitizer
// snaps them to server presets. Null field clears are resolved locally first.
type KnownPreferenceValues = Pick<ReaderPreferenceValuesResponse, "layout" | "authorNotes" | "shortcuts">;
export type PreferenceValues = { [Key in keyof KnownPreferenceValues]?: NonNullable<KnownPreferenceValues[Key]> } & { typography?: Partial<ReaderTypography> | null };
export type PreferenceResponse = Pick<ReaderPreferenceResponse, "revision"> & { scope: PreferenceScope; values: PreferenceValues };
type PendingPreference = Pick<PreferenceWrite, "expected_revision" | "operation_id"> & { values: PreferenceValues };
interface CachedPreference extends PreferenceResponse {
  pending?: PendingPreference;
  conflict?: PreferenceResponse;
  error?: string;
}
export interface PreferenceSyncStatus { pending: number; conflicts: PreferenceScope[]; error?: string; offline?: boolean; memoryOnly?: boolean }

export const PREFERENCE_CACHE_KEY = "nexus-reader-preference-sync";
export const PREFERENCE_CHANGED = "nexus-reader-preference-sync-changed";
export const PREFERENCE_LOCAL_PATCH = "nexus-reader-preference-local-patch";
const locks = new Map<string, Promise<void>>();
let volatileCache: { generation: number; records: Partial<Record<PreferenceScope, CachedPreference>> } | undefined;
onAccountStorageChange(() => { volatileCache = undefined; });
const scopeValid = (value: unknown): value is PreferenceScope => typeof value === "string" && (value === "global" || /^story:[1-9]\d*$/.test(value));
const responseValid = (value: unknown, scope: PreferenceScope): value is PreferenceResponse => {
  if (!value || typeof value !== "object") return false;
  const record = value as PreferenceResponse;
  return record.scope === scope && Number.isSafeInteger(record.revision) && record.revision >= 0
    && Boolean(record.values && typeof record.values === "object" && !Array.isArray(record.values));
};
const read = (): Partial<Record<PreferenceScope, CachedPreference>> => {
  if (volatileCache?.generation === storageGeneration()) return volatileCache.records;
  try {
    const value = JSON.parse(accountStorage.getItem(PREFERENCE_CACHE_KEY) || "{}");
    if (!value || typeof value !== "object" || Array.isArray(value)) return {};
    return Object.fromEntries(Object.entries(value).filter(([scope, record]) => scopeValid(scope) && responseValid(record, scope))) as Partial<Record<PreferenceScope, CachedPreference>>;
  } catch { return {}; }
};
function save(scope: PreferenceScope, value: CachedPreference) {
  const records = { ...read(), [scope]: value };
  try {
    accountStorage.setItem(PREFERENCE_CACHE_KEY, JSON.stringify(records));
    volatileCache = undefined;
  } catch {
    // Private mode and a full browser quota must never break ordinary reading.
    volatileCache = { generation: storageGeneration(), records };
  }
  window.dispatchEvent(new Event(PREFERENCE_CHANGED));
}
const endpoint = (scope: PreferenceScope) => scope === "global" ? "/reader/preferences" : `/reader/preferences/stories/${scope.slice(6)}`;
const operation = () => crypto.randomUUID();

export function preferenceSyncStatus(scopes?: PreferenceScope[]): PreferenceSyncStatus {
  const records = Object.values(read()).filter((record): record is CachedPreference => Boolean(record && (!scopes || scopes.includes(record.scope))));
  return { pending: records.filter(record => record.pending).length,
    conflicts: records.filter(record => record.conflict).map(record => record.scope),
    error: records.find(record => record.error)?.error, offline: navigator.onLine === false,
    memoryOnly: volatileCache?.generation === storageGeneration() };
}

export function queuePreferencePatch(scope: PreferenceScope, patch: PreferenceValues) {
  if (activeStorageAccount() === null) return;
  const cached = read()[scope] || { scope, revision: 0, values: {} };
  const values = { ...cached.values, ...patch };
  if (JSON.stringify(values) === JSON.stringify(cached.values)) return;
  save(scope, { ...cached, values, error: undefined,
    pending: { expected_revision: cached.revision, operation_id: operation(), values } });
}

/** Serialized CAS writes retain newer edits made while a request was running. */
export function flushPreferenceScope(scope: PreferenceScope): Promise<void> {
  const cached = read()[scope];
  if (activeStorageAccount() === null || navigator.onLine === false || !cached?.pending || cached.conflict) return Promise.resolve();
  const owner = storageGeneration();
  const lockKey = `${owner}:${scope}`;
  const existing = locks.get(lockKey);
  if (existing) return existing;
  const run = (async () => {
    if (activeStorageAccount() === null || navigator.onLine === false) return;
    while (owner === storageGeneration()) {
      const cached = read()[scope];
      if (!cached?.pending || cached.conflict) return;
      const pending = cached.pending;
      try {
        const response = (await apiClient.put<PreferenceResponse>(endpoint(scope), pending)).data;
        if (owner !== storageGeneration()) return;
        if (!responseValid(response, scope)) throw new Error("Invalid settings response");
        const latest = read()[scope];
        if (!latest) return;
        if (latest.revision > response.revision) {
          if (latest.pending?.operation_id === pending.operation_id) save(scope, { ...latest, pending: undefined });
          continue;
        }
        if (latest.pending?.operation_id === pending.operation_id) save(scope, response);
        else save(scope, { ...latest, revision: response.revision,
          pending: latest.pending ? { ...latest.pending, expected_revision: response.revision } : undefined });
      } catch (error) {
        if (owner !== storageGeneration()) return;
        const latest = read()[scope];
        if (!latest) return;
        const current = axios.isAxiosError(error) ? error.response?.data?.detail?.current : null;
        if (axios.isAxiosError(error) && error.response?.status === 409 && responseValid(current, scope)) {
          save(scope, { ...latest, conflict: current, error: undefined });
        } else {
          save(scope, { ...latest, error: axios.isAxiosError(error) && [401, 403].includes(error.response?.status ?? 0)
            ? "Sign in again to synchronize settings." : "Settings are saved on this device and will retry when connected." });
        }
        return;
      }
    }
  })().finally(() => locks.delete(lockKey));
  locks.set(lockKey, run);
  return run;
}

export async function resolvePreferenceConflict(scope: PreferenceScope, choice: "account" | "device") {
  const cached = read()[scope];
  if (!cached?.conflict) return;
  if (choice === "account") save(scope, cached.conflict);
  else {
    save(scope, { scope, revision: cached.conflict.revision, values: cached.values,
      pending: { expected_revision: cached.conflict.revision, operation_id: operation(), values: cached.values } });
    await flushPreferenceScope(scope);
  }
}

export function installReaderPreferenceSync(novelId: number, initial: { global: PreferenceValues; story: PreferenceValues; publishLocal?: { global: boolean; story: boolean } }, apply: (scope: PreferenceScope, values: PreferenceValues) => void, status: (value: PreferenceSyncStatus) => void) {
  const scopes: PreferenceScope[] = ["global", `story:${novelId}`];
  const owner = storageGeneration();
  let active = true;
  const seen = new Map<PreferenceScope, string>();
  for (const scope of scopes) if (!read()[scope]) save(scope, { scope, revision: 0, values: scope === "global" ? initial.global : initial.story });
  const notify = () => {
    if (!active || owner !== storageGeneration()) return;
    for (const scope of scopes) {
      const cached = read()[scope];
      if (!cached || cached.pending || cached.conflict || cached.revision === 0) continue;
      const key = JSON.stringify([cached.revision, cached.values]);
      if (seen.get(scope) === key) continue;
      seen.set(scope, key);
      apply(scope, cached.values);
    }
    status(preferenceSyncStatus(scopes));
  };
  const sync = async () => {
    if (!active || activeStorageAccount() === null || owner !== storageGeneration() || navigator.onLine === false) return;
    for (const scope of scopes) {
      await flushPreferenceScope(scope);
      if (!active || owner !== storageGeneration()) return;
      if (read()[scope]?.pending) continue;
      try {
        const response = (await apiClient.get<PreferenceResponse>(endpoint(scope))).data;
        if (!active || owner !== storageGeneration()) return;
        // A local edit made during the GET must not be replaced by its result.
        const existing = read()[scope];
        if (existing && !existing.pending && responseValid(response, scope) && response.revision >= existing.revision) {
          const hasLocal = scope === "global" ? initial.publishLocal?.global : initial.publishLocal?.story;
          if (existing.revision === 0 && hasLocal && JSON.stringify(existing.values) !== JSON.stringify(response.values)) {
            save(scope, { ...existing, error: undefined,
              pending: { expected_revision: 0, operation_id: operation(), values: existing.values },
              conflict: response.revision > 0 ? response : undefined });
            await flushPreferenceScope(scope);
          } else if (response.revision > 0) save(scope, response);
          else save(scope, { ...existing, error: undefined });
        }
      } catch {
        const existing = read()[scope];
        if (active && owner === storageGeneration() && existing) save(scope, { ...existing, error: "Settings remain available on this device; the account service is unavailable." });
      }
    }
    notify();
  };
  const localPatch = (event: Event) => {
    const detail = (event as CustomEvent<{ patch: PreferenceValues }>).detail;
    if (!active || owner !== storageGeneration() || !detail?.patch) return;
    queuePreferencePatch("global", detail.patch);
    void flushPreferenceScope("global");
  };
  const flushAll = () => { void sync(); };
  window.addEventListener(PREFERENCE_CHANGED, notify);
  window.addEventListener(PREFERENCE_LOCAL_PATCH, localPatch);
  window.addEventListener("online", flushAll);
  window.addEventListener("focus", flushAll);
  const storageChanged = (event: StorageEvent) => { if (event.key === accountStorageKey(PREFERENCE_CACHE_KEY)) notify(); };
  window.addEventListener("storage", storageChanged);
  notify();
  void sync();
  return () => {
    active = false;
    window.removeEventListener(PREFERENCE_CHANGED, notify);
    window.removeEventListener(PREFERENCE_LOCAL_PATCH, localPatch);
    window.removeEventListener("online", flushAll);
    window.removeEventListener("focus", flushAll);
    window.removeEventListener("storage", storageChanged);
  };
}

/** Pending settings also flush after launch/reconnection outside the reader. */
export function installPreferenceQueueSync() {
  const flush = () => {
    if (activeStorageAccount() === null) return;
    for (const scope of Object.keys(read())) if (scopeValid(scope)) void flushPreferenceScope(scope);
  };
  window.addEventListener("online", flush);
  window.addEventListener("focus", flush);
  const unsubscribe = onAccountStorageChange(flush);
  flush();
  return () => { unsubscribe(); window.removeEventListener("online", flush); window.removeEventListener("focus", flush); };
}
