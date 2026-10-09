import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import HighlightsExport from "./HighlightsExport";
import { highlightsExportService } from "../../services/highlightsExportService";

const addToast = vi.fn();
vi.mock("../../context/useToast", () => ({ useToast: () => ({ addToast }) }));
vi.mock("../../services/highlightsExportService", () => ({
  highlightsExportService: {
    readwiseStatus: vi.fn(),
    connectReadwise: vi.fn(),
    disconnectReadwise: vi.fn(),
    syncReadwise: vi.fn(),
    downloadLibraryZip: vi.fn(),
    downloadStoryNotes: vi.fn(),
  },
}));

const service = vi.mocked(highlightsExportService);

describe("HighlightsExport", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    service.readwiseStatus.mockResolvedValue({ connected: false });
  });

  it("downloads the Markdown zip", async () => {
    service.downloadLibraryZip.mockResolvedValue(undefined);
    render(<HighlightsExport />);

    fireEvent.click(await screen.findByRole("button", { name: "Download Markdown zip" }));

    await waitFor(() => expect(service.downloadLibraryZip).toHaveBeenCalledTimes(1));
  });

  it("asks for a token when Readwise is not connected and connects with it", async () => {
    service.connectReadwise.mockResolvedValue({ connected: true });
    render(<HighlightsExport />);

    const input = await screen.findByLabelText("Readwise access token");
    fireEvent.change(input, { target: { value: "  rw-token-abcdef  " } });
    fireEvent.click(screen.getByRole("button", { name: "Test and connect" }));

    await waitFor(() => expect(service.connectReadwise).toHaveBeenCalledWith("rw-token-abcdef"));
    expect(await screen.findByRole("button", { name: "Sync now" })).toBeTruthy();
    expect(addToast).toHaveBeenCalledWith("Readwise connected.", "success");
  });

  it("shows a clean error when Readwise rejects the token", async () => {
    service.connectReadwise.mockRejectedValue(Object.assign(new Error("x"), { response: { data: { detail: "Readwise rejected this token" } } }));
    render(<HighlightsExport />);

    fireEvent.change(await screen.findByLabelText("Readwise access token"), { target: { value: "bad-token-value" } });
    fireEvent.click(screen.getByRole("button", { name: "Test and connect" }));

    expect(await screen.findByText("Readwise did not accept this token.")).toBeTruthy();
    expect(service.syncReadwise).not.toHaveBeenCalled();
  });

  it("syncs now when connected and reports the count", async () => {
    service.readwiseStatus.mockResolvedValue({ connected: true });
    service.syncReadwise.mockResolvedValue({ exported: 3 });
    render(<HighlightsExport />);

    fireEvent.click(await screen.findByRole("button", { name: "Sync now" }));

    await waitFor(() => expect(addToast).toHaveBeenCalledWith("Sent 3 highlights to Readwise.", "success"));
  });
});
