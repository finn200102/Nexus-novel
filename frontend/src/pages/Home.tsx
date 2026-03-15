import React, { CSSProperties, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useLibraryContext } from "../context/LibraryContext";
import { novelService } from "../services/novelService";
import { Novel } from "../types/novel";
import "../styles/home.css";

const Home: React.FC = () => {
  const navigate = useNavigate();
  const {
    activeLibrary,
    libraries,
    isLoading: librariesLoading,
    selectLibrary,
  } = useLibraryContext();
  const [recentNovels, setRecentNovels] = useState<Novel[]>([]);
  const [novelLoading, setNovelLoading] = useState(false);
  const [novelError, setNovelError] = useState<string | null>(null);

  useEffect(() => {
    let isCancelled = false;

    const fetchNovels = async () => {
      if (!activeLibrary) {
        setRecentNovels([]);
        return;
      }
      setNovelLoading(true);
      setNovelError(null);
      try {
        const data = await novelService.getAllNovels(activeLibrary.id, "");
        if (isCancelled) return;
        if (Array.isArray(data)) {
          setRecentNovels(data.slice(0, 6));
        } else {
          setRecentNovels([]);
        }
      } catch (err) {
        if (!isCancelled) {
          console.error("Failed to load novels", err);
          setNovelError("Unable to load recent activity");
        }
      } finally {
        if (!isCancelled) {
          setNovelLoading(false);
        }
      }
    };

    fetchNovels();
    return () => {
      isCancelled = true;
    };
  }, [activeLibrary?.id]);

  const heroCover = useMemo(() => {
    const coverCandidate = recentNovels.find((novel) => novel.img_url || novel.cover_image);
    return coverCandidate?.img_url || coverCandidate?.cover_image || null;
  }, [recentNovels]);

  const handleQuickAction = (action: "library" | "add" | "manage") => {
    if (action === "library" && activeLibrary) {
      navigate(`/library/${activeLibrary.id}`);
      return;
    }
    if (action === "add" && activeLibrary) {
      window.dispatchEvent(
        new CustomEvent("nexus:add-novel", {
          detail: { libraryId: activeLibrary.id },
        })
      );
      navigate(`/library/${activeLibrary.id}`);
      return;
    }
    if (action === "manage") {
      const section = document.getElementById("home-libraries");
      section?.scrollIntoView({ behavior: "smooth" });
    }
  };

  const formatDate = (dateString: string) => {
    try {
      const date = new Date(dateString);
      return new Intl.DateTimeFormat("en", {
        month: "short",
        day: "numeric",
      }).format(date);
    } catch {
      return "";
    }
  };

  const heroImageStyle: CSSProperties | undefined = heroCover
    ? ({
        ["--hero-cover" as const]: `url(${heroCover})`,
      } as CSSProperties)
    : undefined;

  return (
    <div className="home-grid">
      <section className="home-hero" style={heroImageStyle}>
        <div className="home-hero__content">
          <p className="home-hero__eyebrow">
            {activeLibrary ? "Active Library" : "Let's build your library"}
          </p>
          <h1>
            {activeLibrary
              ? activeLibrary.name
              : "Collect every story in one space"}
          </h1>
          <p className="home-hero__summary">
            Keep track of your novels, sync metadata, and continue where you left off.
          </p>
          <div className="home-hero__buttons">
            <button
              type="button"
              className="home-hero__btn"
              onClick={() => handleQuickAction("library")}
              disabled={!activeLibrary}
            >
              Enter Library
            </button>
            <button
              type="button"
              className="home-hero__btn home-hero__btn--secondary"
              onClick={() => handleQuickAction("add")}
              disabled={!activeLibrary}
            >
              Add Novel
            </button>
          </div>
        </div>
      </section>

      <section className="home-actions">
        <article className="home-action-card" onClick={() => handleQuickAction("library")}>
          <h3>Jump back in</h3>
          <p>Open the current library workspace.</p>
        </article>
        <article className="home-action-card" onClick={() => handleQuickAction("add")}>
          <h3>Import a novel</h3>
          <p>Paste a URL and start syncing chapters.</p>
        </article>
        <article className="home-action-card" onClick={() => handleQuickAction("manage")}>
          <h3>Manage libraries</h3>
          <p>Switch libraries or create a new collection.</p>
        </article>
      </section>

      <section className="home-panel" aria-live="polite">
        <header className="home-panel__header">
          <div>
            <p className="home-panel__eyebrow">Recent Activity</p>
            <h2>Latest novels</h2>
          </div>
          {activeLibrary && (
            <button
              type="button"
              className="home-panel__link"
              onClick={() => navigate(`/library/${activeLibrary.id}`)}
            >
              View all
            </button>
          )}
        </header>
        <div className="home-panel__body">
          {novelLoading && <p className="home-panel__status">Loading novels…</p>}
          {novelError && <p className="home-panel__status is-error">{novelError}</p>}
          {!novelLoading && !novelError && recentNovels.length === 0 && (
            <p className="home-panel__status">Add a novel to see activity.</p>
          )}
          <ul className="home-activity-list">
            {recentNovels.map((novel) => (
              <li key={novel.id}>
                <button
                  type="button"
                  className="home-activity-card"
                  onClick={() =>
                    navigate(`/library/${novel.library_id}/novels/${novel.id}`)
                  }
                >
                  <div>
                    <h3>{novel.title}</h3>
                    <p>{novel.author || novel.novel_site || "Unknown author"}</p>
                  </div>
                  <span>{formatDate(novel.updated_at)}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="home-panel" id="home-libraries">
        <header className="home-panel__header">
          <div>
            <p className="home-panel__eyebrow">Libraries</p>
            <h2>Your collections</h2>
          </div>
        </header>
        <div className="home-panel__body">
          {librariesLoading && <p className="home-panel__status">Loading libraries…</p>}
          {!librariesLoading && libraries.length === 0 && (
            <p className="home-panel__status">Create your first library to get started.</p>
          )}
          <div className="home-library-grid">
            {libraries.map((library) => (
              <button
                key={library.id}
                type="button"
                className={`home-library-card ${
                  activeLibrary?.id === library.id ? "is-active" : ""
                }`}
                onClick={() => selectLibrary(library.id)}
              >
                <div>
                  <p className="home-library-card__eyebrow">Library</p>
                  <h3>{library.name}</h3>
                </div>
                <p className="home-library-card__status">
                  {activeLibrary?.id === library.id ? "Currently active" : "Set active"}
                </p>
              </button>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
};

export default Home;
