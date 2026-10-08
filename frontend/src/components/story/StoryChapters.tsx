import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Check, CloudDownload, HardDriveDownload, RotateCcw } from "lucide-react";
import { chapterService } from "../../services/chapterService";
import { downloadService } from "../../services/downloadService";
import { organizationService } from "../../services/organizationService";
import { getUserFacingError } from "../../services/apiClient";
import { useToast } from "../../context/useToast";
import { categoryLabel, entryLabel, matchesChapter } from "./storyModel";
import AutoDownloadToggle from "../novel/AutoDownloadToggle";
import OfflineControl from "../novel/OfflineControl";
import type { OfflineCopies } from "../novel/useOfflineCopies";
import type { NovelFollowSettings } from "../../types/novel";
import { Button, Checkbox, Dialog, FilterChip, IconButton, Input, Select, Sheet } from "../ui";

export interface StoryChapter {
  id: number;
  novel_id: number;
  chapter_number: number;
  title: string;
  content_status: string;
  category?: string;
}

interface StoryChaptersProps {
  libraryId: number;
  novelId: number;
  /** Furthest chapter read; null when nothing is read yet. */
  readThrough: number | null;
  offline: OfflineCopies;
  followSettings: NovelFollowSettings | null;
  onFollowSettings: (settings: Partial<NovelFollowSettings>) => Promise<void>;
}

const STUCK_PROCESSING_MS = 60000;
const DOWNLOAD_GAP_MS = 500;
const PAGE = 100;
const DEFAULT_CATEGORIES = ["story"];

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** Chapters tab: progress summary, offline and download controls, followed categories, the list. */
const StoryChapters: React.FC<StoryChaptersProps> = ({ libraryId, novelId, readThrough, offline, followSettings, onFollowSettings }) => {
  const { addToast } = useToast();
  const [chapters, setChapters] = useState<StoryChapter[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(PAGE);
  const [followed, setFollowed] = useState<string[]>(DEFAULT_CATEGORIES);
  const [showOther, setShowOther] = useState(false);
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [confirm, setConfirm] = useState<null | "delete" | "download-all">(null);
  const [manageOpen, setManageOpen] = useState(false);
  const [queueing, setQueueing] = useState(false);
  const processingSince = useRef(new Map<number, number>());

  const fetchChapters = useCallback(async () => {
    try {
      const data = (await chapterService.getChapters(novelId)) as StoryChapter[];
      if (!Array.isArray(data)) return;
      const now = Date.now();
      const since = processingSince.current;
      data.forEach((chapter) => {
        if (chapter.content_status !== "PROCESSING") {
          since.delete(chapter.id);
        } else if (!since.has(chapter.id)) {
          since.set(chapter.id, now);
        } else if (now - since.get(chapter.id)! > STUCK_PROCESSING_MS) {
          // A download that never finishes is marked failed so it can be retried.
          chapterService.resetChapterStatus(chapter.id, "FAILED").catch(() => undefined);
          since.delete(chapter.id);
        }
      });
      setChapters([...data].sort((a, b) => a.chapter_number - b.chapter_number));
      setError(null);
    } catch {
      setError("Could not load chapters. Try again.");
    } finally {
      setLoading(false);
    }
  }, [novelId]);

  useEffect(() => {
    void fetchChapters();
  }, [fetchChapters]);

  useEffect(() => {
    let active = true;
    organizationService.getPersonal(novelId)
      .then((data) => {
        if (active && Array.isArray(data.followed_categories) && data.followed_categories.length) setFollowed(data.followed_categories);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [novelId]);

  const processing = chapters.some((chapter) => chapter.content_status === "PROCESSING");
  useEffect(() => {
    if (!processing) return;
    const timer = window.setInterval(() => void fetchChapters(), 2000);
    return () => window.clearInterval(timer);
  }, [processing, fetchChapters]);

  const savedOffline = useMemo(() => new Set(offline.stored.map((item) => item.chapter_number)), [offline.stored]);
  const categories = useMemo(() => [...new Set(chapters.map((chapter) => chapter.category || "story"))], [chapters]);
  const searching = query.trim() !== "";
  const visible = chapters.filter((chapter) => (searching || showOther || followed.includes(chapter.category || "story")) && matchesChapter(chapter, query));
  const hiddenCount = chapters.filter((chapter) => !followed.includes(chapter.category || "story")).length;
  const shown = visible.slice(0, limit);
  const missing = chapters.filter((chapter) => chapter.content_status === "MISSING" || chapter.content_status === "FAILED");
  const downloaded = chapters.filter((chapter) => chapter.content_status === "PRESENT").length;
  const readCount = readThrough ? chapters.filter((chapter) => chapter.chapter_number <= readThrough).length : 0;

  const summary = [
    chapters.length ? `${readCount} of ${chapters.length} read` : null,
    `${downloaded} downloaded`,
    `${offline.stored.length} saved offline`,
  ].filter(Boolean).join(" · ");

  const toggleCategory = async (category: string, on: boolean) => {
    const next = on ? [...followed, category] : followed.filter((item) => item !== category);
    if (next.length === 0) return;
    const previous = followed;
    setFollowed(next);
    try {
      await organizationService.savePersonal(novelId, { followed_categories: next });
    } catch (err) {
      setFollowed(previous);
      addToast(getUserFacingError(err, "Could not save the categories you follow."), "error");
    }
  };

  const downloadOne = async (chapter: StoryChapter) => {
    try {
      if (chapter.content_status === "FAILED") await chapterService.resetChapterStatus(chapter.id, "MISSING");
      await chapterService.downloadChapter(libraryId, novelId, chapter.chapter_number);
    } catch {
      addToast(`Could not download chapter ${chapter.chapter_number}.`, "error");
    }
    void fetchChapters();
  };

  const downloadMany = async (targets: StoryChapter[]) => {
    for (const chapter of targets) {
      try {
        await chapterService.downloadChapter(libraryId, novelId, chapter.chapter_number);
      } catch {
        // Keep going; failed chapters show a Retry button.
      }
      await sleep(DOWNLOAD_GAP_MS);
    }
    void fetchChapters();
  };

  const queueNext = async (count: number) => {
    setQueueing(true);
    try {
      const jobs = await downloadService.queue(libraryId, novelId, count);
      addToast(jobs.length ? `Queued ${jobs.length} chapter${jobs.length === 1 ? "" : "s"} for download.` : "The next chapters are already downloaded or queued.", "success");
      void fetchChapters();
    } catch (err) {
      addToast(getUserFacingError(err, "Could not queue the download."), "error");
    } finally {
      setQueueing(false);
    }
  };

  const selectedChapters = chapters.filter((chapter) => selected.has(chapter.id));
  const stopSelecting = () => {
    setSelecting(false);
    setSelected(new Set());
  };

  const deleteSelected = async () => {
    setConfirm(null);
    try {
      await chapterService.deleteChaptersByIds(selectedChapters.map((chapter) => chapter.id));
      addToast(`Deleted ${selectedChapters.length} chapter${selectedChapters.length === 1 ? "" : "s"}.`, "success");
      stopSelecting();
    } catch (err) {
      addToast(getUserFacingError(err, "Could not delete the chapters."), "error");
    }
    void fetchChapters();
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
        <p className="story-chapters__summary">{loading ? "Loading chapters…" : summary}</p>
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
      <div className="story-chapters__status" role="status">
        {offline.progress ? `Saving ${offline.progress.done} of ${offline.progress.total}…` : offline.message}
      </div>

      <AutoDownloadToggle novelId={novelId} />

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
        </fieldset>
      )}

      <div className="story-chapters__tools">
        <Input
          search
          label="Find chapter"
          placeholder="Number or title"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onClear={() => setQuery("")}
          fieldClassName="story-chapters__search"
        />
        {selecting ? (
          <div className="story-chapters__select-actions">
            <Button size="sm" variant="secondary" disabled={selected.size === 0} onClick={() => { void downloadMany(selectedChapters); stopSelecting(); }}>
              Download {selected.size || ""} selected
            </Button>
            <Button size="sm" variant="danger" disabled={selected.size === 0} onClick={() => setConfirm("delete")}>
              Delete selected
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
      {!loading && !error && chapters.length === 0 && <p className="story-hint">No chapters yet. Use Update story info in Details to check the source.</p>}
      {!loading && chapters.length > 0 && visible.length === 0 && <p className="story-hint">{searching ? `No chapter matches “${query.trim()}”.` : "No chapters in the categories you follow."}</p>}

      {groups.map(([category, items]) => (
        <section key={category} className="story-chapters__group" aria-label={showHeadings ? undefined : "Chapters"}>
          {showHeadings && <h3>{categoryLabel(category)}</h3>}
          <ul className="story-chapter-list">
            {items.map((chapter) => {
              const read = readThrough != null && chapter.chapter_number <= readThrough;
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
                        {read ? <Check size={16} aria-label="Read" role="img" /> : <span className="story-chapter__dot" role="img" aria-label="Unread" />}
                      </span>
                      <div className="story-chapter__text">
                        <Link className="story-chapter__link ui-stretched-link" to={`/library/${libraryId}/novels/${novelId}/${chapter.chapter_number}`}>
                          <span className="visually-hidden">{entryLabel(chapter)}: </span>
                          {chapter.title || "Untitled"}
                        </Link>
                        {(status || savedOffline.has(chapter.chapter_number)) && (
                          <span className="story-chapter__meta">
                            {[status, savedOffline.has(chapter.chapter_number) ? "Saved offline" : null].filter(Boolean).join(" · ")}
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
        {visible.length > limit && (
          <Button variant="secondary" size="sm" onClick={() => setLimit((value) => value + PAGE * 5)}>
            Show more ({visible.length - limit} left)
          </Button>
        )}
        {!searching && hiddenCount > 0 && (
          <Button variant="ghost" size="sm" aria-expanded={showOther} onClick={() => setShowOther((value) => !value)}>
            {showOther ? "Hide" : "Show"} {hiddenCount} chapter{hiddenCount === 1 ? "" : "s"} in other categories
          </Button>
        )}
      </div>

      <Sheet open={manageOpen} onClose={() => setManageOpen(false)} title="Downloads and offline" variant="auto" closeLabel="Close downloads">
        <div className="story-manage">
          <OfflineControl offline={offline} />
          <section className="story-manage__section" aria-labelledby="story-server-downloads">
            <h3 id="story-server-downloads">Downloaded on the server</h3>
            <p className="story-hint">{downloaded} of {chapters.length} chapters downloaded{missing.length ? `, ${missing.length} missing` : ""}.</p>
            <div className="story-manage__row">
              <Button size="sm" variant="secondary" disabled={missing.length === 0} onClick={() => (missing.length > 10 ? setConfirm("download-all") : void downloadMany(missing))}>
                Download all missing{missing.length ? ` (${missing.length})` : ""}
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
        open={confirm === "delete"}
        onClose={() => setConfirm(null)}
        title={`Delete ${selected.size} chapter${selected.size === 1 ? "" : "s"}?`}
        description="The downloaded text is removed from the server. You can download it again later."
        actions={<>
          <Button variant="secondary" onClick={() => setConfirm(null)}>Cancel</Button>
          <Button variant="danger" onClick={() => void deleteSelected()}>Delete</Button>
        </>}
      />
      <Dialog
        open={confirm === "download-all"}
        onClose={() => setConfirm(null)}
        title={`Download ${missing.length} chapters?`}
        description="This can take a while. Chapters download one after another."
        actions={<>
          <Button variant="secondary" onClick={() => setConfirm(null)}>Cancel</Button>
          <Button onClick={() => { setConfirm(null); void downloadMany(missing); }}>Download all</Button>
        </>}
      />
    </div>
  );
};

export default StoryChapters;
