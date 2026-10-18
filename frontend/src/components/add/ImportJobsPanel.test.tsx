import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ImportJobsPanel } from "./ImportJobsPanel";
import { liveSearchService, type ImportJob } from "../../services/liveSearchService";

vi.mock("../../services/liveSearchService", () => ({ liveSearchService: {
  jobs: vi.fn(), job: vi.fn(), previewUrls: vi.fn(), importUrls: vi.fn(), retry: vi.fn(), cancel: vi.fn(),
} }));
const job = (overrides: Partial<ImportJob> = {}): ImportJob => ({
  id: 4, library_id: 1, source: "url_list", status: "finished", total_items: 2,
  counts: { linked: 1, failed: 1 }, error: null, created_at: "2026-10-14", ...overrides,
});

describe("import center", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(liveSearchService.jobs).mockResolvedValue([]);
    vi.mocked(liveSearchService.job).mockResolvedValue(job());
  });

  it("previews links without starting an import and discards a stale preview after editing", async () => {
    vi.mocked(liveSearchService.previewUrls).mockResolvedValue({ library_id: 1, total_items: 2,
      counts: { ready: 1, duplicate: 1 }, warnings: ["Source checks happen during import."], items: [
        { position: 0, url: "https://example.org/1", title: null, status: "ready", reason: null },
        { position: 1, url: "https://example.org/1", title: null, status: "duplicate", reason: "Repeated" },
      ] });
    render(<ImportJobsPanel libraryId={1} onError={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Links or page text"), { target: { value: "https://example.org/1" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview links" }));
    expect(await screen.findByRole("region", { name: "Import preview" })).toHaveTextContent("Review 2 links");
    expect(liveSearchService.importUrls).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Links or page text"), { target: { value: "https://example.org/2" } });
    expect(screen.queryByRole("region", { name: "Import preview" })).not.toBeInTheDocument();
  });

  it("recognizes completed jobs and retries the same job", async () => {
    vi.mocked(liveSearchService.jobs).mockResolvedValue([job()]);
    vi.mocked(liveSearchService.retry).mockResolvedValue(job({ status: "queued", counts: { linked: 1, queued: 1 } }));
    render(<ImportJobsPanel libraryId={1} onError={vi.fn()} />);
    expect(await screen.findByText("Done")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry unfinished links" }));
    await waitFor(() => expect(liveSearchService.retry).toHaveBeenCalledWith(4));
    expect(await screen.findByText("Waiting")).toBeInTheDocument();
  });

  it("reports cancellation errors instead of losing an unhandled promise", async () => {
    const onError = vi.fn();
    vi.mocked(liveSearchService.jobs).mockResolvedValue([job({ status: "running" })]);
    vi.mocked(liveSearchService.cancel).mockRejectedValue(new Error("failure"));
    render(<ImportJobsPanel libraryId={1} onError={onError} />);
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(onError).toHaveBeenCalled());
  });
});
