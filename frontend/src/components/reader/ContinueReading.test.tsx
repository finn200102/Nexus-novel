import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ContinueReading from "./ContinueReading";
import apiClient from "../../services/apiClient";

vi.mock("../../services/apiClient", () => ({
  default: { get: vi.fn() },
}));

const getMock = vi.mocked(apiClient.get);

const LocationProbe = () => {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
};

const renderRow = () =>
  render(
    <MemoryRouter initialEntries={["/home"]}>
      <Routes>
        <Route path="/home" element={<ContinueReading />} />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );

describe("ContinueReading", () => {
  beforeEach(() => {
    getMock.mockReset();
  });

  it("requests the recent progress list and renders a card per story", async () => {
    getMock.mockResolvedValue({
      data: [
        { novel_id: 4, novel_title: "Ashes of Vael", library_id: 2, chapter_number: 42, position: 900, percent: 42.4, updated_at: "2026-10-01T10:00:00Z" },
        { novel_id: 9, novel_title: "Tidewalker", library_id: 2, chapter_number: 7, position: 0, percent: 3, updated_at: "2026-09-30T10:00:00Z" },
      ],
    });
    renderRow();

    expect(getMock).toHaveBeenCalledWith("/chapter/progress/recent", { params: { limit: 8 } });
    expect(await screen.findByRole("heading", { name: "Ashes of Vael" })).toBeTruthy();
    expect(screen.getByText("Chapter 42 · 42%")).toBeTruthy();
    expect(screen.getByText("Chapter 7 · 3%")).toBeTruthy();
  });

  it("opens the reader at the saved chapter when a card is tapped", async () => {
    getMock.mockResolvedValue({
      data: [{ novel_id: 4, novel_title: "Ashes of Vael", library_id: 2, chapter_number: 42, position: 900, percent: 42, updated_at: "" }],
    });
    renderRow();
    fireEvent.click(await screen.findByRole("button", { name: /Ashes of Vael/ }));
    await waitFor(() => expect(screen.getByTestId("location").textContent).toBe("/library/2/novels/4/42"));
  });

  it("renders nothing when there is no history", async () => {
    getMock.mockResolvedValue({ data: [] });
    const { container } = renderRow();
    await waitFor(() => expect(getMock).toHaveBeenCalled());
    expect(container.querySelector("section")).toBeNull();
  });

  it("renders nothing when the request fails", async () => {
    getMock.mockRejectedValue(new Error("offline"));
    const { container } = renderRow();
    await waitFor(() => expect(getMock).toHaveBeenCalled());
    expect(container.querySelector("section")).toBeNull();
  });
});
