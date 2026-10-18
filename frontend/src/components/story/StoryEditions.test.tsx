import { act, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import StoryEditions from "./StoryEditions";
import { editionReviewService, type ReviewedEditionGroup } from "../../services/editionReviewService";
import { activateAccountStorage } from "../../services/accountStorage";
vi.mock("../../services/editionReviewService", () => ({ editionReviewService: { group: vi.fn() } }));
const group: ReviewedEditionGroup = { group_key: "group", canonical_work_id: 1, revision: 2, title: "Story", reviewed: true, edition_count: 2, editions: [
  { edition_id: 1, novel_id: 42, title: "Story", author: "Writer", source_url: "https://example.org/42", site: "royalroad", language: "en", edition_kind: "original", content_rating: "general", tags: [], genres: [], fandoms: [] },
  { edition_id: 2, novel_id: 99, title: "Geschichte", author: "Writer", source_url: "https://example.org/99", site: "author", language: "de", edition_kind: "translation", content_rating: "general", tags: [], genres: [], fandoms: [] },
] };
beforeEach(() => { vi.clearAllMocks(); activateAccountStorage(1); });
it("opens a reviewed edition without copying library or progress parameters", async () => {
  vi.mocked(editionReviewService.group).mockResolvedValue(group);
  render(<MemoryRouter><StoryEditions metadataId={42} /></MemoryRouter>);
  expect(await screen.findByText("Current edition")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Open edition\s*:\s*Geschichte/ })).toHaveAttribute("href", "/story/99");
  expect(screen.getByText("author · de · translation")).toBeInTheDocument();
  expect(screen.getByText(/positions stay separate/)).toBeInTheDocument();
});
it("does not present an unreviewed legacy group as an edition recommendation", async () => {
  vi.mocked(editionReviewService.group).mockResolvedValue({ ...group, reviewed: false });
  render(<MemoryRouter><StoryEditions metadataId={42} /></MemoryRouter>);
  expect(await screen.findByText("No reviewed edition links yet.")).toBeInTheDocument();
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});
it("fences a late response belonging to the prior account", async () => {
  let finish!: (value: ReviewedEditionGroup) => void;
  vi.mocked(editionReviewService.group).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; })).mockResolvedValue({ ...group, reviewed: false });
  render(<MemoryRouter><StoryEditions metadataId={42} /></MemoryRouter>);
  act(() => activateAccountStorage(2));
  expect(await screen.findByText("No reviewed edition links yet.")).toBeInTheDocument();
  await act(async () => { finish(group); });
  expect(screen.queryByText("Geschichte")).not.toBeInTheDocument();
});
