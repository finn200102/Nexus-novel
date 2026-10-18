import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "./apiClient";
import { insightService, signedGuideChapter } from "./insightService";
vi.mock("./apiClient", () => ({ default: { get: vi.fn(), post: vi.fn() } }));
describe("signed and evidence-bounded guide requests", () => {
  beforeEach(() => { vi.clearAllMocks(); vi.mocked(apiClient.get).mockResolvedValue({ data: {} }); vi.mocked(apiClient.post).mockResolvedValue({ data: {} }); });
  it.each([-2147483648, -2, 0, 2147483647])("retains source boundary %s across reader guide APIs", async (chapter) => {
    await insightService.storyGuide(42, chapter);
    await insightService.storyGuideEntities(42, chapter);
    await insightService.storyGuideRelationships(42, chapter);
    await insightService.storyGuideProjection(42, chapter);
    await insightService.storyGuideEntityProfile(42, "person", chapter);
    await insightService.storyGuideRelationshipTimeline(42, chapter);
    await insightService.storyGuideChapterDossier(42, chapter, chapter);
    await insightService.storyGuideEntityArticle(42, "person", chapter);
    expect(apiClient.get).toHaveBeenCalledTimes(8);
    for (const call of vi.mocked(apiClient.get).mock.calls) expect(call[1]?.params.through_chapter).toBe(chapter);
    await insightService.backfillStoryGuide(42, chapter);
    await insightService.regenerateStoryGuide(42, chapter);
    for (const call of vi.mocked(apiClient.post).mock.calls) expect(call[2]?.params.through_chapter).toBe(chapter);
  });
  it("omits unspecified change start at the minimum signed boundary rather than wrapping or clamping", async () => {
    await insightService.storyGuideChanges(42, undefined, -2147483648);
    expect(apiClient.get).toHaveBeenCalledWith(expect.any(String), { params: { through_chapter: -2147483648 } });
    await insightService.storyGuideChanges(42, -3, -2);
    expect(apiClient.get).toHaveBeenLastCalledWith(expect.any(String), { params: { from_chapter: -3, through_chapter: -2 } });
  });
  it.each([NaN, Infinity, 0.5, 2147483648, -2147483649])("rejects invalid chapter %s before network access", async (chapter) => {
    expect(() => signedGuideChapter(chapter)).toThrow();
    await expect(insightService.storyGuide(42, chapter)).rejects.toThrow();
    await expect(insightService.storyGuideChapterDossier(42, chapter)).rejects.toThrow();
    expect(apiClient.get).not.toHaveBeenCalled();
  });
});
