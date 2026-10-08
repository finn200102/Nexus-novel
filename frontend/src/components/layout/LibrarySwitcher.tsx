import React, { useEffect, useMemo, useRef, useState } from "react";
import { useLibraryContext } from "../../context/useLibraryContext";

interface LibrarySwitcherProps {
  onCreateLibrary?: () => void;
}

const LibrarySwitcher: React.FC<LibrarySwitcherProps> = ({ onCreateLibrary }) => {
  const {
    libraries,
    activeLibrary,
    activeLibraryId,
    selectLibrary,
    isLoading,
    error,
  } = useLibraryContext();
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState("");
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const handler = (event: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    };

    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  useEffect(() => {
    if (!isOpen) {
      setQuery("");
    }
  }, [isOpen]);

  const filteredLibraries = useMemo(() => {
    if (!query.trim()) return libraries;
    const lowered = query.trim().toLowerCase();
    return libraries.filter((library) =>
      library.name.toLowerCase().includes(lowered)
    );
  }, [libraries, query]);

  const handleSelect = (libraryId: number) => {
    selectLibrary(libraryId);
    setIsOpen(false);
  };

  return (
    <div className="library-switcher" ref={containerRef}>
      <button
        type="button"
        className="library-switcher__trigger"
        aria-haspopup="dialog"
        aria-expanded={isOpen}
        onClick={() => setIsOpen((prev) => !prev)}
        disabled={isLoading && libraries.length === 0}
      >
        <div className="library-switcher__text">
          <span className="library-switcher__subtitle">Library</span>
          <span className="library-switcher__title">
            {activeLibrary?.name || (isLoading ? "Loading…" : "Select a library")}
          </span>
        </div>
        <span className="library-switcher__chevron" aria-hidden>
          ▾
        </span>
      </button>
      {isOpen && (
        <div className="library-switcher__panel" role="dialog">
          {error && <div className="library-switcher__status">{error}</div>}
          {isLoading && !error && (
            <div className="library-switcher__status">Fetching libraries…</div>
          )}
          {!isLoading && libraries.length === 0 && (
            <div className="library-switcher__empty">
              <p>You don't have any libraries yet.</p>
              {onCreateLibrary && (
                <button
                  type="button"
                  className="library-switcher__create-btn"
                  onClick={() => {
                    setIsOpen(false);
                    onCreateLibrary();
                  }}
                >
                  Create Library
                </button>
              )}
            </div>
          )}
          {!isLoading && libraries.length > 0 && (
            <>
              {libraries.length > 4 && (
                <div className="library-switcher__search">
                  <input
                    type="search"
                    placeholder="Search libraries"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                  />
                </div>
              )}
              <ul className="library-switcher__list">
                {filteredLibraries.length === 0 && (
                  <li className="library-switcher__status">No matches</li>
                )}
                {filteredLibraries.map((library) => (
                  <li key={library.id}>
                    <button
                      type="button"
                      className={`library-switcher__item ${
                        library.id === activeLibraryId ? "is-active" : ""
                      }`}
                      onClick={() => handleSelect(library.id)}
                    >
                      <span>{library.name}</span>
                      {library.id === activeLibraryId && (
                        <span className="library-switcher__pill">Current</span>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
              {onCreateLibrary && (
                <button
                  type="button"
                  className="library-switcher__create-btn"
                  onClick={() => {
                    setIsOpen(false);
                    onCreateLibrary();
                  }}
                >
                  + New Library
                </button>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
};

export default LibrarySwitcher;
