import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AutoDownloadToggle from "./AutoDownloadToggle";
import { organizationService } from "../../services/organizationService";

vi.mock("../../services/organizationService", () => ({
  organizationService: {
    getPersonal: vi.fn(),
    savePersonal: vi.fn(),
  },
}));

describe("AutoDownloadToggle", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(organizationService.getPersonal).mockResolvedValue({
      novel_id: 7,
      notes: "Keep this note",
      rating: 4,
      user_tags: ["cozy"],
      auto_download: false,
      keep_ahead: 10,
    } as Awaited<ReturnType<typeof organizationService.getPersonal>>);
    vi.mocked(organizationService.savePersonal).mockResolvedValue({} as Awaited<ReturnType<typeof organizationService.savePersonal>>);
  });

  it("saves only the download settings, not the notes, rating or tags", async () => {
    render(<AutoDownloadToggle novelId={7} />);
    const toggle = await screen.findByRole("switch", { name: /Download new chapters automatically/ });

    fireEvent.click(toggle);

    await waitFor(() => expect(organizationService.savePersonal).toHaveBeenCalledWith(7, { auto_download: true, keep_ahead: 10 }));
    expect(organizationService.getPersonal).toHaveBeenCalledTimes(1);
  });
});
