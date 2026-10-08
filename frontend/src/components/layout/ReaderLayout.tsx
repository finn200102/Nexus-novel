import { useMemo } from "react";
import { Outlet } from "react-router-dom";
import { ShellContext } from "./shellContext";
import { RouteAnnouncer } from "./RouteAnnouncer";
import { SkipLink } from "./SkipLink";

/**
 * Full-screen reader frame: no sidebar, top bar or tab bar. Keeps the skip link, `main#main`
 * and route focus/announcements; the reader draws its own top and bottom bars (WP-D5).
 */
export default function ReaderLayout() {
  const shell = useMemo(() => ({ setPageMeta: () => undefined }), []);
  return (
    <ShellContext.Provider value={shell}>
      <div className="reader-frame">
        <SkipLink />
        <main id="main" tabIndex={-1} className="reader-frame__main">
          <Outlet />
        </main>
        <RouteAnnouncer />
      </div>
    </ShellContext.Provider>
  );
}
