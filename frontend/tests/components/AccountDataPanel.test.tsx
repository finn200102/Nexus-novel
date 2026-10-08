import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AccountDataPanel from "../../src/components/account/AccountDataPanel";
import { userDataService, type UserDataImportReport } from "../../src/services/userDataService";

const mocks = vi.hoisted(() => ({
  addToast: vi.fn(),
  refreshLibraries: vi.fn(),
}));

vi.mock("../../src/context/useToast", () => ({
  useToast: () => ({ addToast: mocks.addToast }),
}));

vi.mock("../../src/context/useLibraryContext", () => ({
  useLibraryContext: () => ({ refreshLibraries: mocks.refreshLibraries }),
}));

vi.mock("../../src/services/userDataService", () => ({
  userDataService: {
    exportData: vi.fn(),
    importData: vi.fn(),
  },
}));

const report: UserDataImportReport = {
  format: "nexus-user-export",
  version: 1,
  summary: { novels_created: 1, novels_failed: 1, annotations_deferred: 2, saved_searches_conflicts: 1 },
  libraries: [
    {
      name: "Reading",
      status: "created",
      novels: [
        {
          url: "https://www.royalroad.com/fiction/21220/mother-of-learning",
          title: "Mother of Learning",
          status: "created",
          reason: null,
          follow_state: "updated",
          progress: "applied",
          history: { added: 2, updated: 0, unchanged: 0 },
          annotations: { added: 0, duplicate: 0, deferred: 2 },
        },
        {
          url: "https://example.com/story/1",
          title: null,
          status: "failed",
          reason: "Not a supported source url",
          follow_state: null,
          progress: null,
          history: { added: 0, updated: 0, unchanged: 0 },
          annotations: { added: 0, duplicate: 0, deferred: 0 },
        },
      ],
    },
  ],
  saved_searches: [{ name: "Time loops", status: "conflict" }],
};

const fileWithText = (text: string) => ({ text: () => Promise.resolve(text) }) as unknown as File;

describe("AccountDataPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("downloads the export as a JSON file", async () => {
    vi.mocked(userDataService.exportData).mockResolvedValue({
      format: "nexus-user-export",
      version: 1,
      exported_at: "2026-10-08T00:00:00Z",
      libraries: [],
      saved_searches: [],
    });
    const createObjectURL = vi.fn(() => "blob:nexus-export");
    const revokeObjectURL = vi.fn();
    Object.assign(URL, { createObjectURL, revokeObjectURL });
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    render(<AccountDataPanel />);
    fireEvent.click(screen.getByRole("button", { name: /export my data/i }));

    await waitFor(() => expect(clickSpy).toHaveBeenCalledTimes(1));
    expect(userDataService.exportData).toHaveBeenCalledOnce();
    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:nexus-export");
    expect(mocks.addToast).toHaveBeenCalledWith("Your data export is downloading", "success");

    clickSpy.mockRestore();
  });

  it("imports a chosen file and shows the per-item report", async () => {
    const payload = { format: "nexus-user-export", version: 1, libraries: [] };
    vi.mocked(userDataService.importData).mockResolvedValue(report);
    const { container } = render(<AccountDataPanel />);

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [fileWithText(JSON.stringify(payload))] } });

    expect(await screen.findByRole("status")).toBeInTheDocument();
    expect(userDataService.importData).toHaveBeenCalledWith(payload);
    expect(mocks.refreshLibraries).toHaveBeenCalledOnce();
    expect(screen.getByText("Novels added").nextElementSibling).toHaveTextContent("1");
    expect(screen.getByText("Novels not imported").nextElementSibling).toHaveTextContent("1");
    expect(screen.getByText(/Not a supported source url/)).toBeInTheDocument();
    expect(screen.getByText(/Time loops/)).toBeInTheDocument();
  });

  it("explains when the chosen file is not JSON and does not call the API", async () => {
    const { container } = render(<AccountDataPanel />);

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [fileWithText("not json")] } });

    await waitFor(() =>
      expect(mocks.addToast).toHaveBeenCalledWith("That file is not a Nexus data export", "error")
    );
    expect(userDataService.importData).not.toHaveBeenCalled();
  });
});
