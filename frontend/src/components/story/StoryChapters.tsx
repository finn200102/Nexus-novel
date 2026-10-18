import { chapterIdentity } from "../../services/chapterIdentity";
import StoryChapterChanges from "./StoryChapterChanges";
import React, { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { Link } from "react-router-dom";
import { Check, CloudDownload, HardDriveDownload, RotateCcw } from "lucide-react";
import { onAccountStorageChange, storageGeneration } from "../../services/accountStorage";
import { completedChaptersLabel, readingPlaceLabel } from "./chapterReadingLabels";
import { chapterService, type ChapterReadingItem, type ChapterReadingSummary } from "../../services/chapterService";
import { downloadService } from "../../services/downloadService";
import { organizationService } from "../../services/organizationService";
import { getUserFacingError } from "../../services/apiClient";
import { useToast } from "../../context/useToast";
import { categoryLabel, entryLabel } from "./storyModel";
import AutoDownloadToggle from "../novel/AutoDownloadToggle";
import OfflineControl from "../novel/OfflineControl";
import type { OfflineCopies } from "../novel/useOfflineCopies";
import type { NovelFollowSettings } from "../../types/novel";
import { Button, Checkbox, Dialog, FilterChip, IconButton, Input, Select, Sheet } from "../ui";

export type StoryChapter = Omit<ChapterReadingItem, "title"> & { title: string };

interface StoryChaptersProps {
  manifestReviewRequired?: boolean;
  libraryId: number;
  novelId: number;
  onReadingSummary: (summary: ChapterReadingSummary) => void;
  offline: OfflineCopies;
  followSettings: NovelFollowSettings | null;
  onFollowSettings: (settings: Partial<NovelFollowSettings>) => Promise<void>;
}

const DOWNLOAD_GAP_MS = 500;
const PAGE = 100;
const DEFAULT_CATEGORIES = ["story"];

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** Chapters tab: progress summary, offline and download controls, followed categories, the list. */
const StoryChaptersContents: React.FC<StoryChaptersProps> = ({ manifestReviewRequired, libraryId, novelId, onReadingSummary, offline, followSettings, onFollowSettings }) => {
  const generation = storageGeneration(), mounted = useRef(false), request = useRef(0);
  const current = useCallback(() => mounted.current && generation === storageGeneration(), [generation]);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const { addToast } = useToast();
  const [chapters, setChapters] = useState<StoryChapter[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0), [total, setTotal] = useState(0);
  const [summary, setSummary] = useState<ChapterReadingSummary | null>(null);
  const [downloads, setDownloads] = useState<Awaited<ReturnType<typeof chapterService.getDownloadStatus>> | null>(null);
  const [followed, setFollowed] = useState<string[]>(DEFAULT_CATEGORIES);
  const [showOther, setShowOther] = useState(false);
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [confirm, setConfirm] = useState<null | "download-all">(null);
  const [chapterReviewRequest, setChapterReviewRequest] = useState(0);
  const [manageOpen, setManageOpen] = useState(false);
  const [queueing, setQueueing] = useState(false);
  const searching = query.trim() !== "";
  const scope = searching || showOther ? "all" : "followed";
  const fetchChapters = useCallback(async () => {
    const version = ++request.current; setLoading(true); setError(null);
    const results = await Promise.allSettled([
      chapterService.getReadingChapters(novelId, { offset, limit: PAGE, q: query.trim(), category_scope: scope }),
      chapterService.getReadingSummary(novelId), chapterService.getDownloadStatus(novelId),
    ]);
    if (!current() || version !== request.current) return;
    const messages: string[] = [];
    if (results[0].status === "fulfilled" && results[0].value?.novel_id === novelId) {
      const page = results[0].value;
      const known = results[1].status === "fulfilled" ? results[1].value : null;
      if (known && (known.reading_run_key !== page.reading_run_key || known.revision !== page.revision)) {
        setChapters([]); messages.push("The reading session changed while loading. Refresh chapter records before reviewing the list.");
      } else { setChapters(page.items.map(row => ({ ...row, title: row.title ?? "" }))); setTotal(page.total); }
    } else { setChapters([]); messages.push("Could not load chapters. Try again."); }
    if (results[1].status === "fulfilled" && results[1].value?.novel_id === novelId) { setSummary(results[1].value); onReadingSummary(results[1].value); }
    else { setSummary(null); messages.push("Completed chapter counts could not be verified."); }
    if (results[2].status === "fulfilled" && Number.isSafeInteger(results[2].value?.total)) setDownloads(results[2].value);
    else { setDownloads(null); messages.push("Server download counts could not be verified."); }
    setError(messages.length ? messages.join(" ") : null); setLoading(false);
  }, [novelId, offset, query, scope, onReadingSummary, current]);
  useEffect(() => { void fetchChapters(); return () => { request.current += 1; }; }, [fetchChapters]);
  useEffect(() => { setSelected(new Set()); }, [offset, query, scope]);

  useEffect(() => {
    let active = true;
    organizationService.getPersonal(novelId)
      .then((data) => {
        if (active && current() && Array.isArray(data.followed_categories) && data.followed_categories.length) setFollowed(data.followed_categories);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [novelId, current]);

  const processing = chapters.some((chapter) => chapter.content_status === "PROCESSING");
  useEffect(() => {
    if (!processing) return;
    const timer = window.setInterval(() => void fetchChapters(), 2000);
    return () => window.clearInterval(timer);
  }, [processing, fetchChapters]);

  const savedOffline = useMemo(() => new Set(offline.stored.flatMap((item) => item.chapter_key ? [item.chapter_key] : [])), [offline.stored]);
  const categories = useMemo(() => summary?.categories ?? [...new Set(chapters.map(chapter => chapter.category || "story"))], [chapters, summary]);
  const hiddenCount = summary ? summary.total_chapters - summary.followed_total : null;
  const shown = useMemo(() => loading ? [] : chapters, [loading, chapters]);
  const missing = chapters.filter(chapter => chapter.content_status === "MISSING" || chapter.content_status === "FAILED");
  const downloaded = downloads?.present ?? null;
  const statusSummary = [summary ? completedChaptersLabel(summary) : "Completed chapter counts unavailable", downloaded !== null ? `${downloaded} downloaded on the server` : null, `${offline.stored.length} saved offline`].filter(Boolean).join(" · ");

  const toggleCategory = async (category: string, on: boolean) => {
    const next = on ? [...followed, category] : followed.filter((item) => item !== category);
    if (next.length === 0) return;
    const previous = followed;
    setFollowed(next);
    try {
      await organizationService.savePersonal(novelId, { followed_categories: next });
      if (current()) { if (offset === 0) void fetchChapters(); else setOffset(0); }
    } catch (err) {
      if (!current()) return;
      setFollowed(previous);
      addToast(getUserFacingError(err, "Could not save the categories you follow."), "error");
    }
  };

  const downloadOne = async (chapter: StoryChapter) => {
    try {
      if (chapter.content_status === "FAILED") await chapterService.resetChapterStatus(chapter.id, "MISSING");
      if (!current()) return;
      await chapterService.downloadChapter(libraryId, novelId, chapter.chapter_number,chapterIdentity(chapter) ?? undefined);
    } catch {
      if (!current()) return;
      addToast(`Could not download chapter ${chapter.chapter_number}.`, "error");
    }
    if (current()) void fetchChapters();
  };

  const downloadMany = async (targets: StoryChapter[]) => {
    for (const chapter of targets) {
      if (!current()) return;
      try {
        await chapterService.downloadChapter(libraryId, novelId, chapter.chapter_number,chapterIdentity(chapter) ?? undefined);
      } catch {
        // Keep going; failed chapters show a Retry button.
      }
      if (!current()) return;
      await sleep(DOWNLOAD_GAP_MS);
    }
    if (current()) void fetchChapters();
  };

  const queueNext = async (count: number) => {
    setQueueing(true);
    try {
      const jobs = await downloadService.queue(libraryId, novelId, count);
      if (!current()) return;
      addToast(jobs.length ? `Queued ${jobs.length} chapter${jobs.length === 1 ? "" : "s"} for download.` : "The next chapters are already downloaded or queued.", "success");
      void fetchChapters();
    } catch (err) {
      if (!current()) return;
      addToast(getUserFacingError(err, "Could not queue the download."), "error");
    } finally {
      if (current()) setQueueing(false);
    }
  };

  const selectedChapters = chapters.filter((chapter) => selected.has(chapter.id));
  const stopSelecting = () => {
    setSelecting(false);
    setSelected(new Set());
  };

  const statusText = (chapter: StoryChapter) => {
    switch (chapter.content_status) {
      case "PRESENT":
        return null;
      case "PROCESSING":
        return "Downloading…";
      case "FAILED":
        return "Download failed";
      default:
        return "Not downloaded";
    }
  };

  const groups = useMemo(() => {
    const byCategory = new Map<string, StoryChapter[]>();
    shown.forEach((chapter) => {
      const category = chapter.category || "story";
      byCategory.set(category, [...(byCategory.get(category) || []), chapter]);
    });
    return [...byCategory.entries()];
  }, [shown]);
  const showHeadings = groups.length > 1 || (groups[0] && groups[0][0] !== "story");

  return (
    <div className="story-chapters">
      <div className="story-chapters__bar">
        <p className="story-chapters__summary">{loading ? "Loading chapters…" : statusSummary}</p>
        <div className="story-chapters__actions">
          <Button size="sm" variant="secondary" icon={<HardDriveDownload aria-hidden="true" size={16} />} disabled={offline.busy} onClick={() => void offline.saveBatch("next", 10)}>
            Save next 10 offline
          </Button>
          <Button size="sm" variant="secondary" icon={<CloudDownload aria-hidden="true" size={16} />} loading={queueing} onClick={() => void queueNext(10)}>
            Download next 10
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setManageOpen(true)}>Manage downloads…</Button>
        </div>
      </div>
      {summary && <p className="story-hint">{readingPlaceLabel(summary)}</p>}
      {summary?.completed_reading && <p className="story-hint">This reading is marked finished. Chapter records are shown separately.</p>}
      <div className="story-chapters__status" role="status">
        {offline.progress ? `Saving ${offline.progress.done} of ${offline.progress.total}…` : offline.message}
      </div>

      <AutoDownloadToggle novelId={novelId} />
      <>{manifestReviewRequired&&<p role="status">The source chapter list changed. Your saved chapters remain readable. Review chapter list changes before changing their addresses.</p>}<StoryChapterChanges openRequest={chapterReviewRequest} novelId={novelId} libraryId={libraryId} onApplied={()=>{setSelected(new Set());void fetchChapters();}}/></>

      {categories.length > 1 && (
        <fieldset className="story-chapters__categories">
          <legend>Categories you follow</legend>
          <div className="story-chips">
            {categories.map((category) => (
              <FilterChip
                key={category}
                selected={followed.includes(category)}
                disabled={followed.length === 1 && followed.includes(category)}
                onChange={(on) => void toggleCategory(category, on)}
              >
                {categoryLabel(category)}
              </FilterChip>
            ))}
          </div>
          <p className="story-hint">Continue and unread counts skip categories you don't follow.</p>
          {summary?.categories_truncated && <p className="story-hint">Only the first 256 categories are listed here. Search all chapters to find other categories.</p>}
        </fieldset>
      )}

      <div className="story-chapters__tools">
        <Input
          search
          label="Find chapter"
          placeholder="Number or title"
          value={query}
          maxLength={200}
          onChange={(event) => { setOffset(0); setQuery(event.target.value); }}
          onClear={() => { setOffset(0); setQuery(""); }}
          fieldClassName="story-chapters__search"
        />
        {selecting ? (
          <div className="story-chapters__select-actions">
            <Button size="sm" variant="secondary" disabled={selected.size === 0} onClick={() => { void downloadMany(selectedChapters); stopSelecting(); }}>
              Download {selected.size || ""} selected
            </Button>
            <Button size="sm" variant="secondary" onClick={() => { stopSelecting(); setChapterReviewRequest(value => value + 1); }}>
              Review chapter changes
            </Button>
            <Button size="sm" variant="ghost" onClick={stopSelecting}>Done</Button>
          </div>
        ) : (
          chapters.length > 0 && <Button size="sm" variant="ghost" onClick={() => setSelecting(true)}>Select chapters</Button>
        )}
      </div>

      {error && (
        <p role="alert" className="story-chapters__error">
          {error} <Button size="sm" variant="ghost" onClick={() => void fetchChapters()}>Retry</Button>
        </p>
      )}
      {!loading && !error && total === 0 && <p className="story-hint">{summary?.total_chapters === 0 ? "No chapters yet. Use Update story info in Details to check the source." : searching ? `No chapter matches “${query.trim()}”.` : "No chapters in the categories you follow."}</p>}


      {groups.map(([category, items]) => (
        <section key={category} className="story-chapters__group" aria-label={showHeadings ? undefined : "Chapters"}>
          {showHeadings && <h3>{categoryLabel(category)}</h3>}
          <ul className="story-chapter-list">
            {items.map((chapter) => {
              const read = chapter.completed_checkpoint;
              const isCurrentPlace = summary?.current?.chapter_id === chapter.id;
              const status = statusText(chapter);
              const label = `${entryLabel(chapter)}: ${chapter.title || "Untitled"}`;
              return (
                <li key={chapter.id} className="story-chapter" data-status={chapter.content_status} data-chapter={chapter.chapter_number}>
                  {selecting ? (
                    <Checkbox
                      label={label}
                      checked={selected.has(chapter.id)}
                      onChange={(event) => {
                        const next = new Set(selected);
                        if (event.target.checked) next.add(chapter.id);
                        else next.delete(chapter.id);
                        setSelected(next);
                      }}
                    />
                  ) : (
                    <>
                      <span className="story-chapter__number" aria-hidden="true">{chapter.category && chapter.category !== "story" ? "·" : chapter.chapter_number}</span>
                      <span className="story-chapter__state">
                        {read ? <Check size={16} aria-label="Completed chapter recorded" role="img" /> : <span className="story-chapter__dot" role="img" aria-label="No completed chapter record" />}
                      </span>
                      <div className="story-chapter__text">
                        <Link className="story-chapter__link ui-stretched-link" to={`/library/${libraryId}/novels/${novelId}/${chapter.chapter_number}${chapterIdentity(chapter) ? `?chapter_key=${encodeURIComponent(chapterIdentity(chapter)!.chapter_key)}` : ""}`}>
                          <span className="visually-hidden">{entryLabel(chapter)}: </span>
                          {chapter.title || "Untitled"}
                        </Link>
                        {(status || savedOffline.has(chapterIdentity(chapter)?.chapter_key ?? "") || isCurrentPlace || chapter.max_percent !== null) && (
                          <span className="story-chapter__meta">
                            {[isCurrentPlace ? "Current place" : null, chapter.max_percent !== null ? `${Math.round(chapter.max_percent)}% recorded` : null, status, savedOffline.has(chapterIdentity(chapter)?.chapter_key ?? "") ? "Saved offline" : null].filter(Boolean).join(" · ")}
                          </span>
                        )}
                      </div>
                      {(chapter.content_status === "MISSING" || chapter.content_status === "FAILED") && (
                        <IconButton
                          className="story-chapter__action"
                          size="sm"
                          label={`${chapter.content_status === "FAILED" ? "Retry download of" : "Download"} ${entryLabel(chapter).toLowerCase()}`}
                          icon={chapter.content_status === "FAILED" ? <RotateCcw size={16} /> : <CloudDownload size={16} />}
                          onClick={() => void downloadOne(chapter)}
                        />
                      )}
                    </>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      ))}

      <div className="story-chapters__more">
        <nav className="story-chapters__actions" aria-label="Chapter pages"><Button variant="secondary" size="sm" disabled={loading || offset === 0} onClick={() => setOffset(value => Math.max(0, value - PAGE))}>Previous chapters</Button><span>{total ? offset + 1 : 0}–{Math.min(offset + chapters.length, total)} of {total} matching chapters</span><Button variant="secondary" size="sm" disabled={loading || offset + PAGE >= total} onClick={() => setOffset(value => value + PAGE)}>Next chapters</Button></nav>
        {!searching && (hiddenCount === null || hiddenCount > 0) && <Button variant="ghost" size="sm" aria-expanded={showOther} onClick={() => { setOffset(0); setShowOther(value => !value); }}>{showOther ? "Hide other categories" : hiddenCount === null ? "Show all categories" : `Show ${hiddenCount} chapters in other categories`}</Button>}
      </div>

      <Sheet open={manageOpen} onClose={() => setManageOpen(false)} title="Downloads and offline" variant="auto" closeLabel="Close downloads">
        <div className="story-manage">
          <OfflineControl offline={offline} />
          <section className="story-manage__section" aria-labelledby="story-server-downloads">
            <h3 id="story-server-downloads">Downloaded on the server</h3>
            <p className="story-hint">{downloads ? `${downloads.present} of ${downloads.total} chapters downloaded on the server.` : "Server download counts are unavailable."} {missing.length} missing or failed in the displayed chapters.</p>
            <div className="story-manage__row">
              <Button size="sm" variant="secondary" disabled={missing.length === 0} onClick={() => (missing.length > 10 ? setConfirm("download-all") : void downloadMany(missing))}>
                Download missing from displayed chapters{missing.length ? ` (${missing.length})` : ""}
              </Button>
              <Link to="/updates/downloads" className="story-link">See download queue</Link>
            </div>
            <Select
              label="When new chapters arrive"
              value={followSettings?.download_policy ?? "none"}
              onChange={(event) => void onFollowSettings({ download_policy: event.target.value as NovelFollowSettings["download_policy"] })}
              options={[
                { value: "none", label: "Don't download them" },
                { value: "next_chapter", label: "Download the next chapter" },
                { value: "next_n", label: "Download a batch of chapters" },
              ]}
            />
            {followSettings?.download_policy === "next_n" && (
              <Input
                label="Chapters per batch"
                type="number"
                min={1}
                max={100}
                defaultValue={followSettings.download_count || 1}
                onBlur={(event) => void onFollowSettings({ download_count: Math.min(100, Math.max(1, Number(event.target.value) || 1)) })}
              />
            )}
          </section>
        </div>
      </Sheet>

      <Dialog
        open={confirm === "download-all"}
        onClose={() => setConfirm(null)}
        title={`Download ${missing.length} displayed chapters?`}
        description="This can take a while. Chapters download one after another."
        actions={<>
          <Button variant="secondary" onClick={() => setConfirm(null)}>Cancel</Button>
          <Button onClick={() => { setConfirm(null); void downloadMany(missing); }}>Download displayed chapters</Button>
        </>}
      />
    </div>
  );
};

export default function StoryChapters(props: StoryChaptersProps) {
  const generation = useSyncExternalStore(onAccountStorageChange, storageGeneration);
  return <StoryChaptersContents key={`${generation}:${props.libraryId}:${props.novelId}`} {...props} />;
}
