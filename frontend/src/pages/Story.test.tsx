import {fixtureChapterIdentity as identity} from "../../tests/fixtures/chapterIdentity";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Story, { LibraryStoryRedirect } from "./Story";
import { renderWithToasts } from "../components/organization/testUtils";
import { discoveryService } from "../services/discoveryService";
import { storyService } from "../services/storyService";
import { novelService } from "../services/novelService";
import { chapterService } from "../services/chapterService";
import { editionReviewService } from "../services/editionReviewService";
import { organizationService } from "../services/organizationService";

vi.mock("../context/useLibraryContext", () => ({
  useLibraryContext: () => ({ libraries: [{ id: 1, name: "Main" }], activeLibraryId: 1 }),
}));
vi.mock("../components/common/SourceStatusChip", () => ({ default: () => null }));
vi.mock("../components/story/HiatusBadge", () => ({ default: () => null }));
vi.mock("../components/story/CompletionToggle", () => ({ default: () => null }));
vi.mock("../components/follow/FollowAuthorButton", () => ({ default: () => null }));
vi.mock("../components/story/StoryReadingHistory", () => ({ default: ({ novelId, libraryId }: { novelId:number; libraryId:number }) => <p>History for library {libraryId}, story {novelId}</p> }));
vi.mock("../components/story/StoryTranslations", () => ({ default: ({ novelId, libraryId }: { novelId:number; libraryId:number }) => <p>Translations for library {libraryId}, story {novelId}</p> }));
vi.mock("../components/story/StoryAudio", () => ({ default: ({ novelId, libraryId }: { novelId:number; libraryId:number }) => <p>Audio for library {libraryId}, story {novelId}</p> }));
vi.mock("../services/discoveryService", () => ({ discoveryService: { getNovelById: vi.fn(), addToLibrary: vi.fn() } }));
vi.mock("../services/storyService", () => ({ storyService: { membership: vi.fn() } }));
vi.mock("../services/novelService", () => ({
  novelService: {
    getNovelById: vi.fn(),
    getFollowSettings: vi.fn(),
    updateFollowState: vi.fn(),
    refreshMetadata: vi.fn(),
    rescrapeNovel: vi.fn(),
    deleteNovel: vi.fn(),
  },
}));
vi.mock("../services/chapterService", () => ({
  chapterService: {
    getReadingProgress: vi.fn(),
    getReadingSummary: vi.fn(),
    getReadingChapters: vi.fn(),
    getDownloadStatus: vi.fn(),
    getChapters: vi.fn(),
    exportNovelEpub: vi.fn(),
    downloadChapter: vi.fn(),
    resetChapterStatus: vi.fn(),
    deleteChaptersByIds: vi.fn(),
    getChapterContentByNumber: vi.fn(),
  },
}));
vi.mock("../services/editionReviewService", () => ({ editionReviewService: { group: vi.fn().mockResolvedValue({ group_key: "catalog-story-fixture", canonical_work_id: 1, revision: 1, title: "The Quiet Ledger", reviewed: false, edition_count: 1, editions: [{ edition_id: 1, novel_id: 4, title: "The Quiet Ledger", author: "Mara Thorne", source_url: "https://www.royalroad.com/fiction/4", site: "royalroad", language: null, edition_kind: "original", content_rating: "general", tags: [], genres: [], fandoms: [] }] }) } }));
vi.mock("../services/insightService", () => ({
  insightService: {
    analysis: vi.fn().mockResolvedValue({ state: "not_started", signals: [] }),
    similar: vi.fn().mockResolvedValue({ results: [{ novel_id: 9, title: "The Ninth Archivist", score: 0.8, explanation: "Shared tags", reasons: ["Both are slow burns"] }] }),
    editions: vi.fn().mockResolvedValue(null),
    storyGuide: vi.fn().mockResolvedValue(null),
  },
}));
vi.mock("../services/organizationService", () => ({
  organizationService: {
    getPersonal: vi.fn().mockResolvedValue({ novel_id: 11, notes: null, rating: null, user_tags: [], followed_categories: ["story"], auto_download: false, keep_ahead: 10 }),
    savePersonal: vi.fn(),
    tagSuggestions: vi.fn().mockResolvedValue([]),
    listShelves: vi.fn().mockResolvedValue([{ id: 3, name: "Comfort reads", position: 0, novel_ids: [11] }]),
    addBlocklistEntry: vi.fn(),
    removeBlocklistEntry: vi.fn(),
  },
}));
vi.mock("../services/downloadService", () => ({ downloadService: { queue: vi.fn() } }));
vi.mock("../services/offlineReaderStore", () => ({
  offlineReaderStore: { listForNovel: vi.fn().mockResolvedValue([]), save: vi.fn(), removeForNovel: vi.fn() },
}));

const catalog = {
  id: 4,
  title: "The Quiet Ledger",
  author: "Mara Thorne",
  source_url: "https://www.royalroad.com/fiction/4",
  novel_site: "royalroad",
  img_url: null,
  description: "Orren keeps the books.",
  word_count: 412000,
  chapter_count: 3,
  status: "Ongoing",
  updated_at: new Date().toISOString(),
  created_at: "2026-01-01T00:00:00Z",
  tags: ["Slow burn"],
};

const libraryNovel = {
  id: 11,
  library_id: 1,
  metadata_id: 4,
  title: "The Quiet Ledger",
  url: catalog.source_url,
  source_url: catalog.source_url,
  novel_site: "royalroad",
  author: "Mara Thorne",
  chapter_count: 3,
  follow_state: "reading",
  scrape_status: "completed",
  next_unread_chapter_number: 2,
  updated_at: "2026-10-01T00:00:00Z",
};

afterEach(() => vi.restoreAllMocks());

const Where = () => {
  const location = useLocation();
  return <output data-testid="where">{location.pathname + location.search}</output>;
};

const renderAt = (path: string) =>
  renderWithToasts(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/story/:storyId" element={<><Story /><Where /></>} />
        <Route path="/library/:libraryId/novels/:novelId" element={<><LibraryStoryRedirect /><Where /></>} />
      </Routes>
    </MemoryRouter>,
  );

beforeEach(() => {
  vi.mocked(discoveryService.getNovelById).mockResolvedValue(catalog as never);
  vi.mocked(chapterService.getReadingProgress).mockResolvedValue({ chapter_number: 1, position: 0, percent: 0, revision: 0, reading_run_key: null });
  vi.mocked(chapterService.getChapters).mockResolvedValue([
    { ...identity(11,1),id: 101, novel_id: 11, chapter_number: 1, title: "A Correction", content_status: "PRESENT", category: "story", audio_status: "MISSING", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" },
    { ...identity(11,2),id: 102, novel_id: 11, chapter_number: 2, title: "Interest Compounds", content_status: "PRESENT", category: "story", audio_status: "MISSING", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" },
    { ...identity(11,3),id: 103, novel_id: 11, chapter_number: 3, title: "The Second Column", content_status: "MISSING", category: "story", audio_status: "MISSING", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" },
  ]);
  vi.mocked(chapterService.getReadingSummary).mockResolvedValue({ novel_id:11, reading_run_key:null, revision:0, total_chapters:3, followed_total:3, completed_chapters:1, followed_completed_chapters:1, completion_basis:"recorded_checkpoints", completed_reading:false, current:{chapter_id:101,chapter_number:1,ordinal:1,followed_ordinal:1,percent:0}, next_unread_chapter_id:102,next_unread_chapter_number:2,categories:["story"],categories_truncated:false });
  vi.mocked(chapterService.getReadingChapters).mockImplementation(async (id, params={}) => { const rows=await chapterService.getChapters(id); return {novel_id:id,reading_run_key:null,revision:0,total:rows.length,offset:params.offset??0,limit:params.limit??100,items:rows.slice(params.offset??0,(params.offset??0)+(params.limit??100)).map((row,index)=>({...row,ordinal:index+1,followed_ordinal:index+1,followed:true,completed_checkpoint:row.id===101,max_percent:row.id===101?100:null}))}; });
  vi.mocked(chapterService.getDownloadStatus).mockResolvedValue({total:3,present:2,missing:1,failed:0,processing:0,failed_chapters:[],processing_chapters:[]});
  vi.mocked(novelService.getNovelById).mockResolvedValue(libraryNovel);
  vi.mocked(novelService.getFollowSettings).mockResolvedValue({ novel_id: 11, follow_state: "reading", download_policy: "none", download_count: 1, notification_policy: "immediate", notification_count: 1 });
});

describe("Story page", () => {
  it("renders a catalog-only story with Add to library and no library tabs", async () => {
    vi.mocked(storyService.membership).mockResolvedValue({ metadata_id: 4, library_entries: [], support_links: [] });
    vi.mocked(discoveryService.addToLibrary).mockResolvedValue({ id: 11 });
    renderAt("/story/4");

    expect(await screen.findByRole("heading", { level: 1, name: "The Quiet Ledger" })).toBeInTheDocument();
    expect(screen.getByText("412k words")).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "My notes" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Audio" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Translations" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Reading history" })).not.toBeInTheDocument();
    expect(screen.queryByText(/N\/A/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Add to library" }));
    await waitFor(() => expect(discoveryService.addToLibrary).toHaveBeenCalledWith(1, catalog.source_url));
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/story/4?copy=11"));
  });

  it("renders an in-library story with Continue, status, follow and its audio workspace", async () => {
    const xhr = vi.spyOn(XMLHttpRequest.prototype, "open");
    vi.mocked(storyService.membership).mockResolvedValue({
      metadata_id: 4,
      library_entries: [{ novel_id: 11, library_id: 1, library_name: "Main", title: "The Quiet Ledger", follow_state: "reading", scrape_status: "completed" }],
      support_links: [],
    });
    renderAt("/story/4");

    const cont = await screen.findByRole("link", { name: /Continue · Ch\. 2/ });
    expect(cont).toHaveAttribute("href", "/library/1/novels/11/2");
    expect(screen.getByRole("button", { name: "Status: Reading" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Following/ })).toBeInTheDocument();
    expect(screen.getByText("In Main")).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "The Ninth Archivist" })).toHaveAttribute("href", "/story/9");
    expect(screen.getByText("Both are slow burns")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Chapters" }));
    const row = await screen.findByRole("link", { name: /Chapter 3: The Second Column/ });
    expect(row).toHaveAttribute("href", `/library/1/novels/11/3?chapter_key=${identity(11,3).chapter_key}`);
    expect(screen.getByText("1 of 3 completed chapters recorded · 2 downloaded on the server · 0 saved offline")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download chapter 3" })).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Download new chapters automatically" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Audio" }));
    expect(screen.getByText("Audio for library 1, story 11")).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent("tab=audio");

    fireEvent.click(screen.getByRole("tab", { name: "Translations" }));
    expect(screen.getByText("Translations for library 1, story 11")).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent("tab=translations");

    fireEvent.click(screen.getByRole("tab", { name: "Reading history" }));
    expect(screen.getByText("History for library 1, story 11")).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent("tab=history");

    fireEvent.click(screen.getByRole("tab", { name: "My notes" }));
    expect(await screen.findByRole("group", { name: "Your rating" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Comfort reads" })).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("tab", { name: "Details" }));
    const details = screen.getByRole("tabpanel");
    expect(within(details).getByText("Catalog ID")).toBeInTheDocument();
    expect(within(details).getByText("Library story ID")).toBeInTheDocument();
    expect(await within(details).findByText("No reviewed edition links yet.")).toBeInTheDocument();
    expect(editionReviewService.group).toHaveBeenCalledWith(4, expect.any(AbortSignal));
    expect(xhr).not.toHaveBeenCalled();
  });

  it("hides a tag from its menu instead of a per-tag Hide pill", async () => {
    vi.mocked(storyService.membership).mockResolvedValue({ metadata_id: 4, library_entries: [], support_links: [] });
    vi.mocked(organizationService.addBlocklistEntry).mockResolvedValue({ id: 5, kind: "tag", value: "Slow burn", created_at: null });
    renderAt("/story/4");

    fireEvent.click(await screen.findByRole("button", { name: "Slow burn, tag options" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Hide stories with this tag" }));
    await waitFor(() => expect(organizationService.addBlocklistEntry).toHaveBeenCalledWith("tag", "Slow burn"));
  });

  it("explains a story outside the profile's content limits", async () => {
    const forbidden = Object.assign(new Error("Forbidden"), { isAxiosError: true, response: { status: 403, data: {} } });
    vi.mocked(discoveryService.getNovelById).mockRejectedValue(forbidden);
    vi.mocked(storyService.membership).mockRejectedValue(forbidden);
    renderAt("/story/4");
    expect(await screen.findByText("Not available on your profile")).toBeInTheDocument();
    expect(screen.getByText(/content limits an administrator set/)).toBeInTheDocument();
  });

  it("redirects the old library URL to the story's catalog id", async () => {
    vi.mocked(storyService.membership).mockResolvedValue({ metadata_id: 4, library_entries: [], support_links: [] });
    renderAt("/library/1/novels/11");
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/story/4?copy=11"));
  });

  it("keeps the audio destination when opening a story from the reader", async () => {
    vi.mocked(storyService.membership).mockResolvedValue({ metadata_id:4, library_entries:[{ novel_id:11, library_id:1, library_name:"Main", title:"The Quiet Ledger", follow_state:"reading", scrape_status:"completed" }], support_links:[] });
    renderAt("/library/1/novels/11?tab=audio");
    expect(await screen.findByText("Audio for library 1, story 11")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name:"Audio" })).toHaveAttribute("aria-selected", "true");
  });

  it("preserves the translations destination through a library redirect", async () => {
    vi.mocked(storyService.membership).mockResolvedValue({ metadata_id:4, library_entries:[{ novel_id:11, library_id:1, library_name:"Main", title:"The Quiet Ledger", follow_state:"reading", scrape_status:"completed" }], support_links:[] });
    renderAt("/library/1/novels/11?tab=translations");
    expect(await screen.findByText("Translations for library 1, story 11")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name:"Translations" })).toHaveAttribute("aria-selected", "true");
  });

  it("shows library stories without a catalog id in place", async () => {
    vi.mocked(novelService.getNovelById).mockResolvedValue({ ...libraryNovel, metadata_id: null });
    renderAt("/library/1/novels/11");
    expect(await screen.findByRole("link", { name: /Continue · Ch\. 2/ })).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent("/library/1/novels/11");
  });
});


it.each([-2, 0])('keeps signed saved chapter %s as a continue target when caught up', async chapter_number => {
  vi.mocked(novelService.getNovelById).mockResolvedValue({ ...libraryNovel, metadata_id: null, next_unread_chapter_number: null });
  vi.mocked(chapterService.getReadingProgress).mockResolvedValue({ chapter_number, position: 0, percent: 30, revision: 1, reading_run_key: null });
  const summary = await chapterService.getReadingSummary(11);
  vi.mocked(chapterService.getReadingSummary).mockResolvedValue({ ...summary, current:{chapter_id:101,chapter_number,ordinal:1,followed_ordinal:1,percent:30},next_unread_chapter_id:null,next_unread_chapter_number:null });
  renderAt('/library/1/novels/11');
  const link = await screen.findByRole('link', { name: `Continue · Ch. ${chapter_number}` });
  expect(link).toHaveAttribute('href', `/library/1/novels/11/${chapter_number}`);
});
