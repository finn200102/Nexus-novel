import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowLeft, Plus, Search } from "lucide-react";
import { Button, IconButton, Input } from "../ui";
import type { PageMeta } from "./shellContext";

const isTyping = (target: EventTarget | null) =>
  target instanceof HTMLElement && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName));

interface TopBarProps {
  meta: PageMeta;
  /** Wide layout (≥ 768 px): search field + labelled Add story. Phone: title + icon buttons. */
  wide: boolean;
  onAddStory: () => void;
}

/** Top bar inside the content column. No status text, no bell (Updates badge replaces it). */
export function TopBar({ meta, wide, onAddStory }: TopBarProps) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  // "/" and Ctrl/⌘ K jump to search (never while typing or inside a dialog).
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const slash = event.key === "/" && !event.ctrlKey && !event.metaKey && !event.altKey;
      const cmdK = event.key.toLowerCase() === "k" && (event.ctrlKey || event.metaKey);
      if (!slash && !cmdK) return;
      if (isTyping(event.target) || (event.target instanceof Element && event.target.closest("[role='dialog']"))) return;
      event.preventDefault();
      if (searchRef.current) searchRef.current.focus();
      else navigate("/discover");
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [navigate]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const value = query.trim();
    navigate(value ? `/discover?q=${encodeURIComponent(value)}` : "/discover");
  };

  return (
    <header className="app-topbar">
      {wide ? (
        <>
          <form className="app-topbar__search" role="search" onSubmit={submit}>
            <Input
              ref={searchRef}
              search
              aria-label="Search stories"
              placeholder="Search stories, authors and tags"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onClear={() => setQuery("")}
              clearLabel="Clear search"
            />
            <kbd className="app-topbar__kbd" aria-hidden="true">/</kbd>
          </form>
          <Button variant="primary" icon={<Plus aria-hidden="true" />} onClick={onAddStory}>
            Add story
          </Button>
        </>
      ) : (
        <>
          {meta.back && (
            <Link to={meta.back.to} className="app-topbar__back" aria-label={meta.back.label}>
              <ArrowLeft aria-hidden="true" />
            </Link>
          )}
          <p className="app-topbar__title" aria-hidden="true">{meta.title ?? ""}</p>
          <IconButton label="Search" icon={<Search />} tooltip="below" onClick={() => navigate("/discover")} />
          <IconButton label="Add story" icon={<Plus />} tooltip="below" onClick={onAddStory} />
        </>
      )}
    </header>
  );
}
