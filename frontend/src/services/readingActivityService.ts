import axios from "axios";
import apiClient from "./apiClient";
import { accountStorage, accountStorageKey, activeStorageAccount, onAccountStorageChange, storageGeneration } from "./accountStorage";
import { readingJournalOperationId } from "./readingJournalService";

import type { ActivityWrite, ReadingActivityPreferenceResponse } from "../generated/api";
export type ReadingActivityPreferences = ReadingActivityPreferenceResponse;
type PreferenceWrite = ActivityWrite & { values: Required<ActivityWrite["values"]> };
interface ActivityState {
  generation: number;
  preferences: ReadingActivityPreferences | null;
  pending: PreferenceWrite | null;
  loaded: boolean;
  busy: boolean;
  error: string;
}
const PENDING_KEY = "reading-activity-pending";
const listeners = new Set<() => void>();
let epoch = 0;
function pendingFromStorage(): PreferenceWrite | null {
  try {
    const value = JSON.parse(accountStorage.getItem(PENDING_KEY) || "null");
    if (value && Number.isSafeInteger(value.expected_revision) && value.expected_revision >= 0 && typeof value.operation_id === "string" && value.operation_id.length <= 128 && typeof value.values?.tracking_enabled === "boolean") return value;
  } catch { /* Unavailable or invalid private storage cannot enable tracking. */ }
  return null;
}
let state: ActivityState = { generation: storageGeneration(), preferences: null, pending: pendingFromStorage(), loaded: false, busy: false, error: "" };
function publish(next: Partial<ActivityState>) { state = { ...state, ...next }; for (const listener of listeners) listener(); }
function storePending(value: PreferenceWrite | null) {
  try { if (value) accountStorage.setItem(PENDING_KEY, JSON.stringify(value)); else accountStorage.removeItem(PENDING_KEY); } catch { /* In-memory intent remains effective in this tab. */ }
}
function valid(value: ReadingActivityPreferences) {
  if (!value || !Number.isSafeInteger(value.revision) || value.revision < 0 || typeof value.values?.tracking_enabled !== "boolean") throw new Error("Invalid reading activity setting");
  return value;
}
onAccountStorageChange(() => {
  epoch++;
  publish({ generation: storageGeneration(), preferences: null, pending: pendingFromStorage(), loaded: false, busy: false, error: "" });
});

export const readingActivityService = {
  subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
  snapshot: () => state,
  canTrack: () => activeStorageAccount() !== null && state.generation === storageGeneration() && state.loaded && !!state.preferences?.values.tracking_enabled && state.pending === null,
  async load() {
    if (activeStorageAccount() === null || state.busy) return;
    const generation = storageGeneration(), version = ++epoch;
    publish({ loaded: false, error: "" });
    try {
      const data = valid((await apiClient.get<ReadingActivityPreferences>("/stats/preferences")).data);
      if (generation === storageGeneration() && version === epoch) publish({ preferences: data, loaded: true });
    } catch {
      if (generation === storageGeneration() && version === epoch) publish({ loaded: false, error: "Could not check your reading statistics setting. This device has paused measurement until it can reconnect." });
    }
  },
  async change(enabled: boolean) {
    if (state.busy || state.pending || !state.loaded || !state.preferences) return;
    const pending = { expected_revision: state.preferences.revision, operation_id: readingJournalOperationId(), values: { tracking_enabled: enabled } };
    storePending(pending); epoch++;
    publish({ pending, error: "" });
    await readingActivityService.retry(false);
  },
  async retry(reconcileReceipt = true) {
    if (state.busy || !state.pending || activeStorageAccount() === null) return;
    const pending = state.pending, generation = storageGeneration(), version = ++epoch;
    publish({ busy: true, error: "" });
    try {
      let data = valid((await apiClient.put<ReadingActivityPreferences>("/stats/preferences", pending)).data);
      if (generation !== storageGeneration() || version !== epoch) return;
      if (reconcileReceipt) {
        // An idempotent receipt can describe an older, successful change. A
        // second device may have changed the setting after that operation.
        data = valid((await apiClient.get<ReadingActivityPreferences>("/stats/preferences")).data);
        if (generation !== storageGeneration() || version !== epoch) return;
        if (data.values.tracking_enabled !== pending.values.tracking_enabled) {
          publish({ preferences: data, loaded: true, busy: false, error: "This setting changed on another device. Measurement stays paused here. Reload the current setting to review it before making another change." });
          return;
        }
      }
      if (generation !== storageGeneration() || version !== epoch) return;
      storePending(null);
      publish({ preferences: data, pending: null, loaded: true, busy: false });
    } catch (err) {
      if (generation !== storageGeneration() || version !== epoch) return;
      const conflict = axios.isAxiosError(err) && err.response?.status === 409;
      publish({ busy: false, error: conflict ? "This setting changed on another device. Measurement stays paused here. Reload the current setting to review it before making another change." : "The change could not be confirmed. Measurement stays paused here. Retry the same change to check it safely." });
    }
  },
  async useServerSetting() {
    if (state.busy) return;
    // Explicit reconciliation, never performed by a background refresh.
    storePending(null); epoch++;
    publish({ pending: null, loaded: false, error: "" });
    await readingActivityService.load();
  },
};

if (typeof window !== "undefined") {
  window.addEventListener("storage", event => {
    if (event.key !== accountStorageKey(PENDING_KEY)) return;
    epoch++;
    publish({ pending: pendingFromStorage(), busy: false, loaded: false });
    void readingActivityService.load();
  });
}
