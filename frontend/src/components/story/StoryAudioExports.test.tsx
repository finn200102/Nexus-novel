import {fixtureChapterIdentity as identity} from "../../../tests/fixtures/chapterIdentity";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import StoryAudioExports from "./StoryAudioExports";
import { audioService, type StoryAudioOverview } from "../../services/audioService";
import { audioExportService, type AudioExportJob, type StoryPodcast, type PodcastEpisode } from "../../services/audioExportService";
import { activateAccountStorage } from "../../services/accountStorage";
vi.mock("../../services/audioService", () => ({ audioService: { story: vi.fn() } }));
vi.mock("../../services/audioExportService", () => ({ audioExportService: { list: vi.fn(), create: vi.fn(), retry: vi.fn(), cancel: vi.fn(), remove: vi.fn(), download: vi.fn(), podcast: vi.fn(), createPodcast: vi.fn(), revokePodcast: vi.fn(), retryPodcastEpisode: vi.fn() } }));
const job = (status: AudioExportJob["status"] = "queued"): AudioExportJob => ({ id: 12, novel_id: 11, status, total_chapters: 2, completed_chapters: status === "completed" ? 2 : 1, audio_bytes: status === "completed" ? 2000000 : null, duration_seconds: null, chapters: [], error: null, file_ready: status === "completed", created_at: "2026-10-15T20:00:00Z", updated_at: "2026-10-15T20:00:00Z" });
const overview = (): StoryAudioOverview => ({ novel_id: 11, total: 3, offset: 0, limit: 50, summary: { chapters: 3, downloaded: 3, ready: 2, queued: 1, needs_retry: 0 }, chapters: [1, 2, 3].map(number => ({ ...identity(11,number),id: number, chapter_number: number, title: `Chapter ${number}`, downloaded: true, content_status: "PRESENT", source_version: "original", latest_job: { id: 800 + number, status: number === 2 ? "processing" : "completed", provider_id: "qwen3_clone", provider_model: "local", provider_voice: `Narrator ${number}`, total_parts: 2, completed_parts: 2, source_version: "original", audio_ready: number !== 2 } })) });
const podcast = (changes: Partial<StoryPodcast> = {}): StoryPodcast => ({ active: false, feed_url: null, format: "mp3", ready: 0, pending: 0, failed: 0, episodes: [], ...changes });
const episode = (id: number, status = "queued"): PodcastEpisode => ({ id, source_audio_job_id: 800 + id, chapter_number: id, status, audio_bytes: null, duration_seconds: null, error_code: status === "failed" ? "encoder_failed" : null, error: status === "failed" ? "Podcast preparation failed. The original recording is preserved." : null });
const mount = (selectedChapterNumbers?: number[]) => render(<MemoryRouter><StoryAudioExports novelId={11} libraryId={1} selectedChapterNumbers={selectedChapterNumbers} /></MemoryRouter>);
const startPodcast=async()=>{const button=await screen.findByRole("button",{name:"Create private podcast"});await waitFor(()=>expect(button).toBeEnabled());fireEvent.click(button);};

describe("private story audio exports", () => {
  beforeEach(() => {
    vi.clearAllMocks(); localStorage.clear(); activateAccountStorage(7);
    vi.mocked(audioService.story).mockResolvedValue(overview());
    vi.mocked(audioExportService.list).mockResolvedValue([]);
    vi.mocked(audioExportService.podcast).mockResolvedValue(podcast());
    vi.mocked(audioExportService.create).mockResolvedValue(job());
    vi.mocked(audioExportService.retry).mockResolvedValue(job());
    vi.mocked(audioExportService.cancel).mockResolvedValue(job("cancelled"));
    vi.mocked(audioExportService.remove).mockResolvedValue(undefined);
    vi.mocked(audioExportService.revokePodcast).mockResolvedValue(undefined);
    vi.mocked(audioExportService.createPodcast).mockResolvedValue(podcast({ active: true, feed_url: "https://nexus.example/podcasts/private-token/feed.xml" }));
  });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it("exports exact selected completed audio jobs without generating narration", async () => {
    mount();
    expect(await screen.findByRole("checkbox", { name: "Export chapter 2: Chapter 2" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "Export chapter 1: Chapter 1" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Export chapter 3: Chapter 3" }));
    fireEvent.click(screen.getByRole("button", { name: "Create M4B audiobook" }));
    await waitFor(() => expect(audioExportService.create).toHaveBeenCalledWith(11, [801, 803]));
    expect(await screen.findByText(/Audiobook export queued/)).toBeInTheDocument();
    expect(audioExportService.createPodcast).not.toHaveBeenCalled();
  });

  it("does not silently replace selected job snapshots after newer narration completes", async () => {
    vi.useFakeTimers(); mount(); await act(async () => { await Promise.resolve(); });
    fireEvent.click(screen.getByRole("checkbox", { name: "Export chapter 1: Chapter 1" }));
    const changed = overview(); changed.chapters[0].latest_job = { ...changed.chapters[0].latest_job!, id: 901, provider_voice: "Replacement voice" };
    vi.mocked(audioService.story).mockResolvedValue(changed);
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(screen.getByRole("checkbox", { name: "Export chapter 1: Chapter 1" })).not.toBeChecked();
    expect(screen.getByText("1 recordings selected for audiobook: 1 (Narrator 1)")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Create M4B audiobook" }));
    await act(async () => { await Promise.resolve(); });
    expect(audioExportService.create).toHaveBeenCalledWith(11, [801]);
  });

  it("imports chapter selections while skipping chapters without finished audio", async () => {
    mount([1, 2, 3]);
    await screen.findByRole("checkbox", { name: "Export chapter 1: Chapter 1" });
    fireEvent.click(screen.getByRole("button", { name: "Use selected chapters for audiobook" }));
    expect(await screen.findByText(/2 completed recordings added/)).toBeInTheDocument();
    expect(screen.getByText("2 recordings selected for audiobook: 1 (Narrator 1), 3 (Narrator 3)")).toBeInTheDocument();
  });

  it("polls encoding progress and exposes completed downloads", async () => {
    vi.useFakeTimers(); vi.mocked(audioExportService.list).mockResolvedValue([job()]); mount();
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByRole("progressbar", { name: "Audiobook export 12 progress" })).toHaveAttribute("value", "1");
    vi.mocked(audioExportService.list).mockResolvedValue([job("completed")]);
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(screen.getByRole("button", { name: "Download audiobook 12" })).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("requires review before deleting a completed audiobook", async () => {
    vi.mocked(audioExportService.list).mockResolvedValue([job("completed")]); mount();
    fireEvent.click(await screen.findByRole("button", { name: "Delete export 12" }));
    expect(screen.getByRole("dialog", { name: "Delete audiobook export 12?" })).toBeInTheDocument();
    expect(audioExportService.remove).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Delete audiobook" }));
    await waitFor(() => expect(audioExportService.remove).toHaveBeenCalledWith(12));
  });

  it("shows a private podcast URL only after creation and never stores it", async () => {
    const view = mount();
    await screen.findByText("Private podcast is disabled.");
    expect(screen.queryByLabelText("Private podcast URL")).not.toBeInTheDocument();
    expect(audioExportService.createPodcast).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Create private podcast" }));
    expect(await screen.findByLabelText("Private podcast URL")).toHaveValue("https://nexus.example/podcasts/private-token/feed.xml");
    expect(JSON.stringify(localStorage)).not.toContain("private-token");
    view.unmount(); vi.mocked(audioExportService.podcast).mockResolvedValue(podcast({ active: true })); mount();
    await screen.findByText("Private podcast is active.");
    expect(screen.queryByLabelText("Private podcast URL")).not.toBeInTheDocument();
  });

  it("confirms rotation and revocation without pretending downloaded files can be revoked", async () => {
    vi.mocked(audioExportService.podcast).mockResolvedValue(podcast({ active: true })); mount();
    fireEvent.click(await screen.findByRole("button", { name: "Rotate podcast URL" }));
    expect(audioExportService.createPodcast).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /^Rotate URL$/ }));
    await screen.findByLabelText("Private podcast URL");
    fireEvent.click(screen.getByRole("button", { name: "Revoke podcast URL" }));
    fireEvent.click(screen.getByRole("button", { name: /^Revoke URL$/ }));
    await waitFor(() => expect(audioExportService.revokePodcast).toHaveBeenCalledWith(11));
    expect(screen.queryByLabelText("Private podcast URL")).not.toBeInTheDocument();
    expect(screen.getByText(/files already downloaded to a device cannot be revoked/)).toBeInTheDocument();
  });

  it("discards a one-time feed URL delivered after the account changes", async () => {
    let finish!: (value: StoryPodcast) => void;
    vi.mocked(audioExportService.createPodcast).mockReturnValue(new Promise(resolve => { finish = resolve; })); mount();
    await startPodcast();
    act(() => activateAccountStorage(8));
    await act(async () => finish(podcast({ active: true, feed_url: "https://nexus.example/podcasts/old-account-secret/feed.xml" })));
    expect(screen.queryByLabelText("Private podcast URL")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("old-account-secret");
  });

  it("uses a scoped download URL instead of buffering an audiobook in JavaScript", async () => {
    vi.mocked(audioExportService.list).mockResolvedValue([job("completed")]);
    vi.mocked(audioExportService.download).mockResolvedValue({ url: "/api/audio/exports/12/file" });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined); mount();
    fireEvent.click(await screen.findByRole("button", { name: "Download audiobook 12" }));
    await waitFor(() => expect(click).toHaveBeenCalledTimes(1));
    expect((click.mock.contexts[0] as HTMLAnchorElement).getAttribute("href")).toContain("/api/audio/exports/12/file");
  });
  it("ignores an outdated disabled-feed poll after creating its one-time URL", async () => {
    vi.useFakeTimers(); mount(); await act(async () => { await Promise.resolve(); });
    let finish!: (value: StoryPodcast) => void;
    vi.mocked(audioExportService.podcast).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    fireEvent.click(screen.getByRole("button", { name: "Create private podcast" }));
    await act(async () => { await Promise.resolve(); });
    await act(async () => finish(podcast()));
    expect(screen.getByLabelText("Private podcast URL")).toHaveValue("https://nexus.example/podcasts/private-token/feed.xml");
  });

  it("does not start a delayed audiobook download after switching accounts", async () => {
    vi.mocked(audioExportService.list).mockResolvedValue([job("completed")]);
    let finish!: (value: { url: string }) => void;
    vi.mocked(audioExportService.download).mockReturnValue(new Promise(resolve => { finish = resolve; }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined); mount();
    fireEvent.click(await screen.findByRole("button", { name: "Download audiobook 12" }));
    act(() => activateAccountStorage(8));
    await act(async () => finish({ url: "/api/audio/exports/12/file" }));
    expect(click).not.toHaveBeenCalled();
  });

  it("preserves MP3 preparation status across activation and polling without hiding its one-time URL", async () => {
    vi.useFakeTimers();
    const pending = podcast({ active: true, pending: 1, failed: 1, episodes: [episode(1, "processing"), episode(3, "failed")], feed_url: "https://nexus.example/podcasts/private-token/feed.xml" });
    vi.mocked(audioExportService.createPodcast).mockResolvedValue(pending); mount();
    await act(async () => { await Promise.resolve(); });
    fireEvent.click(screen.getByRole("button", { name: "Create private podcast" }));
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByText("MP3 episodes: 0 ready · 1 queued or preparing · 1 need attention")).toBeInTheDocument();
    expect(screen.getByText("Chapter 1: Preparing MP3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry podcast chapter 3" })).toBeInTheDocument();
    vi.mocked(audioExportService.podcast).mockResolvedValue(podcast({ active: true, ready: 1, failed: 1, episodes: [episode(1, "completed"), episode(3, "failed")] }));
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(screen.getByRole("progressbar", { name: "Podcast MP3 preparation" })).toHaveAttribute("value", "1");
    expect(screen.getByLabelText("Private podcast URL")).toHaveValue("https://nexus.example/podcasts/private-token/feed.xml");
  });

  it("does not let an older status poll replace a newly created podcast or hide its one-time URL",async()=>{
    vi.useFakeTimers();mount();await act(async()=>{await Promise.resolve();});
    expect(screen.getByRole("button",{name:"Create private podcast"})).toBeEnabled();
    let resolve!:(value:StoryPodcast)=>void;
    vi.mocked(audioExportService.podcast).mockReturnValueOnce(new Promise(done=>{resolve=done;}));
    await act(async()=>{await vi.advanceTimersByTimeAsync(3000);});
    const active=podcast({active:true,failed:1,episodes:[episode(3,"failed")],feed_url:"https://nexus.example/podcasts/new-private-token/feed.xml"});
    vi.mocked(audioExportService.createPodcast).mockResolvedValue(active);
    fireEvent.click(screen.getByRole("button",{name:"Create private podcast"}));await act(async()=>{await Promise.resolve();});
    expect(screen.getByRole("button",{name:"Retry podcast chapter 3"})).toBeInTheDocument();
    await act(async()=>resolve(podcast()));
    expect(screen.getByRole("button",{name:"Retry podcast chapter 3"})).toBeInTheDocument();expect(screen.getByLabelText("Private podcast URL")).toHaveValue(active.feed_url);
    expect(screen.queryByText("Private podcast is disabled.")).not.toBeInTheDocument();
  });
  it("retries only a failed MP3 derivative and updates its counters while preserving the feed URL", async () => {
    const pending = podcast({ active: true, failed: 1, episodes: [episode(3, "failed")], feed_url: "https://nexus.example/podcasts/private-token/feed.xml" });
    vi.mocked(audioExportService.createPodcast).mockResolvedValue(pending);
    vi.mocked(audioExportService.retryPodcastEpisode).mockResolvedValue(episode(3)); mount();
    await startPodcast();
    fireEvent.click(await screen.findByRole("button", { name: "Retry podcast chapter 3" }));
    await waitFor(() => expect(audioExportService.retryPodcastEpisode).toHaveBeenCalledWith(11, 3));
    expect(screen.getByText("MP3 episodes: 0 ready · 1 queued or preparing · 0 need attention")).toBeInTheDocument();
    expect(screen.getByText("Chapter 3: Queued")).toBeInTheDocument();
    expect(screen.getByLabelText("Private podcast URL")).toHaveValue("https://nexus.example/podcasts/private-token/feed.xml");
    expect(audioExportService.create).not.toHaveBeenCalled();
    expect(audioExportService.createPodcast).toHaveBeenCalledTimes(1);
  });

  it("does not expose episode results returned after an account switch", async () => {
    vi.mocked(audioExportService.podcast).mockResolvedValue(podcast({ active: true, failed: 1, episodes: [episode(3, "failed")] }));
    let finish!: (value: PodcastEpisode) => void;
    vi.mocked(audioExportService.retryPodcastEpisode).mockReturnValue(new Promise(resolve => { finish = resolve; })); mount();
    fireEvent.click(await screen.findByRole("button", { name: "Retry podcast chapter 3" }));
    vi.mocked(audioExportService.podcast).mockResolvedValue(podcast());
    act(() => activateAccountStorage(8));
    await act(async () => finish({ ...episode(3), error: "Private previous-account episode" }));
    expect(screen.queryByText("Chapter 3: Queued")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("Private previous-account episode");
  });

  it("tolerates a legacy feed response without inventing MP3 readiness", async () => {
    vi.mocked(audioExportService.podcast).mockResolvedValue({ active: true, feed_url: null } as StoryPodcast); mount();
    expect(await screen.findByText(/Episode preparation status is unavailable/)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Podcast episode preparation" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rotate podcast URL" })).toBeInTheDocument();
  });

  it("pages through long podcasts and retries the exact later episode without losing global counts or its URL", async () => {
    const rows = Array.from({ length: 201 }, (_, index) => episode(index + 1, index === 200 ? "failed" : "completed"));
    const status = (offset = 0) => podcast({ active: true, ready: 200, failed: 1, episodes: rows.slice(offset, offset + 50), episodes_total: 201, episodes_offset: offset, episodes_limit: 50 });
    vi.mocked(audioExportService.podcast).mockImplementation(async (_novelId, offset = 0) => status(offset));
    vi.mocked(audioExportService.createPodcast).mockResolvedValue({ ...status(), feed_url: "https://nexus.example/podcasts/private-token/feed.xml" });
    vi.mocked(audioExportService.retryPodcastEpisode).mockResolvedValue(episode(201)); mount();
    fireEvent.click(await screen.findByRole("button", { name: "Rotate podcast URL" }));
    fireEvent.click(screen.getByRole("button", { name: /^Rotate URL$/ }));
    await screen.findByLabelText("Private podcast URL");
    for (let pageNumber = 1; pageNumber <= 4; pageNumber++) {
      fireEvent.click(screen.getByRole("button", { name: "Next podcast episodes" }));
      await screen.findByText(`${pageNumber * 50 + 1}–${Math.min((pageNumber + 1) * 50, 201)} of 201 episodes`);
    }
    expect(audioExportService.podcast).toHaveBeenCalledWith(11, 200, 50);
    expect(screen.getByText("MP3 episodes: 200 ready · 0 queued or preparing · 1 need attention")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry podcast chapter 201" }));
    await waitFor(() => expect(audioExportService.retryPodcastEpisode).toHaveBeenCalledWith(11, 201));
    expect(screen.getByLabelText("Private podcast URL")).toHaveValue("https://nexus.example/podcasts/private-token/feed.xml");
    expect(screen.getByText("MP3 episodes: 200 ready · 1 queued or preparing · 0 need attention")).toBeInTheDocument();
  });

});
