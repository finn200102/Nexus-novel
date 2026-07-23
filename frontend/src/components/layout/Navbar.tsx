import React, { useState } from "react";
import {
  Bell,
  BookOpen,
  Compass,
  Download,
  Grid2X2,
  Library,
  Menu,
  Plus,
  Search,
  X,
} from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import LibrarySwitcher from "./LibrarySwitcher";
import { useLibraryContext } from "../../context/LibraryContext";
import { useAuth } from "../../context/AuthContext";

interface NavbarProps {
  onRequestCreateLibrary?: () => void;
}

const navItems = [
  { label: "Dashboard", to: "/", icon: Grid2X2, exact: true },
  { label: "Discover", to: "/discover/all", icon: Compass },
  { label: "Downloads", to: "/downloads", icon: Download },
  { label: "Activity", to: "/activity", icon: Bell },
];

const Navbar: React.FC<NavbarProps> = ({ onRequestCreateLibrary }) => {
  const navigate = useNavigate();
  const location = useLocation();
  const { activeLibrary } = useLibraryContext();
  const { isAuthenticated, user, logout } = useAuth();
  const [query, setQuery] = useState("");
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  const submitSearch = (event: React.FormEvent) => {
    event.preventDefault();
    const value = query.trim();
    navigate(value ? `/discover/all?q=${encodeURIComponent(value)}` : "/discover/all");
  };

  const isActive = (to: string, exact?: boolean) =>
    exact ? location.pathname === to : location.pathname.startsWith(to);

  const triggerAddNovel = () => {
    if (!activeLibrary) {
      onRequestCreateLibrary?.();
      return;
    }
    window.dispatchEvent(new CustomEvent("nexus:add-novel", { detail: { libraryId: activeLibrary.id } }));
    navigate(`/library/${activeLibrary.id}`);
  };

  return (
    <>
      <aside className="sidebar">
        <Link to="/" className="sidebar__brand" aria-label="Nexus Novel dashboard">
          <span className="sidebar__mark"><BookOpen size={20} strokeWidth={2.4} /></span>
          <span>Nexus Novel</span>
        </Link>

        <button
          type="button"
          className="sidebar__mobile-toggle"
          aria-label={mobileNavOpen ? "Close navigation" : "Open navigation"}
          aria-expanded={mobileNavOpen}
          onClick={() => setMobileNavOpen((open) => !open)}
        >
          {mobileNavOpen ? <X size={19} aria-hidden="true" /> : <Menu size={20} aria-hidden="true" />}
        </button>

        <nav className={mobileNavOpen ? "sidebar__nav is-mobile-open" : "sidebar__nav"} aria-label="Primary navigation" onClick={() => setMobileNavOpen(false)}>
          {navItems.map(({ label, to, icon: Icon, exact }) => (
            <Link key={to} to={to} className={isActive(to, exact) ? "is-active" : ""}>
              <Icon size={18} aria-hidden="true" />
              {label}
            </Link>
          ))}
          <button
            type="button"
            className={location.pathname.startsWith("/library") ? "is-active" : ""}
            onClick={() => activeLibrary ? navigate(`/library/${activeLibrary.id}`) : onRequestCreateLibrary?.()}
          >
            <Library size={18} aria-hidden="true" />
            My library
          </button>
        </nav>

        <div className="sidebar__library">
          <p>ACTIVE LIBRARY</p>
          <LibrarySwitcher onCreateLibrary={onRequestCreateLibrary} />
        </div>

        <div className="sidebar__bottom">
          <div className="sidebar__account">
            <span className="sidebar__avatar">{(user?.username || "R").slice(0, 1).toUpperCase()}</span>
            <div>
              <strong>{isAuthenticated ? user?.username || "Reader" : "Local reader"}</strong>
              {isAuthenticated && <button type="button" onClick={logout}>Sign out</button>}
            </div>
          </div>
        </div>
      </aside>

      <header className="app-topbar">
        <form className="app-topbar__search" onSubmit={submitSearch}>
          <Search size={18} aria-hidden="true" />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search stories, authors, tags, sources..."
            aria-label="Search novels"
          />
          <kbd>⌘ K</kbd>
        </form>
        <div className="app-topbar__actions">
          <button type="button" className="app-topbar__health">
            <span /> Metadata server online
          </button>
          <button type="button" className="app-topbar__bell" title="Notifications" aria-label="Notifications">
            <Bell size={18} aria-hidden="true" />
          </button>
          <button type="button" className="app-topbar__add" onClick={triggerAddNovel}>
            <Plus size={17} aria-hidden="true" /> Add story
          </button>
        </div>
      </header>
    </>
  );
};

export default Navbar;
