import { openAddStory } from "../components/add/addStoryEvents";
import React, { useEffect, useMemo, useState } from "react";
import { BarChart3, BookMarked, ChevronRight, Compass, Library as LibraryIcon } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { useLibraryContext } from "../context/useLibraryContext";
import { novelService } from "../services/novelService";
import { Novel } from "../types/novel";
import type { InboxNovel } from "../types/activity";
import { activityService } from "../services/activityService";
import { useUnreadUpdates } from "../hooks/useUnreadUpdates";
import { usePageTitle } from "../hooks/usePageTitle";
import { displayTitle } from "../utils/displayTitle";
import ContinueReading from "../components/reader/ContinueReading";
import { readingStatsService, type StatsSummary } from "../services/readingStatsService";
import { formatDuration } from "../components/stats/statsFormat";
import { Button, Cover, EmptyState, Input, ListRow, PageHeader } from "../components/ui";
import "../styles/home.css";

const RECENT_LIMIT = 8;
const UPDATES_LIMIT = 5;

const relative = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

/** "2 h ago" style label for an ISO timestamp; empty when the timestamp is unusable. */
const formatAgo = (iso: string | null | undefined, now = Date.now()): string => {
  const time = iso ? Date.parse(iso) : NaN;
  if (Number.isNaN(time)) return "";
  const seconds = Math.round((time - now) / 1000);
  const units: [Intl.RelativeTimeFormatUnit, number][] = [["day", 86400], ["hour", 3600], ["minute", 60]];
  for (const [unit, size] of units) {
    if (Math.abs(seconds) >= size) return relative.format(Math.round(seconds / size), unit);
  }
  return "just now";
};

const Home: React.FC = () => {
  usePageTitle("Home");
  const [week, setWeek] = useState<StatsSummary | null>(null);
  useEffect(() => {
    let active = true;
    readingStatsService.getSummary("week").then((summary) => active && setWeek(summary?.totals ? summary : null)).catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);
  const navigate = useNavigate();
  const { activeLibrary, isLoading: librariesLoading } = useLibraryContext();
  const activeLibraryId = activeLibrary?.id;
  const [novels, setNovels] = useState<Novel[]>([]);
  const [loading, setLoading] = useState(false);
  const [pastedLink, setPastedLink] = useState("");
  const unread = useUnreadUpdates(activeLibraryId);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      if (activeLibraryId === undefined) {
        setNovels([]);
        return;
      }
      setLoading(true);
      try {
        const data = await novelService.getAllNovels(activeLibraryId, "");
        if (!cancelled) setNovels(Array.isArray(data) ? data : []);
      } catch (error) {
        console.error("Failed to load home novels", error);
        if (!cancelled) setNovels([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [activeLibraryId]);

  const recentlyAdded = useMemo(
    () => [...novels].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)).slice(0, RECENT_LIMIT),
    [novels]
  );
  const totals = useMemo(
    () => ({
      chapters: novels.reduce((total, novel) => total + (novel.chapter_count || 0), 0),
      words: novels.reduce((total, novel) => total + (novel.word_count || 0), 0),
    }),
    [novels]
  );
  const novelById = useMemo(() => new Map(novels.map((novel) => [novel.id, novel])), [novels]);

  const openUpdate = async (row: InboxNovel) => {
    const libraryId = activeLibrary?.id;
    try {
      await activityService.markInboxRead(row.novel_id);
      await unread.reload();
    } catch (error) {
      console.error("Failed to mark update read", error);
    }
    if (libraryId === undefined) return;
    navigate(
      row.next_unread_chapter_number != null
        ? `/library/${libraryId}/novels/${row.novel_id}/${row.next_unread_chapter_number}`
        : `/library/${libraryId}/novels/${row.novel_id}`
    );
  };

  const submitLink = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const link = pastedLink.trim();
    if (!link) return;
    openAddStory({ url: link });
  };

  const hasStories = novels.length > 0;
  const showEmpty = !loading && !librariesLoading && activeLibrary && !hasStories;

  return (
    <div className="home">
      <PageHeader title="Home" description="Pick up where you left off, and see what is new." />

      {!activeLibrary && !librariesLoading && (
        <EmptyState
          icon={<LibraryIcon size={40} />}
          title="Create a library to start"
          description="A library holds the stories you read and follow."
          action={<Button onClick={() => window.dispatchEvent(new CustomEvent("nexus:create-library"))}>Create a library</Button>}
        />
      )}

      {showEmpty && (
        <EmptyState
          icon={<BookMarked size={40} />}
          title="Add your first story"
          description="Paste a story link from a supported site, or import an EPUB or an AO3 or FanFiction.net download."
          action={
            <div className="home-empty__actions">
              <form className="home-empty__form" onSubmit={submitLink}>
                <Input
                  label="Story link"
                  type="url"
                  inputMode="url"
                  placeholder="https://"
                  value={pastedLink}
                  onChange={(event) => setPastedLink(event.target.value)}
                  autoComplete="off"
                />
                <Button type="submit" disabled={!pastedLink.trim()}>Add story</Button>
              </form>
              <Button variant="secondary" icon={<Compass size={16} aria-hidden="true" />} onClick={() => navigate("/discover")}>
                Browse Discover
              </Button>
            </div>
          }
        />
      )}

      {activeLibrary && hasStories && (
        <>
          <ContinueReading novels={novels} updates={unread.rows} />

          <section className="home-section" aria-labelledby="home-updates-heading">
            <header className="home-section__header">
              <h2 id="home-updates-heading">New chapters</h2>
              <Link to="/updates" className="home-section__link">See all updates</Link>
            </header>
            {unread.rows.length === 0 ? (
              <p className="home-section__status">No unread story updates.</p>
            ) : (
              <ul className="home-list">
                {unread.rows.slice(0, UPDATES_LIMIT).map((row) => {
                  const novel = novelById.get(row.novel_id);
                  const title = displayTitle({ title: row.title });
                  const last = row.first_new_chapter_number + row.new_chapter_count - 1;
                  const range = row.new_chapter_count > 1 ? `Chapters ${row.first_new_chapter_number}–${last}` : `Chapter ${row.first_new_chapter_number}`;
                  const ago = formatAgo(row.latest_at);
                  return (
                    <li key={row.novel_id}>
                      <ListRow
                        media={<Cover src={novel?.img_url || novel?.cover_image} title={title} size={48} />}
                        title={title}
                        meta={[range, ago].filter(Boolean).join(" · ")}
                        actions={<Button size="sm" variant="secondary" onClick={() => openUpdate(row)} aria-label={`Read new chapters of ${title}`}>Read</Button>}
                      />
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          <section className="home-section" aria-labelledby="home-recent-heading">
            <header className="home-section__header">
              <h2 id="home-recent-heading">Recently added</h2>
              <Link to="/library" className="home-section__link">Open library</Link>
            </header>
            <ul className="home-covers">
              {recentlyAdded.map((novel) => (
                <li key={novel.id}>
                  <Link to={`/library/${novel.library_id}/novels/${novel.id}`} className="home-cover">
                    <Cover src={novel.img_url || novel.cover_image} title={displayTitle(novel)} size="fill" />
                    <span>{displayTitle(novel)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>

          <Link to="/stats" className="home-week">
            <BarChart3 aria-hidden="true" className="home-week__icon" />
            <span className="home-week__text">
              <strong>Your reading this week</strong>
              <span>
                {week && week.totals.seconds > 0
                  ? `${formatDuration(week.totals.seconds)} · ${week.totals.chapters_finished} ${week.totals.chapters_finished === 1 ? "chapter" : "chapters"}`
                  : "See your reading time, streaks and favourite stories."}
              </span>
            </span>
            <ChevronRight aria-hidden="true" className="home-week__chevron" />
          </Link>

          <p className="home-stats">
            {novels.length} {novels.length === 1 ? "story" : "stories"} · {totals.chapters.toLocaleString()} chapters · {totals.words.toLocaleString()} words
          </p>
        </>
      )}
    </div>
  );
};

export default Home;
