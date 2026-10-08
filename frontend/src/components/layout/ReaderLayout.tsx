import { useMemo } from "react";
import { Link, Outlet, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { ShellContext } from "./shellContext";
import { RouteAnnouncer } from "./RouteAnnouncer";
import { SkipLink } from "./SkipLink";

/**
 * Full-screen reader frame: no sidebar, top bar or tab bar. Keeps the skip link, `main#main`,
 * route focus/announcements and a way back to the story until the D5 reader bars replace it.
 */
export default function ReaderLayout() {
  const { libraryId, novelId } = useParams<{ libraryId: string; novelId: string }>();
  const shell = useMemo(() => ({ setPageMeta: () => undefined }), []);
  return (
    <ShellContext.Provider value={shell}>
      <div className="reader-frame">
        <SkipLink />
        <header className="reader-frame__bar">
          <Link className="reader-frame__back" to={`/library/${libraryId}/novels/${novelId}`}>
            <ArrowLeft aria-hidden="true" />
            Back to story
          </Link>
        </header>
        <main id="main" tabIndex={-1} className="reader-frame__main">
          <Outlet />
        </main>
        <RouteAnnouncer />
      </div>
    </ShellContext.Provider>
  );
}
