import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link, Navigate, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Bell, BellOff, BookOpen, ChevronDown, MoreHorizontal, Plus } from "lucide-react";
import { Badge, Button, Cover, Dialog, EmptyState, IconButton, Input, Menu, Select, Skeleton, SkeletonGroup, Tabs, type MenuItem } from "../components/ui";
import SourceStatusChip from "../components/common/SourceStatusChip";
import StoryAbout from "../components/story/StoryAbout";
import StoryChapters from "../components/story/StoryChapters";
import StoryDetails from "../components/story/StoryDetails";
import StoryShelves from "../components/story/StoryShelves";
import CompletionToggle from "../components/story/CompletionToggle";
import HiatusBadge from "../components/story/HiatusBadge";
import FollowAuthorButton from "../components/follow/FollowAuthorButton";
import SourceLinks from "../components/story/SourceLinks";
import SupportLinks from "../components/story/SupportLinks";
import { PersonalPanel } from "../components/organization/PersonalPanel";
import { useOfflineCopies } from "../components/novel/useOfflineCopies";
import { useStoryData, type LibraryCopyRef } from "../components/story/useStoryData";
import {
  FOLLOW_STATE_LABELS,
  NOTIFY_LABELS,
  STATUS_OPTIONS,
  isExperimentalSite,
  siteLabel,
  storyFacts,
  toStoryView,
  type FollowState,
} from "../components/story/storyModel";
import { chapterService } from "../services/chapterService";
import { discoveryService } from "../services/discoveryService";
import { insightService, type CanonicalWork, type InsightSignal, type SimilarNovel, type StoryGuide } from "../services/insightService";
import { novelService } from "../services/novelService";
import { organizationService } from "../services/organizationService";
import { getUserFacingError } from "../services/apiClient";
import { useLibraryContext } from "../context/useLibraryContext";
import { useToast } from "../context/useToast";
import { usePageTitle } from "../hooks/usePageTitle";
import type { Novel, NovelFollowSettings } from "../types/novel";
import { highlightsExportService } from "../services/highlightsExportService";
import type { BlocklistKind } from "../types/organization";
import "../styles/organization.css";
import "../styles/story.css";

type TabValue = "about" | "chapters" | "notes" | "details";
const TABS: TabValue[] = ["about", "chapters", "notes", "details"];

interface StoryPageProps {
  /** Library copy to show when the story has no catalog id (old library stories). */
  fallbackCopy?: LibraryCopyRef;
}

/**
 * One story page for every story (WP-D9), addressed by catalog id: `/story/:storyId`.
 * When the story is in one or more of the user's libraries, the library state (progress,
 * follow, downloads, notes) joins in; `?copy=<library story id>` picks among several copies.
 */
export const StoryPage: React.FC<StoryPageProps> = ({ fallbackCopy }) => {
  const { storyId } = useParams<{ storyId: string }>();
  const metadataId = storyId && /^\d+$/.test(storyId) ? Number(storyId) : null;
  const [searchParams, setSearchParams] = useSearchParams();
  const preferredCopy = Number(searchParams.get("copy")) || null;
  const navigate = useNavigate();
  const { addToast } = useToast();
  const { libraries, activeLibraryId } = useLibraryContext();
  const data = useStoryData(metadataId, preferredCopy, fallbackCopy ?? null);
  const { catalog, novel, copy, entries, followSettings, setNovel, setFollowSettings } = data;
  const view = useMemo(() => toStoryView(catalog, novel), [catalog, novel]);
  const inLibrary = !!(novel && copy);
  const storyMetadataId = view.metadataId;

  usePageTitle(data.loading ? null : data.notFound ? "Story not found" : view.title, {
    back: inLibrary ? { to: "/library", label: "Back to Library" } : { to: "/discover", label: "Back to Discover" },
  });

  const requestedTab = searchParams.get("tab") as TabValue | null;
  const tab: TabValue = requestedTab && TABS.includes(requestedTab) && (inLibrary || requestedTab !== "notes") ? requestedTab : "about";
  const setTab = (next: TabValue) => {
    const params = new URLSearchParams(searchParams);
    if (next === "about") params.delete("tab");
    else params.set("tab", next);
    setSearchParams(params, { replace: true });
  };

  // Reading position: drives Continue, read marks and the spoiler cutoff of the story guide.
  const [readThrough, setReadThrough] = useState<number | null>(null);
  useEffect(() => {
    if (!copy) {
      setReadThrough(null);
      return;
    }
    let active = true;
    chapterService.getReadingProgress(copy.novelId)
      .then((progress) => active && setReadThrough(progress?.chapter_number ?? null))
      .catch(() => active && setReadThrough(null));
    return () => {
      active = false;
    };
  }, [copy]);
  const guideCutoff = Math.max(0, readThrough ?? 0);

  // Insights from the catalog: writing style, similar stories, editions, story guide.
  const [signals, setSignals] = useState<InsightSignal[]>([]);
  const [analysisState, setAnalysisState] = useState("not_started");
  const [similar, setSimilar] = useState<SimilarNovel[]>([]);
  const [editions, setEditions] = useState<CanonicalWork | null>(null);
  const [guide, setGuide] = useState<StoryGuide | null>(null);
  useEffect(() => {
    if (!storyMetadataId) return;
    let active = true;
    Promise.all([
      insightService.analysis(storyMetadataId).catch(() => ({ state: "not_started" as const, signals: [] })),
      insightService.similar(storyMetadataId).catch(() => ({ results: [] })),
      insightService.editions(storyMetadataId).catch(() => null),
      insightService.storyGuide(storyMetadataId, guideCutoff).catch(() => null),
    ]).then(([analysis, matches, work, storyGuide]) => {
      if (!active) return;
      setSignals(analysis?.signals || []);
      setAnalysisState(analysis?.state || "not_started");
      setSimilar(matches?.results || []);
      setEditions(work);
      setGuide(storyGuide);
    });
    return () => {
      active = false;
    };
  }, [storyMetadataId, guideCutoff]);

  const offline = useOfflineCopies(copy?.libraryId ?? 0, copy?.novelId ?? 0);

  // ---- Actions ----------------------------------------------------------
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [notifyCountOpen, setNotifyCountOpen] = useState(false);

  const addToLibrary = async (libraryId: number) => {
    if (!view.sourceUrl) return;
    setBusy("add");
    try {
      const created = (await discoveryService.addToLibrary(libraryId, view.sourceUrl)) as { id?: number };
      const name = libraries.find((library) => library.id === libraryId)?.name ?? "your library";
      addToast(`Added to ${name}.`, "success");
      if (created?.id) {
        const params = new URLSearchParams(searchParams);
        params.set("copy", String(created.id));
        setSearchParams(params, { replace: true });
      }
      await data.reload();
    } catch (error) {
      addToast(getUserFacingError(error, "Could not add the story. Try again."), "error");
    } finally {
      setBusy(null);
    }
  };

  const saveFollow = async (state: FollowState, settings: Partial<NovelFollowSettings> = {}) => {
    if (!copy || !novel) return;
    setBusy("follow");
    try {
      const next: NovelFollowSettings = {
        novel_id: novel.id,
        follow_state: state,
        notification_policy: "immediate",
        notification_count: 1,
        download_policy: "none",
        download_count: 1,
        ...(followSettings || {}),
        ...settings,
      };
      next.follow_state = state;
      const updated = await novelService.updateFollowState(copy.libraryId, copy.novelId, state, next);
      setNovel({ ...novel, ...updated });
      setFollowSettings(next);
    } catch (error) {
      addToast(getUserFacingError(error, "Could not save. Try again."), "error");
    } finally {
      setBusy(null);
    }
  };

  const hide = async (kind: BlocklistKind, value: string) => {
    try {
      const entry = await organizationService.addBlocklistEntry(kind, value);
      addToast(`Hidden ${kind} “${value}”. Stories with it disappear from Discover.`, "success", undefined, {
        action: {
          label: "Undo",
          onClick: () => {
            organizationService.removeBlocklistEntry(entry.id)
              .then(() => addToast(`Showing “${value}” again.`, "info"))
              .catch(() => addToast("Could not undo. Check Settings › Hidden content.", "error"));
          },
        },
      });
    } catch (error) {
      addToast(getUserFacingError(error, "Could not hide this. Try again."), "error");
    }
  };

  const runUpdate = async (label: string, action: () => Promise<Novel>, done: (updated: Novel) => string) => {
    setBusy(label);
    try {
      const updated = await action();
      setNovel(updated);
      const message = done(updated);
      addToast(message, updated.scrape_status === "failed" ? "error" : "success");
    } catch (error) {
      addToast(getUserFacingError(error, "Could not reach the source. Try again later."), "error");
    } finally {
      setBusy(null);
    }
  };
  const refresh = () => copy && runUpdate("refresh", () => novelService.refreshMetadata(copy.libraryId, copy.novelId), () => "Story info updated.");
  const rescrape = () => copy && runUpdate("refresh", () => novelService.rescrapeNovel(copy.libraryId, copy.novelId), () => "Downloading story info again. This can take a minute.");
  const checkStatus = () => copy && runUpdate("refresh", () => novelService.refreshMetadata(copy.libraryId, copy.novelId), (updated) =>
    updated.scrape_status === "completed" ? "Story info is up to date." : updated.scrape_status === "failed" ? `Update failed: ${updated.scrape_error || "unknown error"}` : "Still updating. Check again in a few seconds.");

  const exportEpub = async () => {
    if (!copy) return;
    try {
      addToast("Preparing the EPUB from downloaded chapters…", "info");
      const blob = await chapterService.exportNovelEpub(copy.novelId);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${view.title.replace(/[^a-z0-9]+/gi, "-").toLowerCase() || "story"}.epub`;
      link.click();
      URL.revokeObjectURL(url);
      addToast("EPUB downloaded.", "success");
    } catch {
      addToast("Download at least one chapter before exporting.", "error");
    }
  };

  const enrich = async () => {
    if (!storyMetadataId) return;
    setBusy("enrich");
    try {
      const result = await insightService.enqueue(storyMetadataId);
      setAnalysisState(result.queued ? "queued" : "completed");
      addToast(result.queued ? "Estimating the writing style in the background." : "The estimate is already up to date.", "success");
    } catch {
      addToast("Could not start the estimate. Try again.", "error");
    } finally {
      setBusy(null);
    }
  };

  const buildGuide = async () => {
    if (!storyMetadataId) return;
    setBusy("guide");
    try {
      const result = await insightService.backfillStoryGuide(storyMetadataId);
      if (!result.chapter_count) addToast("Download at least one chapter before building a story guide.", "info");
      else if (result.queued) addToast(`Analyzing ${result.queued} downloaded chapter${result.queued === 1 ? "" : "s"} for the story guide.`, "success");
      else addToast("Every downloaded chapter is already in the story guide.", "info");
    } catch {
      addToast("Could not start the story guide. Try again.", "error");
    } finally {
      setBusy(null);
    }
  };

  const removeFromLibrary = async () => {
    if (!copy) return;
    setConfirmRemove(false);
    setBusy("remove");
    try {
      await novelService.deleteNovel(copy.libraryId, copy.novelId);
      const name = entries.find((entry) => entry.novel_id === copy.novelId)?.library_name;
      addToast(name ? `Removed from ${name}.` : "Removed from your library.", "success");
      if (!storyMetadataId) {
        navigate("/library");
        return;
      }
      const params = new URLSearchParams(searchParams);
      params.delete("copy");
      setSearchParams(params, { replace: true });
      await data.reload();
    } catch (error) {
      addToast(getUserFacingError(error, "Could not remove the story. Try again."), "error");
    } finally {
      setBusy(null);
    }
  };

  const selectCopy = useCallback((novelId: number) => {
    const params = new URLSearchParams(searchParams);
    params.set("copy", String(novelId));
    setSearchParams(params, { replace: true });
  }, [searchParams, setSearchParams]);

  // ---- Render -------------------------------------------------------------
  if (data.loading) {
    return (
      <div className="story">
        <SkeletonGroup label="Loading story" className="story-hero">
          <div className="story-hero__top">
            <div className="story-hero__cover"><Skeleton type="cover" /></div>
            <div className="story-hero__info">
              <Skeleton type="line" style={{ width: "70%" }} />
              <Skeleton type="line" style={{ width: "40%" }} />
              <Skeleton type="line" style={{ width: "55%" }} />
            </div>
          </div>
        </SkeletonGroup>
      </div>
    );
  }

  if (data.notFound) {
    return (
      <div className="story">
        <h1 tabIndex={-1} className="visually-hidden">Story not found</h1>
        <EmptyState
          title="This story isn't available"
          description="It may have been removed from the catalog or from your library."
          action={<Link to="/discover" className="ui-button ui-button--primary ui-button--md">Go to Discover</Link>}
        />
      </div>
    );
  }

  const site = siteLabel(view.site);
  const facts = storyFacts(view);
  const otherLibraries = libraries.filter((library) => !entries.some((entry) => entry.library_id === library.id));
  const followState = (novel?.follow_state ?? "plan_to_read") as FollowState;
  const following = followState !== "ignored";
  const notifyPolicy = followSettings?.notification_policy ?? "immediate";
  const continueChapter = novel?.next_unread_chapter_number ?? (readThrough && readThrough > 0 ? readThrough : null);
  const readerBase = copy ? `/library/${copy.libraryId}/novels/${copy.novelId}` : "";
  const totalChapters = novel?.chapter_count ?? view.chapterCount ?? 0;
  const readCount = Math.min(readThrough ?? 0, totalChapters);

  const addMenuItems: MenuItem[] = (inLibrary ? otherLibraries : libraries).map((library) => ({
    label: `${inLibrary ? "Also add to" : "Add to"} ${library.name}`,
    onSelect: () => void addToLibrary(library.id),
  }));

  const moreItems: MenuItem[] = [
    ...(inLibrary
      ? [
          { label: "Download EPUB", onSelect: () => void exportEpub() },
          ...(copy ? [{ label: "Export notes", onSelect: () => void highlightsExportService.downloadStoryNotes(copy.novelId, view.title).catch(() => addToast("Could not export notes.", "error")) }] : []),
          { label: "Update story info", onSelect: () => void refresh() },
          { label: "Manage downloads and offline…", onSelect: () => setTab("chapters") },
        ]
      : []),
    ...(view.sourceUrl && site ? [{ label: `Open on ${site}`, onSelect: () => window.open(view.sourceUrl!, "_blank", "noopener,noreferrer") }] : []),
    ...(view.author ? [{ label: `Hide stories by ${view.author}`, onSelect: () => void hide("author", view.author!) }] : []),
    ...(inLibrary && addMenuItems.length ? [{ type: "separator" as const }, ...addMenuItems] : []),
    ...(inLibrary ? [{ type: "separator" as const }, { label: "Remove from library…", danger: true, onSelect: () => setConfirmRemove(true) }] : []),
  ];

  const statusItems: MenuItem[] = STATUS_OPTIONS.map((state) => ({
    label: FOLLOW_STATE_LABELS[state],
    hint: state === followState ? "Current" : undefined,
    onSelect: () => void saveFollow(state),
  }));

  const followItems: MenuItem[] = following
    ? [
        ...(Object.keys(NOTIFY_LABELS) as Array<keyof typeof NOTIFY_LABELS>).map((policy) => ({
          label: policy === "after_n" ? "Notify after a number of chapters…" : `Notify ${NOTIFY_LABELS[policy].toLowerCase()}`,
          hint: policy === notifyPolicy ? "Current" : undefined,
          onSelect: () => (policy === "after_n" ? setNotifyCountOpen(true) : void saveFollow(followState, { notification_policy: policy })),
        })),
        { type: "separator" as const },
        { label: "Stop following", onSelect: () => void saveFollow("ignored") },
      ]
    : [{ label: "Follow new chapters", onSelect: () => void saveFollow("reading") }];

  const primaryAction = inLibrary ? (
    <Link to={`${readerBase}/${continueChapter ?? 1}`} className="ui-button ui-button--primary ui-button--lg story-actions__primary">
      <BookOpen size={18} aria-hidden="true" />
      {continueChapter ? `Continue · Ch. ${continueChapter}` : "Start reading"}
    </Link>
  ) : libraries.length > 1 ? (
    <Menu
      trigger={(props) => (
        <Button {...props} variant="primary" size="lg" className="story-actions__primary" icon={<Plus size={18} aria-hidden="true" />} iconEnd={<ChevronDown size={16} aria-hidden="true" className="story-actions__chevron" />} loading={busy === "add"}>
          Add to library
        </Button>
      )}
      items={addMenuItems}
    />
  ) : libraries.length === 1 ? (
    <Button variant="primary" size="lg" className="story-actions__primary" icon={<Plus size={18} aria-hidden="true" />} loading={busy === "add"} disabled={!view.sourceUrl} onClick={() => void addToLibrary(libraries[0].id ?? activeLibraryId)}>
      Add to library
    </Button>
  ) : (
    <Link to="/library" className="ui-button ui-button--primary ui-button--lg story-actions__primary">Create a library to add this story</Link>
  );

  const aboutPanel = (
    <StoryAbout
      view={view}
      inLibrary={inLibrary}
      signals={signals}
      analysisState={analysisState}
      enriching={busy === "enrich"}
      onEnrich={() => void enrich()}
      similar={similar}
      guide={guide}
      guideCutoff={guideCutoff}
      buildingGuide={busy === "guide"}
      onBuildGuide={() => void buildGuide()}
      onHide={(kind, value) => void hide(kind, value)}
      progress={inLibrary ? { read: readCount, total: totalChapters } : null}
      onSaveNext={() => void offline.saveBatch("next", 10)}
      savingOffline={offline.busy}
      offlineCount={offline.stored.length}
    />
  );
  const chaptersPanel = inLibrary && copy ? (
    <StoryChapters
      libraryId={copy.libraryId}
      novelId={copy.novelId}
      readThrough={readThrough}
      offline={offline}
      followSettings={followSettings}
      onFollowSettings={(settings) => saveFollow(followState, settings)}
    />
  ) : (
    <EmptyState
      level={2}
      title={view.chapterCount ? `${view.chapterCount.toLocaleString("en-US")} chapters` : "Chapters"}
      description="Add this story to a library to read, download and save chapters offline."
    />
  );
  const notesPanel = copy ? (
    <div className="story-body story-body--single">
      <div className="story-main">
        <PersonalPanel novelId={copy.novelId} />
        <CompletionToggle novelId={copy.novelId} />
        <StoryShelves novelId={copy.novelId} />
      </div>
    </div>
  ) : null;
  const detailsPanel = (
    <StoryDetails
      view={view}
      novel={novel}
      entries={entries}
      editions={editions}
      updating={busy === "refresh"}
      onRefresh={() => void refresh()}
      onRescrape={() => void rescrape()}
      onCheckStatus={() => void checkStatus()}
    />
  );

  const tabItems = [
    { value: "about" as const, label: "About", panel: aboutPanel },
    { value: "chapters" as const, label: "Chapters", panel: chaptersPanel },
    ...(inLibrary ? [{ value: "notes" as const, label: "My notes", panel: notesPanel }] : []),
    { value: "details" as const, label: "Details", panel: detailsPanel },
  ];

  return (
    <div className="story">
      <header className="story-hero">
        <div className="story-hero__top">
          <div className="story-hero__cover">
            <Cover src={view.cover} title={view.title} author={view.author} size="fill" priority />
          </div>
          <div className="story-hero__info">
            <h1 className="story-hero__title" tabIndex={-1}>{view.title}</h1>
            {view.author && (
              <p className="story-hero__author">
                by {catalog?.author_fk ? <Link to={`/authors/${catalog.author_fk}`}>{view.author}</Link> : view.author}
                {catalog?.author_fk ? <> <FollowAuthorButton authorId={catalog.author_fk} /></> : null}
              </p>
            )}
            <div className="story-hero__badges">
              {site && <Badge>{site}</Badge>}
              {isExperimentalSite(view.site) && <Badge tone="warning">Experimental</Badge>}
              {storyMetadataId && <HiatusBadge metadataId={storyMetadataId} />}
              {inLibrary && novel?.scrape_status === "pending" && <Badge tone="info">Updating…</Badge>}
              {inLibrary && novel?.scrape_status === "failed" && <Badge tone="danger">Update failed</Badge>}
              <SourceStatusChip site={view.site} />
            </div>
            {facts.length > 0 && (
              <p className="story-hero__facts">
                {facts.map((fact) => <span key={fact}>{fact}</span>)}
              </p>
            )}
            {entries.length > 1 && copy && (
              <Select
                label="Library"
                fieldClassName="story-hero__copy"
                value={String(copy.novelId)}
                onChange={(event) => selectCopy(Number(event.target.value))}
                options={entries.map((entry) => ({ value: String(entry.novel_id), label: entry.library_name }))}
              />
            )}
            {entries.length === 1 && <p className="story-hero__in">In {entries[0].library_name}</p>}
            <SourceLinks site={view.site} url={view.sourceUrl} storyId={view.siteStoryId} />
            <SupportLinks links={data.supportLinks} />
          </div>
          <div className={`story-actions${inLibrary ? " story-actions--library" : ""}`}>
          {primaryAction}
          {inLibrary && (
            <>
              <Menu
                trigger={(props) => (
                  <Button {...props} variant="secondary" size="lg" iconEnd={<ChevronDown size={16} aria-hidden="true" className="story-actions__chevron" />} aria-label={`Status: ${FOLLOW_STATE_LABELS[followState]}`} disabled={busy === "follow"}>
                    {following ? FOLLOW_STATE_LABELS[followState] : "Status"}
                  </Button>
                )}
                items={statusItems}
              />
              <Menu
                trigger={(props) => (
                  <Button {...props} variant="secondary" size="lg" icon={following ? <Bell size={18} aria-hidden="true" /> : <BellOff size={18} aria-hidden="true" />} iconEnd={<ChevronDown size={16} aria-hidden="true" className="story-actions__chevron" />} disabled={busy === "follow"}>
                    {following ? "Following" : "Follow"}
                  </Button>
                )}
                items={followItems}
              />
            </>
          )}
          {moreItems.length > 0 && (
            <Menu
              align="end"
              trigger={(props) => <IconButton {...props} label="More actions" size="lg" outlined tooltip="none" icon={<MoreHorizontal size={20} />} />}
              items={moreItems}
            />
          )}
          </div>
        </div>
      </header>

      <Tabs label="Story sections" items={tabItems} value={tab} onChange={setTab} sticky className="story-tabs" />

      <Dialog
        open={confirmRemove}
        onClose={() => setConfirmRemove(false)}
        title="Remove from library?"
        description={`“${view.title}” leaves ${entries.find((entry) => entry.novel_id === copy?.novelId)?.library_name ?? "this library"} with its downloaded chapters, reading progress and notes.`}
        actions={<>
          <Button variant="secondary" onClick={() => setConfirmRemove(false)}>Cancel</Button>
          <Button variant="danger" loading={busy === "remove"} onClick={() => void removeFromLibrary()}>Remove</Button>
        </>}
      />
      <NotifyAfterDialog
        open={notifyCountOpen}
        initial={followSettings?.notification_count ?? 5}
        onClose={() => setNotifyCountOpen(false)}
        onSave={(count) => {
          setNotifyCountOpen(false);
          void saveFollow(followState, { notification_policy: "after_n", notification_count: count });
        }}
      />
    </div>
  );
};

const NotifyAfterDialog: React.FC<{ open: boolean; initial: number; onClose: () => void; onSave: (count: number) => void }> = ({ open, initial, onClose, onSave }) => {
  const [value, setValue] = useState(String(initial));
  useEffect(() => {
    if (open) setValue(String(initial));
  }, [open, initial]);
  const count = Math.min(100, Math.max(1, Math.round(Number(value)) || 1));
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Notify after a number of chapters"
      description="Get one notification once this many new chapters are out."
      actions={<>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button variant="primary" onClick={() => onSave(count)}>Save</Button>
      </>}
    >
      <Input label="New chapters" type="number" min={1} max={100} value={value} onChange={(event) => setValue(event.target.value)} />
    </Dialog>
  );
};

/** `/story/:storyId` */
const Story: React.FC = () => {
  const { storyId } = useParams<{ storyId: string }>();
  return <StoryPage key={storyId} />;
};

/**
 * Old library URL `/library/:libraryId/novels/:novelId`: redirects to `/story/<catalog id>?copy=<id>`.
 * Stories without a catalog id yet are shown here directly.
 */
export const LibraryStoryRedirect: React.FC = () => {
  const { libraryId, novelId } = useParams<{ libraryId: string; novelId: string }>();
  const { search, hash } = useLocation();
  const [target, setTarget] = useState<{ to: string | null } | null>(null);
  useEffect(() => {
    let active = true;
    novelService.getNovelById(Number(libraryId), Number(novelId))
      .then((novel: Novel) => active && setTarget({ to: novel?.metadata_id ? `/story/${novel.metadata_id}?copy=${novel.id}` : null }))
      .catch(() => active && setTarget({ to: null }));
    return () => {
      active = false;
    };
  }, [libraryId, novelId]);

  if (!target) return <div className="story" aria-busy="true" />;
  if (target.to) {
    const extra = search.replace(/^\?/, "");
    return <Navigate replace to={`${extra ? `${target.to}&${extra}` : target.to}${hash}`} />;
  }
  return <StoryPage key={`${libraryId}-${novelId}`} fallbackCopy={{ libraryId: Number(libraryId), novelId: Number(novelId) }} />;
};

export default Story;
