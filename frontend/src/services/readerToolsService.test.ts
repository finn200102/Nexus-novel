import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient, { getUserFacingError } from "./apiClient";
import { readerToolsService } from "./readerToolsService";
vi.mock("./apiClient", async importOriginal => ({ ...await importOriginal<typeof import("./apiClient")>(), default: { post: vi.fn() } }));
describe("translated story EPUB transport", () => {
  beforeEach(() => vi.clearAllMocks());
  it("preserves server JSON details returned as an error Blob", async () => {
    const body = Object.assign(new Blob(['{"detail":"Select fewer chapters: export exceeds 40 MiB."}'], { type: "application/json" }), { text: async () => '{"detail":"Select fewer chapters: export exceeds 40 MiB."}' });
    const error = { isAxiosError: true, response: { status: 422, data: body } };
    vi.mocked(apiClient.post).mockRejectedValue(error);
    await expect(readerToolsService.exportStoryTranslations(11, [4, 7])).rejects.toBe(error);
    expect(getUserFacingError(error, "Fallback")).toBe("Select fewer chapters: export exceeds 40 MiB.");
    expect(apiClient.post).toHaveBeenCalledWith("/reader/stories/11/translations/epub", { translation_job_ids: [4, 7] }, { responseType: "blob" });
  });
  it("keeps malformed or oversized error bodies bounded and preserves the transport error", async () => {
    const text = vi.fn(async () => "x"), body = Object.assign(new Blob(["x".repeat(65537)], { type: "application/json" }), { text });
    const error = { isAxiosError: true, response: { status: 422, data: body } }; vi.mocked(apiClient.post).mockRejectedValue(error);
    await expect(readerToolsService.exportStoryTranslations(11, [4])).rejects.toBe(error); expect(text).not.toHaveBeenCalled();
  });
});
