import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import apiClient from "../../services/apiClient";
import DownloadsTab from "./DownloadsTab";
import { chapterService } from "../../services/chapterService";
import { novelService } from "../../services/novelService";

vi.mock("../../services/apiClient",()=>({default:{get:vi.fn()}}));
const { toast } = vi.hoisted(() => ({ toast: vi.fn() }));
vi.mock("../../context/useLibraryContext", () => ({ useLibraryContext: () => ({ activeLibraryId: 1 }) }));
vi.mock("../../context/useToast", () => ({ useToast: () => ({ addToast: toast }) }));
vi.mock("../../services/novelService", () => ({ novelService: { getAllNovels: vi.fn() } }));
vi.mock("../../services/chapterService", () => ({ chapterService: {
  getDownloadStatus: vi.fn(), getNavigation: vi.fn(), downloadChapter: vi.fn(), resetChapterStatus: vi.fn(),
} }));
const identity = { chapter_key: "00000000-0000-4000-8000-000000000001", manifest_epoch: "00000000-0000-4000-8000-000000000002", manifest_revision: "38" };

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(novelService.getAllNovels).mockResolvedValue([{ id: 2, title: "Book" }] as Awaited<ReturnType<typeof novelService.getAllNovels>>);
  vi.mocked(chapterService.getDownloadStatus).mockResolvedValue({ total: 38, present: 0, processing: 0, failed: 1, missing: 37, processing_chapters: [],
    failed_chapters: [{ id: 112, chapter_number: 3, title: "Third", error: "Source failed", finished_at: null, retry_count: 1 }] });
  vi.mocked(apiClient.get).mockImplementation(async()=>({data:{total:1,novels:[{novel_id:2,title:"Book",status:await chapterService.getDownloadStatus(2)}]}}));
  vi.mocked(chapterService.getNavigation).mockResolvedValue({ novel_id: 2, chapter_id: 112, chapter_number: 3, previous: null, next: null, ...identity });
});

async function openDownloads() {
  render(<MemoryRouter><DownloadsTab jobs={[]} setJobs={vi.fn()} /></MemoryRouter>);
  fireEvent.click(await screen.findByText("Book"));
}

it("retries the same failed chapter with fresh server identity and preserves its failure until accepted", async () => {
  await openDownloads();
  fireEvent.click(screen.getByTitle("Retry"));
  await waitFor(() => expect(chapterService.downloadChapter).toHaveBeenCalledWith(1, 2, 3, identity));
  expect(chapterService.getNavigation).toHaveBeenCalledWith(2, 3);
  expect(chapterService.resetChapterStatus).not.toHaveBeenCalled();
});

it("refuses to retry a different chapter now occupying the old address", async () => {
  vi.mocked(chapterService.getNavigation).mockResolvedValue({ novel_id: 2, chapter_id: 999, chapter_number: 3, previous: null, next: null, ...identity });
  await openDownloads();
  fireEvent.click(screen.getByTitle("Retry"));
  await waitFor(() => expect(toast).toHaveBeenCalledWith("Failed to retry chapter", "error"));
  expect(chapterService.downloadChapter).not.toHaveBeenCalled();
  expect(chapterService.resetChapterStatus).not.toHaveBeenCalled();
});

it("Retry All Failed actually starts downloads with captured identities", async () => {
  await openDownloads();
  fireEvent.click(screen.getByText("Retry All Failed"));
  await waitFor(() => expect(chapterService.downloadChapter).toHaveBeenCalledWith(1, 2, 3, identity));
  expect(toast).toHaveBeenCalledWith("Retrying 1 chapters", "success");
  expect(chapterService.resetChapterStatus).not.toHaveBeenCalled();
});
