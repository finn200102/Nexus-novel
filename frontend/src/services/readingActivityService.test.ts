import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "./apiClient";
import { accountStorageKey, activateAccountStorage } from "./accountStorage";
import { readingActivityService as service } from "./readingActivityService";
vi.mock("./apiClient", () => ({ default: { get: vi.fn(), put: vi.fn() } }));
const preference = (enabled: boolean, revision = 0) => ({ data: { revision, values: { tracking_enabled: enabled } } });
const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; };
let identity = 100;
beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); activateAccountStorage(++identity); });
afterEach(() => activateAccountStorage(null));

describe("reading measurement preferences", () => {
  it("pauses until the current account setting is known, and fails closed offline", async () => {
    expect(service.canTrack()).toBe(false);
    vi.mocked(apiClient.get).mockRejectedValueOnce(new Error("offline"));
    await service.load(); expect(service.canTrack()).toBe(false);
    expect(service.snapshot().error).toMatch(/paused/);
    vi.mocked(apiClient.get).mockResolvedValueOnce(preference(true));
    await service.load(); expect(service.canTrack()).toBe(true);
  });
  it("disables immediately, retains the exact operation after a lost acknowledgement and retries idempotently", async () => {
    vi.mocked(apiClient.get).mockResolvedValue(preference(true, 4)); await service.load();
    vi.mocked(apiClient.put).mockRejectedValueOnce(new Error("lost response"));
    const attempt = service.change(false); expect(service.canTrack()).toBe(false); await attempt;
    const first = vi.mocked(apiClient.put).mock.calls[0][1];
    expect(first).toMatchObject({ expected_revision: 4, values: { tracking_enabled: false } });
    expect(service.snapshot().pending).not.toBeNull();
    expect(localStorage.getItem(accountStorageKey("reading-activity-pending"))).toBe(JSON.stringify(first));
    vi.mocked(apiClient.get).mockResolvedValue(preference(false, 5));
    vi.mocked(apiClient.put).mockResolvedValueOnce(preference(false, 5)); await service.retry();
    expect(vi.mocked(apiClient.put).mock.calls[1][1]).toEqual(first);
    expect(service.snapshot().pending).toBeNull(); expect(service.canTrack()).toBe(false);
    expect(localStorage.getItem(accountStorageKey("reading-activity-pending"))).toBeNull();
  });
  it("cannot re-enable measurement with an automatic refresh while an uncertain request is pending", async () => {
    vi.mocked(apiClient.get).mockResolvedValue(preference(true)); await service.load();
    vi.mocked(apiClient.put).mockRejectedValueOnce(new Error("offline")); await service.change(false);
    await service.load(); expect(service.canTrack()).toBe(false); expect(service.snapshot().pending).not.toBeNull();
    await service.useServerSetting(); expect(service.canTrack()).toBe(true); expect(service.snapshot().pending).toBeNull();
  });
  it("does not mistake an old replay receipt for the current setting on another device", async () => {
    vi.mocked(apiClient.get).mockResolvedValue(preference(true, 4)); await service.load();
    vi.mocked(apiClient.put).mockRejectedValueOnce(new Error("lost response")); await service.change(false);
    vi.mocked(apiClient.put).mockResolvedValueOnce(preference(false, 5));
    vi.mocked(apiClient.get).mockResolvedValue(preference(true, 6)); await service.retry();
    expect(service.snapshot().preferences?.revision).toBe(6);
    expect(service.snapshot().pending?.values.tracking_enabled).toBe(false);
    expect(service.canTrack()).toBe(false); expect(service.snapshot().error).toMatch(/another device/);
  });
  it("ignores responses for a reader who has since signed out or switched accounts", async () => {
    const delayed = deferred<ReturnType<typeof preference>>();
    vi.mocked(apiClient.get).mockReturnValueOnce(delayed.promise);
    const loading = service.load(); activateAccountStorage(++identity);
    delayed.resolve(preference(true, 9)); await loading;
    expect(service.snapshot().preferences).toBeNull(); expect(service.canTrack()).toBe(false);
    vi.mocked(apiClient.get).mockResolvedValue(preference(true)); await service.load();
    const saving = deferred<ReturnType<typeof preference>>(); vi.mocked(apiClient.put).mockReturnValueOnce(saving.promise);
    const changing = service.change(false); activateAccountStorage(++identity);
    saving.resolve(preference(false, 8)); await changing;
    expect(service.snapshot().preferences).toBeNull(); expect(service.snapshot().pending).toBeNull();
  });
  it("does not let focus refresh cancel an in-flight preference acknowledgement", async () => {
    vi.mocked(apiClient.get).mockResolvedValue(preference(false, 2)); await service.load();
    const saving = deferred<ReturnType<typeof preference>>(); vi.mocked(apiClient.put).mockReturnValueOnce(saving.promise);
    const changing = service.change(true); await service.load();
    expect(apiClient.get).toHaveBeenCalledTimes(1); expect(service.canTrack()).toBe(false);
    saving.resolve(preference(true, 3)); await changing;
    expect(service.canTrack()).toBe(true); expect(service.snapshot().busy).toBe(false);
  });
  it("honors a pending disable from another tab and ignores another account's storage event", async () => {
    vi.mocked(apiClient.get).mockResolvedValue(preference(true)); await service.load();
    window.dispatchEvent(new StorageEvent("storage", { key: "unrelated-account" })); expect(service.canTrack()).toBe(true);
    const key = accountStorageKey("reading-activity-pending");
    localStorage.setItem(key, JSON.stringify({ expected_revision: 0, operation_id: "other-tab", values: { tracking_enabled: false } }));
    window.dispatchEvent(new StorageEvent("storage", { key })); await vi.waitFor(() => expect(service.snapshot().loaded).toBe(true));
    expect(service.canTrack()).toBe(false); expect(service.snapshot().pending?.operation_id).toBe("other-tab");
  });
});
