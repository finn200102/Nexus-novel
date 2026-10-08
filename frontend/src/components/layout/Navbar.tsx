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
  Server,
  Link2,
} from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import LibrarySwitcher from "./LibrarySwitcher";
import { useLibraryContext } from "../../context/useLibraryContext";
import { useAuth } from "../../context/AuthContext";
import { activityService, OperationsSummary } from "../../services/activityService";
import { novelService } from "../../services/novelService";
import type { NovelUpdateEvent } from "../../types/novel";

interface NavbarProps {
  onRequestCreateLibrary?: () => void;
}

const navItems = [
  { label: "Dashboard", to: "/", icon: Grid2X2, exact: true },
  { label: "Discover", to: "/discover/all", icon: Compass },
  { label: "Downloads", to: "/downloads", icon: Download },
  { label: "Activity", to: "/activity", icon: Bell },
  { label: "Operations", to: "/operations", icon: Server },
  { label: "Scrape Jobs", to: "/scrape-jobs", icon: Search },
  { label: "Integrations", to: "/integrations", icon: Link2 },
];

const Navbar: React.FC<NavbarProps> = ({ onRequestCreateLibrary }) => {
  const navigate = useNavigate();
  const location = useLocation();
  const { activeLibrary } = useLibraryContext();
  const activeLibraryId = activeLibrary?.id;
  const { isAuthenticated, user, logout } = useAuth();
  const [query, setQuery] = useState("");
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [metadataStatus, setMetadataStatus] = useState<OperationsSummary["metadata_server"]["status"] | "unknown">("unknown");
  const [notifications, setNotifications] = useState<NovelUpdateEvent[]>([]);
  const [notificationsOpen, setNotificationsOpen] = useState(false);

  React.useEffect(() => {
    if (activeLibraryId === undefined) {
      setMetadataStatus("unknown");
      return;
    }
    let cancelled = false;
    activityService.getOperationsSummary(activeLibraryId)
      .then((summary) => { if (!cancelled) setMetadataStatus(summary.metadata_server.status); })
      .catch(() => { if (!cancelled) setMetadataStatus("offline"); });
    return () => { cancelled = true; };
  }, [activeLibraryId]);

  React.useEffect(() => {
    if (activeLibraryId === undefined) { setNotifications([]); return; }
    let cancelled = false;
    novelService.getUpdateEvents(activeLibraryId, true)
      .then((items) => { if (!cancelled) setNotifications(items); })
      .catch(() => { if (!cancelled) setNotifications([]); });
    return () => { cancelled = true; };
  }, [activeLibraryId]);

  const markNotificationRead = async (event: NovelUpdateEvent) => {
    try {
      await novelService.markUpdateEventRead(event.id);
      setNotifications((current) => current.filter((item) => item.id !== event.id));
    } catch { /* Activity page remains available if marking fails. */ }
  };

  const markAllNotificationsRead = async () => {
    if (!activeLibrary || notifications.length === 0) return;
    try {
      await activityService.markAllRead(activeLibrary.id);
      setNotifications([]);
    } catch { /* Activity page remains available if marking fails. */ }
  };

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
              {isAuthenticated && <Link to="/notifications">Notifications</Link>}
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
          <button type="button" className="app-topbar__health" title="Metadata server readiness">
            <span className={`health-dot health-dot--${metadataStatus}`} /> Metadata server {metadataStatus}
          </button>
          <div className="app-topbar__notifications">
            <button type="button" className="app-topbar__bell" title="Notifications" aria-label="Notifications" aria-expanded={notificationsOpen} onClick={() => setNotificationsOpen((open) => !open)}>
              <Bell size={18} aria-hidden="true" />{notifications.length > 0 && <span className="app-topbar__notification-count">{notifications.length > 9 ? "9+" : notifications.length}</span>}
            </button>
            {notificationsOpen && <div className="app-topbar__notification-menu" role="dialog" aria-label="Unread notifications"><strong>Unread updates</strong>{notifications.length === 0 && <p>No new story updates.</p>}{notifications.slice(0, 6).map((event) => <button type="button" key={event.id} onClick={() => void markNotificationRead(event)}><span>{event.message}</span><small>Chapter {event.first_chapter_number ?? "new"} · Mark read</small></button>)}{notifications.length > 0 && <button type="button" className="app-topbar__notification-all" onClick={() => void markAllNotificationsRead()}>Mark all read</button>}<button type="button" className="app-topbar__notification-all" onClick={() => { setNotificationsOpen(false); navigate("/activity"); }}>Open activity</button></div>}
          </div>
          <button type="button" className="app-topbar__add" onClick={triggerAddNovel}>
            <Plus size={17} aria-hidden="true" /> Add story
          </button>
        </div>
      </header>
    </>
  );
};

export default Navbar;
