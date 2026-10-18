import {fixtureChapterIdentity as identity} from "../../../tests/fixtures/chapterIdentity";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import OfflineControl from "./OfflineControl";
import type { OfflineCopies } from "./useOfflineCopies";
import type { OfflineCopyPlan } from "../../services/offlineDownloadService";
const plan = (): OfflineCopyPlan => ({ generation: 0, libraryId: 1, novelId: 42, title: "Story", options: { audio: true, translations: true }, chapters: [{ ...identity(42,3),id: 3, chapter_number: 3, title: "Chapter", downloaded: true, source_version: "v1", text_bytes_estimate: 100, audio: { job_id: 8, bytes: 5000, source_version: "v1" }, translations: [{ job_id: 9, language: "de", bytes_estimate: 100, source_version: "v1" }], translations_limited: true }], estimatedBytes: 5200, audioCount: 1, translationCount: 1, unavailable: 2, unknownVersion: 1, translationsLimited: true, storage: { total_bytes: 500, limit_bytes: 1000, remaining_bytes: 500 } });
const offline = (patch: Partial<OfflineCopies> = {}): OfflineCopies => ({ stored: [], totalBytes: 0, progress: null, message: null, busy: false, review: null, saveBatch: vi.fn(), reviewBatch: vi.fn(), confirmBatch: vi.fn(), cancelBatch: vi.fn(), removeAll: vi.fn(), ...patch });
describe("reviewed offline-copy controls", () => {
  it("starts text-only by default and only reviews explicit chapter/media choices", () => {
    const value = offline(); render(<OfflineControl offline={value} />);
    expect(screen.getByRole("checkbox", { name: "Include completed audio" })).not.toBeChecked(); expect(screen.getByRole("checkbox", { name: "Include completed translations" })).not.toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Review next 10" })); expect(value.reviewBatch).toHaveBeenCalledWith("next", 10, { audio: false, translations: false });
    fireEvent.click(screen.getByRole("checkbox", { name: "Include completed audio" })); fireEvent.click(screen.getByRole("checkbox", { name: "Include completed translations" })); fireEvent.click(screen.getByRole("button", { name: "Review all downloaded chapters" }));
    expect(value.reviewBatch).toHaveBeenLastCalledWith("all", 0, { audio: true, translations: true }); expect(value.confirmBatch).not.toHaveBeenCalled(); expect(value.saveBatch).not.toHaveBeenCalled();
  });
  it("shows reviewed bytes, optional limits, unavailable sources and variant cap before explicit save", () => {
    const value = offline({ review: plan() }); render(<OfflineControl offline={value} />);
    expect(screen.getByRole("region", { name: "Review offline copies" })).toHaveTextContent("1 text chapters · 1 recordings · 1 translations");
    expect(screen.getByText(/Estimated content to copy: 5.1 KB/)).toBeInTheDocument(); expect(screen.getByText(/estimate exceeds remaining space/)).toBeInTheDocument(); expect(screen.getByText(/2 chapters are not downloaded/)).toBeInTheDocument(); expect(screen.getByText(/1 source versions could not be checked/)).toBeInTheDocument(); expect(screen.getByText(/At most 20 completed language variants/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save reviewed offline copies" })).toBeEnabled(); expect(value.confirmBatch).not.toHaveBeenCalled(); fireEvent.click(screen.getByRole("button", { name: "Save reviewed offline copies" })); expect(value.confirmBatch).toHaveBeenCalledOnce();
  });
  it("locks media choices to the reviewed selection until the review is closed", () => {
    const value = offline({ review: { ...plan(), options: { audio: false, translations: false }, audioCount: 0, translationCount: 0 } }); render(<OfflineControl offline={value} />);
    expect(screen.getByRole("checkbox", { name: "Include completed audio" })).toBeDisabled(); expect(screen.getByRole("checkbox", { name: "Include completed translations" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Close offline review" })); expect(value.cancelBatch).toHaveBeenCalledOnce(); expect(value.confirmBatch).not.toHaveBeenCalled();
  });
  it("keeps cancel available while preventing duplicate reviews, removals and media edits during a copy", () => {
    const value = offline({ busy: true, progress: { done: 1, total: 3 }, stored: [{ novel_id: 42, chapter_number: 1, title: "Chapter", pinned: true, cached_at: 1, size_bytes: 100 }] }); render(<OfflineControl offline={value} />);
    expect(screen.getByRole("status")).toHaveTextContent("Saving 1 of 3"); expect(screen.getByRole("button", { name: "Review next 10" })).toBeDisabled(); expect(screen.getByRole("button", { name: "Remove offline text" })).toBeDisabled(); expect(screen.getByRole("checkbox", { name: "Include completed audio" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Stop offline copying" })); expect(value.cancelBatch).toHaveBeenCalledOnce(); expect(value.removeAll).not.toHaveBeenCalled();
  });
  it("does not allow an empty reviewed selection to start copying", () => {
    const value = offline({ review: { ...plan(), chapters: [], audioCount: 0, translationCount: 0, estimatedBytes: 0, storage: { total_bytes: 0, limit_bytes: null, remaining_bytes: null } } }); render(<OfflineControl offline={value} />);
    expect(screen.getByText("No account storage limit is set.")).toBeInTheDocument(); expect(screen.getByRole("button", { name: "Save reviewed offline copies" })).toBeDisabled(); fireEvent.click(screen.getByRole("button", { name: "Close offline review" })); expect(value.cancelBatch).toHaveBeenCalledOnce();
  });
});
