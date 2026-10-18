import { beforeEach, expect, it, vi } from "vitest";
import apiClient from "./apiClient";
import { chapterService } from "./chapterService";
vi.mock("./apiClient", () => ({ default: { get: vi.fn() } }));
vi.mock("./progressSyncQueue", async () => ({ ...await vi.importActual<typeof import("./progressSyncQueue")>("./progressSyncQueue"), installProgressSync: vi.fn(() => () => undefined) }));
beforeEach(() => vi.clearAllMocks());
it("requests bounded metadata pages without altering signed chapter numbers", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ data: [{ id: 4, chapter_number: -2 }] });
  expect(await chapterService.getChapters(42, { skip: 1000, limit: 1000 })).toEqual([{ id: 4, chapter_number: -2 }]);
  expect(apiClient.get).toHaveBeenCalledWith("/chapter/42", { params: { skip: 1000, limit: 1000 } });
});
it("uses exact zero and negative navigation routes", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ data: { chapter_number: 0, next: { chapter_number: 20007 } } });
  expect(await chapterService.getNavigation(42, 0)).toMatchObject({ chapter_number: 0 });
  await chapterService.getNavigation(42, -2);
  expect(vi.mocked(apiClient.get).mock.calls.map(call => call[0])).toEqual(["/chapter/navigation/42/0", "/chapter/navigation/42/-2"]);
});
it("loads exact recorded summary and bounded searchable chapter records without interpreting labels as counts", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ data: { novel_id:42,total_chapters:2001,completed_chapters:1,current:{chapter_number:20007,ordinal:2} } });
  expect(await chapterService.getReadingSummary(42)).toMatchObject({ completed_chapters:1,current:{chapter_number:20007} });
  await chapterService.getReadingChapters(42,{offset:1000,limit:200,q:"-2_%",category_scope:"all"});
  expect(apiClient.get).toHaveBeenCalledWith("/chapter/reading-summary/42");
  expect(apiClient.get).toHaveBeenCalledWith("/chapter/reading-chapters/42",{params:{offset:1000,limit:200,q:"-2_%",category_scope:"all"}});
});
