import React, { useEffect, useMemo, useState } from "react";
import {
  ArrowUpRight,
  BookMarked,
  Database,
  Download,
  Bell,
  Library,
  Play,
  Sparkles,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useLibraryContext } from "../context/LibraryContext";
import { novelService } from "../services/novelService";
import { Novel, NovelUpdateEvent } from "../types/novel";
import defaultCoverImage from "../assets/cover.png";
import "../styles/home.css";

const formatCompact = (value: number) =>
  new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(value);

const Home: React.FC = () => {
  const navigate = useNavigate();
  const { activeLibrary, libraries, isLoading: librariesLoading, selectLibrary } = useLibraryContext();
  const [novels, setNovels] = useState<Novel[]>([]);
  const [updates, setUpdates] = useState<NovelUpdateEvent[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      if (!activeLibrary) {
        setNovels([]);
        return;
      }
      setLoading(true);
      try {
        const [data, updateData] = await Promise.all([
          novelService.getAllNovels(activeLibrary.id, ""),
          novelService.getUpdateEvents(activeLibrary.id, true),
        ]);
        if (!cancelled) {
          setNovels(Array.isArray(data) ? data : []);
          setUpdates(Array.isArray(updateData) ? updateData : []);
        }
      } catch (error) {
        console.error("Failed to load dashboard novels", error);
        if (!cancelled) setNovels([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [activeLibrary?.id]);

  const recent = useMemo(
    () => [...novels].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at)).slice(0, 6),
    [novels]
  );
  const totalWords = useMemo(() => novels.reduce((total, novel) => total + (novel.word_count || 0), 0), [novels]);
  const totalChapters = useMemo(() => novels.reduce((total, novel) => total + (novel.chapter_count || 0), 0), [novels]);
  const completed = useMemo(() => novels.filter((novel) => novel.status?.toLowerCase() === "complete").length, [novels]);

  const goToLibrary = () => activeLibrary && navigate(`/library/${activeLibrary.id}`);
  const addNovel = () => {
    if (!activeLibrary) return;
    window.dispatchEvent(new CustomEvent("nexus:add-novel", { detail: { libraryId: activeLibrary.id } }));
    goToLibrary();
  };

  const metricCards = [
    { label: "Total stories", value: formatCompact(novels.length), detail: activeLibrary ? activeLibrary.name : "No library selected", icon: Library, tone: "violet" },
    { label: "Tracked chapters", value: formatCompact(totalChapters), detail: "Across your collection", icon: BookMarked, tone: "blue" },
    { label: "Library words", value: formatCompact(totalWords), detail: "Across story metadata", icon: Download, tone: "amber" },
    { label: "Completed", value: formatCompact(completed), detail: "Stories marked complete", icon: Sparkles, tone: "green" },
  ];

  return (
    <div className="dashboard" aria-live="polite">
      <header className="dashboard__header">
        <div>
          <p className="dashboard__eyebrow">Overview</p>
          <h1>{activeLibrary ? activeLibrary.name : "Your story dashboard"}</h1>
          <p>{activeLibrary ? "Your library at a glance." : "Select or create a library to begin collecting stories."}</p>
        </div>
        <button type="button" className="dashboard__action" onClick={addNovel} disabled={!activeLibrary}>
          <Download size={16} aria-hidden="true" /> Import story
        </button>
      </header>

      <section className="dashboard__metrics" aria-label="Library statistics">
        {metricCards.map(({ label, value, detail, icon: Icon, tone }) => (
          <article className={`metric-card metric-card--${tone}`} key={label}>
            <span className="metric-card__icon"><Icon size={20} aria-hidden="true" /></span>
            <div>
              <p>{label}</p>
              <strong>{value}</strong>
              <small>{detail}</small>
            </div>
          </article>
        ))}
      </section>

      <section className="dashboard-grid">
        <section className="dashboard-panel dashboard-panel--continue">
          <header className="dashboard-panel__header">
            <div><p>Continue reading</p><h2>Recently updated</h2></div>
            {activeLibrary && <button type="button" onClick={goToLibrary}>View library <ArrowUpRight size={14} /></button>}
          </header>
          {loading && <p className="dashboard-panel__status">Refreshing library...</p>}
          {!loading && recent.length === 0 && (
            <div className="dashboard-empty"><BookMarked size={22} /><p>Your next story will appear here.</p><button type="button" onClick={addNovel} disabled={!activeLibrary}>Import a story</button></div>
          )}
          <div className="continue-grid">
            {recent.map((novel) => (
              <button key={novel.id} type="button" className="continue-card" onClick={() => navigate(`/library/${novel.library_id}/novels/${novel.id}`)}>
                <img src={novel.img_url || novel.cover_image || defaultCoverImage} alt="" referrerPolicy="no-referrer" onError={(event) => { event.currentTarget.src = defaultCoverImage; }} />
                <span className="continue-card__body">
                  <span className="continue-card__source">{novel.novel_site || "Source"}</span>
                  <strong>{novel.title}</strong>
                  <small>{novel.author || "Unknown author"}</small>
                  <span className="continue-card__progress"><i /><em>{novel.chapter_count || 0} chapters</em></span>
                </span>
              </button>
            ))}
          </div>
        </section>

        <section className="dashboard-panel dashboard-panel--activity">
          <header className="dashboard-panel__header"><div><p>Activity</p><h2>Library pulse</h2></div></header>
          <div className="activity-list">
            <div><span className="activity-list__icon"><Database size={16} /></span><p><strong>Metadata server</strong><small>Catalog search and source data are available.</small></p><b>Online</b></div>
            <div><span className="activity-list__icon"><Download size={16} /></span><p><strong>Downloads</strong><small>Manage chapter transfers from one place.</small></p><button type="button" onClick={() => navigate("/downloads")}>Open</button></div>
            <div><span className="activity-list__icon"><Play size={16} /></span><p><strong>Reading queue</strong><small>{recent.length ? `${recent.length} recent stories ready to open.` : "Add a story to start reading."}</small></p><button type="button" onClick={goToLibrary} disabled={!activeLibrary}>Open</button></div>
          </div>
        </section>

        <section className="dashboard-panel dashboard-panel--activity">
          <header className="dashboard-panel__header"><div><p>Updates</p><h2>New chapters</h2></div><Bell size={18} aria-hidden="true" /></header>
          <div className="activity-list">
            {updates.length === 0 && <p className="dashboard-panel__status">No unread story updates.</p>}
            {updates.slice(0, 5).map((update) => (
              <div key={update.id}>
                <span className="activity-list__icon"><BookMarked size={16} /></span>
                <p><strong>{update.message}</strong><small>Chapters {update.first_chapter_number}–{update.last_chapter_number}</small></p>
                <button type="button" onClick={() => navigate(`/library/${activeLibrary?.id}/novels/${update.novel_id}`)}>Open</button>
              </div>
            ))}
          </div>
        </section>
      </section>

      <section className="dashboard-panel dashboard-panel--libraries">
        <header className="dashboard-panel__header"><div><p>Collections</p><h2>Libraries</h2></div></header>
        {librariesLoading && <p className="dashboard-panel__status">Loading libraries...</p>}
        <div className="library-strip">
          {libraries.map((library) => (
            <button key={library.id} type="button" className={activeLibrary?.id === library.id ? "library-strip__item is-active" : "library-strip__item"} onClick={() => selectLibrary(library.id)}>
              <span>{library.name.slice(0, 1).toUpperCase()}</span><strong>{library.name}</strong><small>{activeLibrary?.id === library.id ? "Active library" : "Select library"}</small>
            </button>
          ))}
          {!librariesLoading && libraries.length === 0 && <p className="dashboard-panel__status">No libraries yet.</p>}
        </div>
      </section>
    </div>
  );
};

export default Home;
