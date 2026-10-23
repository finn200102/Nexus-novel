import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Outlet, useLocation } from "react-router-dom";
import CreateLibraryModal from "../library/CreateLibraryModal";
import { AddStorySheet } from "../add/AddStorySheet";
import { OPEN_ADD_STORY, openAddStory, type OpenAddStoryDetail } from "../add/addStoryEvents";
import SourceStatusBanner from "../common/SourceStatusBanner";
import { useLibraryContext } from "../../context/useLibraryContext";
import { useUnreadUpdates } from "../../hooks/useUnreadUpdates";
import { useMediaQuery } from "../../hooks/useMediaQuery";
import { ShellContext, type PageMeta } from "./shellContext";
import { Sidebar } from "./Sidebar";
import { TabBar } from "./TabBar";
import { TopBar } from "./TopBar";
import { RouteAnnouncer } from "./RouteAnnouncer";
import { SkipLink } from "./SkipLink";

/** Width from which the sidebar/rail replaces the phone tab bar (proposal §2.3). */
export const WIDE_QUERY = "(min-width: 768px)";

/**
 * App shell: skip link, sidebar (wide) or tab bar (phone) as the single `nav[aria-label=Main]`,
 * top bar, `main#main` with the source-status strip, then the page (`children` or the route outlet).
 * Pages talk to the shell only through `usePageTitle` (see docs/ui-review/implementation-plan.md).
 */
export default function Layout({ children }: { children?: ReactNode }) {
  const wide = useMediaQuery(WIDE_QUERY);
  const { pathname } = useLocation();
  const { activeLibrary, libraries, isLoading: librariesLoading } = useLibraryContext();
  const [meta, setPageMeta] = useState<PageMeta>({ title: null });
  const [showLibraryModal, setShowLibraryModal] = useState(false);
  const [addRequest, setAddRequest] = useState<OpenAddStoryDetail | null>(null);
  const shell = useMemo(() => ({ setPageMeta }), []);

  // One unread source for the nav badge; refreshed on navigation so marking read elsewhere shows.
  const unread = useUnreadUpdates(activeLibrary?.id);
  const reloadUnread = unread.reload;
  const lastPath = useRef(pathname);
  useEffect(() => {
    if (lastPath.current === pathname) return;
    lastPath.current = pathname;
    void reloadUnread();
  }, [pathname, reloadUnread]);

  useEffect(() => {
    const handler = () => setShowLibraryModal(true);
    window.addEventListener("nexus:create-library", handler);
    return () => window.removeEventListener("nexus:create-library", handler);
  }, []);

  // One Add story sheet for the whole app; without a library, create one first.
  const hasLibrary = libraries.length > 0 || librariesLoading;
  useEffect(() => {
    const handler = (event: Event) => {
      if (!hasLibrary) {
        setShowLibraryModal(true);
        return;
      }
      setAddRequest((event as CustomEvent<OpenAddStoryDetail>).detail ?? {});
    };
    window.addEventListener(OPEN_ADD_STORY, handler);
    return () => window.removeEventListener(OPEN_ADD_STORY, handler);
  }, [hasLibrary]);

  const addStory = () => openAddStory({ libraryId: activeLibrary?.id });

  return (
    <ShellContext.Provider value={shell}>
      <div className={wide ? "app-shell app-shell--wide" : "app-shell app-shell--phone"}>
        <SkipLink />
        {wide && <Sidebar unreadCount={unread.count} activePath={pathname.startsWith("/story/")&&meta.back?.to.startsWith("/library")?"/library":undefined} />}
        <div className="app-shell__column">
          <TopBar meta={meta} wide={wide} onAddStory={addStory} />
          <main id="main" tabIndex={-1} className="app-main">
            <SourceStatusBanner />
            {children ?? <Outlet />}
          </main>
        </div>
        {!wide && <TabBar unreadCount={unread.count} activePath={pathname.startsWith("/story/")&&meta.back?.to.startsWith("/library")?"/library":undefined} />}
        <RouteAnnouncer />
        <CreateLibraryModal isOpen={showLibraryModal} onClose={() => setShowLibraryModal(false)} />
        <AddStorySheet open={addRequest !== null} onClose={() => setAddRequest(null)} request={addRequest ?? {}} />
      </div>
    </ShellContext.Provider>
  );
}
