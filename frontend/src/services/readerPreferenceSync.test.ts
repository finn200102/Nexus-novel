import { waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "./apiClient";
import { accountStorage, activateAccountStorage } from "./accountStorage";
import { flushPreferenceScope, installPreferenceQueueSync, installReaderPreferenceSync, PREFERENCE_CACHE_KEY, preferenceSyncStatus, queuePreferencePatch, resolvePreferenceConflict } from "./readerPreferenceSync";

vi.mock("./apiClient", () => ({ default: { get: vi.fn(), put: vi.fn() } }));
const cleanups: Array<() => void> = [];
const records = () => JSON.parse(accountStorage.getItem(PREFERENCE_CACHE_KEY) || "{}");
const response = (revision: number, fontSize: number) => ({ scope: "global" as const, revision, values: { typography: { fontSize } } });
const conflict = (current: unknown) => ({ isAxiosError: true, response: { status: 409, data: { detail: { current } } } });

beforeEach(() => {
  vi.resetAllMocks();
  localStorage.clear();
  activateAccountStorage(51);
  vi.spyOn(navigator, "onLine", "get").mockReturnValue(true);
  vi.mocked(apiClient.get).mockImplementation(async (url) => ({ data: { scope: String(url).includes("stories") ? "story:1" : "global", revision: 0, values: {} } }) as never);
});
afterEach(() => { cleanups.splice(0).forEach(cleanup => cleanup()); vi.restoreAllMocks(); });

describe("reader preference synchronization", () => {
  it("keeps reading and synchronization functional when browser storage is blocked", async () => {
    vi.spyOn(accountStorage, "setItem").mockImplementation(() => { throw new DOMException("Quota exceeded", "QuotaExceededError"); });
    expect(() => queuePreferencePatch("global", { typography: { fontSize: 22 } })).not.toThrow();
    expect(preferenceSyncStatus()).toMatchObject({ pending: 1, memoryOnly: true });
    vi.mocked(apiClient.put).mockResolvedValue({ data: response(1, 22) });
    await flushPreferenceScope("global");
    expect(preferenceSyncStatus()).toMatchObject({ pending: 0, memoryOnly: true });
    activateAccountStorage(52);
    expect(preferenceSyncStatus().pending).toBe(0);
  });
  it("keeps offline changes and flushes them after reconnection outside the reader", async () => {
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    queuePreferencePatch("global", { typography: { fontSize: 22 } });
    await flushPreferenceScope("global");
    expect(apiClient.put).not.toHaveBeenCalled();
    expect(preferenceSyncStatus().pending).toBe(1);
    cleanups.push(installPreferenceQueueSync());
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(true);
    vi.mocked(apiClient.put).mockResolvedValue({ data: response(1, 22) });
    window.dispatchEvent(new Event("online"));
    await waitFor(() => expect(preferenceSyncStatus().pending).toBe(0));
    expect(apiClient.put).toHaveBeenCalledWith("/reader/preferences", expect.objectContaining({ expected_revision: 0, values: { typography: { fontSize: 22 } } }));
  });

  it("retains conflicting edits until the reader chooses account settings", async () => {
    queuePreferencePatch("global", { typography: { fontSize: 22 } });
    vi.mocked(apiClient.put).mockRejectedValueOnce(conflict(response(2, 18)));
    await flushPreferenceScope("global");
    expect(records().global.values.typography.fontSize).toBe(22);
    expect(preferenceSyncStatus().conflicts).toEqual(["global"]);
    await resolvePreferenceConflict("global", "account");
    expect(records().global.values.typography.fontSize).toBe(18);
    expect(preferenceSyncStatus().pending).toBe(0);
    expect(apiClient.put).toHaveBeenCalledOnce();
  });

  it("an intentional device choice writes against the conflicting server revision", async () => {
    queuePreferencePatch("global", { typography: { fontSize: 22 } });
    vi.mocked(apiClient.put).mockRejectedValueOnce(conflict(response(2, 18)));
    await flushPreferenceScope("global");
    vi.mocked(apiClient.put).mockResolvedValueOnce({ data: response(3, 22) });
    await resolvePreferenceConflict("global", "device");
    expect(apiClient.put).toHaveBeenLastCalledWith("/reader/preferences", expect.objectContaining({ expected_revision: 2, values: { typography: { fontSize: 22 } } }));
    expect(records().global.revision).toBe(3);
    expect(preferenceSyncStatus().conflicts).toEqual([]);
  });

  it("rebases a newer local edit after an earlier in-flight save succeeds", async () => {
    let finish!: (value: unknown) => void;
    const pending = new Promise(done => { finish = done; });
    queuePreferencePatch("global", { typography: { fontSize: 20 } });
    vi.mocked(apiClient.put).mockReturnValueOnce(pending as never).mockResolvedValueOnce({ data: response(2, 24) });
    const flushed = flushPreferenceScope("global");
    queuePreferencePatch("global", { typography: { fontSize: 24 } });
    finish({ data: response(1, 20) });
    await flushed;
    expect(apiClient.put).toHaveBeenCalledTimes(2);
    expect(apiClient.put).toHaveBeenLastCalledWith("/reader/preferences", expect.objectContaining({ expected_revision: 1, values: { typography: { fontSize: 24 } } }));
    expect(records().global.values.typography.fontSize).toBe(24);
    expect(preferenceSyncStatus().pending).toBe(0);
  });

  it("ignores an old account's save result and never sends its next queued scope", async () => {
    let finish!: (value: unknown) => void;
    const pending = new Promise(done => { finish = done; });
    queuePreferencePatch("global", { typography: { fontSize: 20 } });
    vi.mocked(apiClient.put).mockReturnValueOnce(pending as never);
    const flushed = flushPreferenceScope("global");
    activateAccountStorage(52);
    queuePreferencePatch("global", { typography: { fontSize: 26 } });
    finish({ data: response(1, 20) });
    await flushed;
    expect(records().global.values.typography.fontSize).toBe(26);
    expect(records().global.pending).toBeDefined();
    expect(apiClient.put).toHaveBeenCalledOnce();
  });

  it("preserves local pre-sync settings when another device already published preferences", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: response(1, 18) }).mockResolvedValueOnce({ data: { scope: "story:1", revision: 0, values: {} } });
    cleanups.push(installReaderPreferenceSync(1, { global: { typography: { fontSize: 24 } }, story: {}, publishLocal: { global: true, story: false } }, vi.fn(), vi.fn()));
    await waitFor(() => expect(preferenceSyncStatus().conflicts).toEqual(["global"]));
    expect(records().global.values.typography.fontSize).toBe(24);
    expect(apiClient.put).not.toHaveBeenCalled();
  });

  it("publishes existing local preferences when the account has none", async () => {
    vi.mocked(apiClient.put).mockResolvedValueOnce({ data: response(1, 24) });
    cleanups.push(installReaderPreferenceSync(1, { global: { typography: { fontSize: 24 } }, story: {}, publishLocal: { global: true, story: false } }, vi.fn(), vi.fn()));
    await waitFor(() => expect(records().global.revision).toBe(1));
    expect(apiClient.put).toHaveBeenCalledOnce();
  });

  it("a stale GET cannot undo a newer acknowledged preference", async () => {
    accountStorage.setItem(PREFERENCE_CACHE_KEY, JSON.stringify({ global: response(1, 18) }));
    let finish!: (value: unknown) => void;
    const pending = new Promise(done => { finish = done; });
    vi.mocked(apiClient.get).mockReturnValueOnce(pending as never).mockResolvedValueOnce({ data: { scope: "story:1", revision: 0, values: {} } });
    const apply = vi.fn();
    cleanups.push(installReaderPreferenceSync(1, { global: {}, story: {} }, apply, vi.fn()));
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledOnce());
    queuePreferencePatch("global", { typography: { fontSize: 22 } });
    vi.mocked(apiClient.put).mockResolvedValueOnce({ data: response(2, 22) });
    await flushPreferenceScope("global");
    finish({ data: response(1, 18) });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
    expect(records().global.revision).toBe(2);
    expect(records().global.values.typography.fontSize).toBe(22);
    expect(apply).toHaveBeenLastCalledWith("global", { typography: { fontSize: 22 } });
  });

  it("an older idempotent replay cannot downgrade a newer cached revision or loop", async () => {
    accountStorage.setItem(PREFERENCE_CACHE_KEY, JSON.stringify({ global: { ...response(3, 24), pending: {
      operation_id: "previously-accepted", expected_revision: 0, values: { typography: { fontSize: 20 } },
    } } }));
    vi.mocked(apiClient.put).mockResolvedValueOnce({ data: response(1, 20) }).mockRejectedValue(new Error("Unexpected repeated request"));
    await flushPreferenceScope("global");
    expect(apiClient.put).toHaveBeenCalledOnce();
    expect(records().global).toMatchObject(response(3, 24));
    expect(preferenceSyncStatus().pending).toBe(0);
  });
});
