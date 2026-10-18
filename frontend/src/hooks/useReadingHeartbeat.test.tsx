import { act, renderHook, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import apiClient from "../services/apiClient";
import { activateAccountStorage } from "../services/accountStorage";
import { readingActivityService as service } from "../services/readingActivityService";
import { useReadingHeartbeat } from "./useReadingHeartbeat";
vi.mock("../services/apiClient", () => ({ default: { get: vi.fn(), put: vi.fn(), post: vi.fn() } }));
let account = 300;
const response = (enabled: boolean, revision = 0) => ({ data: { revision, values: { tracking_enabled: enabled } } });
beforeEach(() => {
  vi.useFakeTimers(); vi.setSystemTime(new Date("2026-10-16T10:00:00Z")); vi.clearAllMocks();
  localStorage.clear(); activateAccountStorage(++account);
  vi.mocked(apiClient.get).mockResolvedValue(response(true)); vi.mocked(apiClient.post).mockResolvedValue({ data: {} });
});
afterEach(() => { cleanup(); activateAccountStorage(null); vi.useRealTimers(); });
const flush = () => act(async () => { await Promise.resolve(); });
const beat = () => act(async () => { window.dispatchEvent(new Event("pointerdown")); vi.advanceTimersByTime(60_000); await Promise.resolve(); });

it("records only after the server preference loads and drops paused time on resume", async () => {
  renderHook(() => useReadingHeartbeat(9, 91)); await flush(); await beat();
  expect(apiClient.post).toHaveBeenCalledTimes(1);
  expect(apiClient.post).toHaveBeenLastCalledWith("/stats/reading-time", { novel_id: 9, chapter_id: 91, seconds: 60, words_read_estimate: 250 });
  vi.mocked(apiClient.put).mockResolvedValue(response(false, 1));
  await act(async () => { await service.change(false); }); await beat(); await beat();
  expect(apiClient.post).toHaveBeenCalledTimes(1);
  vi.mocked(apiClient.put).mockResolvedValue(response(true, 2));
  await act(async () => { await service.change(true); }); await beat();
  expect(apiClient.post).toHaveBeenCalledTimes(2);
  expect(vi.mocked(apiClient.post).mock.calls[1][1]).toMatchObject({ seconds: 60 });
});

it("never emits measurements when the setting is unknown or has an unconfirmed disable", async () => {
  vi.mocked(apiClient.get).mockRejectedValueOnce(new Error("offline"));
  renderHook(() => useReadingHeartbeat(9, 91)); await flush(); await beat(); expect(apiClient.post).not.toHaveBeenCalled();
  await act(async () => { await service.load(); });
  vi.mocked(apiClient.put).mockRejectedValueOnce(new Error("lost acknowledgement"));
  await act(async () => { await service.change(false); }); await beat(); expect(apiClient.post).not.toHaveBeenCalled();
});

it("does not report an old chapter under a new account, even if its setting is enabled", async () => {
  const hook = renderHook(({ chapter }) => useReadingHeartbeat(9, chapter), { initialProps: { chapter: 91 } });
  await flush(); await beat(); expect(apiClient.post).toHaveBeenCalledTimes(1);
  act(() => activateAccountStorage(++account)); await flush(); await beat();
  expect(service.canTrack()).toBe(true); expect(apiClient.post).toHaveBeenCalledTimes(1);
  hook.rerender({ chapter: 92 }); await beat(); expect(apiClient.post).toHaveBeenCalledTimes(2);
  expect(vi.mocked(apiClient.post).mock.calls[1][1]).toMatchObject({ chapter_id: 92 });
});
